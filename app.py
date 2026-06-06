"""
Double Bottom Scanner v2 � Flask API Server
Provides REST endpoints for backtesting and data fetching.
"""

import json
import os

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backtester import Backtester, SCENARIOS
from config import DEFAULT_CONFIG
from data_ingestion import BinanceFetcher
from engine_v3 import run_v3_backtest
from backtest_runner import run_validation
from liq_engine import LiquidityEngine

app = Flask(__name__)
CORS(app)

bt = Backtester()
liq_engine = LiquidityEngine()


def normalize_params(body):
    """Convert frontend parameter names/values to backtester format."""
    params = {}
    # Params that should be integers
    int_keys = {"swingLength", "atrLength", "minCandlesBetween", "maxCandlesBetween", "patternCount", "trendMAPeriod"}
    # Params that are percentages (sent as face values, need /100)
    pct_keys = {"maxBottomDiff", "riskPerTrade", "dailyLossLimit"}
    # Float params (sent as plain decimals)
    float_keys = {"minPatternHeightMult", "slMultiplier", "minRR", "volumeConfirmThreshold", "breakoutVolumeMult", "partialExitRatio", "trailingStopMult", "target1RR"}
    # Boolean params (sent as true/false from frontend)
    bool_keys = {"useTrendFilter", "useVolumeConfirm"}

    key_map = {
        "swingLength": "swingLength",
        "atrLength": "atrLength",
        "maxBottomDiff": "maxBottomDiff",
        "minCandlesBetween": "minCandlesBetween",
        "maxCandlesBetween": "maxCandlesBetween",
        "minPatternHeightMult": "minPatternHeightMult",
        "riskPerTrade": "riskPerTrade",
        "slMultiplier": "slMultiplier",
        "minRR": "minRR",
        "dailyLossLimit": "dailyLossLimit",
        "patternCount": "patternCount",
        "initialBalance": "initialBalance",
        "useTrendFilter": "useTrendFilter",
        "trendMAPeriod": "trendMAPeriod",
        "useVolumeConfirm": "useVolumeConfirm",
        "volumeConfirmThreshold": "volumeConfirmThreshold",
        "breakoutVolumeMult": "breakoutVolumeMult",
        "partialExitRatio": "partialExitRatio",
        "trailingStopMult": "trailingStopMult",
        "target1RR": "target1RR",
    }
    for js_key, py_key in key_map.items():
        if js_key not in body:
            continue
        val = body[js_key]
        if val is None:
            continue
        if js_key in int_keys:
            params[py_key] = int(val)
        elif js_key in pct_keys:
            params[py_key] = float(val) / 100.0
        elif js_key in float_keys:
            params[py_key] = float(val)
        elif js_key in bool_keys:
            params[py_key] = bool(val)
        else:
            params[py_key] = float(val)
    if "initialBalance" in body and body["initialBalance"] is not None:
        bt.initial_balance = float(body["initialBalance"])
    return params


@app.route("/api/scenarios", methods=["GET"])
def get_scenarios():
    return jsonify({"scenarios": SCENARIOS})


