"""
Liquidity Identifier Engine v2.0 — Institutional-Grade
Detects: Order Blocks, Fair Value Gaps, Liquidity Sweeps,
Swing Point Liquidity, Volume Profile HVN/LVN, CVD Divergence.
Uses free Binance REST API (no API keys required).
"""

import json
import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests
import yfinance as yf
import pandas as pd

# Multiple Binance endpoints for geo-restriction fallback
BINANCE_ENDPOINTS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]
BINANCE_FUTURES = "https://fapi.binance.com"
BINANCE_BASE = BINANCE_ENDPOINTS[0]  # Primary endpoint

Z = 2.0  # Z-score threshold for order book walls

# ─── Quality-Only Confluence Config (backtested: PF 2.47) ───
# Removed low-performing components: OB (29.4% WR, PF 0.59), Sweep (1 trade), VP (8 trades)
# Kept: FVG (46% WR, PF 1.32), Swing (47% WR, PF 1.29), Delta (56% WR, PF 1.57)
QUALITY_ONLY_THRESH = 0.50      # Minimum weighted score for quality mode
QUALITY_MIN_COMPONENTS = 2      # Minimum distinct component sources required (was 3, lowered for 3 comps)
QUALITY_EXCLUDED_SYMBOLS = ["BNBUSDT"]  # Symbols excluded in quality mode (weak performers)

# Component weights for confluence scoring (optimized: FVG+Swing+Delta only)
CONFLUENCE_WEIGHTS = {"FVG": 0.40, "Swing": 0.25, "Delta": 0.35}


# ─── Market Regime Filter ──────────────────────────────────────

def calc_adx(candles, period=14):
    """Calculate Average Directional Index (ADX)."""
    if len(candles) < period * 2 + 1:
        return 0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        ph, pl = candles[i - 1]["high"], candles[i - 1]["low"]
        up = h - ph
        down = pl - l
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        trs.append(max(h - l, abs(h - candles[i - 1]["close"]), abs(l - candles[i - 1]["close"])))
    if len(trs) < period:
        return 0
    atr_s = float(np.mean(trs[:period]))
    plus_s = float(np.mean(plus_dm[:period]))
    minus_s = float(np.mean(minus_dm[:period]))
    dx_vals = []
    for i in range(period, len(trs)):
        atr_s = (atr_s * (period - 1) + trs[i]) / period
        plus_s = (plus_s * (period - 1) + plus_dm[i]) / period
        minus_s = (minus_s * (period - 1) + minus_dm[i]) / period
        if atr_s > 0:
            plus_di = plus_s / atr_s * 100
            minus_di = minus_s / atr_s * 100
        else:
            plus_di = minus_di = 0
        di_sum = plus_di + minus_di
        dx = abs(plus_di - minus_di) / di_sum * 100 if di_sum > 0 else 0
        dx_vals.append(dx)
    if not dx_vals:
        return 0
    adx = float(np.mean(dx_vals[:period]))
    for i in range(period, len(dx_vals)):
        adx = (adx * (period - 1) + dx_vals[i]) / period
    return adx


def calc_bb_width(candles, period=20, num_std=2.0):
    """Calculate Bollinger Band width as a percentage of price."""
    if len(candles) < period:
        return None
    closes = [c["close"] for c in candles[-period:]]
    mid = sum(closes) / period
    variance = sum((x - mid) ** 2 for x in closes) / period
    std = variance ** 0.5
    upper = mid + num_std * std
    lower = mid - num_std * std
    bb_width = (upper - lower) / max(mid, 0.01) * 100
    return bb_width


def detect_market_regime(candles, adx_min_trend=25, adx_choppy=20, bb_squeeze=3.0, bb_wide=6.0):
    """Detect market regime using ADX + Bollinger Band width.

    Returns:
      regime: 'trending', 'choppy', 'squeeze', or 'neutral'
      risk_mult: position size multiplier (0.0 = skip, 0.5 = half, 1.0 = full)
      adx: current ADX value
      bb_width: current BB width (%)
    """
    adx = calc_adx(candles)
    bb_width = calc_bb_width(candles)
    if bb_width is None:
        return {"regime": "unknown", "risk_mult": 0.5, "adx": adx, "bb_width": 0}

    is_trending = adx >= adx_min_trend
    is_choppy = adx < adx_choppy
    is_squeeze = bb_width < bb_squeeze
    is_volatile = bb_width > bb_wide

    if is_squeeze and is_choppy:
        return {"regime": "squeeze", "risk_mult": 0.0, "adx": adx, "bb_width": bb_width}
    elif is_choppy or is_squeeze:
        return {"regime": "choppy", "risk_mult": 0.5, "adx": adx, "bb_width": bb_width}
    elif is_trending and is_volatile:
        return {"regime": "trending", "risk_mult": 1.0, "adx": adx, "bb_width": bb_width}
    else:
        return {"regime": "neutral", "risk_mult": 1.0, "adx": adx, "bb_width": bb_width}


# ─── Binance Client ───────────────────────────────────────────

class RequestCache:
    """Simple in-memory cache for HTTP responses to reduce API calls."""
    def __init__(self, ttl=5):
        self._data = {}
        self._ttl = ttl

    def get(self, key):
        entry = self._data.get(key)
        if entry and (time.time() - entry["ts"]) < self._ttl:
            return entry["value"]
        return None

    def set(self, key, value):
        self._data[key] = {"value": value, "ts": time.time()}
        if len(self._data) > 100:
            now = time.time()
            self._data = {k: v for k, v in self._data.items() if (now - v["ts"]) < self._ttl * 3}


