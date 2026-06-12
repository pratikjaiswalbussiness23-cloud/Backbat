"""Algo Engine v1.0 - Signal Orchestrator"""
import time
from typing import Dict, List, Optional
from liq_engine import BinanceClient, FVGBalancer, SwingPointDetector, CVDAnalyzer, DeltaPatternDetector
from .trend_detector import TrendDetector
from .signal_state_machine import SignalStateMachine, Signal
from .dynamic_sltp import DynamicSLTP
from .trade_journal import TradeJournal
from .confluence_scorer import ConfluenceScorer

class SignalOrchestrator:
    """Ties all components into a real-time signal pipeline."""

    def __init__(self, quality_thresh=0.40, min_components=2):
        self.client = BinanceClient()
        self.trend = TrendDetector()
        self.state_machine = SignalStateMachine()
        self.sltp = DynamicSLTP()
        self.journal = TradeJournal()
        self.scorer = ConfluenceScorer(quality_thresh, min_components)
        self.fvg = FVGBalancer()
        self.swing = SwingPointDetector()
        self.cvd = CVDAnalyzer()
        self.delta = DeltaPatternDetector()
    def process_candle(self, symbol, interval):
        """Process candle: detect patterns, score confluence, update state machine."""
        try:
            candles = self.client.klines(symbol, interval, limit=250)
        except Exception as e:
            return {"success": False, "error": str(e)}

        if len(candles) < 60:
            return {"success": False, "error": "Insufficient data"}

        cp = candles[-1]["close"]
        low = candles[-1]["low"]
        high = candles[-1]["high"]
        vol = candles[-1].get("volume", 0)

        # 1. Detect patterns (same FVG + Swing + Delta as before)
        fvg_r = self.fvg.detect(candles)
        swing_r = self.swing.detect(candles)
        cvd_r = self.cvd.calculate(candles)
        delta_p = self.delta.detect(candles, cvd_r.get("perCandleDelta", []))

        # 2. Score confluence with trend gate
        conf = self.scorer.score(
            candles,
            fvg_r.get("zones", []),
            swing_r,
            {"patterns": delta_p.get("patterns", []),
             "divergences": cvd_r.get("divergences", [])}
        )

        # 3. Update state machine with new price
        trans = self.state_machine.check_price(symbol, cp, low, high, cp, vol)
        active = self.state_machine.get_active_signals(symbol)

        # 4. Create new signal if quality passes
        new_sig = None
        if conf.get("passes_quality"):
            direction = conf["direction"]
            atr = self._calc_atr(candles)
            sltp_r = self.sltp.calculate(candles, direction, cp, atr)

            tc = conf.get("trend", {}).get("confidence", 0)
            cc = conf.get("component_count", 0)
            score = conf.get("score", 0)

            if cc >= 3 and score >= 0.6 and tc >= 0.5:
                confidence = "HIGH"
            elif cc >= 2 and score >= 0.4:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            ez_low = cp * 0.995 if direction == "long" else cp * 0.998
            ez_high = cp * 1.002 if direction == "long" else cp * 1.005

            sig = Signal(
                symbol, interval, direction,
                ez_low, ez_high,
                sltp_r["sl_price"], sltp_r["tp_price"],
                confidence,
                conf.get("components", []), score,
                [f"{direction.upper()}: {cc}/3 comps",
                 f"Trend: {conf.get('trend',{}).get('trend','neutral')} ({tc:.2f})"],
                conf.get("trend", {})
            )
            self.state_machine.add_signal(sig)
            new_sig = sig.to_dict()

        # 5. Cleanup stale
        self.state_machine.cleanup_stale()

        # Log transitions to journal
        for t in trans:
            h = self.state_machine.get_history(1)
            if h:
                self.journal.log(h[0])

        return {
            "success": True, "symbol": symbol, "interval": interval,
            "current_price": cp, "timestamp": int(time.time()),
            "confluence": {
                "direction": conf.get("direction"),
                "score": conf.get("score", 0),
                "components": conf.get("components", []),
                "component_count": conf.get("component_count", 0),
                "passes_quality": conf.get("passes_quality", False),
                "trend": conf.get("trend", {}),
            },
            "transitions": trans,
            "active_signals": active,
            "new_signal": new_sig,
            "state_stats": self.state_machine.get_stats(),
            "cvd": {
                "current": cvd_r.get("currentCVD", 0),
                "latest_delta": (cvd_r.get("latestCandle") or {}).get("delta", 0),
                "divergences": len(cvd_r.get("divergences", [])),
            },
            "delta_patterns": len(delta_p.get("patterns", [])),
        }

    def _calc_atr(self, candles, period=14):
        if len(candles) < period + 1:
            return 0
        trs = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) < period:
            return sum(trs) / max(len(trs), 1)
        a = sum(trs[:period]) / period
        for i in range(period, len(trs)):
            a = (a * (period - 1) + trs[i]) / period
        return a

    def get_state(self, symbol=None):
        """Get current state: active signals, history, stats."""
        return {
            "active_signals": self.state_machine.get_active_signals(symbol),
            "history": self.state_machine.get_history(20),
            "stats": self.state_machine.get_stats(),
            "journal_stats": self.journal.stats(),
        }
