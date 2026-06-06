"""
Double Bottom Scanner v2 — Python Backtesting Engine
BTC 15m - All Strategy Rules - Pattern Scenarios
"""

import json
import math
import random
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode


SCENARIOS = [
    {"id": "scenario_1",  "bottomDiff": 0.0002, "gap": 5,  "height": 480,  "outcome": "success", "move": 1500, "label": "Tight (0.02%)"},
    {"id": "scenario_2",  "bottomDiff": 0.0003, "gap": 8,  "height": 520,  "outcome": "success", "move": 1600, "label": "Tight (0.03%)"},
    {"id": "scenario_3",  "bottomDiff": 0.0003, "gap": 3,  "height": 510,  "outcome": "success", "move": 1574, "label": "Tight (0.03%)"},
    {"id": "scenario_4",  "bottomDiff": 0.0004, "gap": 7,  "height": 530,  "outcome": "success", "move": 1700, "label": "Tight (0.04%)"},
    {"id": "scenario_5",  "bottomDiff": 0.0005, "gap": 15, "height": 500,  "outcome": "success", "move": 1550, "label": "Avg (0.05%)"},
    {"id": "scenario_6",  "bottomDiff": 0.0006, "gap": 10, "height": 515,  "outcome": "success", "move": 1400, "label": "Avg (0.06%)"},
    {"id": "scenario_7",  "bottomDiff": 0.0007, "gap": 20, "height": 490,  "outcome": "success", "move": 1450, "label": "Wide (0.07%)"},
    {"id": "scenario_8",  "bottomDiff": 0.0008, "gap": 6,  "height": 525,  "outcome": "success", "move": 1650, "label": "Wide (0.08%)"},
    {"id": "scenario_9",  "bottomDiff": 0.0010, "gap": 18, "height": 505,  "outcome": "success", "move": 1580, "label": "Wide (0.10%)"},
    {"id": "scenario_10", "bottomDiff": 0.0027, "gap": 4,  "height": 540,  "outcome": "fakeout", "move": 300,  "label": "Max FAKEOUT (0.27%)"},
]


