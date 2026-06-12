"""Algo Engine v1.0 - Confluence Scorer with Trend Gating"""
from typing import Dict, List, Optional, Tuple
from .trend_detector import TrendDetector

BASE_WEIGHTS = {"FVG": 0.40, "Swing": 0.30, "Delta": 0.30}

class ConfluenceScorer:
    """Scores FVG + Swing + Delta with Trend gate multipliers."""
    def __init__(self, quality_thresh=0.40, min_components=2):
        self.trend_detector = TrendDetector()
        self.quality_thresh = quality_thresh
        self.min_components = min_components

    def score(self, candles, fvg_zones, swing_result, delta_result):
        """Score confluence with trend gate applied to each component."""
        cp = candles[-1]["close"] if candles else 0
        if cp <= 0:
            return self._empty_result()

        trend_r = self.trend_detector.analyze(candles)
        trend = trend_r.get("trend", "neutral")
        tc = trend_r.get("confidence", 0)

        bull_signals, bear_signals = [], []

        # FVG
        for z in fvg_zones:
            if "fvg" not in z.get("source", "").lower():
                continue
            sc = BASE_WEIGHTS["FVG"] * min(1.0, z.get("strength", 0) * 2)
            if z.get("type") == "support":
                bull_signals.append((sc, z.get("price", 0), "FVG", z.get("strength", 0)))
            elif z.get("type") == "resistance":
                bear_signals.append((sc, z.get("price", 0), "FVG", z.get("strength", 0)))

        # Swing
        for sl in swing_result.get("swingLows", [])[-10:]:
            if abs(sl["price"] - cp) / max(cp, 1) < 0.015:
                bull_signals.append((BASE_WEIGHTS["Swing"] * 0.8, sl["price"], "Swing", 0.8))
        for sh in swing_result.get("swingHighs", [])[-10:]:
            if abs(sh["price"] - cp) / max(cp, 1) < 0.015:
                bear_signals.append((BASE_WEIGHTS["Swing"] * 0.8, sh["price"], "Swing", 0.8))

        # Delta patterns
        for p in delta_result.get("patterns", []):
            if p.get("significance", 0) < 0.3:
                continue
            sc = BASE_WEIGHTS["Delta"] * min(1.0, p.get("significance", 0) * 2)
            if p.get("direction") in ("long", "bullish"):
                bull_signals.append((sc, cp, "Delta", p.get("significance", 0)))
            elif p.get("direction") in ("short", "bearish"):
                bear_signals.append((sc, cp, "Delta", p.get("significance", 0)))

        # CVD divergences
        for div in delta_result.get("divergences", [])[-3:]:
            ds = div.get("strength", 0)
            if ds < 0.15:
                continue
            sc = BASE_WEIGHTS["Delta"] * min(1.0, ds * 2)
            if div.get("type") == "bullish":
                bull_signals.append((sc, cp, "Delta", ds))
            elif div.get("type") == "bearish":
                bear_signals.append((sc, cp, "Delta", ds))

        # Apply trend gate
        bull_score, bull_comps = self._apply_gate(bull_signals, trend, "long", tc)
        bear_score, bear_comps = self._apply_gate(bear_signals, trend, "short", tc)

        # Determine direction
        direction = None
        if bull_score >= self.quality_thresh and bull_score > bear_score and len(bull_comps) >= self.min_components:
            direction = "long"
        elif bear_score >= self.quality_thresh and bear_score > bull_score and len(bear_comps) >= self.min_components:
            direction = "short"

        return {
            "direction": direction,
            "score": max(bull_score, bear_score),
            "bull_score": round(bull_score, 3),
            "bear_score": round(bear_score, 3),
            "components": list(bull_comps) if direction == "long" else list(bear_comps),
            "component_count": len(bull_comps) if direction == "long" else len(bear_comps),
            "passes_quality": direction is not None,
            "trend": trend_r,
        }

    def _apply_gate(self, signals, trend, sdir, tc):
        """Apply trend gate multipliers to signals."""
        if not signals:
            return 0.0, set()

        if trend == "bullish" and sdir == "long":
            mult = min(2.0, 1.0 + tc * 0.8)
        elif trend == "bearish" and sdir == "short":
            mult = min(2.0, 1.0 + tc * 0.8)
        elif trend == "bullish" and sdir == "short":
            mult = max(0.0, 1.0 - tc * 0.7)
        elif trend == "bearish" and sdir == "long":
            mult = max(0.0, 1.0 - tc * 0.7)
        else:
            mult = 1.0

        if mult <= 0:
            return 0.0, set()

        # Deduplicate by price proximity
        signals.sort(key=lambda s: s[1])
        deduped = [signals[0]]
        for sc, price, name, strength in signals[1:]:
            if abs(price - deduped[-1][1]) / max(deduped[-1][1], 0.01) < 0.003:
                if sc > deduped[-1][0]:
                    deduped[-1] = (sc, price, name, strength)
            else:
                deduped.append((sc, price, name, strength))

        total = sum(s[0] for s in deduped) * mult
        components = set(s[2] for s in deduped)
        return min(1.0, total), components

    def _empty_result(self):
        return {"direction": None, "score": 0, "bull_score": 0, "bear_score": 0,
                "components": [], "component_count": 0, "passes_quality": False,
                "trend": {"trend": "neutral", "confidence": 0, "score": 0}}
