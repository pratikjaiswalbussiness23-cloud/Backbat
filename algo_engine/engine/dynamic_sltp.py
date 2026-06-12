"""
Algo Engine v1.0 - Dynamic SL/TP Placement
Uses market structure (nearest swing + ATR buffer) instead of fixed ATR multiples.
"""

from typing import Dict, List, Optional, Tuple


class DynamicSLTP:
    """Place stop loss and take profit using market structure + ATR buffer."""

    def __init__(self, sl_atr_buffer=0.5, tp1_atr_min=1.2, tp2_atr_min=2.5,
                 partial_exit_ratio=0.5, swing_lookback_sl=10, swing_lookback_tp=20):
        self.sl_atr_buffer = sl_atr_buffer
        self.tp1_atr_min = tp1_atr_min
        self.tp2_atr_min = tp2_atr_min
        self.partial_exit_ratio = partial_exit_ratio
        self.swing_lookback_sl = swing_lookback_sl
        self.swing_lookback_tp = swing_lookback_tp

    def calculate(self, candles, direction: str, entry_price: float, atr: float) -> Dict:
        """Calculate SL and TP using nearest swing + ATR buffer."""
        if atr <= 0 or entry_price <= 0:
            return {"sl": 0, "tp": 0, "tp2": 0, "rr": 0, "rr2": 0, "sl_price": 0, "tp_price": 0, "method": "atr_only"}
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        n = len(candles)
        sl_candidates, tp_candidates = [], []
        for i in range(max(0, n - self.swing_lookback_sl), n - 1):
            is_sl_low = all(lows[i] <= lows[i - j] for j in range(1, min(4, i + 1))) and all(lows[i] <= lows[i + j] for j in range(1, min(4, n - i)))
            is_sh_high = all(highs[i] >= highs[i - j] for j in range(1, min(4, i + 1))) and all(highs[i] >= highs[i + j] for j in range(1, min(4, n - i)))
            if direction == "long":
                if is_sl_low and lows[i] < entry_price: sl_candidates.append(lows[i])
                if is_sh_high and highs[i] > entry_price: tp_candidates.append(highs[i])
            else:
                if is_sh_high and highs[i] > entry_price: sl_candidates.append(highs[i])
                if is_sl_low and lows[i] < entry_price: tp_candidates.append(lows[i])
        for i in range(max(0, n - self.swing_lookback_tp), n - 1):
            is_sl_low = all(lows[i] <= lows[i - j] for j in range(1, min(4, i + 1))) and all(lows[i] <= lows[i + j] for j in range(1, min(4, n - i)))
            is_sh_high = all(highs[i] >= highs[i - j] for j in range(1, min(4, i + 1))) and all(highs[i] >= highs[i + j] for j in range(1, min(4, n - i)))
            if direction == "long":
                if is_sh_high and highs[i] > entry_price: tp_candidates.append(highs[i])
            else:
                if is_sl_low and lows[i] < entry_price: tp_candidates.append(lows[i])
        atr_buffer = atr * self.sl_atr_buffer
        atr_tp1 = atr * self.tp1_atr_min
        atr_tp2 = atr * self.tp2_atr_min
        if direction == "long":
            sl = min(max(sl_candidates) - atr_buffer, entry_price - atr * 1.5) if sl_candidates else entry_price - atr * 1.5
            tp = max(max(tp_candidates), entry_price + atr_tp1) if tp_candidates else entry_price + atr_tp1
            tp2 = entry_price + atr_tp2
        else:
            sl = max(min(sl_candidates) + atr_buffer, entry_price + atr * 1.5) if sl_candidates else entry_price + atr * 1.5
            tp = min(min(tp_candidates), entry_price - atr_tp1) if tp_candidates else entry_price - atr_tp1
            tp2 = entry_price - atr_tp2
        sl_dist = abs(entry_price - sl)
        tp_dist = abs(entry_price - tp)
        tp2_dist = abs(entry_price - tp2)
        rr = round(tp_dist / max(sl_dist, 0.01), 2)
        rr2 = round(tp2_dist / max(sl_dist, 0.01), 2)
        return {"sl": sl_dist, "tp": tp_dist, "tp2": tp2_dist, "rr": rr, "rr2": rr2,
                "sl_price": round(sl, 2), "tp_price": round(tp, 2), "tp2_price": round(tp2, 2),
                "sl_swing": len(sl_candidates) > 0, "tp_swing": len(tp_candidates) > 0, "method": "swing" if sl_candidates else "atr_only"}