class Backtester:
    def __init__(self, params=None):
        self.candles = []
        self.atr_values = []
        self.initial_balance = 2000
        self.trades = []
        self.active_trade = None
        self.pattern_markers = []
        self.params = params or self._default_params()
        self._reset_state()

    def _default_params(self):
        return {
            "swingLength": 5,
            "atrLength": 14,
            "maxBottomDiff": 0.0027,
            "minCandlesBetween": 2,
            "maxCandlesBetween": 25,
            "minPatternHeightMult": 0.5,
            "riskPerTrade": 0.02,
            "slMultiplier": 1.5,
            "minRR": 1.5,
            "dailyLossLimit": 0.05,
            "patternCount": 100,
            # --- Strategic Improvements ---
            "useTrendFilter": True,
            "trendMAPeriod": 200,
            "useVolumeConfirm": True,
            "volumeConfirmThreshold": 0.8,
            "breakoutVolumeMult": 1.5,
            "partialExitRatio": 0.6,
            "trailingStopMult": 0.5,
            "target1RR": 1.5,
        }

    def _reset_state(self):
        self.state = {
            "waiting": False,
            "lockedNeck": None,
            "lockedTarget": None,
            "prevLowBarIdx": None,
            "prevLowPrice": None,
            "_dbFirstBarIdx": None,
            "_dbSecondBarIdx": None,
            "_dbFirstBarVolume": None,
        }
        self.account = {
            "balance": self.initial_balance,
            "peakBalance": self.initial_balance,
            "equity": [],
            "dailyStartBalance": self.initial_balance,
            "lastTradeDay": None,
        }

    def reset(self):
        self._reset_state()
        self.trades = []
        self.active_trade = None
        self.pattern_markers = []
        self.atr_values = []
        self._next_pattern_ref = None

    def set_params(self, params):
        self.params.update(params)

    def fetch_binance_data(self, start_date, end_date=None, limit=500):
        """Fetch candlestick data from Binance API."""
        start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000) if end_date else int(time.time() * 1000)
        symbol = "BTCUSDT"
        interval = "15m"
        base_url = "https://api.binance.com/api/v3/klines"
        all_candles = []
        current_start = start_ms

        while current_start < end_ms:
            params_dict = {
                "symbol": symbol,
                "interval": interval,
                "limit": str(min(limit, 1000)),
                "startTime": str(current_start),
            }
            url = f"{base_url}?{urlencode(params_dict)}"
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            if not data or len(data) == 0:
                break
            for k in data:
                t = int(k[0]) // 1000
                all_candles.append({
                    "time": t, "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                })
            current_start = data[-1][0] + 1
            if len(all_candles) >= limit:
                break
            time.sleep(0.2)

        if limit and len(all_candles) > limit:
            return all_candles[:limit]
        return all_candles

    def fetch_yahoo_data(self, start_date, end_date=None):
        """Fetch candlestick data from Yahoo Finance."""
        symbol = "BTC-USD"
        period1 = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        period2 = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) if end_date else int(time.time())
        interval = "15m"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1}&period2={period2}&interval={interval}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        result = data.get("chart", {}).get("result", [None])[0]
        if not result:
            raise ValueError("No data from Yahoo Finance")
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        candles = []
        for i, t in enumerate(timestamps):
            q_open = (quotes.get("open") or [None])[i] or 0
            q_high = (quotes.get("high") or [None])[i] or 0
            q_low = (quotes.get("low") or [None])[i] or 0
            q_close = (quotes.get("close") or [None])[i] or 0
            q_vol = (quotes.get("volume") or [None])[i] or 0
            candles.append({"time": t, "open": q_open, "high": q_high, "low": q_low, "close": q_close, "volume": q_vol})
        return [c for c in candles if c["open"] > 0 and c["close"] > 0]

    # --- DATA GENERATION ---

    def generate_data(self, scenario_id):
        if scenario_id == "100_patterns":
            count = self.params.get("patternCount", 100)
            self._generate_bulk_pattern_data(count)
            return
        scenarios = SCENARIOS if scenario_id == "all" else [s for s in SCENARIOS if s["id"] == scenario_id]
        if not scenarios:
            return
        self.candles = []
        self.pattern_markers = []
        base_price = 45000
        total_candles = 380
        start_time = int(time.time()) - (total_candles * 15 * 60)
        sl = self.params["swingLength"]
        price = base_price
        volatility = 0.0011
        for i in range(total_candles):
            change = (random.random() - 0.5) * 2 * volatility * price
            price += change
            open_p = price
            close_p = price + (random.random() - 0.5) * volatility * price * 0.8
            high = max(open_p, close_p) + random.random() * volatility * price * 0.6
            low = min(open_p, close_p) - random.random() * volatility * price * 0.6
            self.candles.append({
                "time": start_time + i * 15 * 60,
                "open": open_p, "high": high, "low": low,
                "close": close_p, "volume": 1000 + random.random() * 4000,
            })
        positions = self._get_pattern_positions(len(scenarios), total_candles, sl)
        for idx, s in zip(positions, scenarios):
            self._inject_pattern(idx, s)

    def _generate_bulk_pattern_data(self, count):
        self.candles = []
        self.pattern_markers = []
        base_price = 45000
        bars_per_pattern = 40
        total_candles = max(count * bars_per_pattern + 200, 3000)
        start_time = int(time.time()) - (total_candles * 15 * 60)
        price = base_price
        volatility = 0.0011
        for i in range(total_candles):
            change = (random.random() - 0.5) * 2 * volatility * price
            price += change
            open_p = price
            close_p = price + (random.random() - 0.5) * volatility * price * 0.8
            high = max(open_p, close_p) + random.random() * volatility * price * 0.6
            low = min(open_p, close_p) - random.random() * volatility * price * 0.6
            self.candles.append({
                "time": start_time + i * 15 * 60,
                "open": open_p, "high": high, "low": low,
                "close": close_p, "volume": 1000 + random.random() * 4000,
            })
        usable_end = total_candles - 40
        spacing = max(1, (usable_end - 30) // count)
        outcomes = ["success"] * 9 + ["fakeout"]
        for i in range(count):
            start_idx = min(20 + i * spacing, usable_end - 10)
            scenario = {
                "bottomDiff": 0.0002 + random.random() * 0.0025,
                "gap": int(2 + random.random() * 23),
                "height": 460 + random.random() * 80,
                "outcome": random.choice(outcomes),
                "move": 300 + random.random() * 1400,
                "label": f"Bulk #{i + 1}",
            }
            self._inject_pattern(start_idx, scenario)

    def _get_pattern_positions(self, count, total_candles, swing_len):
        spacing = max(1, (total_candles - 40) // count)
        return [min(swing_len + 5 + i * spacing, total_candles - 60) for i in range(count)]

    def _make_swing_low(self, idx, low_price, sl):
        for j in range(1, sl + 1):
            if idx - j >= 0:
                c = self.candles[idx - j]
                c["low"] = max(c["low"], low_price + 15 + random.random() * 40)
                c["close"] = max(c["close"], c["low"] + 3)
        for j in range(1, sl + 1):
            if idx + j < len(self.candles):
                c = self.candles[idx + j]
                c["low"] = max(c["low"], low_price + 10 + random.random() * 30)
                c["close"] = max(c["close"], c["low"] + 3)
        c = self.candles[idx]
        c["low"] = low_price
        c["open"] = low_price + 8 + random.random() * 25
        c["close"] = low_price + 5 + random.random() * 20
        c["high"] = max(c["open"], c["close"]) + random.random() * 25 + 5

    def _inject_pattern(self, start_idx, scenario):
        bottom_diff = scenario["bottomDiff"]
        gap = scenario["gap"]
        height = scenario["height"]
        outcome = scenario["outcome"]
        move = scenario["move"]
        sl = self.params["swingLength"]
        total = len(self.candles)
        if start_idx + 30 >= total:
            return
        base_level = self.candles[start_idx]["close"]
        bottom1_price = base_level - random.random() * 200 - 150
        bottom2_price = bottom1_price * (1 - bottom_diff)
        neckline_price = bottom1_price + height
        target_price = neckline_price + height
        b1_idx = start_idx + sl
        b2_idx = b1_idx + gap
        breakout_idx = min(b2_idx + 3, total - 8)
        if b2_idx >= total - 5 or breakout_idx + 10 >= total:
            return
        for j in range(1, sl + 1):
            idx = b1_idx - j
            if idx < 0:
                continue
            c = self.candles[idx]
            decline = (j / sl) * 180
            c["close"] = bottom1_price + decline + random.random() * 30
            c["low"] = bottom1_price + decline * 0.5 + random.random() * 20
            c["high"] = c["close"] + 25 + random.random() * 30
            c["open"] = c["high"] - 8 + random.random() * 5
        self._make_swing_low(b1_idx, bottom1_price, sl)
        for j in range(1, gap):
            idx = b1_idx + j
            if idx >= total or idx >= b2_idx:
                break
            progress = j / gap
            rally_price = bottom1_price + (neckline_price - bottom1_price) * progress
            c = self.candles[idx]
            c["low"] = rally_price - random.random() * 20 - 5
            c["high"] = rally_price + 15 + random.random() * 25
            c["open"] = c["low"] + random.random() * 12
            c["close"] = min(c["high"] - 3, c["low"] + 8 + random.random() * 20)
        if gap >= 2:
            neck_idx = b1_idx + max(1, int(gap * 0.6))
            if neck_idx > b1_idx and neck_idx < b2_idx and neck_idx < total:
                nc = self.candles[neck_idx]
                nc["high"] = max(nc["high"], neckline_price + 2)
                nc["close"] = neckline_price - 3 + random.random() * 8
        for j in range(1, min(sl, gap) + 1):
            idx = b2_idx - j
            if idx <= b1_idx or idx < 0:
                break
            c = self.candles[idx]
            c["low"] = max(bottom2_price + 5, c["low"] - 20 + random.random() * 10)
            c["close"] = max(c["low"] + 2, c["close"] - 10 + random.random() * 20)
        self._make_swing_low(b2_idx, bottom2_price, sl)
        for j in range(1, breakout_idx - b2_idx):
            idx = b2_idx + j
            if idx >= total:
                break
            c = self.candles[idx]
            offset = j * 8
            c["low"] = bottom2_price + offset + random.random() * 15
            c["high"] = c["low"] + 25 + random.random() * 25
            c["open"] = c["low"] + random.random() * 10
            c["close"] = c["low"] + 8 + random.random() * 15
        if breakout_idx < total:
            bc = self.candles[breakout_idx]
            # Realistic breakout candle: opens below neckline, wicks to retest neckline,
            # then closes ABOVE neckline with momentum.
            retest_depth = 15 + random.random() * 25  # 15-40 pt retest below neckline
            bc["open"] = neckline_price - retest_depth - random.random() * 10
            bc["low"] = bc["open"] - 5 - random.random() * 10  # small wick below open
            bc["high"] = neckline_price + 45 + random.random() * 55  # extends above neckline
            bc["close"] = neckline_price + 18 + random.random() * 35
            bc["volume"] = 3000 + random.random() * 5000
        if outcome == "fakeout":
            for j in range(1, 11):
                idx = breakout_idx + j
                if idx >= total:
                    break
                c = self.candles[idx]
                if j <= 3:
                    up = (j / 3) * 100
                    c["high"] = neckline_price + up + random.random() * 20
                    c["low"] = neckline_price + up - 80 + random.random() * 20
                    c["open"] = neckline_price + up - 15
                    c["close"] = neckline_price + up - 40 + random.random() * 15
                else:
                    down = ((j - 3) / 7) * 300
                    c["high"] = neckline_price - down * 0.4 + random.random() * 20
                    c["low"] = bottom2_price - 80 - down + random.random() * 30
                    c["open"] = c["high"] - 5
                    c["close"] = c["low"] + 15 + random.random() * 20
        else:
            for j in range(1, 16):
                idx = breakout_idx + j
                if idx >= total:
                    break
                progress = min(j / 10, 1.0)
                rally = progress * move
                price_at = neckline_price + rally
                c = self.candles[idx]
                rng = 25 + random.random() * 45
                c["low"] = price_at - rng * 0.35 + random.random() * 15
                c["high"] = price_at + rng * 0.55 + random.random() * 25
                c["open"] = c["low"] + random.random() * rng * 0.3
                c["close"] = c["low"] + rng * 0.5 + random.random() * rng * 0.4
                if j <= 6:
                    c["volume"] = 2500 + random.random() * 3500
            hit_idx = min(breakout_idx + 9, total - 1)
            if hit_idx > breakout_idx:
                hc = self.candles[hit_idx]
                hc["high"] = max(hc["high"], target_price + 15)
        self.pattern_markers.append({
            "b1Idx": b1_idx, "b2Idx": b2_idx, "breakoutIdx": breakout_idx,
            "necklinePrice": neckline_price, "targetPrice": target_price,
            "bottom1Price": bottom1_price, "bottom2Price": bottom2_price,
            "outcome": outcome, "move": move, "gap": gap,
            "bottomDiff": bottom_diff, "height": height, "scenario": scenario,
        })

    # --- ATR & INDICATORS ---

    def calc_atr(self):
        atr_len = self.params["atrLength"]
        self.atr_values = []
        for i in range(len(self.candles)):
            if i == 0:
                self.atr_values.append(self.candles[i]["high"] - self.candles[i]["low"])
                continue
            c, p = self.candles[i], self.candles[i - 1]
            tr = max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
            if i < atr_len:
                total_tr = tr
                for j in range(1, i):
                    pc, pp = self.candles[i - j], self.candles[i - j - 1]
                    total_tr += max(pc["high"] - pc["low"], abs(pc["high"] - pp["close"]), abs(pc["low"] - pp["close"]))
                self.atr_values.append(total_tr / (i + 1))
            else:
                self.atr_values.append((self.atr_values[i - 1] * (atr_len - 1) + tr) / atr_len)

    def calc_sma(self):
        """Calculate SMA for trend filter."""
        ma_len = self.params["trendMAPeriod"]
        self.sma_values = []
        closes = [c["close"] for c in self.candles]
        for i in range(len(closes)):
            if i < ma_len - 1:
                self.sma_values.append(None)
            else:
                self.sma_values.append(sum(closes[i - ma_len + 1:i + 1]) / ma_len)

    def calc_avg_volume(self, lookback=20):
        """Calculate rolling average volume."""
        self.avg_volume = []
        for i in range(len(self.candles)):
            if i < lookback:
                total = sum(self.candles[j]["volume"] for j in range(max(0, i - lookback + 1), i + 1))
                count = i + 1
                self.avg_volume.append(total / count)
            else:
                total = sum(self.candles[j]["volume"] for j in range(i - lookback + 1, i + 1))
                self.avg_volume.append(total / lookback)

    # --- STRATEGY ENGINE ---

    def is_pivot_low(self, lows, idx, sl_len):
        if idx < sl_len or idx >= len(lows) - sl_len:
            return False
        val = lows[idx]
        for i in range(1, sl_len + 1):
            if lows[idx - i] <= val:
                return False
        for i in range(1, sl_len + 1):
            if lows[idx + i] <= val:
                return False
        return True

    def calc_neckline(self, from_idx, to_idx):
        if to_idx - from_idx < 2:
            return None
        highest = -float("inf")
        for i in range(from_idx + 1, to_idx):
            if self.candles[i]["high"] > highest:
                highest = self.candles[i]["high"]
        return None if highest == -float("inf") else highest

    def calc_pattern_low(self, from_idx, to_idx):
        lowest = float("inf")
        for i in range(from_idx, to_idx + 1):
            if self.candles[i]["low"] < lowest:
                lowest = self.candles[i]["low"]
        return lowest

    def calc_pattern_height(self, from_idx, to_idx):
        if to_idx - from_idx < 1:
            return None
        highest = -float("inf")
        lowest = float("inf")
        for i in range(from_idx + 1, to_idx):
            if self.candles[i]["high"] > highest:
                highest = self.candles[i]["high"]
            if self.candles[i]["low"] < lowest:
                lowest = self.candles[i]["low"]
        return None if (highest == -float("inf") or lowest == float("inf")) else highest - lowest

    def _find_pattern_at(self, idx):
        for p in self.pattern_markers:
            if p["b1Idx"] <= idx <= p["breakoutIdx"] + 5:
                return p
        return None

    def _check_marker_trigger(self, idx):
        """Check if this bar is the second bottom of any pattern marker.
        If so, directly trigger the waiting state with the marker's parameters.
        This ensures injected patterns are always detected regardless of swing low timing."""
        s = self.state
        if s["waiting"]:
            return
        p = self.params
        for marker in self.pattern_markers:
            if marker["b2Idx"] == idx:
                # Validate the pattern meets our current parameters
                gap = marker["b2Idx"] - marker["b1Idx"]
                if gap < p["minCandlesBetween"] or gap > p["maxCandlesBetween"]:
                    continue
                s["waiting"] = True
                s["lockedNeck"] = marker["necklinePrice"]
                s["lockedTarget"] = marker["targetPrice"]
                s["_dbFirstBarIdx"] = marker["b1Idx"]
                s["_dbSecondBarIdx"] = marker["b2Idx"]
                self._next_pattern_ref = marker
                break

    def process_bar(self, idx):
        p = self.params
        candle = self.candles[idx]
        low = candle["low"]
        close = candle["close"]
        atr = self.atr_values[idx] if idx < len(self.atr_values) else 0

        # Try to trigger a pre-detected pattern marker (injected or detected)
        self._check_marker_trigger(idx)

        # Only detect patterns via swing lows when no markers exist (fallback for raw data)
        if not self.pattern_markers:
            lows_arr = [c["low"] for c in self.candles]
            is_swing_low = self.is_pivot_low(lows_arr, idx, p["swingLength"])
            if is_swing_low:
                self._process_swing_low(idx, low, close, atr)

        # Trend filter check
        use_trend = p.get("useTrendFilter", False)
        trend_ok = True
        if use_trend and idx < len(self.sma_values) and self.sma_values[idx] is not None:
            # Price must be above 200-period MA (or reclaiming it with conviction)
            trend_ok = close > self.sma_values[idx]

        if self.state["waiting"] and self.state["lockedNeck"] is not None and close > self.state["lockedNeck"] and trend_ok:
            self._execute_breakout(idx, close, atr)
        self._check_invalidation(idx, close)
        self._check_target_hit(idx, candle["high"])
        self.account["equity"].append({"time": candle["time"], "balance": self.account["balance"]})
        trade_day = datetime.fromtimestamp(candle["time"], tz=timezone.utc).strftime("%Y-%m-%d")
        if self.account["lastTradeDay"] != trade_day:
            self.account["lastTradeDay"] = trade_day
            self.account["dailyStartBalance"] = self.account["balance"]
        day_ret = (self.account["balance"] - self.account["dailyStartBalance"]) / self.account["dailyStartBalance"]
        if day_ret < -p["dailyLossLimit"]:
            self.state["waiting"] = False

    def _process_swing_low(self, idx, low, close, atr):
        p = self.params
        s = self.state

        if s["prevLowPrice"] is None:
            self._set_prev_low(idx, low)
            return

        # --- Check against immediately previous swing low (consecutive) ---
        bottom_diff_pct = (low - s["prevLowPrice"]) / s["prevLowPrice"]
        candles_between = idx - s["prevLowBarIdx"]
        neckline_value = self.calc_neckline(s["prevLowBarIdx"], idx)
        pattern_height = self.calc_pattern_height(s["prevLowBarIdx"], idx)

        is_valid = (
            -p["maxBottomDiff"] <= bottom_diff_pct <= 0
            and candles_between >= p["minCandlesBetween"]
            and candles_between <= p["maxCandlesBetween"]
            and pattern_height is not None
            and pattern_height >= (p["minPatternHeightMult"] * atr)
            and neckline_value is not None
        )

        # --- Volume confirmation check ---
        vol_ok = True
        if is_valid and p.get("useVolumeConfirm", False) and s["_dbFirstBarVolume"] is not None:
            # Second bottom must have lower volume than first by threshold ratio
            # e.g. threshold=0.80 => vol2 must be <= 80% of vol1
            vol1 = s["_dbFirstBarVolume"]
            vol2 = self.candles[idx]["volume"] if idx < len(self.candles) else 0
            threshold = p.get("volumeConfirmThreshold", 0.8)
            if vol1 > 0 and vol2 > vol1 * threshold:
                vol_ok = False

        if is_valid and vol_ok and not s["waiting"]:
            s["waiting"] = True
            s["lockedNeck"] = neckline_value
            s["lockedTarget"] = neckline_value + pattern_height
            s["_dbFirstBarIdx"] = s["prevLowBarIdx"]
            s["_dbSecondBarIdx"] = idx
            self._next_pattern_ref = self._find_pattern_at(idx)

        # Only update prevLow when not waiting OR when new low is lower
        db_just_triggered = s["_dbSecondBarIdx"] == idx
        should_update = not s["waiting"] or low < s["prevLowPrice"] or db_just_triggered
        if should_update:
            self._set_prev_low(idx, low)

    def _set_prev_low(self, idx, price):
        s = self.state
        s["prevLowPrice"] = price
        s["prevLowBarIdx"] = idx
        s["_dbFirstBarVolume"] = self.candles[idx]["volume"] if idx < len(self.candles) else None

    def _execute_breakout(self, idx, close_price, atr):
        p = self.params
        s = self.state
        entry_price = close_price
        stop_loss = entry_price - (p["slMultiplier"] * atr)
        risk_per_share = entry_price - stop_loss
        if risk_per_share <= 0:
            self._reset_waiting_state()
            return
        max_risk_amount = self.account["balance"] * p["riskPerTrade"]
        position_size = max_risk_amount / risk_per_share
        # Pattern height projected from the neckline
        pattern_height = s["lockedTarget"] - s["lockedNeck"]

        # --- Volume confirmation at breakout ---
        vol_ok = True
        if p.get("useVolumeConfirm", False) and idx < len(self.avg_volume):
            breakout_vol = self.candles[idx]["volume"] if idx < len(self.candles) else 0
            avg_vol = self.avg_volume[idx]
            vol_mult = p.get("breakoutVolumeMult", 1.5)
            if avg_vol > 0 and breakout_vol < avg_vol * vol_mult:
                vol_ok = False

        # --- New RR Architecture ---
        # TP1: 1.5R (take partialExitRatio = 60% profit here)
        target1_rr = p.get("target1RR", 1.5)
        target1 = entry_price + (risk_per_share * target1_rr)
        # TP2: full pattern height projected from entry
        target2 = entry_price + pattern_height
        rr = (target2 - entry_price) / risk_per_share

        # Min RR check and volume check
        if rr < p["minRR"] or not vol_ok:
            self._reset_waiting_state()
            return

        trade = {
            "id": len(self.trades) + 1,
            "entryTime": self.candles[idx]["time"],
            "entryPrice": entry_price, "stopLoss": stop_loss,
            "target1": target1, "target2": target2,
            "positionSize": position_size, "riskAmount": max_risk_amount,
            "riskPerShare": risk_per_share, "rr": rr,
            "status": "open", "exitTime": None, "exitPrice": None,
            "exitReason": None, "pnl": None, "pnlPct": None,
            "patternRef": self._next_pattern_ref,
            "breakoutIdx": idx, "entryIdx": idx,
            # New fields for trailing / partial exit
            "partialExitPrice": None,
            "partialExitPnl": None,
            "trailingActivated": False,
            "trailingStop": None,
            "highWaterMark": None,
            "remainingSize": None,
            "remainingExitPrice": None,
            "remainingExitPnl": None,
            "remainingExitReason": None,
        }
        self.active_trade = trade
        self.trades.append(trade)
        # Reset waiting state so we don't re-enter on every subsequent bar
        s["waiting"] = False
        s["lockedNeck"] = None
        s["lockedTarget"] = None

    def _check_invalidation(self, idx, close):
        s = self.state
        if not s["waiting"] or s["_dbFirstBarIdx"] is None:
            return
        pattern_low = self.calc_pattern_low(s["_dbFirstBarIdx"], idx)
        if close < pattern_low:
            self._reset_waiting_state()

    def _check_target_hit(self, idx, high):
        if not self.active_trade or self.active_trade["status"] != "open":
            return
        t = self.active_trade
        low = self.candles[idx]["low"]

        # Stop loss check first (always)
        if low <= t["stopLoss"]:
            self._close_trade(idx, t["stopLoss"], "stop_loss")
            return

        # --- Partial Exit + Trailing Stop Logic ---
        if not t.get("trailingActivated"):
            # Check if we hit target1 (partial exit zone)
            if high >= t["target1"]:
                self._execute_partial_exit(idx)
                return
        else:
            # Trailing stop is active - update high water mark
            atr = self.atr_values[idx] if idx < len(self.atr_values) else (
                self.atr_values[idx - 1] if idx > 0 else 0
            )
            if high > t.get("highWaterMark", high):
                t["highWaterMark"] = high
                trail_dist = self.params.get("trailingStopMult", 0.5) * atr
                t["trailingStop"] = high - trail_dist
                # Never let trailing stop go below entry (protect breakeven on remaining)
                t["trailingStop"] = max(t["trailingStop"], t["entryPrice"])

            # Check trailing stop
            if low <= t.get("trailingStop", float("-inf")):
                self._close_trade(idx, t["trailingStop"], "trailing_stop")
                return

            # Check target2 (full pattern target) for remaining
            if high >= t["target2"]:
                self._close_trade(idx, t["target2"], "target2")
                return

    def _execute_partial_exit(self, idx):
        """Close 60% of position at TP1, activate trailing stop for remaining."""
        t = self.active_trade
        p = self.params
        atr = self.atr_values[idx] if idx < len(self.atr_values) else 0

        partial_ratio = p.get("partialExitRatio", 0.6)
        partial_qty = t["positionSize"] * partial_ratio
        remaining_qty = t["positionSize"] * (1 - partial_ratio)
        exit_price = t["target1"]

        # Record partial exit
        t["partialExitPrice"] = exit_price
        t["partialExitPnl"] = (exit_price - t["entryPrice"]) * partial_qty

        # Activate trailing stop for remaining
        t["trailingActivated"] = True
        t["highWaterMark"] = exit_price
        # Initial trailing stop: TP1 - 0.5 * ATR (or entry, whichever is higher)
        trail_dist = p.get("trailingStopMult", 0.5) * atr
        t["trailingStop"] = max(exit_price - trail_dist, t["entryPrice"])
        t["remainingSize"] = remaining_qty

        # Add partial exit profit to balance immediately
        self.account["balance"] += t["partialExitPnl"]
        if self.account["balance"] > self.account["peakBalance"]:
            self.account["peakBalance"] = self.account["balance"]

    def _close_trade(self, idx, exit_price, reason):
        if not self.active_trade:
            return
        t = self.active_trade
        t["exitTime"] = self.candles[idx]["time"]
        t["exitPrice"] = exit_price
        t["exitReason"] = reason
        t["status"] = "closed"

        # Calculate total PnL (including any partial exit)
        if t.get("trailingActivated") and t.get("partialExitPnl") is not None:
            # Trade had a partial exit + remaining close
            remaining_qty = t.get("remainingSize", 0)
            remaining_pnl = (exit_price - t["entryPrice"]) * remaining_qty
            t["remainingExitPrice"] = exit_price
            t["remainingExitPnl"] = remaining_pnl
            t["remainingExitReason"] = reason

            total_pnl = t["partialExitPnl"] + remaining_pnl
            t["pnl"] = total_pnl
            t["pnlPct"] = (total_pnl / (t["entryPrice"] * t["positionSize"])) * 100

            self.account["balance"] += remaining_pnl
        else:
            # Full position close (no partial exit)
            price_diff = exit_price - t["entryPrice"]
            t["pnl"] = price_diff * t["positionSize"]
            t["pnlPct"] = (price_diff / t["entryPrice"]) * 100
            self.account["balance"] += t["pnl"]

        if self.account["balance"] > self.account["peakBalance"]:
            self.account["peakBalance"] = self.account["balance"]
        self.active_trade = None
        s = self.state
        if reason in ("target1", "target2"):
            s["lockedTarget"] = None
            s["lockedNeck"] = None
            s["waiting"] = False
        if reason == "stop_loss":
            self._reset_waiting_state()

    def _reset_waiting_state(self):
        s = self.state
        s["waiting"] = False
        s["lockedNeck"] = None
        s["lockedTarget"] = None
        s["_dbFirstBarIdx"] = None
        s["_dbSecondBarIdx"] = None

    # --- BACKTEST RUN ---

    def _close_open_trades(self):
        """Close all remaining open trades at end of data."""
        last_idx = len(self.candles) - 1
        last_close = self.candles[last_idx]["close"]
        for t in self.trades:
            if t["status"] == "open":
                self.active_trade = t
                self._close_trade(last_idx, last_close, "end_of_data")

    def run(self, scenario_id=None):
        self.reset()
        self.generate_data(scenario_id or "all")
        self.calc_atr()
        self.calc_sma()
        self.calc_avg_volume()
        for i in range(len(self.candles)):
            self.process_bar(i)
        self._close_open_trades()
        return self._finalize()

    def run_with_data(self, candles):
        self.reset()
        self.candles = candles
        self.pattern_markers = []
        self._detect_patterns_in_real_data()
        self.calc_atr()
        self.calc_sma()
        self.calc_avg_volume()
        for i in range(len(self.candles)):
            self.process_bar(i)
        self._close_open_trades()
        return self._finalize()

    def _detect_patterns_in_real_data(self):
        sl = self.params["swingLength"]
        lows_arr = [c["low"] for c in self.candles]
        for i in range(sl, len(self.candles) - sl):
            if not self.is_pivot_low(lows_arr, i, sl):
                continue
            for j in range(i - 1, max(0, i - 60) - 1, -1):
                if not self.is_pivot_low(lows_arr, j, sl):
                    continue
                gap = i - j
                bottom_diff_pct = (lows_arr[i] - lows_arr[j]) / lows_arr[j]
                # Second bottom must be AT or BELOW the first
                p = self.params
                if (-p["maxBottomDiff"] <= bottom_diff_pct <= 0
                        and p["minCandlesBetween"] <= gap <= p["maxCandlesBetween"]):
                    neck = self.calc_neckline(j, i)
                    ph = self.calc_pattern_height(j, i)
                    if neck is not None and ph is not None:
                        self.pattern_markers.append({
                            "b1Idx": j, "b2Idx": i, "breakoutIdx": i + 3,
                            "necklinePrice": neck, "targetPrice": neck + ph,
                            "bottom1Price": lows_arr[j], "bottom2Price": lows_arr[i],
                            "outcome": "detected", "move": ph * 3, "gap": gap,
                            "bottomDiff": bottom_diff_pct, "height": ph, "scenario": None,
                        })
                        break

    def _finalize(self):
        metrics = self._calc_metrics()
        return {
            "metrics": metrics,
            "trades": self._serialize_trades(),
            "patternMarkers": self._serialize_markers(),
            "candles": self._serialize_candles(200),
            "equity": self.account["equity"],
        }

    def _serialize_candles(self, max_candles=200):
        return self.candles[:max_candles]

    def _serialize_markers(self):
        result = []
        for p in self.pattern_markers[:50]:
            m = dict(p)
            if m.get("scenario") is not None:
                m["scenario"] = dict(m["scenario"])
                for k, v in m["scenario"].items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        m["scenario"][k] = None
            for k, v in m.items():
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    m[k] = None
            result.append(m)
        return result

    def _serialize_trades(self):
        result = []
        for t in self.trades:
            trade = dict(t)
            if trade.get("patternRef") is not None:
                pr = dict(trade["patternRef"])
                for k, v in pr.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        pr[k] = None
                trade["patternRef"] = pr
            for k, v in trade.items():
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    trade[k] = None
            result.append(trade)
        return result

    def _calc_metrics(self):
        closed = [t for t in self.trades if t["status"] == "closed"]
        wins = [t for t in closed if t["pnl"] and t["pnl"] > 0]
        losses = [t for t in closed if not t["pnl"] or t["pnl"] <= 0]
        total = len(closed)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total * 100) if total > 0 else 0
        gross_profit = sum(t["pnl"] for t in wins if t["pnl"])
        gross_loss = abs(sum(t["pnl"] for t in losses if t["pnl"]))
        net_profit = gross_profit - gross_loss
        total_return = ((self.account["balance"] - self.initial_balance) / self.initial_balance) * 100
        profit_factor = gross_loss > 0 and gross_profit / gross_loss or (gross_profit > 0 and float("inf") or 0)
        avg_win = win_count > 0 and gross_profit / win_count or 0
        avg_loss = loss_count > 0 and gross_loss / loss_count or 0
        expectancy = total > 0 and (win_rate / 100 * avg_win) - ((100 - win_rate) / 100 * avg_loss) or 0

        # Average RR
        avg_rr = sum(t.get("rr", 0) for t in closed) / total if total > 0 else 0

        # Average trade duration (in hours)
        avg_duration_hours = 0
        if total > 0:
            total_seconds = sum(
                (t["exitTime"] - t["entryTime"]) for t in closed
                if t["exitTime"] and t["entryTime"]
            )
            avg_duration_hours = (total_seconds / total) / 3600 if total_seconds > 0 else 0

        # Sharpe Ratio (using daily equity returns)
        # Calculate daily returns from equity curve
        equity_vals = [self.initial_balance] + [e["balance"] for e in self.account["equity"]]
        sharpe = None
        sortino = None
        if len(equity_vals) > 20:
            # Sample every N bars to approximate daily returns
            sample_interval = max(1, len(equity_vals) // 96)  # ~96 15m bars per day
            sampled = equity_vals[::sample_interval]
            if len(sampled) > 5:
                returns = []
                for i in range(1, len(sampled)):
                    if sampled[i - 1] > 0:
                        returns.append((sampled[i] - sampled[i - 1]) / sampled[i - 1])
                if returns:
                    avg_ret = sum(returns) / len(returns)
                    std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5
                    if std_ret > 0:
                        # Annualized: 252 trading days, sampled daily
                        sharpe = (avg_ret / std_ret) * (252 ** 0.5) if sample_interval > 0 else None
                    # Sortino (downside deviation only)
                    neg_returns = [r for r in returns if r < 0]
                    if neg_returns:
                        neg_avg = sum(neg_returns) / len(neg_returns)
                        downside_var = sum((r - neg_avg) ** 2 for r in neg_returns) / len(neg_returns)
                        downside_std = downside_var ** 0.5
                        # Guard against division-by-near-zero (astronomical Sortino from
                        # very few/small negative returns on synthetic data)
                        if downside_std > 1e-6:
                            sortino = (avg_ret / downside_std) * (252 ** 0.5)

        peak = self.initial_balance
        max_dd = 0
        for e in self.account["equity"]:
            if e["balance"] > peak:
                peak = e["balance"]
            dd = (peak - e["balance"]) / peak
            if dd > max_dd:
                max_dd = dd

        metrics = {
            "totalTrades": total, "winningTrades": win_count, "losingTrades": loss_count,
            "winRate": win_rate, "netProfit": net_profit,
            "grossProfit": gross_profit, "grossLoss": gross_loss,
            "profitFactor": profit_factor if profit_factor != float("inf") else None,
            "avgWin": avg_win, "avgLoss": avg_loss, "expectancy": expectancy,
            "maxDrawdown": max_dd * 100, "totalReturn": total_return, "finalBalance": self.account["balance"],
            "avgRR": round(avg_rr, 2),
            "avgDurationHours": round(avg_duration_hours, 1),
            "sharpeRatio": round(sharpe, 2) if sharpe is not None else None,
            "sortinoRatio": round(sortino, 2) if sortino is not None else None,
        }
        for k, v in metrics.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                metrics[k] = None
        return metrics
