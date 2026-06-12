"""Algo Engine v1.0 - Backtest Runner"""
import numpy as np
from liq_engine import BinanceClient, FVGBalancer, SwingPointDetector, CVDAnalyzer, DeltaPatternDetector
from ..engine.confluence_scorer import ConfluenceScorer

RISK = 2.0; TX = 0.2; SLIP = 0.05

class BacktestRunner:
    """Mirrors live SignalOrchestrator logic exactly."""
    def __init__(self, thresh=0.40, minc=2):
        self.client = BinanceClient()
        self.scorer = ConfluenceScorer(thresh, minc)
        self.fvg = FVGBalancer(); self.swing = SwingPointDetector()
        self.cvd = CVDAnalyzer(); self.delta = DeltaPatternDetector()

    def run(self, candles, hold=30):
        trades = []
        last_trade_i = -8
        for i in range(60, len(candles) - hold - 1):
            if i - last_trade_i < 8:
                continue
            w, c, f = candles[:i+1], candles[i], candles[i+1:i+1+hold]
            a = self._atr(w)
            if a <= 0:
                continue
            va = sum(x.get("volume", 0) for x in w[-20:]) / max(20, 1)
            if c.get("volume", 0) < va * 0.6:
                continue
            fr = self.fvg.detect(w); sr = self.swing.detect(w)
            cr = self.cvd.calculate(w); dp = self.delta.detect(w, cr.get("perCandleDelta", []))
            cf = self.scorer.score(w, fr.get("zones", []), sr,
                {"patterns": dp.get("patterns", []), "divergences": cr.get("divergences", [])})
            if not cf.get("passes_quality"):
                continue
            d = cf["direction"]; cp = c["close"]
            sltp = self._sltp(w, d, cp, a)
            if d == "long" and (len(f) == 0 or f[0]["close"] <= f[0]["open"]):
                continue
            if d == "short" and (len(f) == 0 or f[0]["close"] >= f[0]["open"]):
                continue
            trades.append(self._sim(cp, d, f, a, sltp["sl"], sltp["tp"]))
            last_trade_i = i
        return trades

    def _sltp(self, candles, direction, entry, atr):
        highs = [c["high"] for c in candles]; lows = [c["low"] for c in candles]
        n = len(candles); sl_c = []; tp_c = []
        for i in range(max(0, n-10), n-1):
            is_sl = all(lows[i] <= lows[i-j] for j in range(1, min(4, i+1))) and all(lows[i] <= lows[i+j] for j in range(1, min(4, n-i)))
            is_sh = all(highs[i] >= highs[i-j] for j in range(1, min(4, i+1))) and all(highs[i] >= highs[i+j] for j in range(1, min(4, n-i)))
            if direction == "long":
                if is_sl and lows[i] < entry: sl_c.append(lows[i])
                if is_sh and highs[i] > entry: tp_c.append(highs[i])
            else:
                if is_sh and highs[i] > entry: sl_c.append(highs[i])
                if is_sl and lows[i] < entry: tp_c.append(lows[i])
        for i in range(max(0, n-20), n-1):
            is_sh = all(highs[i] >= highs[i-j] for j in range(1, min(4, i+1))) and all(highs[i] >= highs[i+j] for j in range(1, min(4, n-i)))
            is_sl = all(lows[i] <= lows[i-j] for j in range(1, min(4, i+1))) and all(lows[i] <= lows[i+j] for j in range(1, min(4, n-i)))
            if direction == "long":
                if is_sh and highs[i] > entry: tp_c.append(highs[i])
            else:
                if is_sl and lows[i] < entry: tp_c.append(lows[i])
        if direction == "long":
            sl = min(max(sl_c) - atr*0.5, entry - atr*1.5) if sl_c else entry - atr*1.5
            tp = max(max(tp_c), entry + atr*1.2) if tp_c else entry + atr*3.0
        else:
            sl = max(min(sl_c) + atr*0.5, entry + atr*1.5) if sl_c else entry + atr*1.5
            tp = min(min(tp_c), entry - atr*1.2) if tp_c else entry - atr*3.0
        return {"sl": sl, "tp": tp}

    def _sim(self, entry, d, fc, atr, sl, tp):
        if atr <= 0:
            return {"r": "T", "p": 0}
        if fc:
            entry = fc[0]["open"]
        entry *= (1 + SLIP/100) if d == "long" else (1 - SLIP/100)
        wp = RISK * 2.0; lp = -RISK
        for i, c in enumerate(fc):
            if d == "long":
                if c["low"] <= sl: return {"r": "L", "p": lp - TX, "b": i+1}
                if c["high"] >= tp: return {"r": "W", "p": wp - TX, "b": i+1}
            else:
                if c["high"] >= sl: return {"r": "L", "p": lp - TX, "b": i+1}
                if c["low"] <= tp: return {"r": "W", "p": wp - TX, "b": i+1}
        if fc:
            l = fc[-1]
            mv = ((l["close"] - entry)/entry*100) if d == "long" else ((entry - l["close"])/entry*100)
            sd = abs(entry - sl)
            ar = mv/(sd/entry*100) if sd > 0 else 0
            pnl = ar*RISK - TX; pnl = max(lp, min(wp, pnl))
            return {"r": "W" if pnl > 0 else "L", "p": round(pnl, 4), "b": len(fc)}
        return {"r": "T", "p": 0}

    def _atr(self, c, period=14):
        if len(c) < period+1:
            return 0
        tr = []
        for i in range(1, len(c)):
            h, l, pc = c[i]["high"], c[i]["low"], c[i-1]["close"]
            tr.append(max(h-l, abs(h-pc), abs(l-pc)))
        if len(tr) < period:
            return float(np.mean(tr)) if tr else 0
        a = float(np.mean(tr[:period]))
        for i in range(period, len(tr)):
            a = (a*(period-1)+tr[i])/period
        return a
