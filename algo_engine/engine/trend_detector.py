"""
Algo Engine v1.0 — Trend Detector
Multi-factor trend analysis for gating signal components.

Uses:
1. ADX (Average Directional Index) — trend strength
2. EMA Slope (EMA9, EMA21, EMA50 alignment) — direction
3. VWAP (Volume-Weighted Average Price) — intraday bias
4. Swing Structure (HH/HL/LH/LL) — market structure trend
5. Composite Trend Score -> {bullish, bearish, neutral} + confidence
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from liq_engine import calc_adx as _calc_adx


class TrendDetector:
    """Multi-factor trend detector that produces a trend gate signal."""

    def __init__(self):
        self.adx_period = 14
        self.ema_periods = [9, 21, 50]
        self.vwap_period = 20

    def analyze(self, candles: List[Dict]) -> Dict:
        """
        Analyze candles and return trend gate result.

        Returns:
            trend: 'bullish', 'bearish', or 'neutral'
            confidence: 0.0-1.0
            score: -1.0 (strong bear) to +1.0 (strong bull)
            adx: current ADX value
            ema_alignment: 'bullish', 'bearish', 'mixed', 'flat'
            vwap_relation: 'above', 'below', 'at'
            swing_trend: 'uptrend', 'downtrend', 'ranging'
            details: dict with all sub-scores
        """
        if len(candles) < 60:
            return self._neutral_result("Insufficient data")

        n = len(candles)
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c.get("volume", 0) for c in candles]

        # 1. ADX - trend strength
        adx = self._calc_adx(candles)
        adx_strength = min(1.0, adx / 40.0)

        # 2. EMA alignment & slope
        ema9 = self._ema(closes, 9)
        ema21 = self._ema(closes, 21)
        ema50 = self._ema(closes, 50) if len(closes) >= 50 else ema21
        ema_alignment = self._assess_ema_alignment(closes[-1], ema9[-1], ema21[-1], ema50[-1])

        ema9_slope = (ema9[-1] - ema9[-6]) / ema9[-6] * 100 if len(ema9) >= 6 else 0
        ema21_slope = (ema21[-1] - ema21[-6]) / ema21[-6] * 100 if len(ema21) >= 6 else 0

        # 3. VWAP
        vwap = self._vwap(candles, self.vwap_period)
        if vwap is not None:
            vwap_relation = "above" if closes[-1] > vwap else ("below" if closes[-1] < vwap else "at")
            vwap_dist = (closes[-1] - vwap) / vwap * 100
        else:
            vwap_relation = "at"
            vwap_dist = 0

        # 4. Swing structure
        swing_trend = self._detect_swing_structure(candles)

        # 5. Price vs MA50
        price_vs_ma50 = closes[-1] / ema50[-1] - 1

        # Composite score
        ema_score_map = {"bullish": 1.0, "bearish": -1.0, "mixed": 0.2, "flat": 0.0}
        ema_score = ema_score_map.get(ema_alignment, 0.0)
        slope_score = np.sign(ema9_slope) * min(1.0, abs(ema9_slope) / 0.5) if abs(ema9_slope) > 0.01 else 0
        vwap_score = min(1.0, max(-1.0, vwap_dist * 10)) if vwap is not None else 0
        swing_score_map = {"uptrend": 1.0, "downtrend": -1.0, "ranging": 0.0}
        swing_score = swing_score_map.get(swing_trend, 0.0)
        ma50_score = min(1.0, max(-1.0, price_vs_ma50 * 20))

        composite = (
            ema_score * 0.35 +
            slope_score * 0.20 +
            vwap_score * 0.15 +
            swing_score * 0.20 +
            ma50_score * 0.10
        )

        factors = [np.sign(ema_score), np.sign(slope_score), np.sign(vwap_score), np.sign(swing_score), np.sign(ma50_score)]
        agreement = sum(1 for f in factors if f == np.sign(composite) and f != 0) / max(sum(1 for f in factors if f != 0), 1)
        confidence = min(1.0, adx_strength * 0.5 + agreement * 0.5)

        if composite >= 0.3 and adx >= 20:
            trend = "bullish"
        elif composite <= -0.3 and adx >= 20:
            trend = "bearish"
        elif composite >= 0.15:
            trend = "bullish"
        elif composite <= -0.15:
            trend = "bearish"
        else:
            trend = "neutral"

        return {
            "trend": trend,
            "confidence": round(confidence, 3),
            "score": round(composite, 3),
            "adx": round(adx, 2),
            "ema_alignment": ema_alignment,
            "vwap_relation": vwap_relation,
            "swing_trend": swing_trend,
            "details": {
                "adx": round(adx, 2),
                "adx_strength": round(adx_strength, 3),
                "ema9": round(ema9[-1], 2) if ema9 else 0,
                "ema21": round(ema21[-1], 2) if ema21 else 0,
                "ema50": round(ema50[-1], 2) if ema50 else 0,
                "ema9_slope": round(ema9_slope, 4),
                "ema21_slope": round(ema21_slope, 4),
                "vwap": round(vwap, 2) if vwap is not None else None,
                "vwap_dist_pct": round(vwap_dist, 3),
                "price_vs_ma50_pct": round(price_vs_ma50 * 100, 3),
                "agreement": round(agreement, 3),
            }
        }

    def get_gate_multiplier(self, trend_result: Dict, signal_direction: str) -> Dict:
        """Apply trend gate to a signal direction."""
        trend = trend_result.get("trend", "neutral")
        score = trend_result.get("score", 0)
        confidence = trend_result.get("confidence", 0)

        if trend == "neutral" or confidence < 0.2:
            return {"multiplier": 1.0, "gate_action": "allow",
                    "reasoning": "No clear trend - signals pass at normal weight"}

        if trend == "bullish":
            if signal_direction == "long":
                mult = min(2.0, 1.0 + confidence * 0.8)
                return {"multiplier": round(mult, 2), "gate_action": "boost",
                        "reasoning": f"Bullish trend - boosting long signals {mult:.1f}x"}
            else:
                mult = max(0.0, 1.0 - confidence * 0.7)
                return {"multiplier": round(mult, 2), "gate_action": "reduce" if mult > 0 else "block",
                        "reasoning": f"Bullish trend - reducing short signals to {mult:.1f}x"}

        if trend == "bearish":
            if signal_direction == "short":
                mult = min(2.0, 1.0 + confidence * 0.8)
                return {"multiplier": round(mult, 2), "gate_action": "boost",
                        "reasoning": f"Bearish trend - boosting short signals {mult:.1f}x"}
            else:
                mult = max(0.0, 1.0 - confidence * 0.7)
                return {"multiplier": round(mult, 2), "gate_action": "reduce" if mult > 0 else "block",
                        "reasoning": f"Bearish trend - reducing long signals to {mult:.1f}x"}

        return {"multiplier": 1.0, "gate_action": "allow", "reasoning": "Neutral market - no gating"}

    def _calc_adx(self, candles, period=14):
        """Calculate ADX — delegates to shared liq_engine implementation."""
        return _calc_adx(candles, period)

    def _ema(self, values, period):
        if len(values) < period:
            return values
        alpha = 2 / (period + 1)
        result = [values[0]]
        for v in values[1:]:
            result.append(alpha * v + (1 - alpha) * result[-1])
        return result

    def _vwap(self, candles, period):
        if len(candles) < period:
            return None
        total_pv = 0
        total_v = 0
        for c in candles[-period:]:
            tp = (c["high"] + c["low"] + c["close"]) / 3
            v = c.get("volume", 0)
            total_pv += tp * v
            total_v += v
        return total_pv / total_v if total_v > 0 else None

    def _assess_ema_alignment(self, price, ema9, ema21, ema50):
        if price > ema9 > ema21 > ema50:
            return "bullish"
        elif price < ema9 < ema21 < ema50:
            return "bearish"
        elif price > ema50 and ema9 > ema21:
            return "mixed"
        else:
            return "flat"

    def _detect_swing_structure(self, candles):
        if len(candles) < 30:
            return "ranging"
        highs = [c["high"] for c in candles[-30:]]
        lows = [c["low"] for c in candles[-30:]]
        recent_highs = highs[-10:]
        recent_lows = lows[-10:]
        prev_highs = highs[-20:-10]
        prev_lows = lows[-20:-10]
        hh = max(recent_highs) > max(prev_highs) * 1.01
        hl = min(recent_lows) > min(prev_lows) * 0.99
        lh = max(recent_highs) < max(prev_highs) * 0.99
        ll = min(recent_lows) < min(prev_lows) * 1.01
        if hh and hl:
            return "uptrend"
        elif lh and ll:
            return "downtrend"
        else:
            return "ranging"

    def _neutral_result(self, reason="Insufficient data"):
        return {
            "trend": "neutral",
            "confidence": 0.0,
            "score": 0.0,
            "adx": 0.0,
            "ema_alignment": "flat",
            "vwap_relation": "at",
            "swing_trend": "ranging",
            "details": {"reason": reason},
        }
