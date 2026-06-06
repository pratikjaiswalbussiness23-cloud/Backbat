"""
BACKBAT v3 -- Main Trading Engine Orchestrator
Ties together Layers 1-4: Data, Detection, Scoring, Signal Gate
"""
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from config import DEFAULT_CONFIG, BackbatConfig
from data_ingestion import DataIngestionLayer
from detection_filter import DetectLayer, VolProf
from scoring_engine import ScoringLayer
from signal_gate import SignalGate, DB
logger = logging.getLogger("backbat.engine")


class Candle:
    def __init__(self, t, o, h, l, c, vol):
        self.time = t
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = vol


class Trade:
    def __init__(self):
        self.id = 0
        self.entry_time = 0
        self.exit_time = 0
        self.entry_price = 0.0
        self.exit_price = 0.0
        self.stop_loss = 0.0
        self.target1 = 0.0
        self.target2 = 0.0
        self.pnl = 0.0
        self.pnl_pct = 0.0
        self.rr = 0.0
        self.status = 0
        self.pattern_ref = None

    def to_dict(self):
        return {"id": self.id, "entryTime": self.entry_time, "exitTime": self.exit_time, "entryPrice": round(self.entry_price, 2), "exitPrice": round(self.exit_price, 2), "stopLoss": round(self.stop_loss, 2), "target1": round(self.target1, 2), "target2": round(self.target2, 2), "pnl": round(self.pnl, 2), "pnlPct": round(self.pnl_pct, 4), "rr": round(self.rr, 2), "status": "open" if self.status == 0 else "closed", "patternRef": self.pattern_ref}


