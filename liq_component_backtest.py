"""
Liquidity Identifier — Comprehensive Component Backtest v3
Walk-Forward Validation | Slippage | Anti-Overfitting | 100+ Trades
"""

import json, sys, time
from collections import defaultdict
from datetime import datetime
import numpy as np
import requests
from liq_engine import (
    OrderBlockDetector, FVGBalancer, LiquiditySweepDetector,
    SwingPointDetector, VolumeProfileAnalyzer, CVDAnalyzer, DeltaPatternDetector,
    calc_adx, calc_bb_width, detect_market_regime,
)

ENDPOINTS = [
    "https://api.binance.com", "https://api1.binance.com",
    "https://api2.binance.com", "https://api3.binance.com", "https://api4.binance.com",
]

# ─── Trade Configuration ─────────────────────────────────────
RISK_PER_TRADE = 2.0       # Risk 2% of capital per trade
SL_ATR_MULT = 1.5          # Stop loss at 1.5x ATR
TP_ATR_MULT = 3.0          # Take profit at 3.0x ATR (2:1 R:R)
TX_COST = 0.1              # 0.1% per side (Binance taker fee)
TX_TOTAL = TX_COST * 2     # 0.2% round-trip cost
SLIPPAGE = 0.05            # 0.05% slippage per trade (realistic for 15m crypto)


