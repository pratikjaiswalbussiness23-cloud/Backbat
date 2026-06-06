"""
BACKBAT v3 -- Layer 3: Probabilistic Scorer
5-Input Composite Score: HTF Structure, Volume Density, OI, Funding, Historical Hit Rate
"""
import logging
from typing import Dict, List, Optional
from config import DEFAULT_CONFIG

logger = logging.getLogger("backbat.scoring")


class ProbabilisticScorer:
    """Core scoring engine. Combines 5 inputs into a composite conviction score."""

    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        sc = self.cfg.scoring
        self.w_htf = sc.weight_htf_structure
        self.w_vol = sc.weight_volume_density
        self.w_oi = sc.weight_oi_buildup
        self.w_fund = sc.weight_funding_bias
        self.w_hist = sc.weight_historical_hit_rate
        self.alert_thresh = sc.alert_threshold
        self.high_conv = sc.high_conviction_threshold

    def score_zone(self, zone_type: str, zone_price: float, market_snapshot: dict,
                   detections: dict, base_rates: dict) -> dict:
        """Score a zone based on all 5 inputs. Returns dict with score and components."""
        htf_score = self._score_htf_structure(zone_type, zone_price, market_snapshot)
        vol_score = self._score_volume_density(zone_price, detections)
        oi_score = self._score_oi_buildup(zone_type, market_snapshot)
        fund_score = self._score_funding_bias(zone_type, market_snapshot)
        hist_score = self._score_historical(zone_type, "bounce", base_rates)

        composite = (htf_score * self.w_htf + vol_score * self.w_vol +
                     oi_score * self.w_oi + fund_score * self.w_fund +
                     hist_score * self.w_hist)

        return {
            "composite_score": round(composite, 3),
            "components": {
                "htf_structure": round(htf_score, 3),
                "volume_density": round(vol_score, 3),
                "oi_buildup": round(oi_score, 3),
                "funding_bias": round(fund_score, 3),
                "historical_hit_rate": round(hist_score, 3),
            },
            "weights": {
                "htf": self.w_htf, "vol": self.w_vol,
                "oi": self.w_oi, "fund": self.w_fund, "hist": self.w_hist,
            },
            "alert": composite >= self.alert_thresh,
            "high_conviction": composite >= self.high_conv,
        }

    def _score_htf_structure(self, zone_type: str, zone_price: float, snapshot: dict) -> float:
        """Score: is this zone at a 4H or daily S/R level?"""
        # In backtest mode, estimate from price structure
        # Use order book imbalance as proxy for HTF alignment
        imb = snapshot.get("ob_imbalance", 0)
        if zone_type == "support":
            # Support zones score higher when imbalance is positive (buyers present)
            return min(1.0, max(0.0, 0.5 + imb * 2))
        else:
            # Resistance zones score higher when imbalance is negative (sellers present)
            return min(1.0, max(0.0, 0.5 - imb * 2))

    def _score_volume_density(self, price: float, detections: dict) -> float:
        """Score based on volume profile density (HVN = higher score)."""
        dens = detections.get("volume_density", 1.0)
        # Normalize: 0.0 = LVN, 0.5 = average, 1.0 = strong HVN
        if dens >= 1.3:
            return 1.0  # Strong HVN
        elif dens >= 0.8:
            return 0.5 + (dens - 0.8) * 1.0  # 0.5 -> 1.0
        else:
            return max(0.0, 0.5 - (0.8 - dens) * 1.5)

    def _score_oi_buildup(self, zone_type: str, snapshot: dict) -> float:
        """Score: are contracts accumulating at this level?"""
        oi_delta = snapshot.get("oi_delta", {}).get("aggregated", 0)
        # Positive OI delta = contracts building = higher conviction
        # Normalize: 0 at 0 OI delta, 1 at large positive
        if oi_delta > 0:
            return min(1.0, oi_delta / 1000)
        else:
            return max(0.0, 0.3 + oi_delta / 1000)

    def _score_funding_bias(self, zone_type: str, snapshot: dict) -> float:
        """Score: is the market positioned against this zone?"""
        funding = snapshot.get("funding", {})
        bias = funding.get("bias", 0)
        crowded_long = funding.get("crowded_long", False)
        crowded_short = funding.get("crowded_short", False)

        if zone_type == "support":
            # Support zones score higher when shorts are crowded (squeeze potential)
            if crowded_short:
                return 1.0
            return max(0.0, 0.5 - bias * 100)
        else:
            # Resistance zones score higher when longs are crowded (liquidation cascade)
            if crowded_long:
                return 1.0
            return max(0.0, 0.5 + bias * 100)

    def _score_historical(self, zone_type: str, target: str, base_rates: dict) -> float:
        """Score: historical hit rate for similar zones."""
        rates = base_rates.get(zone_type, {})
        rate = rates.get(target, 0.0)
        # Base rate of 50% = 0.5 score, 80% = 1.0 score
        return min(1.0, rate * 1.25)

    def should_alert(self, score_result: dict) -> bool:
        """Check if a zone should generate an alert."""
        return score_result.get("high_conviction", False)


class ScoringLayer:
    """Layer 3 orchestrator."""

    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        self.scorer = ProbabilisticScorer(config)
        self.active_zones = []

    def evaluate_zone(self, zone: dict, market: dict, detections: dict, base_rates: dict) -> Optional[dict]:
        """Evaluate a zone and return score if it meets threshold."""
        score = self.scorer.score_zone(
            zone["type"], zone["price"], market, detections, base_rates
        )
        if score["alert"]:
            entry = {
                "zone": zone,
                "score": score,
                "timestamp": 0,
            }
            self.active_zones.append(entry)
            if len(self.active_zones) > self.cfg.scoring.max_zones_tracked:
                self.active_zones = self.active_zones[-self.cfg.scoring.max_zones_tracked:]
            return entry
        return None

    def high_conviction_zones(self) -> list:
        """Get zones with high conviction score (>=70%)."""
        return [z for z in self.active_zones
                if z["score"]["composite_score"] >= self.cfg.scoring.high_conviction_threshold]