class EngineV3:
    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        self.data = DataIngestionLayer(config)
        self.detect = DetectLayer(config)
        self.scoring = ScoringLayer(config)
        self.gate = SignalGate(config)
        self.candles = []
        self.trades = []
        self.equity = []
        self.pattern_markers = []
        self.balance = self.cfg.initial_balance
        self.active_trade = None
        self.trade_id = 1
        self.atr_values = []

    def load_candles(self, candle_list):
        self.candles = []
        for c in candle_list:
            if isinstance(c, dict):
                self.candles.append(Candle(c["time"], c["open"], c["high"], c["low"], c["close"], c.get("volume", 0)))
            else:
                self.candles.append(c)

    def process_all(self):
        self.trades = []
        self.equity = []
        self.pattern_markers = []
        self.balance = self.cfg.initial_balance
        self.active_trade = None
        self.trade_id = 1
        self.atr_values = []
        for i, c in enumerate(self.candles):
            self._process_candle(c, i)
        if self.active_trade:
            self._close_trade(self.candles[-1], "end_of_data", self.candles[-1].close)
        return {"metrics": self._calc_metrics(), "trades": [t.to_dict() for t in self.trades], "patternMarkers": self.pattern_markers, "candles": [{"time": c.time, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in self.candles], "equity": self.equity}

    def _process_candle(self, c, i):
        det = self.detect.process(c.open, c.high, c.low, c.close, c.volume, i)
        atr = det.get("atr", 0)
        self.atr_values.append(atr)
        market = self.data.snapshot()
        market["price"] = c.close
        vol_dens = self.detect.vp.dens(c.close)
        det["volume_density"] = vol_dens
        base_rates = self.detect.clf.br("support", "bounce")
        for z in det.get("new_zones", []):
            scored = self.scoring.evaluate_zone(z, market, det, {"support": {"bounce": base_rates}})
            if scored:
                near = self.detect.near_zone(c.close, atr)
                if near:
                    pat = self._find_db_pattern(i)
                    if pat:
                        score_val = scored["score"]["composite_score"]
                        day = datetime.fromtimestamp(c.time).strftime("%Y-%m-%d")
                        sig = self.gate.evaluate(pat, z, score_val, market, det, self.balance, day)
                        if sig and not self.active_trade:
                            self._enter_trade(sig, c, i, z)
        if self.active_trade:
            self._check_exit(c, i, market)
        self.equity.append({"time": c.time, "balance": round(self.balance, 2)})

    def _find_db_pattern(self, idx):
        if idx < 5:
            return None
        start = max(0, idx - 30)
        lows = [(j, self.candles[j].low, self.candles[j].volume) for j in range(start, idx + 1)]
        if len(lows) < 5:
            return None
        swing_lows = []
        for j in range(1, len(lows) - 1):
            if lows[j][1] < lows[j-1][1] and lows[j][1] < lows[j+1][1]:
                swing_lows.append(lows[j])
        if len(swing_lows) < 2:
            return None
        sl1, sl2 = swing_lows[-2], swing_lows[-1]
        b1i, b1p, b1v = sl1
        b2i, b2p, b2v = sl2
        between = self.candles[b1i:b2i+1]
        if not between:
            return None
        neckline = max(c.high for c in between)
        height = neckline - min(b1p, b2p)
        pat = DB(b1i, b2i, b1p, b2p, neckline, height, b1v, b2v)
        atr = self.atr_values[-1] if self.atr_values else 200
        return pat if pat.valid(atr=atr) else None

    def _enter_trade(self, sig, c, i, zone):
        trade = Trade()
        trade.id = self.trade_id
        self.trade_id += 1
        trade.entry_time = c.time
        trade.entry_price = sig.entry
        trade.stop_loss = sig.sl
        trade.target1 = sig.pat.tp
        trade.target2 = sig.pat.tp * 1.5
        trade.pattern_ref = {"b1Idx": sig.pat.b1i, "b2Idx": sig.pat.b2i, "b1Price": sig.pat.b1p, "b2Price": sig.pat.b2p, "necklinePrice": sig.pat.nl, "targetPrice": sig.pat.tp, "height": sig.pat.h, "breakoutIdx": i, "outcome": "success", "zonePrice": zone.get("price", 0), "zoneType": zone.get("type", ""), "score": sig.score}
        self.active_trade = trade
        self.pattern_markers.append(trade.pattern_ref)

    def _check_exit(self, c, i, market):
        t = self.active_trade
        if not t:
            return
        # Stop loss: trigger on ANY cross below (long trades)
        # For long trades, SL is below entry
        if c.low <= t.stop_loss:
            self._close_trade(c, "stop_loss", t.stop_loss)
            return
        # Take profit: trigger on ANY cross above target
        if t.target1 > 0 and c.high >= t.target1:
            self._close_trade(c, "take_profit_1", t.target1)

    def _close_trade(self, c, reason, exit_price):
        t = self.active_trade
        if not t:
            return
        t.exit_time, t.exit_price, t.status = c.time, exit_price, 1
        if t.entry_price > 0:
            pnl_raw = (exit_price - t.entry_price) / t.entry_price
            t.pnl = pnl_raw * self.balance
            t.pnl_pct = pnl_raw * 100
            risk = abs(t.entry_price - t.stop_loss)
            t.rr = abs(exit_price - t.entry_price) / risk if risk > 0 else 0
        self.balance += t.pnl
        self.gate.record(t.pnl_pct, datetime.fromtimestamp(c.time).strftime("%Y-%m-%d"))
        self.trades.append(t)
        self.active_trade = None

    def _calc_metrics(self):
        closed = [t for t in self.trades if t.status == 1]
        if not closed:
            return {"winRate": 0, "winningTrades": 0, "totalTrades": 0, "totalReturn": 0, "maxDrawdown": 0, "profitFactor": 0, "expectancy": 0, "finalBalance": self.balance, "sharpeRatio": 0, "sortinoRatio": 0, "avgRR": 0}
        winners = [t for t in closed if t.pnl > 0]
        losers = [t for t in closed if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in closed)
        total_return = (self.balance - self.cfg.initial_balance) / self.cfg.initial_balance * 100
        peak = self.cfg.initial_balance
        dd = 0
        for eq in self.equity:
            if eq["balance"] > peak:
                peak = eq["balance"]
            draw = (peak - eq["balance"]) / peak * 100
            if draw > dd:
                dd = draw
        gp = sum(t.pnl for t in winners)
        gl = abs(sum(t.pnl for t in losers))
        pf = gp / gl if gl > 0 else None
        rets = [t.pnl_pct for t in closed]
        avg_r = sum(rets) / len(rets) if rets else 0
        std_r = (sum((r - avg_r)**2 for r in rets) / len(rets))**0.5 if len(rets) > 1 else 0
        negs = [r for r in rets if r < 0]
        avg_n = sum(negs) / len(negs) if negs else 0
        std_n = (sum((r - avg_n)**2 for r in negs) / len(negs))**0.5 if len(negs) > 1 else 1
        return {"winRate": round(len(winners)/len(closed)*100, 2), "winningTrades": len(winners), "losingTrades": len(losers), "totalTrades": len(closed), "totalReturn": round(total_return, 2), "maxDrawdown": round(dd, 2), "profitFactor": round(pf, 4) if pf else None, "expectancy": round(total_pnl/len(closed), 2), "finalBalance": round(self.balance, 2), "sharpeRatio": round(avg_r/std_r, 4) if std_r > 0 else 0, "sortinoRatio": round(avg_r/std_n, 4) if std_n > 0 else 0, "avgRR": round(sum(t.rr for t in closed)/len(closed), 2), "grossProfit": round(gp, 2), "grossLoss": round(gl, 2)}


def run_v3_backtest(config=None, candles=None):
    cfg = config or DEFAULT_CONFIG
    engine = EngineV3(cfg)
    if candles:
        engine.load_candles(candles)
    return engine.process_all()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("BACKBAT v3 Engine -- Test Run")
    print("Use run_v3_backtest() with candle data.")