class BinanceClient:
    """Thin client for Binance REST API with request-level caching and geo-fallback."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LiquidityIdentifier/2.0"})
        self.cache = RequestCache(ttl=5)
        self._working_base = None  # Cache the working endpoint

    def _try_endpoints(self, path, params, timeout=10):
        """Try all Binance endpoints until one works (geo-restriction fallback)."""
        # If we already know which endpoint works, use it first
        endpoints = list(BINANCE_ENDPOINTS)
        if self._working_base and self._working_base in endpoints:
            endpoints.remove(self._working_base)
            endpoints.insert(0, self._working_base)

        last_error = None
        for base in endpoints:
            try:
                url = f"{base}{path}"
                resp = self.session.get(url, params=params, timeout=timeout)
                resp.raise_for_status()
                self._working_base = base  # Cache the working endpoint
                return resp.json()
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(f"All Binance endpoints failed. Last error: {last_error}")

    def klines(self, symbol="BTCUSDT", interval="15m", limit=200):
        cache_key = f"klines:{symbol}:{interval}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            data = self._try_endpoints("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
            result = [{
                "time": k[0] // 1000,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5])
            } for k in data]
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            raise RuntimeError(f"Failed to fetch price data: Binance API error (klines): {e}")

    def depth(self, symbol="BTCUSDT", limit=100):
        cache_key = f"depth:{symbol}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            data = self._try_endpoints("/api/v3/depth", {"symbol": symbol, "limit": limit})
            result = {
                "bids": [[float(p), float(q)] for p, q in data["bids"]],
                "asks": [[float(p), float(q)] for p, q in data["asks"]],
            }
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            raise RuntimeError(f"Binance API error (depth): {e}")

    def ticker_price(self, symbol="BTCUSDT"):
        cache_key = f"ticker:{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            data = self._try_endpoints("/api/v3/ticker/price", {"symbol": symbol})
            result = float(data["price"])
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            raise RuntimeError(f"Binance API error (ticker): {e}")


# ─── Order Book Analyzer ──────────────────────────────────────

class OrderBookAnalyzer:
    """Detect liquidity walls, clusters, and imbalances from order book."""

    @staticmethod
    def analyze(bids, asks, current_price, z_threshold=Z):
        bid_levels = [(p, q) for p, q in bids]
        ask_levels = [(p, q) for p, q in asks]

        bid_vol = sum(q for _, q in bid_levels)
        ask_vol = sum(q for _, q in ask_levels)

        bid_walls = OrderBookAnalyzer._find_walls(bid_levels, "bid", z_threshold)
        ask_walls = OrderBookAnalyzer._find_walls(ask_levels, "ask", z_threshold)

        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0

        return {
            "bids": [{"price": round(p, 2), "volume": round(q, 6)} for p, q in bid_levels],
            "asks": [{"price": round(p, 2), "volume": round(q, 6)} for p, q in ask_levels],
            "totalBidVolume": round(bid_vol, 4),
            "totalAskVolume": round(ask_vol, 4),
            "bidAskRatio": round(bid_vol / ask_vol, 4) if ask_vol > 0 else 0,
            "imbalance": round(imbalance, 4),
            "bidWalls": bid_walls,
            "askWalls": ask_walls,
            "currentPrice": current_price,
        }

    @staticmethod
    def _find_walls(levels, side, z_threshold):
        if len(levels) < 5:
            return []
        volumes = [q for _, q in levels]
        prices = [p for p, _ in levels]
        mean_v = np.mean(volumes)
        std_v = np.std(volumes)
        if std_v < 1e-8:
            return []
        walls = []
        for i, (p, q) in enumerate(levels):
            z = (q - mean_v) / std_v
            if z > z_threshold:
                walls.append({
                    "price": round(p, 2),
                    "volume": round(q, 4),
                    "strength": round(min((z - z_threshold) / 3, 1.0), 3),
                    "side": side,
                })
        return walls

    @staticmethod
    def extract_zones(depth_result, current_price, max_zones=8):
        zones = []
        for w in depth_result.get("bidWalls", []):
            dist = (current_price - w["price"]) / current_price
            zones.append({
                "type": "support",
                "subtype": "order_wall",
                "price": w["price"],
                "strength": w["strength"],
                "volume": w["volume"],
                "source": "order_wall",
                "distance": round(dist * 100, 2),
                "isFresh": True,
            })
        for w in depth_result.get("askWalls", []):
            dist = (w["price"] - current_price) / current_price
            zones.append({
                "type": "resistance",
                "subtype": "order_wall",
                "price": w["price"],
                "strength": w["strength"],
                "volume": w["volume"],
                "source": "order_wall",
                "distance": round(dist * 100, 2),
                "isFresh": True,
            })
        zones.sort(key=lambda z: z["strength"], reverse=True)
        return zones[:max_zones]


# ─── Structural Swing Point Detector ──────────────────────────

class SwingPointDetector:
    """
    Institutional-Grade Swing Point Detector v2.

    Upgrades over basic fractal detection:
    1. Volume at pivot (spike = institutional absorption)
    2. Freshness decay (first touch = max, retested = degraded)
    3. Structure impact (BOS/CHoCH caused = bonus)
    4. Impulse velocity (sharp rejection = strong)
    5. Multi-timeframe via lookback sizing
    6. Proximity to current price
    """

    @staticmethod
    def detect(candles, lookback=5, lookforward=3):
        if len(candles) < lookback + lookforward + 1:
            return {"swingHighs": [], "swingLows": [], "zones": [], "structure": []}

        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        n = len(candles)

        # Pre-compute average volume for scoring
        vol_period = min(20, n)
        avg_vol = sum(c.get("volume", 0) for c in candles[-vol_period:]) / max(vol_period, 1)

        swing_highs = []
        swing_lows = []
        structure_points = []  # BOS / CHoCH markers

        # ── Detect swing highs / lows ──
        for i in range(lookback, n - lookforward):
            is_sh = True
            for j in range(1, lookback + 1):
                if highs[i] <= highs[i - j]:
                    is_sh = False
                    break
            if is_sh:
                for j in range(1, lookforward + 1):
                    if highs[i] <= highs[i + j]:
                        is_sh = False
                        break
            if is_sh:
                swing_highs.append({"index": i, "price": round(highs[i], 2), "time": candles[i]["time"]})

            is_sl = True
            for j in range(1, lookback + 1):
                if lows[i] >= lows[i - j]:
                    is_sl = False
                    break
            if is_sl:
                for j in range(1, lookforward + 1):
                    if lows[i] >= lows[i + j]:
                        is_sl = False
                        break
            if is_sl:
                swing_lows.append({"index": i, "price": round(lows[i], 2), "time": candles[i]["time"]})

        # ── Detect Break of Structure (BOS) ──
        for sh_idx in range(3, len(swing_highs)):
            prev = swing_highs[sh_idx - 1]["price"]
            curr = swing_highs[sh_idx]["price"]
            prev_low = swing_highs[sh_idx - 1]["index"]
            curr_idx = swing_highs[sh_idx]["index"]
            interval_max = max(highs[prev_low:curr_idx + 1])
            if interval_max > prev and curr > prev:
                structure_points.append({
                    "index": curr_idx, "type": "BOS", "direction": "up",
                    "price": curr, "time": candles[curr_idx]["time"], "breakLevel": prev,
                })

        for sl_idx in range(3, len(swing_lows)):
            prev = swing_lows[sl_idx - 1]["price"]
            curr = swing_lows[sl_idx]["price"]
            prev_high = swing_lows[sl_idx - 1]["index"]
            curr_idx = swing_lows[sl_idx]["index"]
            interval_min = min(lows[prev_high:curr_idx + 1])
            if interval_min < prev and curr < prev:
                structure_points.append({
                    "index": curr_idx, "type": "BOS", "direction": "down",
                    "price": curr, "time": candles[curr_idx]["time"], "breakLevel": prev,
                })

        # ── Detect Change of Character (CHoCH) ──
        if len(swing_highs) > 3 and len(swing_lows) > 3:
            last_shs = swing_highs[-4:]
            last_sls = swing_lows[-4:]
            sh_prices = [s["price"] for s in last_shs]
            sl_prices = [s["price"] for s in last_sls]
            if len(sh_prices) >= 2 and len(sl_prices) >= 2:
                if (sh_prices[-1] < sh_prices[-2] and
                        sl_prices[-1] < sl_prices[-2] and
                        closes[-1] < sl_prices[-2]):
                    structure_points.append({
                        "index": n - 1, "type": "CHoCH", "direction": "bearish",
                        "price": round(closes[-1], 2), "time": candles[-1]["time"],
                    })
                elif (sh_prices[-1] > sh_prices[-2] and
                      sl_prices[-1] > sl_prices[-2] and
                      closes[-1] > sh_prices[-2]):
                    structure_points.append({
                        "index": n - 1, "type": "CHoCH", "direction": "bullish",
                        "price": round(closes[-1], 2), "time": candles[-1]["time"],
                    })

        # ── Build a set of structure-impacting indices for scoring ──
        bos_choch_indices = {sp["index"] for sp in structure_points}
        # Also mark indices that caused BOS/CHoCH (the swing before the break)
        structure_cause_indices = set()
        for sp in structure_points:
            if sp["type"] == "BOS" and sp["direction"] == "up":
                for sh in swing_highs:
                    if sh["index"] < sp["index"] and abs(sh["price"] - sp.get("breakLevel", 0)) < 0.01:
                        structure_cause_indices.add(sh["index"])
            elif sp["type"] == "BOS" and sp["direction"] == "down":
                for sl in swing_lows:
                    if sl["index"] < sp["index"] and abs(sl["price"] - sp.get("breakLevel", 0)) < 0.01:
                        structure_cause_indices.add(sl["index"])

        # ── Generate scored liquidity zones from swing points ──
        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2
        zones = []

        for sl in swing_lows[-20:]:
            si = sl["index"]
            zone = SwingPointDetector._score_swing(
                candles, si, "support", sl["price"], sl["time"],
                cp, avg_vol, n, lookback, bos_choch_indices, structure_cause_indices)
            zones.append(zone)

        for sh in swing_highs[-20:]:
            si = sh["index"]
            zone = SwingPointDetector._score_swing(
                candles, si, "resistance", sh["price"], sh["time"],
                cp, avg_vol, n, lookback, bos_choch_indices, structure_cause_indices)
            zones.append(zone)

        return {
            "swingHighs": swing_highs[-30:],
            "swingLows": swing_lows[-30:],
            "structure": structure_points[-10:],
            "zones": zones,
        }

    @staticmethod
    def _score_swing(candles, idx, zone_type, price, time_val,
                     cp, avg_vol, n, lookback, bos_indices, cause_indices):
        """
        Score a swing point with institutional metrics.

        Factors:
        1. Volume at pivot (spike = institutional absorption, 0-1)
        2. Freshness (first touch = 1.0, decays with age)
        3. Structure impact (caused BOS/CHoCH = bonus)
        4. Impulse velocity (speed of rejection after touch)
        5. Multi-timeframe proxy (larger lookback = higher TF)
        6. Proximity to current price
        """
        c = candles[idx]

        # ── 1. Volume at pivot ──
        # Higher volume at the swing = more institutional absorption
        pivot_vol = c.get("volume", 0)
        vol_ratio = pivot_vol / max(avg_vol, 0.001)
        # Score: 2.0x avg = 1.0, 1.0x = 0.5, 0.5x = 0.2
        vol_score = min(1.0, max(0.1, (vol_ratio - 0.3) / 1.7))

        # ── 2. Freshness: exponential decay from creation ──
        age = n - 1 - idx  # candles since swing was formed
        # Half-life of 40 candles (swing points last longer than OBs)
        freshness = max(0.1, 2.0 ** (-age / 40.0))

        # ── 3. Structure impact ──
        # Did this swing cause a BOS/CHoCH? Bonus if yes.
        structure_bonus = 0.0
        if idx in cause_indices:
            structure_bonus = 0.25  # Significant bonus
        elif idx in bos_indices:
            structure_bonus = 0.15  # Some bonus if it was the break itself

        # ── 4. Impulse velocity (rejection strength) ──
        # Measure how quickly price moved away from the swing
        impulse_score = 0.5  # default
        if zone_type == "support" and idx + 5 < n:
            # For support: measure upward move in next 5 candles
            max_move = max(candles[j]["high"] for j in range(idx + 1, min(idx + 6, n)))
            move_pct = (max_move - price) / max(price, 0.01) * 100
            impulse_score = min(1.0, max(0.2, move_pct / 1.0))  # 1% move = 1.0 score
        elif zone_type == "resistance" and idx + 5 < n:
            # For resistance: measure downward move in next 5 candles
            min_move = min(candles[j]["low"] for j in range(idx + 1, min(idx + 6, n)))
            move_pct = (price - min_move) / max(price, 0.01) * 100
            impulse_score = min(1.0, max(0.2, move_pct / 1.0))

        # ── 5. Multi-timeframe proxy (lookback sizing) ──
        # Larger lookback = higher timeframe equivalent = stronger
        # lookback 3 = 15m, lookback 5 = 1H equivalent, lookback 10 = 4H equivalent
        tf_score = min(1.0, lookback / 10.0)

        # ── 6. Proximity to current price ──
        dist = abs(price - cp) / max(cp, 1)
        proximity = max(0.2, 1.0 - dist * 10)

        # ── Composite strength score ──
        strength = (
            vol_score * 0.20 +          # volume at pivot
            freshness * 0.20 +           # freshness decay
            structure_bonus +            # structure impact (0-0.25)
            impulse_score * 0.20 +       # rejection velocity
            tf_score * 0.10 +            # multi-timeframe proxy
            proximity * 0.10             # proximity
        )
        strength = round(min(1.0, max(0.05, strength)), 3)

        # Re-tested check: has price come back to this level since?
        retested = False
        for j in range(idx + 1, n):
            c2 = candles[j]
            tolerance = price * 0.002  # 0.2% tolerance
            if zone_type == "support":
                if abs(c2["low"] - price) < tolerance:
                    retested = True
                    break
            else:
                if abs(c2["high"] - price) < tolerance:
                    retested = True
                    break

        return {
            "type": zone_type,
            "subtype": "swing_low" if zone_type == "support" else "swing_high",
            "price": price,
            "strength": strength,
            "source": "swing_low" if zone_type == "support" else "swing_high",
            "time": time_val,
            "distance": round(abs(price - cp) / max(cp, 1) * 100, 2),
            "isFresh": not retested and age < 3,
            "volScore": round(vol_score, 3),
            "freshnessScore": round(freshness, 3),
            "structureBonus": structure_bonus,
            "impulseScore": round(impulse_score, 3),
            "retested": retested,
            "age": age,
        }



# ─── Order Block Detector (ICT / Smart Money Concept) ─────────

class OrderBlockDetector:
    """
    Institutional-Grade Order Block Detector v2.

    Upgrades over basic ICT definition:
    1. Full impulse measurement (tracks entire displacement, not just 3 candles)
    2. Impulse velocity (speed of move away — faster = more institutional conviction)
    3. Volume Profile alignment (OB at HVN = strong, LVN = weak)
    4. Freshness decay (exponential — older blocks lose probability)
    5. Mitigation detection (has price returned to fill the block?)
    6. Body-to-range ratio (larger bearish/bullish body before impulse = more conviction)
    """

    @staticmethod
    def detect(candles, min_impulse_pct=0.15):
        """
        Find order blocks with institutional-grade scoring.
        """
        if len(candles) < 15:
            return {"orderBlocks": [], "zones": []}

        obs = []
        n = len(candles)
        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2

        # Pre-compute volume profile bins for volume-weighted scoring
        vp_bins = OrderBlockDetector._compute_vp_bins(candles)

        for i in range(5, n - 3):
            ob_candle = candles[i]
            is_bearish_ob = (ob_candle["close"] < ob_candle["open"])
            is_bullish_ob = (ob_candle["close"] > ob_candle["open"])
            next_c = candles[i + 1]

            # ── Bullish Order Block: bearish candle → strong bullish impulse ──
            if is_bearish_ob and next_c["close"] > next_c["open"]:
                ob = OrderBlockDetector._score_ob(
                    candles, i, "bullish", vp_bins, min_impulse_pct, cp)
                if ob:
                    obs.append(ob)

            # ── Bearish Order Block: bullish candle → strong bearish impulse ──
            if is_bullish_ob and next_c["close"] < next_c["open"]:
                ob = OrderBlockDetector._score_ob(
                    candles, i, "bearish", vp_bins, min_impulse_pct, cp)
                if ob:
                    obs.append(ob)

        # Convert to zones with institutional scoring
        zones = []
        for ob in obs[-15:]:
            zones.append({
                "type": "support" if ob["type"] == "bullish" else "resistance",
                "subtype": "order_block",
                "price": ob["price"],
                "priceLow": ob["priceLow"],
                "priceHigh": ob["priceHigh"],
                "strength": ob["strength"],
                "source": "order_block",
                "time": ob["time"],
                "impulse": ob["impulse"],
                "isFresh": ob["isFresh"],
                "mitigated": ob["mitigated"],
                "impulseVelocity": ob["impulseVelocity"],
                "freshnessScore": ob["freshnessScore"],
                "volumeProfileAlign": ob["volumeProfileAlign"],
                "bodyRatio": ob["bodyRatio"],
            })

        return {"orderBlocks": obs[-15:], "zones": zones}

    @staticmethod
    def _compute_vp_bins(candles, num_bins=30):
        """Build a simple volume profile map: price_range -> relative_volume."""
        if len(candles) < 10:
            return {}
        pmin = min(c["low"] for c in candles)
        pmax = max(c["high"] for c in candles)
        if pmax - pmin < 0.5:
            return {}
        bs = (pmax - pmin) / num_bins
        bins = [0.0] * num_bins
        for c in candles:
            mid = (c["high"] + c["low"]) / 2
            idx = int((mid - pmin) / bs)
            idx = max(0, min(num_bins - 1, idx))
            bins[idx] += c.get("volume", 0)
        avg_vol = sum(bins) / max(len(bins), 1)
        if avg_vol <= 0:
            return {}
        # Return normalized volume ratio for each bin
        return {i: bins[i] / avg_vol for i in range(num_bins) if bins[i] > 0}

    @staticmethod
    def _vp_score_for_price(candles, price, vp_bins, num_bins=30):
        """Return volume profile alignment score (0.0-1.0) for a price level.
        HVN (ratio > 1.3) = high score (institutional interest confirmed).
        LVN (ratio < 0.4) = low score (liquidity void, less institutional presence).
        """
        if not vp_bins:
            return 0.5  # neutral if no VP data
        pmin = min(c["low"] for c in candles)
        pmax = max(c["high"] for c in candles)
        if pmax <= pmin:
            return 0.5
        bs = (pmax - pmin) / num_bins
        idx = int((price - pmin) / bs)
        idx = max(0, min(num_bins - 1, idx))
        ratio = vp_bins.get(idx, 1.0)
        # Map ratio to score: 2.0+ = 1.0, 1.3 = 0.8, 1.0 = 0.5, 0.4 = 0.2, 0.0 = 0.0
        return min(1.0, max(0.0, (ratio - 0.2) / 1.8))

    @staticmethod
    def _score_ob(candles, ob_idx, ob_type, vp_bins, min_impulse_pct, cp):
        """
        Score an order block with institutional metrics.
        Returns the scored OB dict or None if impulse is too small.
        """
        n = len(candles)
        ob_candle = candles[ob_idx]

        # ── 1. Measure full impulse (not just 3 candles) ──
        # Track until momentum fades: consecutive candles in impulse direction
        # or until we hit 15 candles max
        impulse_start_idx = ob_idx + 1
        if ob_type == "bullish":
            impulse_low = ob_candle["low"]
            impulse_end = ob_candle["low"]
            max_idx = min(ob_idx + 16, n)
            for j in range(impulse_start_idx, max_idx):
                c = candles[j]
                if c["close"] > c["open"] or (j == impulse_start_idx):
                    impulse_end = max(impulse_end, c["high"])
                else:
                    # Momentum fading — stop measuring
                    break
            impulse_pct = (impulse_end - impulse_low) / max(impulse_low, 0.01) * 100
        else:
            impulse_high = ob_candle["high"]
            impulse_end = ob_candle["high"]
            max_idx = min(ob_idx + 16, n)
            for j in range(impulse_start_idx, max_idx):
                c = candles[j]
                if c["close"] < c["open"] or (j == impulse_start_idx):
                    impulse_end = min(impulse_end, c["low"])
                else:
                    break
            impulse_pct = (impulse_high - impulse_end) / max(impulse_high, 0.01) * 100

        if impulse_pct < min_impulse_pct:
            return None

        # ── 2. Impulse velocity (candles per % move) ──
        impulse_candles = min(max_idx - impulse_start_idx, 15)
        if impulse_candles < 1:
            impulse_candles = 1
        velocity = impulse_pct / impulse_candles  # % per candle
        # Normalize: fast move (>0.3%/candle) = 1.0, slow (<0.05%/candle) = 0.2
        velocity_score = min(1.0, max(0.2, velocity / 0.3))

        # ── 3. Body-to-range ratio (conviction of the OB candle) ──
        body = abs(ob_candle["close"] - ob_candle["open"])
        rng = ob_candle["high"] - ob_candle["low"]
        body_ratio = body / max(rng, 0.01)
        # Larger body = more conviction. Score: 0.5+ body ratio = strong
        body_score = min(1.0, max(0.3, body_ratio))

        # ── 4. Volume Profile alignment ──
        ob_mid = (ob_candle["low"] + ob_candle["high"]) / 2
        vp_score = OrderBlockDetector._vp_score_for_price(candles, ob_mid, vp_bins)

        # ── 5. Freshness: exponential decay from creation ──
        age = len(candles) - 1 - ob_idx  # candles since creation
        # Half-life of 30 candles: after 30 candles, score is 0.5
        freshness = max(0.1, 2.0 ** (-age / 30.0))

        # ── 6. Mitigation detection ──
        # Has price returned to the OB zone since creation?
        mitigated = False
        ob_low = ob_candle["low"]
        ob_high = ob_candle["high"]
        for j in range(ob_idx + 2, len(candles)):
            c = candles[j]
            if ob_type == "bullish":
                # Bullish OB mitigated when price dips back into the zone
                if c["low"] <= ob_high and c["low"] >= ob_low:
                    mitigated = True
                    break
            else:
                # Bearish OB mitigated when price rallies back into the zone
                if c["high"] >= ob_low and c["high"] <= ob_high:
                    mitigated = True
                    break
        mitigation_score = 0.6 if mitigated else 1.0  # mitigated = reduced strength

        # ── 7. Distance from current price ──
        dist = abs(ob_mid - cp) / max(cp, 1)
        dist_score = max(0.3, 1.0 - dist * 6)

        # ── Composite strength score ──
        strength = (
            min(1.0, impulse_pct / 2) * 0.25 +    # impulse size
            velocity_score * 0.20 +                  # impulse velocity
            body_score * 0.10 +                      # OB candle conviction
            vp_score * 0.15 +                        # volume profile alignment
            freshness * 0.10 +                       # freshness decay
            dist_score * 0.10 +                      # proximity
            mitigation_score * 0.10                  # mitigation status
        )
        strength = round(min(1.0, max(0.05, strength)), 3)

        is_fresh = not mitigated and age < 2

        return {
            "type": ob_type,
            "price": round(ob_mid, 2),
            "priceLow": round(ob_candle["low"], 2),
            "priceHigh": round(ob_candle["high"], 2),
            "strength": strength,
            "impulse": round(impulse_pct, 2),
            "impulseVelocity": round(velocity_score, 3),
            "bodyRatio": round(body_ratio, 3),
            "volumeProfileAlign": round(vp_score, 3),
            "freshnessScore": round(freshness, 3),
            "mitigated": mitigated,
            "isFresh": is_fresh,
            "age": age,
            "index": ob_idx,
            "time": candles[ob_idx]["time"],
        }


# ─── Fair Value Gap Detector ──────────────────────────────────

class FVGBalancer:
    """
    Detects Fair Value Gaps (FVG) — also known as imbalances.
    FVG = gap between consecutive candle wicks where price
    moved so fast the order book couldn't fill all orders.
    These gaps act as price magnets for rebalancing.
    """

    @staticmethod
    def detect(candles, min_gap_pct=0.02):
        """
        Find FVGs:
        - Bullish FVG: low of candle i+1 > high of candle i-1 (gap upward)
        - Bearish FVG: high of candle i+1 < low of candle i-1 (gap downward)
        """
        if len(candles) < 5:
            return {"fvgs": [], "zones": []}

        fvgs = []
        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2

        for i in range(1, len(candles) - 1):
            prev, curr, nxt = candles[i - 1], candles[i], candles[i + 1]

            # Bullish FVG: next low > prev high (price jumped up)
            if nxt["low"] > prev["high"]:
                gap_top = nxt["low"]
                gap_bottom = prev["high"]
                gap_size = gap_top - gap_bottom
                gap_pct = gap_size / prev["high"] * 100

                if gap_pct >= min_gap_pct:
                    gap_mid = (gap_top + gap_bottom) / 2
                    dist = abs(gap_mid - cp) / cp
                    strength = min(1.0, gap_pct * 3) * max(0.2, 1.0 - dist * 8)

                    fvgs.append({
                        "type": "bullish",
                        "price": round(gap_mid, 2),
                        "priceLow": round(gap_bottom, 2),
                        "priceHigh": round(gap_top, 2),
                        "gapPct": round(gap_pct, 3),
                        "strength": round(strength, 3),
                        "index": i,
                        "time": candles[i]["time"],
                        "isFresh": True,
                    })

            # Bearish FVG: next high < prev low (price jumped down)
            if nxt["high"] < prev["low"]:
                gap_top = prev["low"]
                gap_bottom = nxt["high"]
                gap_size = gap_top - gap_bottom
                gap_pct = gap_size / prev["low"] * 100

                if gap_pct >= min_gap_pct:
                    gap_mid = (gap_top + gap_bottom) / 2
                    dist = abs(gap_mid - cp) / cp
                    strength = min(1.0, gap_pct * 3) * max(0.2, 1.0 - dist * 8)

                    fvgs.append({
                        "type": "bearish",
                        "price": round(gap_mid, 2),
                        "priceLow": round(gap_bottom, 2),
                        "priceHigh": round(gap_top, 2),
                        "gapPct": round(gap_pct, 3),
                        "strength": round(strength, 3),
                        "index": i,
                        "time": candles[i]["time"],
                        "isFresh": True,
                    })

        # Convert to zones
        zones = []
        for fvg in fvgs[-15:]:
            zones.append({
                "type": "support" if fvg["type"] == "bullish" else "resistance",
                "subtype": "fvg",
                "price": fvg["price"],
                "priceLow": fvg["priceLow"],
                "priceHigh": fvg["priceHigh"],
                "strength": fvg["strength"],
                "source": "fvg",
                "time": fvg["time"],
                "gapPct": fvg["gapPct"],
                "isFresh": True,
            })

        return {"fvgs": fvgs[-15:], "zones": zones}


# ─── Liquidity Sweep Detector ─────────────────────────────────

class LiquiditySweepDetector:
    """
    Institutional-Grade Liquidity Sweep Detector v2.

    Upgrades over basic sweep detection:
    1. Multi-timeframe sweep detection (lookback 15, 25, 40)
    2. Speed-of-rejection metric (faster = higher probability)
    3. Volume fade detection (spike then fade = sweep, sustained = breakout)
    4. Rejection strength (how far price moves back into range)
    5. Freshness scoring (untouched levels have more liquidity)
    6. Sweep depth scoring (not too deep = better reversal chance)
    """

    @staticmethod
    def detect(candles, lookback=20, sweep_threshold=0.1):
        """
        Detect liquidity sweeps with institutional scoring.
        Uses multiple lookback periods to detect sweeps at different timeframes.
        """
        if len(candles) < 45:  # Need enough data for all lookbacks
            return {"sweeps": [], "zones": []}

        n = len(candles)
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2

        # Pre-compute average volume for fade detection
        avg_vol = sum(c.get("volume", 0) for c in candles[-20:]) / max(20, 1)

        sweeps = []
        # Multi-timeframe: detect at different lookback periods
        for lb in [15, 25, 40]:
            if n < lb + 5:
                continue
            for i in range(lb, n - 1):
                window = candles[i - lb:i]
                window_high = max(c["high"] for c in window)
                window_low = min(c["low"] for c in window)

                # ── Support Sweep: break below, close above ──
                if (lows[i] < window_low and
                        closes[i] > window_low and
                        (window_low - lows[i]) / window_low * 100 < sweep_threshold * 5):
                    sweep_pct = (window_low - lows[i]) / window_low * 100
                    sw = LiquiditySweepDetector._score_sweep(
                        candles, i, "support", window_low, sweep_pct,
                        cp, avg_vol, lb, n)
                    if sw:
                        sweeps.append(sw)

                # ── Resistance Sweep: break above, close below ──
                if (highs[i] > window_high and
                        closes[i] < window_high and
                        (highs[i] - window_high) / window_high * 100 < sweep_threshold * 5):
                    sweep_pct = (highs[i] - window_high) / window_high * 100
                    sw = LiquiditySweepDetector._score_sweep(
                        candles, i, "resistance", window_high, sweep_pct,
                        cp, avg_vol, lb, n)
                    if sw:
                        sweeps.append(sw)

        # Deduplicate: keep the strongest sweep at each price level
        sweeps = LiquiditySweepDetector._dedupe_sweeps(sweeps)

        # Convert to zones
        zones = []
        for sw in sweeps[-15:]:
            zones.append({
                "type": "resistance" if sw["type"] == "resistance" else "support",
                "subtype": "liquidity_sweep",
                "price": sw["price"],
                "strength": sw["strength"],
                "source": "liquidity_sweep",
                "time": sw["time"],
                "sweptPrice": sw["sweptPrice"],
                "sweepPct": sw["sweepPct"],
                "isFresh": sw.get("isFresh", True),
            })

        return {"sweeps": sweeps[-15:], "zones": zones}

    @staticmethod
    def _score_sweep(candles, idx, sweep_type, level_price, sweep_pct,
                     cp, avg_vol, lookback, n):
        """
        Score a liquidity sweep with institutional metrics.

        Factors:
        1. Speed of rejection (fast = high probability)
        2. Volume fade (spike then fade = sweep, sustained = breakout)
        3. Rejection strength (close position within range)
        4. Sweep depth (not too deep = better)
        5. Multi-timeframe bonus (higher lookback = stronger)
        6. Proximity to current price
        """
        c = candles[idx]
        rng = c["high"] - c["low"]
        if rng <= 0:
            return None

        # ── 1. Speed of rejection ──
        # How quickly did price close back inside the range after the break?
        # On the sweep candle itself: if wick is long and close is deep inside, that's fast rejection
        if sweep_type == "support":
            # For support sweep: close should be well above the swept low
            rejection_depth = (c["close"] - c["low"]) / rng  # 0-1, higher = more rejection
        else:
            # For resistance sweep: close should be well below the swept high
            rejection_depth = (c["high"] - c["close"]) / rng
        # Score: 0.7+ rejection depth = 1.0, 0.3 = 0.5
        rejection_score = min(1.0, max(0.2, rejection_depth / 0.7))

        # ── 2. Volume fade detection ──
        # A true sweep has volume spike at the extreme then fade
        # Check: sweep candle volume vs next 2 candles
        sweep_vol = c.get("volume", 0)
        vol_ratio = sweep_vol / max(avg_vol, 0.001)
        fade_detected = False
        if idx + 2 < n:
            next_vol1 = candles[idx + 1].get("volume", 0)
            next_vol2 = candles[idx + 2].get("volume", 0) if idx + 2 < n else avg_vol
            # Volume should decrease after the sweep (fade)
            if next_vol1 < sweep_vol * 0.9 and next_vol2 < sweep_vol * 0.9:
                fade_detected = True
        # Score: high volume spike + fade = 1.0, no fade = 0.5
        vol_score = min(1.0, max(0.3, (vol_ratio - 0.5) / 1.5))
        if fade_detected:
            vol_score = min(1.0, vol_score + 0.3)  # Bonus for fade

        # ── 3. Rejection strength (candle body position) ──
        body = abs(c["close"] - c["open"])
        body_ratio = body / max(rng, 0.01)
        # Strong rejection = large body in the reversal direction
        if sweep_type == "support":
            # Bullish rejection candle (close > open) is stronger
            is_reversal_candle = c["close"] > c["open"]
        else:
            is_reversal_candle = c["close"] < c["open"]
        strength_bonus = 0.2 if is_reversal_candle else 0.0

        # ── 4. Sweep depth (not too deep = better reversal chance) ──
        # Too deep = might be a breakout, not a sweep
        depth_pct = sweep_pct  # How far beyond the level
        # Sweet spot: 0.05-0.5% depth
        if depth_pct < 0.05:
            depth_score = 0.6  # Too shallow — might not have triggered enough stops
        elif depth_pct <= 0.5:
            depth_score = 1.0  # Perfect depth
        else:
            depth_score = max(0.2, 1.0 - (depth_pct - 0.5) * 2)  # Too deep

        # ── 5. Multi-timeframe bonus ──
        # Higher lookback = higher timeframe level = stronger
        tf_score = min(1.0, lookback / 40.0)

        # ── 6. Proximity to current price ──
        dist = abs(level_price - cp) / max(cp, 1)
        proximity = max(0.2, 1.0 - dist * 10)

        # ── 7. Freshness: has this level been swept before? ──
        is_fresh = True
        for j in range(max(0, idx - 50), idx):
            if j == idx:
                continue
            c2 = candles[j]
            tolerance = level_price * 0.003  # 0.3% tolerance
            if sweep_type == "support":
                if abs(c2["low"] - level_price) < tolerance:
                    is_fresh = False
                    break
            else:
                if abs(c2["high"] - level_price) < tolerance:
                    is_fresh = False
                    break
        freshness = 1.0 if is_fresh else 0.6

        # ── Composite strength score ──
        strength = (
            rejection_score * 0.25 +    # speed of rejection
            vol_score * 0.20 +           # volume fade
            strength_bonus +             # reversal candle bonus (0-0.2)
            depth_score * 0.15 +         # sweep depth
            tf_score * 0.10 +            # multi-timeframe
            proximity * 0.10 +           # proximity
            freshness * 0.10             # freshness
        )
        strength = round(min(1.0, max(0.05, strength)), 3)

        swept_price = c["low"] if sweep_type == "support" else c["high"]

        return {
            "type": sweep_type,
            "price": round(level_price, 2),
            "sweptPrice": round(swept_price, 2),
            "sweepPct": round(sweep_pct, 3),
            "strength": strength,
            "rejectionDepth": round(rejection_depth, 3),
            "volRatio": round(vol_ratio, 2),
            "volFade": fade_detected,
            "depthScore": round(depth_score, 3),
            "tfScore": round(tf_score, 3),
            "freshness": round(freshness, 3),
            "isFresh": is_fresh,
            "index": idx,
            "time": candles[idx]["time"],
        }

    @staticmethod
    def _dedupe_sweeps(sweeps, price_threshold=0.002):
        """Deduplicate sweeps at the same price level, keeping the strongest."""
        if not sweeps:
            return []
        # Sort by price
        sorted_sw = sorted(sweeps, key=lambda s: s["price"])
        deduped = [dict(sorted_sw[0])]
        for sw in sorted_sw[1:]:
            last = deduped[-1]
            if abs(sw["price"] - last["price"]) / max(last["price"], 1) < price_threshold:
                # Same level — keep the stronger sweep
                if sw["strength"] > last["strength"]:
                    deduped[-1] = dict(sw)
            else:
                deduped.append(dict(sw))
        return deduped


# ─── Volume Profile Analyzer ─────────────────────────────────

class VolumeProfileAnalyzer:
    """Calculate Volume Profile — HVN/LVN, POC, Value Area."""

    @staticmethod
    def calculate(candles, num_bins=20):
        if len(candles) < 10:
            return {"bins": [], "poc": 0, "valueAreaHigh": 0, "valueAreaLow": 0,
                    "totalVolume": 0, "zones": []}

        pmin = min(c["low"] for c in candles)
        pmax = max(c["high"] for c in candles)
        if pmax - pmin < 0.5:
            return {"bins": [], "poc": 0, "valueAreaHigh": 0, "valueAreaLow": 0,
                    "totalVolume": 0, "zones": []}

        bs = (pmax - pmin) / num_bins
        bins = [{
            "priceLow": round(pmin + i * bs, 2),
            "priceHigh": round(pmin + (i + 1) * bs, 2),
            "volume": 0.0,
        } for i in range(num_bins)]

        for c in candles:
            mid = (c["high"] + c["low"]) / 2
            mid_price = mid
            for b in bins:
                if b["priceLow"] <= mid_price <= b["priceHigh"]:
                    b["volume"] += c.get("volume", 0)
                    break

        tv = sum(b["volume"] for b in bins)
        if tv == 0:
            return {"bins": [], "poc": 0, "valueAreaHigh": 0, "valueAreaLow": 0,
                    "totalVolume": 0, "zones": []}

        # Find POC (Point of Control)
        poc_bin = max(bins, key=lambda b: b["volume"])
        poc_price = round((poc_bin["priceLow"] + poc_bin["priceHigh"]) / 2, 2)
        poc_idx = bins.index(poc_bin)

        # Value Area (70% of volume around POC)
        vv = poc_bin["volume"]
        li = hi = poc_idx
        total_target = tv * 0.70
        while vv < total_target:
            lv = bins[li - 1]["volume"] if li > 0 else 0
            hv = bins[hi + 1]["volume"] if hi < len(bins) - 1 else 0
            if lv >= hv and li > 0:
                li -= 1
                vv += lv
            elif hi < len(bins) - 1:
                hi += 1
                vv += hv
            else:
                break

        # Classify bins
        avg = tv / num_bins
        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2
        zones = []

        for b in bins:
            if b["volume"] > avg * 1.3:
                b["type"] = "HVN"
                mid = (b["priceLow"] + b["priceHigh"]) / 2
                strength = min(1.0, b["volume"] / poc_bin["volume"])
                dist = abs(mid - cp) / cp
                strength *= max(0.3, 1.0 - dist * 5)
                zones.append({
                    "type": "support" if mid < cp else "resistance",
                    "subtype": "volume_hvn",
                    "price": round(mid, 2),
                    "priceLow": b["priceLow"],
                    "priceHigh": b["priceHigh"],
                    "strength": round(strength, 3),
                    "volume": round(b["volume"], 2),
                    "source": "volume_hvn",
                    "distance": round(dist * 100, 2),
                    "isFresh": True,
                })
            elif b["volume"] < avg * 0.4:
                b["type"] = "LVN"
            else:
                b["type"] = "normal"

        return {
            "bins": bins,
            "poc": poc_price,
            "pocVolume": round(poc_bin["volume"], 2),
            "valueAreaHigh": round(bins[hi]["priceHigh"], 2),
            "valueAreaLow": round(bins[li]["priceLow"], 2),
            "totalVolume": round(tv, 2),
            "zones": zones,
        }


# ─── CVD Analyzer ────────────────────────────────────────────

class CVDAnalyzer:
    """
    Cumulative Volume Delta — tracks buying vs selling pressure.
    Detects divergence: price making higher highs while CVD
    makes lower highs = bearish divergence (and vice versa).
    Exposes per-candle delta for live pattern detection.
    """

    @staticmethod
    def calculate(candles):
        if len(candles) < 5:
            return {"cvd": [], "divergences": [], "perCandleDelta": []}

        cvd_vals = []
        per_candle_delta = []
        cum = 0.0

        for c in candles:
            rng = c["high"] - c["low"]
            if rng < 0.01:
                rng = 0.01
            body = abs(c["close"] - c["open"])
            upper = c["high"] - max(c["open"], c["close"])
            lower = min(c["open"], c["close"]) - c["low"]
            bull_ratio = (lower + body) / rng
            bear_ratio = (upper + body) / rng
            delta = (bull_ratio - bear_ratio) * c.get("volume", 0)
            cum += delta
            cvd_vals.append({"time": c["time"], "value": round(cum, 2), "delta": round(delta, 2)})
            per_candle_delta.append({
                "time": c["time"],
                "delta": round(delta, 2),
                "bullRatio": round(bull_ratio, 4),
                "bearRatio": round(bear_ratio, 4),
                "buyVolume": round(bull_ratio * c.get("volume", 0), 2),
                "sellVolume": round(bear_ratio * c.get("volume", 0), 2),
            })

        divs = []
        if len(cvd_vals) > 30:
            highs_list = [c["high"] for c in candles]
            lows_list = [c["low"] for c in candles]
           
            # Step 1: Find swing highs and lows (lookback=5)
            lb = 5
            swing_highs_idx = []
            swing_lows_idx = []
            for i in range(lb, len(candles) - lb):
                is_sh = all(highs_list[i] > highs_list[i - j] for j in range(1, lb + 1)) and \
                        all(highs_list[i] > highs_list[i + j] for j in range(1, lb + 1))
                if is_sh:
                    swing_highs_idx.append(i)
                is_sl = all(lows_list[i] < lows_list[i - j] for j in range(1, lb + 1)) and \
                        all(lows_list[i] < lows_list[i + j] for j in range(1, lb + 1))
                if is_sl:
                    swing_lows_idx.append(i)
            
            # Step 2: At consecutive swing highs, check for bearish CVD divergence
            for k in range(1, len(swing_highs_idx)):
                i1, i2 = swing_highs_idx[k - 1], swing_highs_idx[k]
                p1, p2 = highs_list[i1], highs_list[i2]
                cvd1, cvd2 = cvd_vals[i1]["value"], cvd_vals[i2]["value"]
                # Bearish: price higher high, CVD lower high
                if p2 > p1 and cvd2 < cvd1:
                    price_diff_pct = (p2 - p1) / p1 * 100
                    cvd_diff_pct = (cvd1 - cvd2) / max(abs(cvd1), 1) * 100
                    # Only if meaningful divergence (both diverging by >2%)
                    if cvd_diff_pct > 2 and price_diff_pct > 0.1:
                        strength = min(1.0, cvd_diff_pct / 20)
                        divs.append({
                            "index": i2,
                            "time": candles[i2]["time"],
                            "type": "bearish",
                            "strength": round(strength, 3),
                            "priceDivergence": round(price_diff_pct, 2),
                            "cvdDivergence": round(cvd_diff_pct, 2),
                        })
            
            # Step 3: At consecutive swing lows, check for bullish CVD divergence
            for k in range(1, len(swing_lows_idx)):
                i1, i2 = swing_lows_idx[k - 1], swing_lows_idx[k]
                p1, p2 = lows_list[i1], lows_list[i2]
                cvd1, cvd2 = cvd_vals[i1]["value"], cvd_vals[i2]["value"]
                # Bullish: price lower low, CVD higher low
                if p2 < p1 and cvd2 > cvd1:
                    price_diff_pct = (p1 - p2) / p1 * 100
                    cvd_diff_pct = (cvd2 - cvd1) / max(abs(cvd1), 1) * 100
                    if cvd_diff_pct > 2 and price_diff_pct > 0.1:
                        strength = min(1.0, cvd_diff_pct / 20)
                        divs.append({
                            "index": i2,
                            "time": candles[i2]["time"],
                            "type": "bullish",
                            "strength": round(strength, 3),
                            "priceDivergence": round(price_diff_pct, 2),
                            "cvdDivergence": round(cvd_diff_pct, 2),
                        })

        return {
            "cvd": cvd_vals,
            "divergences": divs[-10:],
            "currentCVD": round(cum, 2),
            "perCandleDelta": per_candle_delta,
            "latestDelta": per_candle_delta[-1] if per_candle_delta else None,
            "latestCandle": {
                "delta": round(per_candle_delta[-1]["delta"], 2) if per_candle_delta else 0,
                "buyVolume": round(per_candle_delta[-1]["buyVolume"], 2) if per_candle_delta else 0,
                "sellVolume": round(per_candle_delta[-1]["sellVolume"], 2) if per_candle_delta else 0,
                "bullRatio": round(per_candle_delta[-1]["bullRatio"], 4) if per_candle_delta else 0,
            } if per_candle_delta else None,
        }


# ─── Delta Pattern Detector (Live Patterns 1-4) ──────────────

class DeltaPatternDetector:
    """
    Detects 4 live delta-based patterns for the Liquidity Hunter.

    Pattern 1: High Volume + Small Body (Absorption)
    Pattern 2: Price Falls + Delta Positive (Hidden Buying)
    Pattern 3: Stop Hunt Spike + Instant Reversal
    Pattern 4: Tight Range Squeeze + Sudden Explosion
    """

    @staticmethod
    def detect(candles, per_candle_delta=None):
        """
        Run all 4 pattern detectors on the latest candle data.
        Returns a list of active patterns with metadata.
        """
        if len(candles) < 30:
            return {"patterns": [], "activeCount": 0}

        # If per_candle_delta not provided, compute it
        if per_candle_delta is None or not per_candle_delta:
            cvd_result = CVDAnalyzer.calculate(candles)
            per_candle_delta = cvd_result.get("perCandleDelta", [])

        patterns = []

        # ── Pattern 1: Absorption ──
        p1 = DeltaPatternDetector._detect_absorption(candles, per_candle_delta)
        if p1:
            patterns.append(p1)

        # ── Pattern 2: Hidden Buying ──
        p2 = DeltaPatternDetector._detect_hidden_buying(candles, per_candle_delta)
        if p2:
            patterns.append(p2)

        # ── Pattern 3: Stop Hunt Reversal ──
        p3 = DeltaPatternDetector._detect_stop_hunt_reversal(candles, per_candle_delta)
        if p3:
            patterns.append(p3)

        # ── Pattern 4: Squeeze Explosion ──
        p4 = DeltaPatternDetector._detect_squeeze_explosion(candles, per_candle_delta)
        if p4:
            patterns.append(p4)

        return {
            "patterns": patterns,
            "activeCount": len(patterns),
        }

    @staticmethod
    def _get_avg_volume(candles, lookback=20):
        """Get average volume over lookback period."""
        if len(candles) < lookback:
            lookback = len(candles)
        recent = candles[-lookback:]
        return sum(c.get("volume", 0) for c in recent) / len(recent)

    @staticmethod
    def _detect_absorption(candles, deltas):
        """
        Pattern 1: High Volume + Small Candle Body.
        Volume >> average, body < 30% of total range.
        Someone absorbed all that selling — they did not let price drop.
        """
        if len(candles) < 21:
            return None

        latest = candles[-1]
        rng = latest["high"] - latest["low"]
        if rng < 0.01:
            return None

        body = abs(latest["close"] - latest["open"])
        body_pct = body / rng
        volume = latest.get("volume", 0)
        avg_vol = DeltaPatternDetector._get_avg_volume(candles, 20)
        vol_ratio = volume / avg_vol if avg_vol > 0 else 1

        # High volume (>1.5x avg) AND small body (<35% of range)
        if vol_ratio >= 1.5 and body_pct <= 0.35:
            # Determine if it's bullish or bearish absorption
            direction = "bullish" if latest["close"] >= latest["open"] else "bearish"
            # More significant if volume is very high and body is very small
            significance = max(0.1, min(1.0, (vol_ratio - 1.0) * 0.4 + (0.35 - body_pct) * 1.5))
            latest_delta = deltas[-1]["delta"] if deltas and len(deltas) > 0 else 0
            return {
                "pattern": 1,
                "name": "Absorption Candle",
                "description": f"High volume ({vol_ratio:.1f}x avg) with tiny body ({body_pct*100:.0f}% of range).",
                "insight": "Someone absorbed all that selling. They did not let price drop." if direction == "bullish" else "Supply absorbed without price advance.",
                "direction": direction,
                "significance": round(min(significance, 1.0), 3),
                "delta": round(latest_delta, 2),
                "volume": round(volume, 2),
                "volRatio": round(vol_ratio, 2),
                "bodyPct": round(body_pct * 100, 1),
                "time": latest["time"],
                "isFresh": True,
            }
        return None

    @staticmethod
    def _detect_hidden_buying(candles, deltas):
        """
        Pattern 2: Price Falls But Delta Stays Positive.
        Price going down but buyers still more aggressive than sellers.
        Someone is buying the dip silently while price looks weak.
        """
        if len(candles) < 5 or not deltas or len(deltas) < 5:
            return None

        latest = candles[-1]
        prev = candles[-2]
        latest_delta = deltas[-1]["delta"] if len(deltas) > 0 else 0

        # Price is falling (close < previous close OR bearish candle)
        price_falling = latest["close"] < prev["close"] or latest["close"] < latest["open"]

        # Delta is positive (buyers more aggressive)
        delta_positive = latest_delta > 0

        if price_falling and delta_positive:
            # Check multi-candle consistency: look at last 3 candles
            recent_deltas = [d["delta"] for d in deltas[-3:]]
            avg_delta = sum(recent_deltas) / len(recent_deltas) if recent_deltas else 0
            prices = [c["close"] for c in candles[-4:]]
            price_trend = prices[-1] - prices[0]

            # Stronger signal if multiple candles show this
            bullish_delta_count = sum(1 for d in recent_deltas if d > 0)
            significance = 0.4 + (bullish_delta_count / 3) * 0.4 + min(abs(avg_delta) / 1000, 0.2)

            return {
                "pattern": 2,
                "name": "Hidden Buying",
                "description": f"Price fell {abs(price_trend):.2f} but delta is +{latest_delta:.2f} (buyers aggressive).",
                "insight": "Someone is buying the dip silently while price looks weak. Classic hiding.",
                "direction": "bullish",
                "significance": round(min(significance, 1.0), 3),
                "delta": round(latest_delta, 2),
                "avgDelta": round(avg_delta, 2),
                "priceChange": round(price_trend, 2),
                "bullishDeltaCount": bullish_delta_count,
                "time": latest["time"],
                "isFresh": True,
            }
        return None

    @staticmethod
    def _detect_stop_hunt_reversal(candles, deltas):
        """
        Pattern 3: Stop Hunt Spike + Instant Reversal.
        Price breaks below a key low (triggers stops), then snaps back fast.
        The wick is the operator collecting cheap BTC from panicking traders.
        """
        if len(candles) < 15:
            return None

        latest = candles[-1]
        prev = candles[-2]

        # Lookback window for key low
        lookback = 15
        window = candles[-lookback:-1]  # Exclude current candle
        if len(window) < 5:
            return None

        window_low = min(c["low"] for c in window)
        window_high = max(c["high"] for c in window)

        # Price broke below the window low (stop hunt down)
        broke_below = latest["low"] < window_low
        # Closed back above the window low (reversal)
        closed_above = latest["close"] > window_low
        # The break was not too deep (< 1%)
        break_depth = (window_low - latest["low"]) / window_low * 100
        not_too_deep = break_depth < 1.0

        if broke_below and closed_above and not_too_deep:
            # Check if delta was strong on the reversal candle
            latest_delta = deltas[-1]["delta"] if deltas and len(deltas) > 0 else 0
            delta_positive = latest_delta > 0
            significance = 0.5 + (0.3 if delta_positive else 0) + min(break_depth * 0.3, 0.2)

            return {
                "pattern": 3,
                "name": "Stop Hunt Reversal",
                "description": f"Broke below {window_low:.2f} (low of last {lookback} candles), then reversed to close at {latest['close']:.2f}.",
                "insight": "The wick is their shopping window. Operator collected cheap BTC from panicking traders.",
                "direction": "bullish",
                "significance": round(min(significance, 1.0), 3),
                "delta": round(latest_delta, 2),
                "breakLevel": round(window_low, 2),
                "breakDepth": round(break_depth, 3),
                "lowPrice": round(latest["low"], 2),
                "closePrice": round(latest["close"], 2),
                "time": latest["time"],
                "isFresh": True,
            }

        # Also check for stop hunt up (short squeeze)
        broke_above = latest["high"] > window_high
        closed_below = latest["close"] < window_high
        break_up_depth = (latest["high"] - window_high) / window_high * 100
        not_too_deep_up = break_up_depth < 1.0

        if broke_above and closed_below and not_too_deep_up:
            latest_delta = deltas[-1]["delta"] if deltas and len(deltas) > 0 else 0
            delta_negative = latest_delta < 0
            significance = 0.5 + (0.3 if delta_negative else 0) + min(break_up_depth * 0.3, 0.2)

            return {
                "pattern": 3,
                "name": "Stop Hunt Reversal (Short)",
                "description": f"Broke above {window_high:.2f} (high of last {lookback} candles), then reversed to close at {latest['close']:.2f}.",
                "insight": "Short sellers trapped. Operator shook out weak shorts before driving price down.",
                "direction": "bearish",
                "significance": round(min(significance, 1.0), 3),
                "delta": round(latest_delta, 2),
                "breakLevel": round(window_high, 2),
                "breakDepth": round(break_up_depth, 3),
                "highPrice": round(latest["high"], 2),
                "closePrice": round(latest["close"], 2),
                "time": latest["time"],
                "isFresh": True,
            }

        return None

    @staticmethod
    def _detect_squeeze_explosion(candles, deltas):
        """
        Pattern 4: Tight Range Squeeze + Sudden Explosion.
        Price goes sideways for many candles with low volume. Tight range.
        Then one massive directional candle with huge delta.
        That patience was the operator filling. Explosion = done filling, now letting it run.
        """
        if len(candles) < 15 or not deltas or len(deltas) < 10:
            return None

        latest = candles[-1]

        # Look at candles before the latest (the squeeze period)
        squeeze_window = 10
        if len(candles) < squeeze_window + 3:
            return None

        squeeze_candles = candles[-(squeeze_window + 1):-1]
        if len(squeeze_candles) < squeeze_window:
            return None

        # Calculate squeeze metrics
        squeeze_highs = [c["high"] for c in squeeze_candles]
        squeeze_lows = [c["low"] for c in squeeze_candles]
        squeeze_volumes = [c.get("volume", 0) for c in squeeze_candles]

        squeeze_range = max(squeeze_highs) - min(squeeze_lows)
        avg_squeeze_range = squeeze_range / max(min(squeeze_lows), 1)
        avg_squeeze_vol = sum(squeeze_volumes) / len(squeeze_volumes)

        # Current candle metrics
        latest_rng = latest["high"] - latest["low"]
        latest_vol = latest.get("volume", 0)
        latest_delta = deltas[-1]["delta"] if deltas and len(deltas) > 0 else 0

        # Conditions for explosion:
        # 1. Squeeze period had tight range (< 0.5% avg daily range)
        # 2. Current candle has > 1.8x the squeeze range
        # 3. Volume explosion > 1.5x avg squeeze volume
        # 4. Strong delta (abs > some threshold)

        range_ratio = latest_rng / max(squeeze_range, 0.01)
        vol_ratio = latest_vol / max(avg_squeeze_vol, 0.01)
        squeeze_tight = avg_squeeze_range < 0.005  # Tight range in % terms

        # Use relative delta threshold: latest delta should exceed 2x average absolute delta
        squeeze_deltas = [abs(d["delta"]) for d in deltas[-squeeze_window-1:-1]] if len(deltas) > squeeze_window else [abs(d["delta"]) for d in deltas]
        avg_abs_delta = sum(squeeze_deltas) / max(len(squeeze_deltas), 1)
        delta_threshold = max(avg_abs_delta * 2.0, 10)  # At least 2x avg, minimum 10

        if range_ratio >= 1.8 and vol_ratio >= 1.5 and abs(latest_delta) > delta_threshold:
            direction = "bullish" if latest["close"] > latest["open"] else "bearish"
            significance = min(1.0, (range_ratio - 1.0) * 0.2 + (vol_ratio - 1.0) * 0.2 + min(abs(latest_delta) / max(avg_abs_delta * 10, 1), 0.3))

            # Categorize how long the squeeze was
            squeeze_descriptor = "long" if squeeze_window >= 10 else "short"

            return {
                "pattern": 4,
                "name": "Squeeze Explosion",
                "description": f"{squeeze_window} tight candles ({avg_squeeze_range*100:.3f}% range, low vol) then {range_ratio:.1f}x range with delta {latest_delta:+.0f}.",
                "insight": "Operator filled patiently during the squeeze. Now letting it run.",
                "direction": direction,
                "significance": round(min(significance, 1.0), 3),
                "delta": round(latest_delta, 2),
                "rangeRatio": round(range_ratio, 2),
                "volRatio": round(vol_ratio, 2),
                "avgSqueezeVol": round(avg_squeeze_vol, 2),
                "squeezeRange": round(squeeze_range, 2),
                "squeezeCandles": squeeze_window,
                "time": latest["time"],
                "isFresh": True,
            }

        return None


# ─── Zone Merger & Scorer ────────────────────────────────────

class LiquidityMerger:
    """
    Merge duplicate/close zones, then score by institutional criteria:
    - Strength of the signal (impulse size, volume, wall size)
    - Proximity to current price (nearer = more relevant)
    - Freshness (unmitigated = stronger)
    - Confluence (multiple sources at same level = stronger)
    """

    @staticmethod
    def merge(zones, threshold=0.0015):
        """
        Merge zones at similar price levels.
        threshold = 0.15% proximity for merging.
        """
        if not zones:
            return []
        # Sort by price
        sz = sorted(zones, key=lambda z: z["price"])
        merged = [dict(sz[0])]  # deep copy
        for z in sz[1:]:
            last = merged[-1]
            if abs(z["price"] - last["price"]) / max(last["price"], 1) < threshold:
                # Merge: keep the stronger signal
                last["strength"] = max(last["strength"], z.get("strength", 0))
                last["volume"] = max(last.get("volume", 0), z.get("volume", 0))
                last["score"] = max(last.get("score", 0), z.get("score", 0))

                # Track sources for confluence
                existing_sources = last.get("source", "").split("+")
                new_sources = z.get("source", "").split("+")
                combined = list(dict.fromkeys(existing_sources + new_sources))
                last["source"] = "+".join(combined)

                # Track ALL subtypes at this level
                existing_sub = last.get("subtypes", [last.get("subtype", "")])
                new_sub = z.get("subtype", "")
                if isinstance(existing_sub, str):
                    existing_sub = [existing_sub]
                if new_sub and new_sub not in existing_sub:
                    existing_sub.append(new_sub)
                last["subtypes"] = existing_sub

                # Weighted average price
                w1 = last.get("strength", 0.5)
                w2 = z.get("strength", 0.5)
                last["price"] = round((last["price"] * w1 + z["price"] * w2) / (w1 + w2), 2)
                last["distance"] = min(last.get("distance", 999), z.get("distance", 999))

                # Prefer the type of the stronger signal
                if z.get("strength", 0) > last.get("strength", 0):
                    last["type"] = z["type"]
                    last["subtype"] = z.get("subtype", last.get("subtype", ""))

                # Confluence bonus
                num_sources = len(combined)
                if num_sources >= 2:
                    last["confluence"] = min(num_sources / 4.0, 1.0)
            else:
                z_copy = dict(z)
                z_copy["subtypes"] = [z_copy.get("subtype", "")]
                merged.append(z_copy)

        return merged

    @staticmethod
    def score_zones(zones, current_price):
        """Score each zone and assign tier."""
        for z in zones:
            dist = abs(z["price"] - current_price) / max(current_price, 1)
            z["distance"] = round(dist * 100, 2)

            # Base score from strength
            score = z.get("strength", 0.3) * 0.5

            # Distance bonus: nearer = better (up to 0.3)
            dist_bonus = max(0, 1.0 - dist * 15) * 0.3
            score += dist_bonus

            # Confluence bonus (up to 0.2)
            confl = z.get("confluence", 0)
            score += confl * 0.2

            z["score"] = round(score, 3)

        # Sort by score descending
        zones.sort(key=lambda z: z["score"], reverse=True)

        # Assign tiers
        for z in zones:
            if z["score"] >= 0.7:
                z["tier"] = "A+"
            elif z["score"] >= 0.55:
                z["tier"] = "A"
            elif z["score"] >= 0.4:
                z["tier"] = "B"
            elif z["score"] >= 0.25:
                z["tier"] = "C"
            else:
                z["tier"] = "D"

        return zones


# ─── Main Liquidity Engine ────────────────────────────────────

class LiquidityEngine:
    """Orchestrates all liquidity analysis into a unified result."""

    def __init__(self, quality_only=True):
        self.client = BinanceClient()
        self.ob = OrderBookAnalyzer()
        self.swing = SwingPointDetector()
        self.ob_detector = OrderBlockDetector()
        self.fvg = FVGBalancer()
        self.sweep = LiquiditySweepDetector()
        self.vp = VolumeProfileAnalyzer()
        self.cvd = CVDAnalyzer()
        self.delta_patterns = DeltaPatternDetector()
        self.merger = LiquidityMerger()
        self.quality_only = quality_only

    def is_symbol_excluded(self, symbol):
        """Check if a symbol is excluded in quality-only mode."""
        if self.quality_only:
            return symbol in QUALITY_EXCLUDED_SYMBOLS
        return False

    def quality_confluence_check(self, candles, zones):
        """
        Assess confluence quality from raw zones (before merger dedup).
        Each zone has a single source, enabling accurate component counting.
        Returns: {quality_score, component_count, components, passes_quality, direction}
        """
        W = CONFLUENCE_WEIGHTS
        cp = candles[-1]["close"] if candles else 0
        if cp <= 0:
            return {"quality_score": 0, "component_count": 0, "components": [],
                    "passes_quality": False, "direction": None}

        bull_signals = []
        bear_signals = []

        for z in zones:
            ztype = z.get("type")
            zsrc = z.get("source", "")
            zstr = z.get("strength", 0)
            zprice = z.get("price", 0)

            # Map zone source to component name (removed OB, VP, Sweep — low performers)
            src = zsrc.strip()
            component = None
            weight = 0
            if "fvg" in src:
                component = "FVG"
                weight = W["FVG"]
            elif "swing_low" in src or "swing_high" in src:
                component = "Swing"
                weight = W["Swing"]
            # OB, VP, Sweep excluded — backtested: negative/zero expectancy
            if component is None:
                continue
            sc = weight * min(1.0, zstr * 2)
            if ztype == "support":
                bull_signals.append((sc, zprice, component))
            elif ztype == "resistance":
                bear_signals.append((sc, zprice, component))

        # Dedup by price proximity (0.3%), keeping highest score per component
        def _dedup(sig):
            if not sig:
                return 0.0, []
            sig.sort(key=lambda s: s[1])
            kept = [sig[0]]
            comps = [sig[0][2]]
            for sc, price, name in sig[1:]:
                if abs(price - kept[-1][1]) / max(kept[-1][1], 1) < 0.003:
                    if sc > kept[-1][0]:
                        kept[-1] = (sc, price, name)
                else:
                    kept.append((sc, price, name))
                    comps.append(name)
            return sum(s[0] for s in kept), comps

        # Count components from raw signals BEFORE dedup — matches backtester approach
        raw_bull_comps = len(set(name for _, _, name in bull_signals))
        raw_bear_comps = len(set(name for _, _, name in bear_signals))

        bull_s, _ = _dedup(bull_signals)
        bear_s, _ = _dedup(bear_signals)

        direction = None
        score = 0.0
        components = []
        if bull_s >= QUALITY_ONLY_THRESH and bull_s > bear_s and raw_bull_comps >= QUALITY_MIN_COMPONENTS:
            direction = "long"
            score = bull_s
            components = list(set(name for _, _, name in bull_signals))
        elif bear_s >= QUALITY_ONLY_THRESH and bear_s > bull_s and raw_bear_comps >= QUALITY_MIN_COMPONENTS:
            direction = "short"
            score = bear_s
            components = list(set(name for _, _, name in bear_signals))

        return {
            "quality_score": round(score, 3),
            "component_count": len(components),
            "components": components,
            "passes_quality": direction is not None,
            "direction": direction,
            "bull_score": round(bull_s, 3),
            "bear_score": round(bear_s, 3),
        }

    def generate_signal(self, symbol="BTCUSDT", interval="15m"):
        """
        Final Signal Generator — produces actionable trade setups.
        Uses ONLY FVG + Swing + Delta (removed: OB, Sweep, VP, BNB).
        Returns: {signal, direction, entry, sl, tp, rr, atr, components, regime, deltaPatterns, confidence, reasoning}
        """
        # Excluded symbols
        if symbol in QUALITY_EXCLUDED_SYMBOLS:
            return {"signal": "NO_TRADE", "reason": f"{symbol} excluded from quality mode",
                    "direction": None, "entry": 0, "sl": 0, "tp": 0, "rr": 0,
                    "atr": 0, "components": [], "regime": {}, "deltaPatterns": [],
                    "confidence": "NONE", "reasoning": ["Symbol excluded"]}

        try:
            candles = self.client.klines(symbol, interval, limit=250)
        except Exception as e:
            return {"signal": "ERROR", "reason": str(e), "direction": None,
                    "entry": 0, "sl": 0, "tp": 0, "rr": 0, "atr": 0,
                    "components": [], "regime": {}, "deltaPatterns": [],
                    "confidence": "NONE", "reasoning": [str(e)]}

        if len(candles) < 30:
            return {"signal": "NO_TRADE", "reason": "Insufficient data",
                    "direction": None, "entry": 0, "sl": 0, "tp": 0, "rr": 0,
                    "atr": 0, "components": [], "regime": {}, "deltaPatterns": [],
                    "confidence": "NONE", "reasoning": ["Need 30+ candles"]}

        cp = self.client.ticker_price(symbol)

        # 1) Market regime (ADX + BB width)
        regime = detect_market_regime(candles)

        # 2) Run FVG + Swing + Delta detection
        fvg_result = self.fvg.detect(candles)
        swing_result = self.swing.detect(candles)
        cvd_d = self.cvd.calculate(candles)
        delta_patterns = self.delta_patterns.detect(candles, cvd_d.get("perCandleDelta", []))

        # Collect raw zones from FVG + Swing ONLY (no OB, no Sweep, no VP)
        raw = []
        raw.extend(fvg_result.get("zones", []))
        raw.extend(swing_result.get("zones", []))

        # 3) Quality confluence check (FVG + Swing — zone-based)
        quality = self.quality_confluence_check(candles, raw)

        # 3b) Delta confluence check (CVD-based, not zone-based)
        latest_delta_val = cvd_d.get("latestCandle", {}).get("delta", 0) if cvd_d.get("latestCandle") else 0
        recent_deltas = [d.get("delta", 0) for d in cvd_d.get("perCandleDelta", [])[-5:]]
        avg_recent_delta = sum(recent_deltas) / max(len(recent_deltas), 1)
        bull_div = any(d.get("type") == "bullish" for d in cvd_d.get("divergences", [])[-3:])
        bear_div = any(d.get("type") == "bearish" for d in cvd_d.get("divergences", [])[-3:])

        # Delta confirms long if: positive delta + bullish divergence OR consistently positive
        # Delta confirms short if: negative delta + bearish divergence OR consistently negative
        delta_confirms_long = (latest_delta_val > 0 and avg_recent_delta > 0) or bull_div
        delta_confirms_short = (latest_delta_val < 0 and avg_recent_delta < 0) or bear_div

        # Merge Delta into quality components if it confirms direction
        q_direction = quality.get("direction")
        q_components = list(quality.get("components", []))
        q_score = quality.get("quality_score", 0)
        if q_direction == "long" and delta_confirms_long and "Delta" not in q_components:
            q_components.append("Delta")
            q_score += CONFLUENCE_WEIGHTS["Delta"] * min(1.0, abs(latest_delta_val) / 500)
        elif q_direction == "short" and delta_confirms_short and "Delta" not in q_components:
            q_components.append("Delta")
            q_score += CONFLUENCE_WEIGHTS["Delta"] * min(1.0, abs(latest_delta_val) / 500)
        q_score = min(1.0, q_score)  # Cap at 1.0 for safety

        # Recalculate component count and direction with Delta included
        direction = q_direction
        raw_fvg_count = len([z for z in raw if "fvg" in z.get("source", "")])
        raw_sw_count = len([z for z in raw if "swing_low" in z.get("source", "") or "swing_high" in z.get("source", "")])
        has_fvg_or_sw = raw_fvg_count > 0 or raw_sw_count > 0
        delta_confirms = (direction == "long" and delta_confirms_long) or (direction == "short" and delta_confirms_short)
        if direction and not has_fvg_or_sw and not delta_confirms:
            direction = None
            q_components = []
        elif direction and len(q_components) < QUALITY_MIN_COMPONENTS:
            direction = None
            q_components = []  # Clear when no valid signal

        # 4) ATR for SL/TP
        atr = self._calc_atr(candles, 14)

        # 5) Build component evidence
        components_detail = []

        # FVG evidence
        active_fvgs = [z for z in raw if "fvg" in z.get("source", "") and z.get("type") == ("support" if direction == "long" else "resistance")]
        if active_fvgs:
            best_fvg = max(active_fvgs, key=lambda z: z.get("strength", 0))
            components_detail.append({
                "name": "FVG", "weight": CONFLUENCE_WEIGHTS["FVG"],
                "active": True, "strength": best_fvg.get("strength", 0),
                "price": best_fvg.get("price", 0),
                "evidence": f"{best_fvg.get('type', '').title()} FVG at ${best_fvg.get('price', 0):,.2f} (gap: {best_fvg.get('gapPct', 0):.3f}%)",
            })
        else:
            components_detail.append({"name": "FVG", "weight": CONFLUENCE_WEIGHTS["FVG"],
                "active": False, "strength": 0, "price": 0, "evidence": "No active FVG in signal direction"})

        # Swing evidence
        active_swings = [z for z in raw if ("swing_low" in z.get("source", "") or "swing_high" in z.get("source", "")) and z.get("type") == ("support" if direction == "long" else "resistance")]
        if active_swings:
            best_sw = max(active_swings, key=lambda z: z.get("strength", 0))
            src = "swing_low" if best_sw.get("type") == "support" else "swing_high"
            components_detail.append({
                "name": "Swing", "weight": CONFLUENCE_WEIGHTS["Swing"],
                "active": True, "strength": best_sw.get("strength", 0),
                "price": best_sw.get("price", 0),
                "evidence": f"{src.replace('_', ' ').title()} at ${best_sw.get('price', 0):,.2f} (strength: {best_sw.get('strength', 0):.2f})",
            })
        else:
            components_detail.append({"name": "Swing", "weight": CONFLUENCE_WEIGHTS["Swing"],
                "active": False, "strength": 0, "price": 0, "evidence": "No active Swing in signal direction"})

        # Delta evidence
        delta_active = "Delta" in q_components
        latest_delta = cvd_d.get("latestCandle", {})
        if delta_active:
            delta_val = latest_delta.get("delta", 0) if latest_delta else 0
            divs = cvd_d.get("divergences", [])
            bull_div = any(d.get("type") == "bullish" for d in divs[-3:]) if direction == "long" else False
            bear_div = any(d.get("type") == "bearish" for d in divs[-3:]) if direction == "short" else False
            div_note = " (CVD divergence)" if (bull_div or bear_div) else ""
            components_detail.append({
                "name": "Delta", "weight": CONFLUENCE_WEIGHTS["Delta"],
                "active": True, "strength": min(1.0, abs(delta_val) / 500),
                "price": 0,
                "evidence": f"Delta: {delta_val:+,.0f}{div_note} (buyers{'>' if direction == 'long' else '<'} sellers)",
            })
        else:
            components_detail.append({"name": "Delta", "weight": CONFLUENCE_WEIGHTS["Delta"],
                "active": False, "strength": 0, "price": 0, "evidence": "Delta not confirming direction"})

        # 6) Determine confidence
        active_count = sum(1 for c in components_detail if c["active"])
        score = q_score
        regime_ok = regime.get("risk_mult", 0) > 0

        if active_count >= 3 and score >= 0.7 and regime_ok:
            confidence = "HIGH"
        elif active_count >= 2 and score >= 0.5 and regime_ok:
            confidence = "MEDIUM"
        elif active_count >= 2 and score >= 0.5:
            confidence = "LOW"  # regime not ideal
        else:
            confidence = "NONE"

        # 7) Entry / SL / TP
        entry = cp
        sl = 0
        tp = 0
        rr = 0
        signal = "NO_TRADE"
        reasoning = []

        if direction and atr > 0 and confidence != "NONE":
            sl_dist = atr * 1.5
            tp_dist = atr * 3.0
            if direction == "long":
                sl = round(entry - sl_dist, 2)
                tp = round(entry + tp_dist, 2)
            else:
                sl = round(entry + sl_dist, 2)
                tp = round(entry - tp_dist, 2)
            rr = round(tp_dist / sl_dist, 1)
            signal = "TRADE"
            reasoning.append(f"{direction.upper()} signal: {active_count}/3 components aligned")
            reasoning.append(f"Quality score: {score:.3f} (threshold: {QUALITY_ONLY_THRESH})")
            reasoning.append(f"ATR(14): ${atr:,.2f} → SL: ${sl:,.2f} / TP: ${tp:,.2f}")
            reasoning.append(f"Risk:Reward = 1:{rr}")
            if not regime_ok:
                reasoning.append(f"⚠️ Market regime: {regime.get('regime', '?')} (risk_mult: {regime.get('risk_mult', 0)})")
        elif not direction:
            reasoning.append("No directional signal — components don't agree")
            reasoning.append(f"Bull score: {quality.get('bull_score', 0):.3f} / Bear score: {quality.get('bear_score', 0):.3f}")
        if regime.get("regime") in ("squeeze", "choppy"):
            reasoning.append(f"Market is {regime.get('regime', '?')} — reduced confidence")

        return {
            "signal": signal,
            "direction": direction,
            "entry": round(entry, 2),
            "sl": sl,
            "tp": tp,
            "rr": rr,
            "atr": round(atr, 2),
            "symbol": symbol,
            "interval": interval,
            "quality_score": score,
            "components": components_detail,
            "component_count": active_count,
            "regime": regime,
            "deltaPatterns": delta_patterns.get("patterns", []),
            "deltaCVD": {
                "current": cvd_d.get("currentCVD", 0),
                "latest": latest_delta,
                "divergences": cvd_d.get("divergences", [])[-3:],
            },
            "confidence": confidence,
            "reasoning": reasoning,
            "timestamp": int(time.time()),
            "currentPrice": entry,
        }

    def _calc_atr(self, candles, period=14):
        """Calculate Average True Range."""
        if len(candles) < period + 1:
            return 0
        trs = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) < period:
            return sum(trs) / max(len(trs), 1)
        atr = sum(trs[:period]) / period
        for i in range(period, len(trs)):
            atr = (atr * (period - 1) + trs[i]) / period
        return atr

    def analyze_all(self, symbol="BTCUSDT", interval="15m", depth_limit=100):
        # Check if symbol is excluded in quality-only mode
        if self.is_symbol_excluded(symbol):
            return {
                "symbol": symbol,
                "interval": interval,
                "currentPrice": 0,
                "timestamp": int(time.time()),
                "depth": {"bids": [], "asks": [], "totalBidVolume": 0, "totalAskVolume": 0,
                           "imbalance": 0, "bidAskRatio": 0, "bidWalls": [], "askWalls": [],
                           "currentPrice": 0},
                "zones": [],
                "zoneCounts": {"support": 0, "resistance": 0, "total": 0},
                "marketSummary": {"totalBidLiquidity": 0, "totalAskLiquidity": 0,
                                   "imbalance": 0, "bidAskRatio": 0, "activeWalls": 0},
                "swingPoints": {"highs": [], "lows": []},
                "structure": [], "orderBlocks": [], "fvgs": [], "sweeps": [],
                "volumeProfile": {}, "cvd": {}, "deltaPatterns": {"patterns": [], "activeCount": 0},
                "qualityFilter": {
                    "passes_quality": False,
                    "quality_score": 0,
                    "component_count": 0,
                    "components": [],
                    "reason": "symbol_excluded",
                    "excluded_symbols": QUALITY_EXCLUDED_SYMBOLS,
                },
                "marketRegime": {"regime": "excluded", "risk_mult": 0, "adx": 0, "bb_width": 0},
                "candles": [],
            }

        try:
            candles = self.client.klines(symbol, interval, limit=250)
        except Exception as e:
            # If klines fail, return error gracefully
            raise RuntimeError(f"Failed to fetch price data: {e}")

        try:
            dr = self.client.depth(symbol, limit=depth_limit)
        except Exception as e:
            # If depth fails, continue with empty depth data
            dr = {"bids": [], "asks": []}

        try:
            cp = self.client.ticker_price(symbol)
        except Exception as e:
            # If price fails, estimate from last candle
            cp = (candles[-1]["high"] + candles[-1]["low"]) / 2 if candles else 0

        # ── Market Regime Filter ──
        regime = detect_market_regime(candles)

        # Run all analyses in parallel (sequential calls but logically independent)
        depth = self.ob.analyze(dr["bids"], dr["asks"], cp)
        swing_result = self.swing.detect(candles)
        ob_result = self.ob_detector.detect(candles)
        fvg_result = self.fvg.detect(candles)
        sweep_result = self.sweep.detect(candles)
        vpd = self.vp.calculate(candles)
        cvd_d = self.cvd.calculate(candles)
        delta_patterns = self.delta_patterns.detect(candles, cvd_d.get("perCandleDelta", []))

        # Collect all raw zones
        raw = []
        raw.extend(self.ob.extract_zones(depth, cp))
        raw.extend(swing_result.get("zones", []))
        raw.extend(ob_result.get("zones", []))
        raw.extend(fvg_result.get("zones", []))
        raw.extend(sweep_result.get("zones", []))
        raw.extend(vpd.get("zones", []))

        # Merge, score, and tier
        merged = self.merger.merge(raw, threshold=0.0015)
        zones = self.merger.score_zones(merged, cp)

        bid_liq = sum(w.get("volume", 0) for w in depth.get("bidWalls", []))
        ask_liq = sum(w.get("volume", 0) for w in depth.get("askWalls", []))

        # Quality confluence check — uses raw zones before dedup for accurate component counting
        quality = self.quality_confluence_check(candles, raw)

        return {
            "symbol": symbol,
            "interval": interval,
            "currentPrice": cp,
            "timestamp": int(time.time()),
            "depth": depth,
            "zones": zones[:25],
            "zoneCounts": {
                "support": len([z for z in zones if z["type"] == "support"]),
                "resistance": len([z for z in zones if z["type"] == "resistance"]),
                "total": min(len(zones), 25),
            },
            "marketSummary": {
                "totalBidLiquidity": round(bid_liq, 4),
                "totalAskLiquidity": round(ask_liq, 4),
                "imbalance": depth["imbalance"],
                "bidAskRatio": depth["bidAskRatio"],
                "activeWalls": len(depth.get("bidWalls", [])) + len(depth.get("askWalls", [])),
            },
            "swingPoints": {
                "highs": swing_result.get("swingHighs", [])[-15:],
                "lows": swing_result.get("swingLows", [])[-15:],
            },
            "structure": swing_result.get("structure", []),
            "orderBlocks": ob_result.get("orderBlocks", []),
            "fvgs": fvg_result.get("fvgs", []),
            "sweeps": sweep_result.get("sweeps", []),
            "volumeProfile": vpd,
            "cvd": cvd_d,
            "deltaPatterns": delta_patterns,
            "marketRegime": regime,
            "qualityFilter": quality,
            "candles": candles[-120:],
        }