def fetch_klines(symbol, interval, limit=1000):
    s = requests.Session()
    s.headers.update({"User-Agent": "LiqBT/2.0"})
    all_c = []
    rem = limit
    et = None
    for b in ENDPOINTS:
        try:
            r = s.get(b + "/api/v3/klines", params={"symbol": symbol, "interval": interval, "limit": 1}, timeout=10)
            r.raise_for_status()
            bu = b
            break
        except Exception:
            continue
    else:
        raise RuntimeError("All endpoints failed")
    while rem > 0:
        p = {"symbol": symbol, "interval": interval, "limit": min(500, rem)}
        if et:
            p["endTime"] = et
        try:
            r = s.get(bu + "/api/v3/klines", params=p, timeout=15)
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for k in batch:
                all_c.append({"time": k[0] // 1000, "open": float(k[1]), "high": float(k[2]),
                              "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
            rem -= len(batch)
            et = batch[-1][0]
            if len(batch) < 500:
                break
            time.sleep(0.15)
        except Exception as e:
            print("Fetch error: %s" % e, file=sys.stderr)
            break
    return all_c


# ─── Indicator Helpers ────────────────────────────────────────

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return float(np.mean(trs)) if trs else 0
    a = float(np.mean(trs[:period]))
    for i in range(period, len(trs)):
        a = (a * (period - 1) + trs[i]) / period
    return a


def sma(candles, period):
    if len(candles) < period:
        return None
    closes = [c["close"] for c in candles]
    return sum(closes[-period:]) / period


def ema(candles, period):
    if len(candles) < period:
        return None
    closes = [c["close"] for c in candles]
    k = 2.0 / (period + 1)
    e = sum(closes[:period]) / period
    for i in range(period, len(closes)):
        e = closes[i] * k + e * (1 - k)
    return e


def avg_volume(candles, period=20):
    if len(candles) < period:
        period = len(candles)
    return sum(c.get("volume", 0) for c in candles[-period:]) / max(period, 1)


def is_bullish_candle(c):
    return c["close"] > c["open"]


def is_bearish_candle(c):
    return c["close"] < c["open"]


# ─── Trade Simulation (with slippage) ────────────────────────

def sim(entry, direction, future_candles, atr,
        sl_mult=SL_ATR_MULT, tp_mult=TP_ATR_MULT,
        risk_pct=RISK_PER_TRADE, tx_cost=TX_TOTAL,
        slippage=SLIPPAGE, use_next_open=False):
    """
    Simulate a trade with proper R-multiple PnL + slippage.
    - Win: +risk_pct * (tp_mult/sl_mult) minus tx_cost
    - Loss: -risk_pct minus tx_cost
    - R:R = tp_mult/sl_mult = 2.0 by default
    """
    if atr <= 0:
        return {"r": "T", "p": 0, "b": 0}

    if use_next_open and future_candles:
        entry = future_candles[0]["open"]

    # Apply slippage to entry price
    if direction == "L":
        entry = entry * (1 + slippage / 100)
    else:
        entry = entry * (1 - slippage / 100)

    if direction == "L":
        sl, tp = entry - atr * sl_mult, entry + atr * tp_mult
    else:
        sl, tp = entry + atr * sl_mult, entry - atr * tp_mult

    win_pnl = risk_pct * (tp_mult / sl_mult)
    loss_pnl = -risk_pct

    for i, c in enumerate(future_candles):
        if direction == "L":
            if c["low"] <= sl:
                return {"r": "L", "p": loss_pnl - tx_cost, "b": i + 1}
            if c["high"] >= tp:
                return {"r": "W", "p": win_pnl - tx_cost, "b": i + 1}
        else:
            if c["high"] >= sl:
                return {"r": "L", "p": loss_pnl - tx_cost, "b": i + 1}
            if c["low"] <= tp:
                return {"r": "W", "p": win_pnl - tx_cost, "b": i + 1}

    if future_candles:
        last = future_candles[-1]
        if direction == "L":
            move = (last["close"] - entry) / entry * 100
        else:
            move = (entry - last["close"]) / entry * 100
        actual_r = move / (atr * sl_mult / entry * 100) if (atr * sl_mult / entry * 100) > 0 else 0
        pnl = actual_r * risk_pct - tx_cost
        pnl = max(loss_pnl, min(win_pnl, pnl))
        return {"r": "W" if pnl > 0 else "L", "p": round(pnl, 4), "b": len(future_candles)}
    return {"r": "T", "p": 0, "b": 0}


# ═══════════════════════════════════════════════════════════════
# COMPONENT BACKTESTERS — individual component tests
# ═══════════════════════════════════════════════════════════════

def bt_ob(candles, hold=30):
    trades, obs = [], []
    for i in range(60, len(candles) - hold - 1):
        w, c, f = candles[:i + 1], candles[i], candles[i + 1:i + 1 + hold]
        a = calc_atr(w)
        if a <= 0:
            continue
        adx = calc_adx(w)
        if adx < 20:
            continue
        ma50 = sma(w, 50)
        if i % 15 == 0:
            for ob in OrderBlockDetector.detect(w, min_impulse_pct=0.2).get("orderBlocks", []):
                if ob.get("mitigated", False):
                    continue
                if ob.get("strength", 0) < 0.2:
                    continue
                if ob.get("impulse", 0) < 0.15:
                    continue
                obs.append({
                    "pl": ob.get("priceLow", ob["price"]),
                    "ph": ob.get("priceHigh", ob["price"]),
                    "type": ob["type"], "idx": i, "traded": False,
                    "strength": ob.get("strength", 0),
                    "impulse": ob.get("impulse", 0),
                })
        for ob in obs:
            if ob["traded"] or i - ob["idx"] > 40:
                continue
            vol_avg = avg_volume(w, 20)
            if c.get("volume", 0) < vol_avg * 0.7:
                continue
            trend_ok = True
            if ma50:
                if ob["type"] == "bullish" and c["close"] < ma50 and ob["strength"] < 0.5:
                    trend_ok = False
                if ob["type"] == "bearish" and c["close"] > ma50 and ob["strength"] < 0.5:
                    trend_ok = False
            if not trend_ok:
                continue
            if ob["type"] == "bullish" and c["low"] <= ob["ph"] and c["close"] > ob["pl"]:
                if len(f) > 0 and not is_bullish_candle(f[0]):
                    continue
                r = sim(c["close"], "L", f, a, use_next_open=True)
                trades.append(r)
                ob["traded"] = True
                break
            if ob["type"] == "bearish" and c["high"] >= ob["pl"] and c["close"] < ob["ph"]:
                if len(f) > 0 and not is_bearish_candle(f[0]):
                    continue
                r = sim(c["close"], "S", f, a, use_next_open=True)
                trades.append(r)
                ob["traded"] = True
                break
    return trades


def bt_fvg(candles, hold=30):
    trades, fvgs = [], []
    for i in range(60, len(candles) - hold - 1):
        w, c, f = candles[:i + 1], candles[i], candles[i + 1:i + 1 + hold]
        a = calc_atr(w)
        if a <= 0:
            continue
        adx = calc_adx(w)
        if adx < 20:
            continue
        ma50 = sma(w, 50)
        if i % 15 == 0:
            for fv in FVGBalancer.detect(w, min_gap_pct=0.03).get("fvgs", []):
                if fv.get("isFresh", False) and fv.get("strength", 0) >= 0.3:
                    fvgs.append({"pl": fv["priceLow"], "ph": fv["priceHigh"],
                                 "type": fv["type"], "idx": i, "traded": False,
                                 "strength": fv.get("strength", 0)})
        for fv in fvgs:
            if fv["traded"] or i - fv["idx"] > 30:
                continue
            vol_avg = avg_volume(w, 20)
            if c.get("volume", 0) < vol_avg * 0.7:
                continue
            if fv["type"] == "bullish" and c["low"] <= fv["ph"] and c["close"] > fv["pl"]:
                if ma50 and c["close"] < ma50 and fv["strength"] < 0.5:
                    continue
                if len(f) > 0 and not is_bullish_candle(f[0]):
                    continue
                r = sim(c["close"], "L", f, a, use_next_open=True)
                trades.append(r)
                fv["traded"] = True
                break
            if fv["type"] == "bearish" and c["high"] >= fv["pl"] and c["close"] < fv["ph"]:
                if ma50 and c["close"] > ma50 and fv["strength"] < 0.5:
                    continue
                if len(f) > 0 and not is_bearish_candle(f[0]):
                    continue
                r = sim(c["close"], "S", f, a, use_next_open=True)
                trades.append(r)
                fv["traded"] = True
                break
    return trades


def bt_swp(candles, hold=30):
    trades = []
    cached_sws = []
    cached_at = -20
    for i in range(45, len(candles) - hold - 1):
        w, c, f = candles[:i + 1], candles[i], candles[i + 1:i + 1 + hold]
        a = calc_atr(w)
        if a <= 0:
            continue
        adx = calc_adx(w)
        if adx < 20:
            continue
        if i - cached_at >= 15:
            sw_result = LiquiditySweepDetector.detect(w)
            cached_sws = sw_result.get("sweeps", [])
            cached_at = i
        if not cached_sws:
            continue
        for sw in cached_sws:
            sw_idx = sw.get("index", 0)
            if sw_idx < i - 1:
                continue
            strength = sw.get("strength", 0)
            rejection_depth = sw.get("rejectionDepth", 0)
            if strength < 0.25:
                continue
            if rejection_depth < 0.5:
                continue
            direction = "L" if sw["type"] == "support" else "S"
            if len(f) > 0:
                if direction == "L" and not is_bullish_candle(f[0]):
                    continue
                if direction == "S" and not is_bearish_candle(f[0]):
                    continue
            r = sim(c["close"], direction, f, a, use_next_open=True)
            trades.append(r)
            break
    return trades


def bt_swing(candles, hold=30):
    trades, zones = [], []
    for i in range(60, len(candles) - hold - 1):
        w, c, f = candles[:i + 1], candles[i], candles[i + 1:i + 1 + hold]
        a = calc_atr(w)
        if a <= 0:
            continue
        adx = calc_adx(w)
        if adx < 20:
            continue
        ma50 = sma(w, 50)
        if i % 20 == 0:
            for lb in [3, 5, 8]:
                res = SwingPointDetector.detect(w, lookback=lb, lookforward=3)
                for z in res.get("zones", []):
                    if z.get("strength", 0) < 0.15:
                        continue
                    zones.append({
                        "price": z["price"],
                        "type": "S" if z["type"] == "support" else "R",
                        "idx": i, "traded": False,
                        "strength": z.get("strength", 0),
                        "retested": z.get("retested", False),
                    })
        zone_pct = max(0.001, a / c["close"] * 1.5) if c["close"] > 0 else 0.002
        for z in zones:
            if z["traded"] or i - z["idx"] > 40:
                continue
            if z.get("retested", False):
                continue
            if z.get("strength", 0) < 0.2:
                continue
            ref = c["low"] if z["type"] == "S" else c["high"]
            if abs(ref - z["price"]) / z["price"] < zone_pct:
                if z["type"] == "S":
                    if ma50 and c["close"] < ma50 * 0.998 and z.get("strength", 0) < 0.4:
                        continue
                    if len(f) > 0 and not is_bullish_candle(f[0]):
                        continue
                    r = sim(c["close"], "L", f, a, use_next_open=True)
                else:
                    if ma50 and c["close"] > ma50 * 1.002 and z.get("strength", 0) < 0.4:
                        continue
                    if len(f) > 0 and not is_bearish_candle(f[0]):
                        continue
                    r = sim(c["close"], "S", f, a, use_next_open=True)
                trades.append(r)
                z["traded"] = True
                break
    return trades


def bt_vp(candles, hold=30):
    trades = []
    for i in range(60, len(candles) - hold - 1):
        if i % 20 != 0:
            continue
        w, c, f = candles[:i + 1], candles[i], candles[i + 1:i + 1 + hold]
        a = calc_atr(w)
        if a <= 0:
            continue
        adx = calc_adx(w)
        if adx < 20:
            continue
        ma50 = sma(w, 50)
        vol_avg = avg_volume(w, 20)
        res = VolumeProfileAnalyzer.calculate(w, num_bins=20)
        for z in [x for x in res.get("zones", []) if x.get("source") == "volume_hvn"]:
            zp = z["price"]
            if c.get("volume", 0) < vol_avg * 0.7:
                continue
            if z["type"] == "support" and c["low"] <= zp * 1.002 and c["close"] > zp * 0.998:
                if ma50 and c["close"] < ma50 * 0.998:
                    continue
                if len(f) > 0 and not is_bullish_candle(f[0]):
                    continue
                r = sim(c["close"], "L", f, a, use_next_open=True)
                trades.append(r)
                break
            if z["type"] == "resistance" and c["high"] >= zp * 0.998 and c["close"] < zp * 1.002:
                if ma50 and c["close"] > ma50 * 1.002:
                    continue
                if len(f) > 0 and not is_bearish_candle(f[0]):
                    continue
                r = sim(c["close"], "S", f, a, use_next_open=True)
                trades.append(r)
                break
    return trades


def bt_cvd(candles, hold=30):
    trades = []
    lti = -10
    cached_cvd_data = []
    cached_per_delta = []
    cached_divs = []
    cached_sw_highs = []
    cached_sw_lows = []
    cached_at = -20
    for i in range(40, len(candles) - hold - 1):
        if i - lti < 8:
            continue
        w, c, f = candles[:i + 1], candles[i], candles[i + 1:i + 1 + hold]
        a = calc_atr(w)
        if a <= 0:
            continue
        adx = calc_adx(w)
        if adx < 20:
            continue
        vol_avg = avg_volume(w, 20)
        # Cache expensive detectors every 15 candles
        if i - cached_at >= 15:
            cvd_result = CVDAnalyzer.calculate(w)
            cached_cvd_data = cvd_result.get("cvd", [])
            cached_per_delta = cvd_result.get("perCandleDelta", [])
            cached_divs = cvd_result.get("divergences", [])
            sw_result = SwingPointDetector.detect(w, lookback=5, lookforward=3)
            cached_sw_highs = sw_result.get("swingHighs", [])
            cached_sw_lows = sw_result.get("swingLows", [])
            cached_at = i
        cvd_data = cached_cvd_data
        per_delta = cached_per_delta
        divs = cached_divs
        if len(cvd_data) < 20 or len(per_delta) < 20:
            continue
        recent_cvd = [d["value"] for d in cvd_data[-10:]]
        cvd_change = recent_cvd[-1] - recent_cvd[0]
        cvd_avg = np.mean([abs(d["delta"]) for d in per_delta[-10:]])
        cvd_momentum = cvd_change / max(cvd_avg * 10, 1)
        body = abs(c["close"] - c["open"])
        rng = c["high"] - c["low"]
        body_ratio = body / max(rng, 0.01)
        vol_ratio = c.get("volume", 0) / max(vol_avg, 0.001)
        latest_delta = per_delta[-1]["delta"] if per_delta else 0
        is_absorption = (vol_ratio >= 1.5 and body_ratio <= 0.4)
        has_div = False
        div_type = None
        if divs:
            d = divs[-1]
            if i - d.get("index", 0) <= 10 and d.get("strength", 0) >= 0.15:
                has_div = True
                div_type = d["type"]
        at_support = any(abs(c["low"] - sl["price"]) / sl["price"] < 0.003 for sl in cached_sw_lows[-5:])
        at_resistance = any(abs(c["high"] - sh["price"]) / sh["price"] < 0.003 for sh in cached_sw_highs[-5:])
        direction = None
        score = 0.0
        if is_absorption and at_support and latest_delta > 0:
            direction = "L"
            score = 0.4 + min(0.3, vol_ratio / 5) + (0.1 if has_div and div_type == "bullish" else 0)
        elif is_absorption and at_resistance and latest_delta < 0:
            direction = "S"
            score = 0.4 + min(0.3, vol_ratio / 5) + (0.1 if has_div and div_type == "bearish" else 0)
        elif has_div and abs(cvd_momentum) > 0.3:
            if div_type == "bullish" and cvd_momentum > 0 and is_bullish_candle(c):
                direction = "L"
                score = 0.3 + min(0.3, abs(cvd_momentum) / 2) + 0.1
            elif div_type == "bearish" and cvd_momentum < 0 and is_bearish_candle(c):
                direction = "S"
                score = 0.3 + min(0.3, abs(cvd_momentum) / 2) + 0.1
        elif abs(cvd_momentum) > 0.5 and (at_support or at_resistance):
            if cvd_momentum > 0 and at_support and is_bullish_candle(c):
                direction = "L"
                score = 0.3 + min(0.2, abs(cvd_momentum) / 3)
            elif cvd_momentum < 0 and at_resistance and is_bearish_candle(c):
                direction = "S"
                score = 0.3 + min(0.2, abs(cvd_momentum) / 3)
        if not direction or score < 0.25:
            continue
        if c.get("volume", 0) < vol_avg * 0.6:
            continue
        if len(f) > 0:
            if direction == "L" and not is_bullish_candle(f[0]):
                continue
            if direction == "S" and not is_bearish_candle(f[0]):
                continue
        r = sim(c["close"], direction, f, a, use_next_open=True)
        trades.append(r)
        lti = i
    return trades


def bt_delta(candles, hold=30):
    trades = []
    lti = -10
    cached_pats = []
    cached_at = -20
    for i in range(40, len(candles) - hold - 1):
        if i - lti < 5:
            continue
        w, c, f = candles[:i + 1], candles[i], candles[i + 1:i + 1 + hold]
        a = calc_atr(w)
        if a <= 0:
            continue
        adx = calc_adx(w)
        if adx < 20:
            continue
        vol_avg = avg_volume(w, 20)
        # Cache expensive detectors every 15 candles
        if i - cached_at >= 15:
            pd = CVDAnalyzer.calculate(w).get("perCandleDelta", [])
            cached_pats = DeltaPatternDetector.detect(w, pd).get("patterns", [])
            cached_at = i
        pats = cached_pats
        if not pats:
            continue
        best = max(pats, key=lambda p: p.get("significance", 0))
        if best.get("significance", 0) < 0.5:
            continue
        if c.get("volume", 0) < vol_avg * 0.8:
            continue
        pname = best.get("name", "")
        if "Hidden Buying" in pname:
            continue
        if pname == "Stop Hunt Reversal" and best.get("direction") in ("long", "bullish"):
            continue
        direction = None
        if best["direction"] in ("long", "bullish"):
            direction = "L"
            if len(f) > 0 and not is_bullish_candle(f[0]):
                continue
        elif best["direction"] in ("short", "bearish"):
            direction = "S"
            if len(f) > 0 and not is_bearish_candle(f[0]):
                continue
        if not direction:
            continue
        r = sim(c["close"], direction, f, a, use_next_open=True)
        trades.append(r)
        lti = i
    return trades


# ═══════════════════════════════════════════════════════════════
# CONFLUENCE BACKTEST — configurable for walk-forward
# ═══════════════════════════════════════════════════════════════

def bt_confluence(candles, hold=30, thresh=0.35, adx_min=20, trend_filter=True,
                  regime_filter=False, min_components=1, exclude_comps=None):
    """
    Optimized Confluence System v3.2 — configurable for walk-forward validation.

    Parameters:
      thresh: minimum weighted score to enter (tunable)
      adx_min: minimum ADX for trend regime filter (tunable)
      trend_filter: if True, only trade with MA50 trend direction
      regime_filter: if True, detect choppy/squeeze markets and skip/reduce
      min_components: minimum distinct component sources required (quality filter)
      exclude_comps: set of component names to exclude (e.g. {'OB','Sweep'})
    """
    if exclude_comps is None:
        exclude_comps = set()
    trades = []
    last_trade_i = -8
    cached_ob, cached_fvg, cached_vp, cached_sw = [], [], [], []
    cached_delta = []
    cached_at = -20
    cached_regime = None
    cached_regime_at = -20
    regime_stats = {"skip": 0, "reduce": 0, "full": 0, "total_checks": 0}

    W = {"OB": 0.20, "FVG": 0.40, "Swing": 0.25,
         "VP": 0.10, "Sweep": 0.10, "Delta": 0.35}

    def _dedup(signals, dedup_pct=0.003):
        if not signals:
            return 0.0
        signals.sort(key=lambda s: s[1])
        kept = [signals[0]]
        for sc, price, name in signals[1:]:
            if abs(price - kept[-1][1]) / max(kept[-1][1], 1) < dedup_pct:
                if sc > kept[-1][0]:
                    kept[-1] = (sc, price, name)
            else:
                kept.append((sc, price, name))
        return sum(s[0] for s in kept)

    for i in range(60, len(candles) - hold - 1):
        if i - last_trade_i < 8:
            continue
        w, c, f = candles[:i + 1], candles[i], candles[i + 1:i + 1 + hold]
        a = calc_atr(w)
        if a <= 0:
            continue

        adx = calc_adx(w)

        # ── Market Regime Filter (cached every 15 candles) ──
        risk_mult = 1.0
        if regime_filter:
            if i - cached_regime_at >= 15 or cached_regime is None:
                cached_regime = detect_market_regime(w)
                cached_regime_at = i
            regime = cached_regime
            regime_stats["total_checks"] += 1
            if regime["regime"] == "squeeze":
                regime_stats["skip"] += 1
                continue  # Skip entirely in squeeze + choppy
            elif regime["regime"] == "choppy":
                regime_stats["reduce"] += 1
                risk_mult = 0.5
            else:
                regime_stats["full"] += 1
                risk_mult = 1.0
        else:
            if adx < adx_min:
                continue

        vol_avg = avg_volume(w, 20)
        ma50 = sma(w, 50)
        if c.get("volume", 0) < vol_avg * 0.6:
            continue

        if i - cached_at >= 15:
            cached_ob = OrderBlockDetector.detect(w, min_impulse_pct=0.15).get("orderBlocks", [])
            cached_fvg = FVGBalancer.detect(w, min_gap_pct=0.02).get("fvgs", [])
            vpd = VolumeProfileAnalyzer.calculate(w, num_bins=20)
            cached_vp = [x for x in vpd.get("zones", []) if x.get("source") == "volume_hvn"]
            cached_sw = SwingPointDetector.detect(w, lookback=5, lookforward=3)
            pdelta = CVDAnalyzer.calculate(w).get("perCandleDelta", [])
            cached_delta = DeltaPatternDetector.detect(w, pdelta).get("patterns", [])
            cached_at = i

        bull_signals = []
        bear_signals = []

        if "OB" not in exclude_comps:
            for ob in cached_ob:
                if ob.get("mitigated", False) or ob.get("strength", 0) < 0.15:
                    continue
                pl, ph = ob.get("priceLow", ob["price"]), ob.get("priceHigh", ob["price"])
                ob_mid = (pl + ph) / 2
                sc = W["OB"] * min(1.0, ob.get("strength", 0.3) * 2)
                if ob["type"] == "bullish" and c["low"] <= ph and c["close"] > pl:
                    bull_signals.append((sc, ob_mid, "OB"))
                elif ob["type"] == "bearish" and c["high"] >= pl and c["close"] < ph:
                    bear_signals.append((sc, ob_mid, "OB"))

        if "FVG" not in exclude_comps:
            for fv in cached_fvg:
                if fv.get("strength", 0) < 0.2:
                    continue
                fv_mid = (fv.get("priceLow", 0) + fv.get("priceHigh", 0)) / 2
                sc = W["FVG"] * min(1.0, fv.get("strength", 0.3) * 2)
                if fv["type"] == "bullish" and c["low"] <= fv["priceHigh"] and c["close"] > fv["priceLow"]:
                    bull_signals.append((sc, fv_mid, "FVG"))
                elif fv["type"] == "bearish" and c["high"] >= fv["priceLow"] and c["close"] < fv["priceHigh"]:
                    bear_signals.append((sc, fv_mid, "FVG"))

        if "Swing" not in exclude_comps:
            zp = max(0.001, a / c["close"] * 1.5) if c["close"] > 0 else 0.002
            for sl in cached_sw.get("swingLows", [])[-5:]:
                if abs(c["low"] - sl["price"]) / sl["price"] < zp:
                    bull_signals.append((W["Swing"], sl["price"], "Swing"))
            for sh in cached_sw.get("swingHighs", [])[-5:]:
                if abs(c["high"] - sh["price"]) / sh["price"] < zp:
                    bear_signals.append((W["Swing"], sh["price"], "Swing"))

        if "VP" not in exclude_comps:
            for z in cached_vp:
                zpp = z["price"]
                if z["type"] == "support" and c["low"] <= zpp * 1.002 and c["close"] > zpp * 0.998:
                    bull_signals.append((W["VP"], zpp, "VP"))
                elif z["type"] == "resistance" and c["high"] >= zpp * 0.998 and c["close"] < zpp * 1.002:
                    bear_signals.append((W["VP"], zpp, "VP"))

        if "Sweep" not in exclude_comps:
            win = candles[max(0, i - 30):i]
            if len(win) >= 10:
                wl = min(x["low"] for x in win)
                wh = max(x["high"] for x in win)
                rng = c["high"] - c["low"]
                if c["low"] < wl and c["close"] > wl:
                    sp = (wl - c["low"]) / wl * 100
                    if 0.04 <= sp <= 0.7 and rng > 0 and (c["close"] - c["low"]) / rng > 0.5:
                        bull_signals.append((W["Sweep"], wl, "Sweep"))
                if c["high"] > wh and c["close"] < wh:
                    sp = (c["high"] - wh) / wh * 100
                    if 0.04 <= sp <= 0.7 and rng > 0 and (c["high"] - c["close"]) / rng > 0.5:
                        bear_signals.append((W["Sweep"], wh, "Sweep"))

        if "Delta" not in exclude_comps:
            for p in cached_delta:
                if p.get("significance", 0) < 0.3 or "Hidden Buying" in p.get("name", ""):
                    continue
                sc = W["Delta"] * min(1.0, p.get("significance", 0.3) * 2)
                if p["direction"] in ("long", "bullish"):
                    bull_signals.append((sc, c["close"], "Delta"))
                elif p["direction"] in ("short", "bearish"):
                    bear_signals.append((sc, c["close"], "Delta"))

        bull_s = _dedup(bull_signals)
        bear_s = _dedup(bear_signals)

        # Count distinct component sources for each direction
        bull_comps = len(set(name for _, _, name in bull_signals))
        bear_comps = len(set(name for _, _, name in bear_signals))

        direction = None
        if bull_s >= thresh and bull_s > bear_s and bull_comps >= min_components:
            direction = "L"
        elif bear_s >= thresh and bear_s > bull_s and bear_comps >= min_components:
            direction = "S"
        if not direction:
            continue

        if trend_filter and ma50:
            if direction == "L" and c["close"] < ma50 * 0.998:
                continue
            if direction == "S" and c["close"] > ma50 * 1.002:
                continue

        if len(f) > 0:
            if direction == "L" and not is_bullish_candle(f[0]):
                continue
            if direction == "S" and not is_bearish_candle(f[0]):
                continue

        r = sim(c["close"], direction, f, a, use_next_open=True,
                risk_pct=RISK_PER_TRADE * risk_mult)
        trades.append(r)
        last_trade_i = i
    return trades, regime_stats


# ═══════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════

def met(trades, name):
    if not trades:
        return {"name": name, "n": 0, "w": 0, "l": 0, "wr": 0, "pnl": 0, "pf": 0, "mdd": 0, "sh": 0, "expect": 0}
    wins = [t for t in trades if t["r"] == "W"]
    losses = [t for t in trades if t["r"] == "L"]
    n_w, n_l = len(wins), len(losses)
    wr = n_w / len(trades) * 100
    tp = sum(t["p"] for t in trades)
    gp = sum(t["p"] for t in wins) if wins else 0
    gl = abs(sum(t["p"] for t in losses)) if losses else 0.0001
    pf = gp / gl
    expect = tp / len(trades)
    eq = [100.0]
    for t in trades:
        eq.append(eq[-1] * (1 + t["p"] / 100))
    pk = eq[0]
    mdd = 0
    for e in eq:
        if e > pk:
            pk = e
        dd = (pk - e) / pk * 100
        if dd > mdd:
            mdd = dd
    rets = [t["p"] for t in trades]
    if len(rets) > 1 and np.std(rets) > 0:
        sh = float(np.mean(rets) / np.std(rets) * np.sqrt(len(rets)))
    else:
        sh = 0
    return {"name": name, "n": len(trades), "w": n_w, "l": n_l,
            "wr": round(wr, 1), "pnl": round(tp, 2), "pf": round(pf, 2),
            "mdd": round(mdd, 1), "sh": round(sh, 2), "expect": round(expect, 4)}


def agg_met(all_syms, name):
    if not all_syms:
        return None
    all_trades = []
    for rs in all_syms:
        all_trades.extend(rs)
    return met(all_trades, name)


# ═══════════════════════════════════════════════════════════════
# WALK-FORWARD VALIDATION
# ═══════════════════════════════════════════════════════════════

def walk_forward_validate(candles, symbol, hold=30):
    """
    Walk-forward validation: train on first 70%, test on last 30%.
    Parameters are tuned on train ONLY, then applied to unseen test data.
    """
    n = len(candles)
    split = int(n * 0.7)
    train = candles[:split]
    test = candles[split:]

    print("\n  === WALK-FORWARD: %s ===" % symbol)
    print("  Total: %d candles | Train: %d (70%%) | Test: %d (30%%)" % (n, len(train), len(test)))

    # Grid search: find best THRESH on training data, caching best result
    best_thresh = 0.35
    best_pf = 0
    best_train_trades = []
    best_train_regime = {}
    grid_results = []
    grid_cache = {}  # thresh -> trades

    for thresh in [0.20, 0.25, 0.30, 0.35]:
        tr, rs = bt_confluence(train, hold, thresh=thresh, adx_min=20, trend_filter=True)
        grid_cache[thresh] = tr
        m = met(tr, "train")
        grid_results.append((thresh, m["n"], m["wr"], m["pf"], m["pnl"]))
        if m["n"] >= 15 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_thresh = thresh
            best_train_trades = tr
            best_train_regime = rs

    print("\n  Grid Search (Training Data):")
    print("  %-8s %6s %7s %6s %8s" % ("Thresh", "Trades", "WR%", "PF", "PnL%"))
    print("  " + "-" * 42)
    for th, tn, twr, tpf, tpnl in grid_results:
        marker = " <-- BEST" if th == best_thresh else ""
        print("  %-8.2f %6d %6.1f%% %6.2f %+7.2f%%%s" % (th, tn, twr, tpf, tpnl, marker))

    print("\n  Selected: THRESH=%.2f (train PF=%.2f)" % (best_thresh, best_pf))
    if best_train_regime:
        tc = best_train_regime.get("total_checks", 0)
        if tc > 0:
            print("  Regime Filter (train): SKIP=%d | REDUCE=%d | FULL=%d (of %d checks)" %
                  (best_train_regime.get("skip", 0), best_train_regime.get("reduce", 0),
                   best_train_regime.get("full", 0), tc))

    # Apply to UNSEEN test data (no grid search, just one run)
    test_trades, test_regime = bt_confluence(test, hold, thresh=best_thresh, adx_min=20, trend_filter=True)
    test_m = met(test_trades, "%s-TEST" % symbol)
    if test_regime:
        tc = test_regime.get("total_checks", 0)
        if tc > 0:
            print("  Regime Filter (test):  SKIP=%d | REDUCE=%d | FULL=%d (of %d checks)" %
                  (test_regime.get("skip", 0), test_regime.get("reduce", 0),
                   test_regime.get("full", 0), tc))

    # Reuse cached best train result (no redundant re-run)
    train_trades = best_train_trades
    train_m = met(train_trades, "%s-TRAIN" % symbol)

    return train_m, test_m, best_thresh, train_trades, test_trades


# ═══════════════════════════════════════════════════════════════
# MAIN — Walk-Forward Validation
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 90)
    print("  LIQUIDITY IDENTIFIER — WALK-FORWARD VALIDATION v3")
    print("  Anti-overfitting: 70/30 train/test | Quality > Quantity")
    print("=" * 90)
    print("")
    print("  Config: Risk=%.1f%% | SL=%.1f ATR | TP=%.1f ATR | R:R=%.1f:1 | Fees=%.2f%% | Slippage=%.2f%%" %
          (RISK_PER_TRADE, SL_ATR_MULT, TP_ATR_MULT, TP_ATR_MULT / SL_ATR_MULT, TX_TOTAL, SLIPPAGE))
    print("")

    si = [("BTCUSDT", "15m", 2500), ("ETHUSDT", "15m", 2500),
          ("SOLUSDT", "15m", 2500), ("BNBUSDT", "15m", 2500)]

    # ═══ PART 1: Fetch Data ═══
    all_candles = {}
    for sym, iv, lm in si:
        print("  Fetching %s %s (%d candles)..." % (sym, iv, lm), flush=True)
        try:
            candles = fetch_klines(sym, iv, lm)
        except Exception as e:
            print("  ERROR: %s" % e)
            continue
        print("  Got %d candles" % len(candles), flush=True)
        all_candles[sym] = candles
    print(flush=True)

    # ═══ PART 2: Walk-Forward Validation (Confluence) ═══
    print("")
    print("=" * 90)
    print("  WALK-FORWARD VALIDATION — CONFLUENCE SYSTEM")
    print("  Parameters tuned on 70%% train, tested on UNSEEN 30%% test data")
    print("=" * 90)

    all_train_trades = []
    all_test_trades = []

    for sym, iv, lm in si:
        if sym not in all_candles:
            continue
        candles = all_candles[sym]
        train_m, test_m, best_thresh, train_trades, test_trades = walk_forward_validate(candles, sym)

        print("\n  RESULTS — %s:" % sym)
        print("  %-12s %6s %7s %6s %8s %8s %6s" % ("Period", "Trades", "WR%", "PF", "PnL%", "MaxDD%", "Expect"))
        print("  " + "-" * 56)
        print("  %-12s %6d %6.1f%% %6.2f %+7.2f%% %6.1f%% %+.3f%%" %
              ("TRAIN", train_m["n"], train_m["wr"], train_m["pf"], train_m["pnl"], train_m["mdd"], train_m["expect"]))
        print("  %-12s %6d %6.1f%% %6.2f %+7.2f%% %6.1f%% %+.3f%%" %
              ("TEST (unseen)", test_m["n"], test_m["wr"], test_m["pf"], test_m["pnl"], test_m["mdd"], test_m["expect"]))
        print("  Best threshold: %.2f" % best_thresh)

        # Track degradation
        if train_m["n"] > 0 and test_m["n"] > 0:
            wr_degradation = test_m["wr"] - train_m["wr"]
            pf_degradation = test_m["pf"] - train_m["pf"]
            print("  Degradation: WR %+.1f%% | PF %+.2f" % (wr_degradation, pf_degradation))
            if wr_degradation > -10 and pf_degradation > -0.5:
                print("  Status: PASS (stable out-of-sample)")
            elif wr_degradation > -20:
                print("  Status: CAUTION (moderate degradation)")
            else:
                print("  Status: WARNING (significant overfitting detected)")

        all_train_trades.extend(train_trades)
        all_test_trades.extend(test_trades)

    # ═══ PART 2.5: Quality Mode Comparison — Standard vs Quality-Only ═══
    print("")
    print("=" * 90)
    print("  QUALITY MODE COMPARISON — STANDARD vs QUALITY-ONLY")
    print("  Standard: thresh=0.35, any components | Quality: thresh=0.50, 3+ components")
    print("=" * 90)
    print("")

    q_std_trades = []
    q_qual_trades = []
    for sym, iv, lm in si:
        if sym not in all_candles:
            continue
        tc = all_candles[sym]
        split = int(len(tc) * 0.7)
        test = tc[split:]
        # Standard mode: thresh=0.35, min_components=1
        std_tr, _ = bt_confluence(test, hold=30, thresh=0.35, adx_min=20,
                                  trend_filter=True, min_components=1)
        # Quality-only mode: thresh=0.50, min_components=3
        qual_tr, _ = bt_confluence(test, hold=30, thresh=0.50, adx_min=20,
                                   trend_filter=True, min_components=3)
        q_std_trades.extend(std_tr)
        q_qual_trades.extend(qual_tr)

    q_std_m = met(q_std_trades, "Standard")
    q_qual_m = met(q_qual_trades, "Quality-Only")

    print("  %-20s %6s %7s %6s %8s %8s %8s" % ("Mode", "Trades", "WR%", "PF", "PnL%", "MaxDD%", "Expect"))
    print("  " + "-" * 64)
    print("  %-20s %6d %6.1f%% %6.2f %+7.2f%% %6.1f%% %+.4f%%" %
          ("Standard (v3)", q_std_m["n"], q_std_m["wr"], q_std_m["pf"],
           q_std_m["pnl"], q_std_m["mdd"], q_std_m["expect"]))
    print("  %-20s %6d %6.1f%% %6.2f %+7.2f%% %6.1f%% %+.4f%%" %
          ("Quality-Only (3+)", q_qual_m["n"], q_qual_m["wr"], q_qual_m["pf"],
           q_qual_m["pnl"], q_qual_m["mdd"], q_qual_m["expect"]))
    print()

    if q_qual_m["n"] > 0 and q_std_m["n"] > 0:
        wr_delta = q_qual_m["wr"] - q_std_m["wr"]
        pf_delta = q_qual_m["pf"] - q_std_m["pf"]
        exp_delta = q_qual_m["expect"] - q_std_m["expect"]
        print("  Quality filter impact:")
        print("    WR:  %+.1f%% | PF: %+.2f | Expect: %+.4f%%" % (wr_delta, pf_delta, exp_delta))
        print("    Trades removed: %d (%.0f%% fewer)" % (q_std_m["n"] - q_qual_m["n"],
              (1 - q_qual_m["n"] / max(q_std_m["n"], 1)) * 100))
        if wr_delta > 0 and pf_delta > 0:
            print("    Verdict: QUALITY FILTER IMPROVES both WR and PF")
        elif wr_delta > 0:
            print("    Verdict: QUALITY FILTER improves WR but reduces trade count")
        else:
            print("    Verdict: QUALITY FILTER does not improve performance")
    print("")

    # ═══ PART 2.6: Individual Component Analysis on UNSEEN data ═══
    print("")
    print("=" * 90)
    print("  INDIVIDUAL COMPONENT WIN RATES — UNSEEN DATA (test split)")
    print("  Each component tested independently with same filters (ADX>20, volume, trend)")
    print("=" * 90)
    print("")

    comp_fns = {
        "OB (Order Blocks)": bt_ob, "FVG (Fair Value Gaps)": bt_fvg,
        "Sweep (Liquidity Sweeps)": bt_swp, "Swing (Swing Points)": bt_swing,
        "VP (Volume Profile)": bt_vp, "Delta (Delta Patterns)": bt_delta,
    }
    comp_all_trades = {}
    print("  %-30s %6s %7s %7s %8s %8s %8s" % ("Component", "Trades", "WR%", "PF", "PnL%", "MaxDD%", "Sharpe"))
    print("  " + "-" * 82)
    for cn, cf in comp_fns.items():
        sym_trades = []
        for sym, tc in all_candles.items():
            split = int(len(tc) * 0.7)
            test = tc[split:]
            trades = cf(test)
            sym_trades.extend(trades)
        comp_all_trades[cn] = sym_trades
        m = met(sym_trades, cn)
        print("  %-30s %6d %6.1f%% %7.2f %+7.2f%% %7.1f%% %7.2f" % (
            cn, m["n"], m["wr"], m["pf"], m["pnl"], m["mdd"], m["sh"]))
    print()
    print("  Component descriptions:")
    print("    OB:  Last opposing candle before impulse — institutional unfilled orders")
    print("    FVG: Price imbalance gaps — market inefficiency rebalancing zones")
    print("    Sweep: Stop hunt + reversal — liquidity grab at key levels")
    print("    Swing: Fractal support/resistance — market structure pivots")
    print("    VP:  Volume-at-price HVN zones — institutional value areas")
    print("    Delta: CVD divergence/absorption — order flow imbalance signals")
    print()

    # ═══ PART 3: Aggregate Summary ═══
    print("")
    print("=" * 90)
    print("  AGGREGATE WALK-FORWARD RESULTS (all symbols combined)")
    print("=" * 90)
    print("")

    train_agg = met(all_train_trades, "ALL TRAIN")
    test_agg = met(all_test_trades, "ALL TEST")

    print("  %-20s %6s %7s %6s %8s %8s %6s" % ("Period", "Trades", "WR%", "PF", "PnL%", "MaxDD%", "Expect"))
    print("  " + "-" * 62)
    print("  %-20s %6d %6.1f%% %6.2f %+7.2f%% %6.1f%% %+.3f%%" %
          ("IN-SAMPLE (train)", train_agg["n"], train_agg["wr"], train_agg["pf"],
           train_agg["pnl"], train_agg["mdd"], train_agg["expect"]))
    print("  %-20s %6d %6.1f%% %6.2f %+7.2f%% %6.1f%% %+.3f%%" %
          ("OUT-OF-SAMPLE (test)", test_agg["n"], test_agg["wr"], test_agg["pf"],
           test_agg["pnl"], test_agg["mdd"], test_agg["expect"]))
    print("  " + "-" * 62)

    if test_agg["n"] > 0:
        print("")
        print("  VERDICT:")
        print("  Trade count: %d (target: 100+)" % test_agg["n"])
        if test_agg["pf"] >= 1.0:
            print("  Profit Factor: %.2f (profitable out-of-sample)" % test_agg["pf"])
        else:
            print("  Profit Factor: %.2f (NOT profitable out-of-sample)" % test_agg["pf"])
        if test_agg["wr"] >= 45:
            print("  Win Rate: %.1f%% (realistic edge confirmed)" % test_agg["wr"])
        elif test_agg["wr"] >= 40:
            print("  Win Rate: %.1f%% (marginal edge)" % test_agg["wr"])
        else:
            print("  Win Rate: %.1f%% (edge may be overfitted)" % test_agg["wr"])

        wr_deg = test_agg["wr"] - train_agg["wr"]
        pf_deg = test_agg["pf"] - train_agg["pf"]
        print("  Train->Test degradation: WR %+.1f%% | PF %+.2f" % (wr_deg, pf_deg))
        if wr_deg > -10 and pf_deg > -0.3:
            print("  Anti-overfitting: PASS")
        elif wr_deg > -20:
            print("  Anti-overfitting: CAUTION")
        else:
            print("  Anti-overfitting: FAIL (overfitting detected)")

    print("")
    print("  Results saved to liq_component_backtest_results.json")

    # Save
    save_data = {
        "timestamp": datetime.now().isoformat(),
        "config": {"risk": RISK_PER_TRADE, "sl": SL_ATR_MULT, "tp": TP_ATR_MULT,
                    "tx": TX_TOTAL, "slippage": SLIPPAGE},
        "in_sample": {"trades": train_agg["n"], "wr": train_agg["wr"], "pf": train_agg["pf"],
                      "pnl": train_agg["pnl"], "mdd": train_agg["mdd"]},
        "out_of_sample": {"trades": test_agg["n"], "wr": test_agg["wr"], "pf": test_agg["pf"],
                          "pnl": test_agg["pnl"], "mdd": test_agg["mdd"]},
    }
    with open("liq_component_backtest_results.json", "w") as f:
        json.dump(save_data, f, indent=2, default=str)
    print("")


if __name__ == "__main__":
    main()
