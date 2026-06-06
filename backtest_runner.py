"""BACKBAT v3 -- Walk-Forward Validation Framework"""
import json, logging, time
from datetime import datetime
from typing import Dict, List, Optional
from config import DEFAULT_CONFIG
from engine_v3 import run_v3_backtest
logger = logging.getLogger("backbat.validation")

class RegimeDetector:
    def __init__(self, atr_period=20, adx_period=14):
        self.atr_p, self.adx_p = atr_period, adx_period
    def detect(self, candles):
        if len(candles) < 50:
            return "unknown"
        closes = [c["close"] if isinstance(c, dict) else c.close for c in candles[-50:]]
        highs = [c["high"] if isinstance(c, dict) else c.high for c in candles[-50:]]
        lows = [c["low"] if isinstance(c, dict) else c.low for c in candles[-50:]]
        avg_p = sum(closes)/len(closes)
        trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1,len(highs))]
        atr = sum(trs)/len(trs) if trs else 0
        vol = atr/avg_p if avg_p > 0 else 0
        pc = (closes[-1]-closes[0])/closes[0] if closes[0] > 0 else 0
        if abs(pc) > 0.05 and vol > 0.01:
            return "trending" if pc > 0 else "bear_trend"
        elif vol > 0.02:
            return "volatile"
        return "ranging"
    def volatility_regime(self, candles):
        if len(candles) < 30:
            return "normal"
        closes = [c["close"] if isinstance(c, dict) else c.close for c in candles[-30:]]
        rets = [abs(closes[i]-closes[i-1])/closes[i-1] for i in range(1,len(closes))]
        avg_v = sum(rets)/len(rets) if rets else 0
        if avg_v > 0.005:
            return "high"
        elif avg_v > 0.002:
            return "normal"
        return "low"



class WalkForwardValidator:
    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        self.regime = RegimeDetector()
        self.period_results = []

    def run(self, candles, periods=6):
        self.period_results = []
        if not candles or len(candles) < 200:
            return {"valid": False, "reason": "insufficient_data", "periods": []}
        ps = len(candles) // periods
        if ps < 100:
            periods = max(2, len(candles) // 100)
            ps = len(candles) // periods
        for p in range(periods):
            start = p * ps
            end = min((p + 1) * ps, len(candles))
            if end - start < 100:
                break
            split = start + int((end - start) * 0.8)
            ins = candles[start:split]
            oos = candles[split:end]
            if len(oos) < 30:
                continue
            regime = self.regime.detect(ins)
            in_res = run_v3_backtest(candles=ins)
            out_res = run_v3_backtest(candles=oos)
            self.period_results.append({
                "period": p + 1, "regime": regime,
                "in_sample_size": len(ins), "out_sample_size": len(oos),
                "in_sample_metrics": in_res["metrics"],
                "out_sample_metrics": out_res["metrics"],
            })
        return self.summarize()

    def summarize(self):
        if not self.period_results:
            return {"valid": False, "reason": "no_periods", "periods": []}
        oos = [p["out_sample_metrics"] for p in self.period_results]
        total_trades = sum(m.get("totalTrades", 0) for m in oos)
        avg_wr = sum(m.get("winRate", 0) for m in oos) / len(oos)
        avg_ret = sum(m.get("totalReturn", 0) for m in oos) / len(oos)
        returns = [m.get("totalReturn", 0) for m in oos]
        avg_r = sum(returns)/len(returns) if returns else 0
        std_r = (sum((r-avg_r)**2 for r in returns)/len(returns))**0.5 if len(returns)>1 else 0
        max_dd = max(m.get("maxDrawdown", 0) for m in oos)
        pf_list = [m.get("profitFactor") for m in oos if m.get("profitFactor") is not None]
        avg_pf = sum(pf_list)/len(pf_list) if pf_list else None
        rc = {}
        for p in self.period_results:
            r = p.get("regime", "unknown")
            rc[r] = rc.get(r, 0) + 1
        valid = total_trades >= 30
        return {
            "valid": valid, "total_periods": len(self.period_results),
            "total_oos_trades": total_trades, "avg_oos_win_rate": round(avg_wr, 2),
            "avg_oos_return": round(avg_ret, 2),
            "avg_oos_sharpe": round(avg_r/std_r, 4) if std_r > 0 else 0,
            "max_oos_drawdown": round(max_dd, 2),
            "avg_oos_profit_factor": round(avg_pf, 4) if avg_pf else None,
            "regime_breakdown": rc, "periods": self.period_results,
        }


def run_validation(candles, config=None):
    v = WalkForwardValidator(config)
    return v.run(candles)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("BACKBAT v3 -- Walk-Forward Validator")
    print("Use run_validation(candles) to validate.")
