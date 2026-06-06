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

BINANCE_BASE = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

Z = 2.0  # Z-score threshold for order book walls


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
    """Thin client for Binance REST API with request-level caching."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LiquidityIdentifier/2.0"})
        self.cache = RequestCache(ttl=5)

    def klines(self, symbol="BTCUSDT", interval="15m", limit=200):
        cache_key = f"klines:{symbol}:{interval}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            url = f"{BINANCE_BASE}/api/v3/klines"
            resp = self.session.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
            resp.raise_for_status()
            result = [{
                "time": k[0] // 1000,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5])
            } for k in resp.json()]
            self.cache.set(cache_key, result)
            return result
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Binance API timeout fetching klines for {symbol} {interval}")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Cannot connect to Binance API for {symbol} {interval}")
        except Exception as e:
            raise RuntimeError(f"Binance API error (klines): {e}")

    def depth(self, symbol="BTCUSDT", limit=100):
        cache_key = f"depth:{symbol}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            url = f"{BINANCE_BASE}/api/v3/depth"
            resp = self.session.get(url, params={"symbol": symbol, "limit": limit}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            result = {
                "bids": [[float(p), float(q)] for p, q in data["bids"]],
                "asks": [[float(p), float(q)] for p, q in data["asks"]],
            }
            self.cache.set(cache_key, result)
            return result
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Binance API timeout fetching depth for {symbol}")
        except Exception as e:
            raise RuntimeError(f"Binance API error (depth): {e}")

    def ticker_price(self, symbol="BTCUSDT"):
        cache_key = f"ticker:{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            url = f"{BINANCE_BASE}/api/v3/ticker/price"
            resp = self.session.get(url, params={"symbol": symbol}, timeout=10)
            resp.raise_for_status()
            result = float(resp.json()["price"])
            self.cache.set(cache_key, result)
            return result
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Binance API timeout fetching price for {symbol}")
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
    Enhanced swing detection with structural analysis.
    Identifies Break of Structure (BOS), Change of Character (CHoCH),
    and proper swing high/lows for liquidity zone identification.
    """

    @staticmethod
    def detect(candles, lookback=5, lookforward=3):
        if len(candles) < lookback + lookforward + 1:
            return {"swingHighs": [], "swingLows": [], "zones": [], "structure": []}

        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]

        swing_highs = []
        swing_lows = []
        structure_points = []  # BOS / CHoCH markers

        # ── Detect swing highs / lows ──
        for i in range(lookback, len(candles) - lookforward):
            # Swing High: higher than lookback candles before AND lookforward after
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

            # Swing Low: lower than lookback candles before AND lookforward after
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
        # BOS occurs when price breaks above a prior swing high or below a prior swing low
        for sh_idx in range(3, len(swing_highs)):
            prev = swing_highs[sh_idx - 1]["price"]
            curr = swing_highs[sh_idx]["price"]
            prev_low = swing_highs[sh_idx - 1]["index"]
            curr_idx = swing_highs[sh_idx]["index"]
            # Check if price broke above previous swing high between them
            interval_max = max(highs[prev_low:curr_idx + 1])
            if interval_max > prev and curr > prev:
                structure_points.append({
                    "index": curr_idx,
                    "type": "BOS",
                    "direction": "up",
                    "price": curr,
                    "time": candles[curr_idx]["time"],
                    "breakLevel": prev,
                })

        for sl_idx in range(3, len(swing_lows)):
            prev = swing_lows[sl_idx - 1]["price"]
            curr = swing_lows[sl_idx]["price"]
            prev_high = swing_lows[sl_idx - 1]["index"]
            curr_idx = swing_lows[sl_idx]["index"]
            interval_min = min(lows[prev_high:curr_idx + 1])
            if interval_min < prev and curr < prev:
                structure_points.append({
                    "index": curr_idx,
                    "type": "BOS",
                    "direction": "down",
                    "price": curr,
                    "time": candles[curr_idx]["time"],
                    "breakLevel": prev,
                })

        # ── Detect Change of Character (CHoCH) ──
        # CHoCH occurs when the dominant trend direction shifts
        if len(swing_highs) > 3 and len(swing_lows) > 3:
            # Check last few swings for higher highs vs lower lows
            last_shs = swing_highs[-4:]
            last_sls = swing_lows[-4:]
            sh_prices = [s["price"] for s in last_shs]
            sl_prices = [s["price"] for s in last_sls]

            # If most recent swing high and low are both lower
            if len(sh_prices) >= 2 and len(sl_prices) >= 2:
                if (sh_prices[-1] < sh_prices[-2] and
                        sl_prices[-1] < sl_prices[-2] and
                        closes[-1] < sl_prices[-2]):
                    structure_points.append({
                        "index": len(candles) - 1,
                        "type": "CHoCH",
                        "direction": "bearish",
                        "price": round(closes[-1], 2),
                        "time": candles[-1]["time"],
                    })
                elif (sh_prices[-1] > sh_prices[-2] and
                      sl_prices[-1] > sl_prices[-2] and
                      closes[-1] > sh_prices[-2]):
                    structure_points.append({
                        "index": len(candles) - 1,
                        "type": "CHoCH",
                        "direction": "bullish",
                        "price": round(closes[-1], 2),
                        "time": candles[-1]["time"],
                    })

        # ── Generate liquidity zones from swing points ──
        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2
        zones = []

        # Support zones from swing lows (resistance when broken above)
        for sl in swing_lows[-20:]:
            dist = abs(sl["price"] - cp) / cp
            # Nearer zones are more relevant
            base_strength = max(0.25, 1.0 - dist * 8)
            zones.append({
                "type": "support",
                "subtype": "swing_low",
                "price": sl["price"],
                "strength": round(base_strength, 3),
                "source": "swing_low",
                "time": sl["time"],
                "distance": round(dist * 100, 2),
                "isFresh": True,
            })

        # Resistance zones from swing highs (support when broken below)
        for sh in swing_highs[-20:]:
            dist = abs(sh["price"] - cp) / cp
            base_strength = max(0.25, 1.0 - dist * 8)
            zones.append({
                "type": "resistance",
                "subtype": "swing_high",
                "price": sh["price"],
                "strength": round(base_strength, 3),
                "source": "swing_high",
                "time": sh["time"],
                "distance": round(dist * 100, 2),
                "isFresh": True,
            })

        return {
            "swingHighs": swing_highs[-30:],
            "swingLows": swing_lows[-30:],
            "structure": structure_points[-10:],
            "zones": zones,
        }