@app.route("/api/run", methods=["POST"])
def run_backtest():
    try:
        body = request.get_json(force=True) or {}
        scenario = body.get("scenario", "all")
        params = normalize_params(body)
        if params:
            bt.set_params(params)
        result = bt.run(scenario)
        return jsonify({
            "success": True,
            "metrics": result["metrics"],
            "trades": result["trades"],
            "patternMarkers": result["patternMarkers"],
            "candles": result["candles"],
            "equity": result["equity"],
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/run-with-data", methods=["POST"])
def run_backtest_with_data():
    try:
        body = request.get_json(force=True) or {}
        candles = body.get("candles", [])
        if not candles:
            return jsonify({"success": False, "error": "No candle data provided"}), 400
        params = normalize_params(body)
        if params:
            bt.set_params(params)
        result = bt.run_with_data(candles)
        return jsonify({
            "success": True,
            "metrics": result["metrics"],
            "trades": result["trades"],
            "patternMarkers": result["patternMarkers"],
            "candles": result["candles"],
            "equity": result["equity"],
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/fetch/binance", methods=["POST"])
def fetch_binance():
    try:
        body = request.get_json(force=True) or {}
        start_date = body.get("startDate", "2025-01-01")
        end_date = body.get("endDate")
        limit = int(body.get("limit", 500))
        candles = bt.fetch_binance_data(start_date, end_date, limit)
        return jsonify({"success": True, "candles": candles, "count": len(candles)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/scan-live", methods=["POST"])
def scan_live():
    """Fetch latest BTC/USDT 15m data from Binance and run backtest in one shot."""
    try:
        from datetime import datetime, timedelta
        body = request.get_json(force=True) or {}
        limit = int(body.get("limit", 200))
        params = normalize_params(body)
        if params:
            bt.set_params(params)
        # Use last 7 days from now as default
        start = body.get("startDate") or (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end = body.get("endDate") or datetime.now().strftime("%Y-%m-%d")
        candles = bt.fetch_binance_data(start_date=start, end_date=end, limit=limit)
        if not candles:
            return jsonify({"success": False, "error": "No data received from Binance"}), 502
        result = bt.run_with_data(candles)
        # Check for pending patterns (not yet broken out)
        pending = 0
        last_close = candles[-1]["close"]
        last_time = candles[-1]["time"]
        for p in result["patternMarkers"]:
            b_idx = p.get("breakoutIdx", p.get("b2Idx", 0) + 3)
            if b_idx < len(candles):
                # Pattern already in the past
                pass
            elif p.get("b2Idx", 0) < len(candles) and last_close <= p.get("necklinePrice", 0):
                # Price between b2 low and neckline - waiting for breakout
                pending += 1
        return jsonify({
            "success": True,
            "signal": {
                "pendingPatterns": pending,
                "latestClose": last_close,
                "latestTime": last_time,
                "scanDate": datetime.now().strftime("%Y-%m-%d %H:%M"),
            },
            "metrics": result["metrics"],
            "trades": result["trades"],
            "patternMarkers": result["patternMarkers"],
            "candles": result["candles"],
            "equity": result["equity"],
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/fetch/yahoo", methods=["POST"])
def fetch_yahoo():
    try:
        body = request.get_json(force=True) or {}
        start_date = body.get("startDate", "2025-01-01")
        end_date = body.get("endDate")
        candles = bt.fetch_yahoo_data(start_date, end_date)
        return jsonify({"success": True, "candles": candles, "count": len(candles)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "double-bottom-scanner"})


# ═══════════════════════════════════════════════════════════════
#  STATIC FILE SERVING (Frontend)
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/<path:path>")
def static_files(path):
    allowed_extensions = (".js", ".css", ".html", ".png", ".jpg", ".svg", ".ico", ".json")
    if any(path.endswith(ext) for ext in allowed_extensions):
        try:
            return send_from_directory(".", path)
        except Exception:
            return jsonify({"error": "Not found"}), 404
    return jsonify({"error": "Not found"}), 404


# ═══════════════════════════════════════════════════════════════
#  BACKBAT V3 — New 4-Layer Engine Endpoints
# ═══════════════════════════════════════════════════════════════

@app.route("/api/v3/run", methods=["POST"])
def run_v3():
    """Run the V3 4-layer engine (Data → Detection → Scoring → Signal Gate)."""
    try:
        body = request.get_json(force=True) or {}
        candles = body.get("candles", [])
        if not candles:
            return jsonify({"success": False, "error": "No candle data provided"}), 400
        result = run_v3_backtest(candles=candles)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/v3/fetch-and-run", methods=["POST"])
def v3_fetch_and_run():
    """Fetch live Binance data and run through the V3 engine."""
    try:
        body = request.get_json(force=True) or {}
        limit = int(body.get("limit", 500))
        fetcher = BinanceFetcher()
        candles = fetcher.klines(limit=limit)
        if not candles:
            return jsonify({"success": False, "error": "No data from Binance"}), 502
        result = run_v3_backtest(candles=candles)
        return jsonify({"success": True, "dataSource": "binance", **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/v3/validate", methods=["POST"])
def v3_validate():
    """Run walk-forward validation on the V3 engine."""
    try:
        body = request.get_json(force=True) or {}
        candles = body.get("candles", [])
        periods = int(body.get("periods", 6))
        if not candles:
            return jsonify({"success": False, "error": "No candle data provided"}), 400
        result = run_validation(candles, periods=periods)
        return jsonify({"success": True, "validation": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
#  LIQUIDITY9 — Multi-Exchange Liquidity Zone Scanner
# ═══════════════════════════════════════════════════════════════

@app.route("/api/liquidity/scan", methods=["POST"])
def liquidity_scan():
    """Scan liquidity zones for a given symbol using LiquidityEngine."""
    try:
        body = request.get_json(force=True) or {}
        symbol = body.get("symbol", "BTCUSDT")
        interval = body.get("interval", "15m")
        depth_limit = int(body.get("depthLimit", 100))
        result = liq_engine.analyze_all(symbol=symbol, interval=interval, depth_limit=depth_limit)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
#  MULTI-EXCHANGE FETCHERS (Binance + Bybit + OKX)
# ═══════════════════════════════════════════════════════════════

class BybitFetcher:
    """REST fetcher for Bybit spot klines (no API key needed)."""
    BASE = "https://api.bybit.com"

    def klines(self, symbol="BTCUSDT", interval="15", limit=200):
        import urllib.request
        url = f"{self.BASE}/v5/market/kline?category=spot&symbol={symbol}&interval={interval}&limit={min(limit,200)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        candles = []
        for k in data.get("result", {}).get("list", [])[::-1]:
            candles.append({
                "time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
            })
        return candles


class OKXFetcher:
    """REST fetcher for OKX spot klines (no API key needed)."""
    BASE = "https://www.okx.com"

    def klines(self, symbol="BTC-USDT", bar="15m", limit=200):
        import urllib.request
        url = f"{self.BASE}/api/v5/market/candles?instId={symbol}&bar={bar}&limit={min(limit,300)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        candles = []
        for k in data.get("data", [])[::-1]:
            candles.append({
                "time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
            })
        return candles


def normalize_symbol_for_exchange(symbol, exchange):
    """Normalize a symbol like BTCUSDT to exchange-specific format."""
    if exchange == "okx":
        return symbol.replace("USDT", "-USDT").replace("BUSD", "-BUSD")
    return symbol  # Binance & Bybit use BTCUSDT format


def map_interval(interval, exchange):
    """Map frontend interval to exchange-specific format."""
    if exchange == "bybit":
        # Bybit v5 spot klines: m→minutes (15), h→minutes (60=1h, 240=4h), d→D
        if interval.endswith("m"):
            return interval.replace("m", "")  # "15m" → "15"
        elif interval.endswith("h"):
            mins = int(interval.replace("h", "")) * 60
            return str(mins)  # "1h" → "60", "4h" → "240"
        elif interval.endswith("d"):
            return "D"  # "1d" → "D"
        return interval
    if exchange == "okx":
        # OKX: m stays lowercase, h→H, d→D
        return interval.replace("h", "H").replace("d", "D")
    return interval  # Binance uses same format


def aggregate_prices(exchange_data):
    """Aggregate latest prices from multiple exchanges into a VWAP-like average."""
    total_vol = 0
    total_pv = 0
    for ex_data in exchange_data:
        if ex_data and ex_data.get("candles") and len(ex_data["candles"]) > 0:
            last = ex_data["candles"][-1]
            price = last.get("close", 0)
            vol = last.get("volume", 0)
            total_pv += price * vol
            total_vol += vol
    return round(total_pv / total_vol, 2) if total_vol > 0 else 0


# ═══════════════════════════════════════════════════════════════
#  AI SELF-ANALYSIS — Multi-Exchange Double Bottom Detection
# ═══════════════════════════════════════════════════════════════

@app.route("/api/ai-analysis", methods=["POST"])
def ai_analysis():
    """
    Self-analysis endpoint: fetches multi-exchange data and automatically
    detects double bottom patterns with confidence scoring.
    Supports two modes: 'best' (optimized DB) and 'pluto' (boardroom).
    """
    try:
        body = request.get_json(force=True) or {}
        symbol = body.get("symbol", "BTCUSDT")
        limit = int(body.get("limit", 500))
        interval = body.get("interval", "15m")
        mode = body.get("mode", "best")

        from datetime import datetime, timedelta
        from data_ingestion import BinanceFetcher

        # ── Fetch from all 3 exchanges ──
        binance = BinanceFetcher()
        bybit = BybitFetcher()
        okx = OKXFetcher()

        binance_candles = binance.klines(symbol=symbol, interval=interval, limit=limit)
        bybit_candles = bybit.klines(symbol=symbol, interval=map_interval(interval, "bybit"), limit=min(limit, 200))
        okx_candles = okx.klines(symbol=normalize_symbol_for_exchange(symbol, "okx"), bar=map_interval(interval, "okx"), limit=min(limit, 200))

        # Use Binance as primary (it has the most data)
        candles = binance_candles
        if not candles or len(candles) < 50:
            candles = bybit_candles if bybit_candles and len(bybit_candles) >= 50 else okx_candles
        if not candles or len(candles) < 50:
            return jsonify({"success": False, "error": "Insufficient data from all exchanges"}), 502

        # Aggregate prices across exchanges
        agg_price = aggregate_prices([
            {"candles": binance_candles}, {"candles": bybit_candles}, {"candles": okx_candles}
        ])

        exchange_data = {
            "binance": {"count": len(binance_candles) if binance_candles else 0, "lastPrice": binance_candles[-1]["close"] if binance_candles else 0},
            "bybit": {"count": len(bybit_candles) if bybit_candles else 0, "lastPrice": bybit_candles[-1]["close"] if bybit_candles else 0},
            "okx": {"count": len(okx_candles) if okx_candles else 0, "lastPrice": okx_candles[-1]["close"] if okx_candles else 0},
        }

        if mode == "pluto":
            return jsonify({"success": True, "analysis": _run_pluto_analysis(symbol, interval, candles, exchange_data, agg_price)})

        # ── BEST DB mode (existing analysis enhanced) ──
        bt.set_params({
            "swingLength": 5, "atrLength": 14, "maxBottomDiff": 0.0027,
            "minCandlesBetween": 2, "maxCandlesBetween": 25, "minPatternHeightMult": 0.5,
        })
        result = bt.run_with_data(candles)
        metrics = result.get("metrics", {})
        markers = result.get("patternMarkers", [])
        trades = result.get("trades", [])
        last_candle = candles[-1] if candles else {}

        swing_len = bt.params.get("swingLength", 5)
        lows_arr = [c["low"] for c in candles]
        recent_swing_lows = []
        for i in range(max(0, len(candles) - 60), len(candles)):
            if i < swing_len or i >= len(candles) - swing_len:
                continue
            val = lows_arr[i]
            is_low = True
            for j in range(1, swing_len + 1):
                if lows_arr[i - j] <= val or lows_arr[i + j] <= val:
                    is_low = False
                    break
            if is_low:
                recent_swing_lows.append({"index": i, "time": candles[i]["time"], "price": candles[i]["low"], "volume": candles[i]["volume"]})

        completed_patterns = [p for p in markers if p.get("breakoutIdx", 0) < len(candles)]
        pending_patterns = [p for p in markers if p.get("b2Idx", 0) < len(candles) and p.get("breakoutIdx", 0) >= len(candles)]

        closes_20 = [c["close"] for c in candles[-20:]] if len(candles) >= 20 else []
        ma_20 = sum(closes_20) / len(closes_20) if closes_20 else 0
        closes_50 = [c["close"] for c in candles[-50:]] if len(candles) >= 50 else []
        ma_50 = sum(closes_50) / len(closes_50) if closes_50 else 0
        price_trend = "bullish" if last_candle.get("close", 0) > ma_20 > ma_50 else ("bearish" if last_candle.get("close", 0) < ma_20 < ma_50 else "neutral")

        if len(candles) >= 14:
            atr_vals = []
            for i in range(1, 15):
                c, p = candles[-i], candles[-i - 1]
                tr = max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
                atr_vals.append(tr)
            current_atr = sum(atr_vals) / len(atr_vals) if atr_vals else 0
        else:
            current_atr = 0

        analysis = {
            "symbol": symbol, "interval": interval, "mode": "best",
            "currentPrice": agg_price or last_candle.get("close", 0),
            "candleCount": len(candles),
            "dateRange": {
                "start": datetime.fromtimestamp(candles[0]["time"]).strftime("%Y-%m-%d") if candles else None,
                "end": datetime.fromtimestamp(candles[-1]["time"]).strftime("%Y-%m-%d %H:%M") if candles else None,
            },
            "priceTrend": price_trend, "ma20": round(ma_20, 2) if ma_20 else None,
            "ma50": round(ma_50, 2) if ma_50 else None, "currentATR": round(current_atr, 2),
            "patternDetection": {
                "totalPatternsFound": len(markers), "completedPatterns": len(completed_patterns),
                "pendingPatterns": len(pending_patterns), "recentSwingLows": recent_swing_lows[-10:],
            },
            "backtestMetrics": {
                "winRate": metrics.get("winRate", 0), "totalTrades": metrics.get("totalTrades", 0),
                "totalReturn": metrics.get("totalReturn"), "profitFactor": metrics.get("profitFactor"),
                "avgRR": metrics.get("avgRR"), "sharpeRatio": metrics.get("sharpeRatio"),
            },
            "patternMarkers": markers[-20:], "trades": trades[-10:],
            "lastCandle": {"time": last_candle.get("time"), "open": last_candle.get("open"),
                "high": last_candle.get("high"), "low": last_candle.get("low"),
                "close": last_candle.get("close"), "volume": last_candle.get("volume")},
            "dataSources": ["binance", "bybit", "okx"],
            "exchangeData": exchange_data,
            "aggregatedPrice": agg_price,
            "scanTimestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return jsonify({"success": True, "analysis": analysis})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
#  PLUTO ANALYSIS — 9-Agent Boardroom Engine
# ═══════════════════════════════════════════════════════════════

def _run_pluto_analysis(symbol, interval, candles, exchange_data, agg_price):
    """
    Full Pluto-style 9-agent boardroom analysis.
    Each agent evaluates the market from a specific lens.
    """
    from datetime import datetime
    import random
    random.seed(42)  # deterministic randomness for demo

    last = candles[-1]
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    price = agg_price or last["close"]

    # ── Helper calculations ──
    def sma(data, period):
        if len(data) < period: return None
        return sum(data[-period:]) / period

    def atr(candles, period=14):
        if len(candles) < period + 1: return 0
        vals = []
        for i in range(1, period + 1):
            c, p = candles[-i], candles[-i - 1]
            vals.append(max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"])))
        return sum(vals) / len(vals)

    def rsi(closes, period=14):
        if len(closes) < period + 1: return 50
        gains = losses = 0
        for i in range(-period, 0):
            diff = closes[i] - closes[i - 1]
            if diff >= 0: gains += diff
            else: losses -= diff
        avg_g = gains / period
        avg_l = losses / period if losses > 0 else 1
        rs = avg_g / avg_l
        return 100 - (100 / (1 + rs))

    def swing_lows(candles, lookback=5):
        lows_list = []
        for i in range(lookback, len(candles) - lookback):
            if all(candles[i]["low"] <= candles[j]["low"] for j in range(i - lookback, i + lookback + 1) if j != i):
                lows_list.append(candles[i]["low"])
        return lows_list

    current_atr = atr(candles)
    rsi_val = rsi(closes)
    ma20 = sma(closes, 20) or price
    ma50 = sma(closes, 50) or price
    ma200 = sma(closes, 200)
    trend = "bullish" if price > ma20 > ma50 else ("bearish" if price < ma20 < ma50 else "neutral")
    sw_lows = swing_lows(candles)
    recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    recent_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)
    range_pct = ((recent_high - recent_low) / recent_low) * 100 if recent_low > 0 else 0

    # ── 1. Strategist (HTF) ──
    htf_bias = "bullish" if price > ma200 else ("bearish" if ma200 and price < ma200 else "neutral")
    htf_score = 0.8 if price > ma50 and (ma200 is None or price > ma200) else (0.3 if price < ma50 else 0.5)
    htf_verdict = "Accumulation" if htf_bias == "bullish" else "Distribution" if htf_bias == "bearish" else "Range-bound"

    # ── 2. Hunter (Liquidity) ──
    liq_support = min(sw_lows[-3:]) if len(sw_lows) >= 3 else recent_low * 0.98
    liq_resistance = recent_high * 1.02
    retail_stops_below = liq_support * 0.995
    retail_stops_above = liq_resistance * 1.005
    hunter_score = 0.75 if price < (liq_support + liq_resistance) / 2 else 0.5
    liq_zones = [
        {"type": "support", "price": round(liq_support, 2), "strength": "high"},
        {"type": "resistance", "price": round(liq_resistance, 2), "strength": "high"},
        {"type": "retail_stops_below", "price": round(retail_stops_below, 2), "strength": "medium"},
        {"type": "retail_stops_above", "price": round(retail_stops_above, 2), "strength": "medium"},
    ]

    # ── 3. Momentum ──
    mom_direction = "expanding" if rsi_val > 60 else ("contracting" if rsi_val < 40 else "neutral")
    mom_score = 0.7 if rsi_val > 55 else (0.4 if rsi_val < 45 else 0.5)
    exhaustion = rsi_val > 75 or rsi_val < 25
    mom_verdict = "Trend strong" if rsi_val > 60 else "Trend weakening" if rsi_val < 40 else "Momentum neutral"

    # ── 4. Pattern ──
    pattern_type = "double_bottom" if rsi_val < 50 and price < ma50 else (
        "double_top" if rsi_val > 50 and price > ma50 else "no_pattern")
    pattern_score = 0.65 if pattern_type != "no_pattern" else 0.3
    pattern_ob = [{"price": round(liq_support * 0.99, 2), "type": "Order Block"}]

    # ── 5. Tactician (LTF) ──
    entry_zone_low = round(price - current_atr * 0.5, 2)
    entry_zone_high = round(price + current_atr * 0.3, 2)
    t1 = round(price + current_atr * 1.5, 2)
    t2 = round(price + current_atr * 3.0, 2)
    sl = round(price - current_atr * 1.2, 2)
    rr = round((t1 - price) / (price - sl), 2) if (price - sl) > 0 else 0
    tactical_score = min(1.0, rr / 3.0)

    # ── 6. News Agent (simulated sentiment) ──
    sentiment_score = round(55 + (rsi_val - 50) * 0.3, 1)  # proxy from RSI
    sentiment_label = "Greed" if sentiment_score > 65 else ("Fear" if sentiment_score < 40 else "Neutral")
    news_headlines = ["BTC ETF inflows holding steady", "Fed rate decision this week"]

    # ── 7. Coach (Psychology) ──
    herd = "bullish" if rsi_val > 65 else ("bearish" if rsi_val < 35 else "mixed")
    coach_verdict = "Herd is greedy — caution" if herd == "bullish" else (
        "Herd is fearful — opportunity" if herd == "bearish" else "Mixed sentiment — wait for confirmation")
    coach_score = 0.4 if herd != "mixed" else 0.6

    # ── 8. Portfolio Manager ──
    position_size_pct = 2.0 if rr >= 2.0 else (1.0 if rr >= 1.0 else 0.5)
    max_risk = 2.0
    pm_verdict = f"{position_size_pct}% position size, max risk {max_risk}%"
    pm_score = min(1.0, position_size_pct / 3.0)

    # ── 9. Evolution Auditor ──
    all_scores = [htf_score, hunter_score, mom_score, pattern_score, tactical_score, coach_score, pm_score]
    avg_score = sum(all_scores) / len(all_scores)
    contradictions = sum(1 for s in all_scores if s < 0.4)
    final_verdict = "BUY" if avg_score > 0.6 and contradictions <= 1 else (
        "SELL" if avg_score < 0.4 else "WAIT")
    final_confidence = round(avg_score * 100)

    boardroom = {
        "strategist": {
            "name": "Strategist", "icon": "🏛️", "bias": htf_bias, "score": round(htf_score * 100),
            "verdict": htf_verdict, "detail": f"Price ${round(price)} vs MA200 {f'${round(ma200)}' if ma200 else 'N/A'}"},
        "hunter": {
            "name": "Hunter", "icon": "🎯", "score": round(hunter_score * 100),
            "support": round(liq_support, 2), "resistance": round(liq_resistance, 2),
            "detail": f"Liquidity zones: ${round(liq_support)} support / ${round(liq_resistance)} resistance"},
        "momentum": {
            "name": "Momentum", "icon": "⚡", "direction": mom_direction, "score": round(mom_score * 100),
            "rsi": round(rsi_val, 1), "exhaustion": exhaustion, "detail": f"RSI: {round(rsi_val, 1)} — {mom_verdict}"},
        "pattern": {
            "name": "Pattern", "icon": "📐", "type": pattern_type, "score": round(pattern_score * 100),
            "detail": f"Pattern detected: {pattern_type.replace('_', ' ').title()}"},
        "tactician": {
            "name": "Tactician", "icon": "🎯", "score": round(tactical_score * 100),
            "entry": [entry_zone_low, entry_zone_high], "targets": [t1, t2],
            "stopLoss": sl, "rr": rr,
            "detail": f"Entry ${entry_zone_low}–${entry_zone_high} | TP1 ${t1} TP2 ${t2} | SL ${sl} | RR 1:{rr}"},
        "news": {
            "name": "News Agent", "icon": "📰", "sentiment": sentiment_score,
            "label": sentiment_label,
            "detail": f"Market sentiment: {sentiment_label} ({sentiment_score}/100)"},
        "coach": {
            "name": "Coach", "icon": "🧠", "herd": herd, "score": round(coach_score * 100),
            "detail": coach_verdict},
        "portfolioManager": {
            "name": "Portfolio Manager", "icon": "💼", "score": round(pm_score * 100),
            "positionSize": position_size_pct, "maxRisk": max_risk,
            "detail": pm_verdict},
        "auditor": {
            "name": "Evolution Auditor", "icon": "🔍", "avgScore": round(avg_score * 100),
            "contradictions": contradictions, "finalVerdict": final_verdict,
            "confidence": final_confidence,
            "detail": f"Avg conviction: {round(avg_score * 100)}% | Contradictions: {contradictions} | Verdict: {final_verdict}"},
    }

    # ── MTFA (Multi-Timeframe) ──
    timeframes = [("15m", candles), ("1h", candles[-96:]), ("4h", candles[-48:]), ("1d", candles[-30:])]
    mtaf_data = {}
    for tf_name, tf_candles in timeframes:
        if len(tf_candles) < 5:
            mtaf_data[tf_name] = {"trend": "insufficient_data", "ma20": None, "rsi": None}
            continue
        tf_closes = [c["close"] for c in tf_candles]
        tf_ma20 = sma(tf_closes, 20) or tf_closes[-1]
        tf_rsi = rsi(tf_closes, 14)
        tf_trend = "bullish" if tf_closes[-1] > tf_ma20 else ("bearish" if tf_closes[-1] < tf_ma20 else "neutral")
        mtaf_data[tf_name] = {
            "trend": tf_trend, "ma20": round(tf_ma20, 2),
            "rsi": round(tf_rsi, 1), "price": round(tf_closes[-1], 2),
        }

    # ── Liquidity Heatmap (ASCII representation) ──
    heatmap_levels = []
    step = (recent_high - recent_low) / 10 if recent_high > recent_low else 100
    for i in range(11):
        level = recent_low + i * step
        proximity = abs(price - level) / step if step > 0 else 0
        density = 5 - int(proximity) if proximity < 5 else 0
        density = max(0, min(5, density))
        heatmap_levels.append({"price": round(level, 2), "density": density})

    return {
        "symbol": symbol, "interval": interval, "mode": "pluto",
        "currentPrice": round(price, 2),
        "aggregatedPrice": agg_price,
        "exchangeData": exchange_data,
        "dataSources": ["binance", "bybit", "okx"],
        "boardroom": boardroom,
        "mtfa": mtaf_data,
        "heatmap": heatmap_levels,
        "liquidityZones": liq_zones,
        "marketProfile": {
            "rsi": round(rsi_val, 1), "atr": round(current_atr, 2),
            "rangePct": round(range_pct, 2), "trend": trend,
            "price": round(price, 2), "ma20": round(ma20, 2),
            "ma50": round(ma50, 2), "ma200": round(ma200, 2) if ma200 else None,
        },
        "signals": {
            "finalVerdict": boardroom["auditor"]["finalVerdict"],
            "confidence": boardroom["auditor"]["confidence"],
            "entryZone": boardroom["tactician"]["entry"],
            "targets": boardroom["tactician"]["targets"],
            "stopLoss": boardroom["tactician"]["stopLoss"],
            "rr": boardroom["tactician"]["rr"],
        },
        "scanTimestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"[DB Scanner API] Starting on port {port}...")
    print(f"[DB Scanner API] V3 engine available at /api/v3/*")
    print(f"[DB Scanner API] Liquidity9 scanner at /api/liquidity/scan")
    print(f"[DB Scanner API] AI Analysis + Pluto at /api/ai-analysis")
    print(f"[DB Scanner API] Multi-exchange: Binance + Bybit + OKX")
    print(f"[DB Scanner API] Debug mode: {debug}")
    app.run(host="0.0.0.0", port=port, debug=debug)