# ─── Order Block Detector (ICT / Smart Money Concept) ─────────

class OrderBlockDetector:
    """
    Detects institutional Order Blocks.
    An Order Block is the last candle(s) before an impulsive move
    that breaks structure. These zones are where institutions
    placed large orders.
    """

    @staticmethod
    def detect(candles, min_impulse_pct=0.15):
        """
        Find order blocks: look for the last bearish candle before a
        bullish impulsive move (bullish OB) or last bullish candle
        before a bearish impulsive move (bearish OB).
        """
        if len(candles) < 15:
            return {"orderBlocks": [], "zones": []}

        obs = []
        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2

        for i in range(5, len(candles) - 3):
            # Bullish Order Block: bearish candle(s) followed by strong bullish move
            if (candles[i]["close"] < candles[i]["open"] and  # bearish candle
                    candles[i + 1]["close"] > candles[i + 1]["open"]):  # next is bullish

                # Check for impulse: at least 3 candles after, measure net move
                impulse_start = candles[i + 1]["low"]
                impulse_end = max(c["high"] for c in candles[i + 1:i + 4])
                impulse_pct = (impulse_end - impulse_start) / impulse_start * 100

                if impulse_pct >= min_impulse_pct:
                    # The OB is the low of the bearish candle + some buffer
                    ob_price_low = candles[i]["low"]
                    ob_price_high = candles[i]["high"]
                    ob_mid = (ob_price_low + ob_price_high) / 2
                    dist = abs(ob_mid - cp) / cp
                    strength = min(1.0, impulse_pct / 2) * max(0.3, 1.0 - dist * 6)

                    obs.append({
                        "type": "bullish",
                        "price": round(ob_mid, 2),
                        "priceLow": round(ob_price_low, 2),
                        "priceHigh": round(ob_price_high, 2),
                        "strength": round(strength, 3),
                        "impulse": round(impulse_pct, 2),
                        "index": i,
                        "time": candles[i]["time"],
                        "isFresh": True,
                    })

            # Bearish Order Block: bullish candle(s) followed by strong bearish move
            if (candles[i]["close"] > candles[i]["open"] and  # bullish candle
                    candles[i + 1]["close"] < candles[i + 1]["open"]):  # next is bearish

                impulse_start = candles[i + 1]["high"]
                impulse_end = min(c["low"] for c in candles[i + 1:i + 4])
                impulse_pct = (impulse_start - impulse_end) / impulse_start * 100

                if impulse_pct >= min_impulse_pct:
                    ob_price_low = candles[i]["low"]
                    ob_price_high = candles[i]["high"]
                    ob_mid = (ob_price_low + ob_price_high) / 2
                    dist = abs(ob_mid - cp) / cp
                    strength = min(1.0, impulse_pct / 2) * max(0.3, 1.0 - dist * 6)

                    obs.append({
                        "type": "bearish",
                        "price": round(ob_mid, 2),
                        "priceLow": round(ob_price_low, 2),
                        "priceHigh": round(ob_price_high, 2),
                        "strength": round(strength, 3),
                        "impulse": round(impulse_pct, 2),
                        "index": i,
                        "time": candles[i]["time"],
                        "isFresh": True,
                    })

        # Convert to zones
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
                "isFresh": True,
            })

        return {"orderBlocks": obs[-15:], "zones": zones}


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
    Detects liquidity sweeps — when price briefly breaks a
    swing high/low to trigger stop-losses (grab liquidity)
    before reversing. This is a key institutional signature.
    """

    @staticmethod
    def detect(candles, lookback=20, sweep_threshold=0.1):
        """
        A sweep occurs when price breaks a prior swing point
        by a small margin (< threshold%) and then closes back
        inside the range (rejection).
        """
        if len(candles) < lookback + 3:
            return {"sweeps": [], "zones": []}

        sweeps = []
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2

        for i in range(lookback, len(candles) - 1):
            window = candles[i - lookback:i]
            window_high = max(c["high"] for c in window)
            window_low = min(c["low"] for c in window)

            # Sweep up: break above window high but close back below
            if (highs[i] > window_high and
                    closes[i] < window_high and
                    (highs[i] - window_high) / window_high * 100 < sweep_threshold * 5):
                sweep_pct = (highs[i] - window_high) / window_high * 100
                dist = abs(window_high - cp) / cp
                strength = min(0.8, sweep_pct * 5) * max(0.3, 1.0 - dist * 6)
                sweeps.append({
                    "type": "resistance_sweep",
                    "direction": "up",
                    "price": round(window_high, 2),
                    "sweptPrice": round(highs[i], 2),
                    "sweepPct": round(sweep_pct, 3),
                    "strength": round(strength, 3),
                    "index": i,
                    "time": candles[i]["time"],
                    "isFresh": True,
                })

            # Sweep down: break below window low but close back above
            if (lows[i] < window_low and
                    closes[i] > window_low and
                    (window_low - lows[i]) / window_low * 100 < sweep_threshold * 5):
                sweep_pct = (window_low - lows[i]) / window_low * 100
                dist = abs(window_low - cp) / cp
                strength = min(0.8, sweep_pct * 5) * max(0.3, 1.0 - dist * 6)
                sweeps.append({
                    "type": "support_sweep",
                    "direction": "down",
                    "price": round(window_low, 2),
                    "sweptPrice": round(lows[i], 2),
                    "sweepPct": round(sweep_pct, 3),
                    "strength": round(strength, 3),
                    "index": i,
                    "time": candles[i]["time"],
                    "isFresh": True,
                })

        # Convert sweeps to zones (they represent strong levels)
        zones = []
        for sw in sweeps[-15:]:
            zones.append({
                "type": "resistance" if sw["type"] == "resistance_sweep" else "support",
                "subtype": "liquidity_sweep",
                "price": sw["price"],
                "strength": sw["strength"],
                "source": "liquidity_sweep",
                "time": sw["time"],
                "sweptPrice": sw["sweptPrice"],
                "sweepPct": sw["sweepPct"],
                "isFresh": True,
            })

        return {"sweeps": sweeps[-15:], "zones": zones}


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
            prices = [(c["high"] + c["low"]) / 2 for c in candles]
            # Regular divergence: price vs CVD
            for i in range(20, len(cvd_vals) - 3):
                # Bearish: price makes higher high, CVD makes lower high
                p_prev = prices[i - 10]
                p_curr = prices[i]
                cvd_prev = cvd_vals[i - 10]["value"]
                cvd_curr = cvd_vals[i]["value"]
                if (p_curr > p_prev * 1.002 and
                        cvd_curr < cvd_prev * 0.95):
                    divs.append({
                        "index": i,
                        "time": candles[i]["time"],
                        "type": "bearish",
                        "strength": round(min(1.0, abs(cvd_prev - cvd_curr) / max(abs(cvd_prev), 1)), 3),
                    })
                # Bullish: price makes lower low, CVD makes higher low
                elif (p_curr < p_prev * 0.998 and
                      cvd_curr > cvd_prev * 1.05):
                    divs.append({
                        "index": i,
                        "time": candles[i]["time"],
                        "type": "bullish",
                        "strength": round(min(1.0, abs(cvd_curr - cvd_prev) / max(abs(cvd_prev), 1)), 3),
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

    def __init__(self):
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

    def analyze_all(self, symbol="BTCUSDT", interval="15m", depth_limit=100):
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
            "candles": candles[-120:],
        }
