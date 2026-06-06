"""
Liquidity Identifier - Flask API Server
Separate clean app for liquidity zone detection and visualization.
v2.0 — Adds server-side caching for fast refresh.
"""

import os
import json
import time
import requests
import smtplib
from email.message import EmailMessage
from flask import Flask, jsonify, request, send_from_directory

from liq_engine import LiquidityEngine
from liq_indian_engine import IndianLiquidityEngine
from institutional_engine import InstitutionalEngine
from liq_events import get_events_data

app = Flask(__name__)
engine = LiquidityEngine()
indian_engine = IndianLiquidityEngine()
institutional_engine = InstitutionalEngine()

PORT = int(os.environ.get("PORT", 5001))

# ─── In-Memory Cache for Fast Refresh ────────────────────────

class ScanCache:
    """Caches scan results by (symbol, interval) with configurable TTL."""

    def __init__(self, ttl_seconds=10):
        self.cache = {}
        self.ttl = ttl_seconds

    def get(self, symbol, interval):
        key = (symbol.upper(), interval)
        entry = self.cache.get(key)
        if entry and (time.time() - entry["ts"]) < self.ttl:
            return entry["data"]
        return None

    def set(self, symbol, interval, data):
        key = (symbol.upper(), interval)
        self.cache[key] = {"data": data, "ts": time.time()}
        # Evict stale entries occasionally
        if len(self.cache) > 50:
            now = time.time()
            self.cache = {k: v for k, v in self.cache.items() if (now - v["ts"]) < self.ttl * 2}

    def clear(self, symbol=None, interval=None):
        if symbol and interval:
            self.cache.pop((symbol.upper(), interval), None)
        elif symbol:
            self.cache = {k: v for k, v in self.cache.items() if k[0] != symbol.upper()}
        else:
            self.cache.clear()

    def age(self, symbol, interval):
        """Return age in seconds of cached entry, or -1 if not cached."""
        key = (symbol.upper(), interval)
        entry = self.cache.get(key)
        if entry:
            return time.time() - entry["ts"]
        return -1


scan_cache = ScanCache(ttl_seconds=10)


# ─── Delta Live Cache (very short TTL for fast polling) ──────
class DeltaLiveCache:
    """Ultra-short TTL cache specifically for /api/delta-live fast polling."""
    def __init__(self, ttl_seconds=2):
        self.cache = {}
        self.ttl = ttl_seconds

    def get(self, symbol, interval):
        key = (symbol.upper(), interval)
        entry = self.cache.get(key)
        if entry and (time.time() - entry["ts"]) < self.ttl:
            return entry["data"]
        return None

    def set(self, symbol, interval, data):
        key = (symbol.upper(), interval)
        self.cache[key] = {"data": data, "ts": time.time()}
        if len(self.cache) > 20:
            now = time.time()
            self.cache = {k: v for k, v in self.cache.items() if (now - v["ts"]) < self.ttl * 3}


delta_live_cache = DeltaLiveCache(ttl_seconds=2)


@app.route("/")
def index():
    return send_from_directory(".", "liq_index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "liquidity-identifier",
        "port": PORT,
        "cachedItems": len(scan_cache.cache),
    })


def _run_scan(symbol, interval, force_refresh=False):
    """Run scan with caching support.
    Returns (result_dict, from_cache_bool).
    The returned result dict must not be mutated after cache insertion.
    """
    if not force_refresh:
        cached = scan_cache.get(symbol, interval)
        if cached is not None:
            return cached, True

    result = engine.analyze_all(symbol, interval)
    result["success"] = True

    scan_cache.set(symbol, interval, result)
    return result, False


@app.route("/api/quick-scan", methods=["POST"])
def quick_scan():
    """Quick scan — returns cached results if available (faster)."""
    try:
        body = request.get_json(force=True) or {}
        symbol = body.get("symbol", "BTCUSDT")
        interval = body.get("interval", "15m")
        force = body.get("forceRefresh", False)
        result, from_cache = _run_scan(symbol, interval, force_refresh=force)
        # Return a copy so the cached object is never mutated by the caller
        resp = dict(result)
        resp["cached"] = from_cache
        return jsonify(resp)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/full-scan", methods=["POST"])
def full_scan():
    """Full scan — bypasses cache, returns comprehensive data with more depth."""
    try:
        body = request.get_json(force=True) or {}
        symbol = body.get("symbol", "BTCUSDT")
        interval = body.get("interval", "15m")
        # full-scan always bypasses cache and requests more depth data
        result = engine.analyze_all(symbol, interval, depth_limit=200)
        result["success"] = True
        result["fullScan"] = True
        # Update cache with full data
        scan_cache.set(symbol, interval, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cache-status", methods=["GET"])
def cache_status():
    """Get cache status information."""
    return jsonify({
        "cachedItems": len(scan_cache.cache),
        "ttlSeconds": scan_cache.ttl,
        "keys": [f"{k[0]}:{k[1]}" for k in scan_cache.cache.keys()],
    })


@app.route("/api/clear-cache", methods=["POST"])
def clear_cache():
    """Clear the server cache."""
    body = request.get_json(force=True) or {}
    symbol = body.get("symbol")
    interval = body.get("interval")
    scan_cache.clear(symbol=symbol, interval=interval)
    return jsonify({"success": True, "cleared": True})


@app.route("/api/delta-live", methods=["POST"])
def delta_live():
    """
    Ultra-lightweight endpoint for fast delta polling.
    Only fetches candles + computes CVD + delta patterns.
    No order book, no zones, no volume profile — max speed.
    Uses its own short-TTL cache (2s) for quick consecutive polls.
    """
    try:
        body = request.get_json(force=True) or {}
        symbol = body.get("symbol", "BTCUSDT")
        interval = body.get("interval", "15m")
        force = body.get("forceRefresh", False)

        if not force:
            cached = delta_live_cache.get(symbol, interval)
            if cached is not None:
                return jsonify(cached)

        # Only fetch candles — most lightweight call
        candles = engine.client.klines(symbol, interval, limit=100)

        # Compute CVD (includes per-candle delta)
        cvd_result = engine.cvd.calculate(candles)

        # Compute delta patterns
        delta_patterns = engine.delta_patterns.detect(candles, cvd_result.get("perCandleDelta", []))

        # Get current price from last candle (avoids extra API call)
        last_candle = candles[-1] if candles else None
        current_price = (last_candle["high"] + last_candle["low"]) / 2 if last_candle else 0

        result = {
            "success": True,
            "symbol": symbol,
            "interval": interval,
            "currentPrice": round(current_price, 2),
            "timestamp": int(time.time()),
            "cvd": cvd_result,
            "deltaPatterns": delta_patterns,
            "candlesCount": len(candles),
            "live": True,
        }

        delta_live_cache.set(symbol, interval, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══ Email Alert Helper ═══════════════════════════════════

EMAIL_ENABLED = False
EMAIL_SENDER = None
EMAIL_PASSWORD = None
EMAIL_RECIPIENT = "pratikaifounder@gmail.com"

# Check for environment variables on startup
def _init_email():
    global EMAIL_ENABLED, EMAIL_SENDER, EMAIL_PASSWORD
    sender = os.environ.get("GMAIL_USER")
    pwd = os.environ.get("GMAIL_APP_PASSWORD")
    if sender and pwd:
        EMAIL_ENABLED = True
        EMAIL_SENDER = sender
        EMAIL_PASSWORD = pwd
        print("  [Email] Alerts: ENABLED  (" + sender + " -> " + EMAIL_RECIPIENT + ")")
    else:
        print("  [Email] Alerts: DISABLED  (set GMAIL_USER + GMAIL_APP_PASSWORD env vars)")


def send_delta_alert_email(pattern_data):
    """Send an email notification for a new delta pattern.
    Returns True if sent, False if email is disabled or send fails.
    """
    if not EMAIL_ENABLED:
        return False

    try:
        p = pattern_data
        sig_pct = int((p.get("significance", 0) or 0) * 100)
        direction = p.get("direction", "neutral").capitalize()
        name = p.get("name", "Unknown Pattern")
        desc = p.get("description", "")
        insight = p.get("insight", "")
        symbol = p.get("symbol", "BTCUSDT")
        interval = p.get("interval", "15m")

        msg = EmailMessage()
        msg["Subject"] = f"🚨 Delta Pattern P{p.get('pattern','?')} — {name} ({direction}, {sig_pct}%)"
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECIPIENT

        body = f"""🔔 Liquidity Identifier — Delta Pattern Alert

Pattern: P{p.get('pattern','?')} — {name}
Direction: {direction}
Significance: {sig_pct}%
Symbol: {symbol}
Interval: {interval}
Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

Description:
{desc}

Insight:
{insight}

Metrics:
"""
        for key, val in p.items():
            if key in ("pattern", "name", "direction", "significance", "description", "insight"):
                continue
            body += f"  {key}: {val}\n"

        body += "\n— Liquidity Identifier v2.0"
        msg.set_content(body)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)

        return True
    except Exception as e:
        print(f"[Email] Failed to send alert: {e}")
        return False


_init_email()


@app.route("/api/send-email-alert", methods=["POST"])
def send_email_alert():
    """Send an email alert for a detected delta pattern.
    Requires GMAIL_USER and GMAIL_APP_PASSWORD env vars to be set.
    """
    try:
        body = request.get_json(force=True) or {}
        pattern = body.get("pattern", {})
        if not pattern or not pattern.get("pattern"):
            return jsonify({"success": False, "error": "No pattern data provided"})

        if not EMAIL_ENABLED:
            return jsonify({
                "success": False,
                "error": "Email not configured. Set GMAIL_USER and GMAIL_APP_PASSWORD environment variables.",
                "hint": "Generate an App Password at myaccount.google.com/apppasswords",
            })

        # Attach symbol/interval from request
        pattern["symbol"] = body.get("symbol", "BTCUSDT")
        pattern["interval"] = body.get("interval", "15m")

        sent = send_delta_alert_email(pattern)
        if sent:
            return jsonify({"success": True, "sent": True, "to": EMAIL_RECIPIENT})
        else:
            return jsonify({"success": False, "error": "Failed to send email"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══ Telegram Bot Alert Helper ═══════════════════════

TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = None
TELEGRAM_CHAT_ID = None


def _init_telegram():
    global TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if bot_token and chat_id:
        TELEGRAM_ENABLED = True
        TELEGRAM_BOT_TOKEN = bot_token
        TELEGRAM_CHAT_ID = chat_id
        print(f"  [Telegram] Alerts: ENABLED  (bot -> chat {chat_id})")
    else:
        missing = []
        if not bot_token: missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id: missing.append("TELEGRAM_CHAT_ID")
        print(f"  [Telegram] Alerts: DISABLED  (set env vars: {', '.join(missing)})")
        print("  [Telegram] Get a bot token from @BotFather on Telegram. Then get your chat ID by messaging @userinfobot or visiting https://api.telegram.org/bot<token>/getUpdates")


def send_delta_alert_telegram(pattern_data):
    """Send a Telegram notification for a new delta pattern.
    Returns True if sent, False if Telegram is disabled or send fails.
    """
    if not TELEGRAM_ENABLED:
        return False

    try:
        p = pattern_data
        sig_pct = int((p.get("significance", 0) or 0) * 100)
        direction = p.get("direction", "neutral").capitalize()
        name = p.get("name", "Unknown Pattern")
        desc = p.get("description", "")
        insight = p.get("insight", "")
        symbol = p.get("symbol", "BTCUSDT")
        interval = p.get("interval", "15m")

        # Build a concise alert message with Markdown formatting
        msg_lines = [
            f"🚨 *Liquidity Alert* — {symbol} ({interval})",
            "",
            f"📊 *Pattern P{p.get('pattern','?')}*: {name}",
            f"📌 Direction: {direction}",
            f"⚡ Significance: {sig_pct}%",
            "",
            f"📝 {desc}",
            f"💡 {insight}",
            "",
            "📈 *Key Metrics:*",
        ]
        for key, val in p.items():
            if key in ("pattern", "name", "direction", "significance", "description", "insight", "symbol", "interval"):
                continue
            msg_lines.append(f"   • `{key}`: {val}")

        msg_lines.append("")
        msg_lines.append(f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
        msg_lines.append("— Liquidity Identifier")

        msg_body = "\n".join(msg_lines)

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg_body,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        resp = requests.post(url, data=payload, timeout=10)
        result = resp.json()

        if result.get("ok"):
            print(f"  [Telegram] Alert sent! Message ID: {result.get('result', {}).get('message_id')}")
            return True
        else:
            print(f"  [Telegram] API error: {result.get('description')}")
            return False

    except Exception as e:
        print(f"  [Telegram] Failed to send alert: {e}")
        return False


_init_telegram()


@app.route("/api/send-telegram-alert", methods=["POST"])
def send_telegram_alert():
    """Send a Telegram alert for a detected delta pattern.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables to be set.
    Get a bot token from @BotFather on Telegram, then get your chat ID by messaging @userinfobot.
    """
    try:
        body = request.get_json(force=True) or {}
        pattern = body.get("pattern", {})
        if not pattern or not pattern.get("pattern"):
            return jsonify({"success": False, "error": "No pattern data provided"})

        if not TELEGRAM_ENABLED:
            return jsonify({
                "success": False,
                "error": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.",
                "hint": "1) Message @BotFather on Telegram to create a bot and get a token. 2) Message @userinfobot to get your chat ID.",
            })

        # Attach symbol/interval from request
        pattern["symbol"] = body.get("symbol", "BTCUSDT")
        pattern["interval"] = body.get("interval", "15m")

        sent = send_delta_alert_telegram(pattern)
        if sent:
            return jsonify({"success": True, "sent": True, "to": TELEGRAM_CHAT_ID})
        else:
            return jsonify({"success": False, "error": "Failed to send Telegram message"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/telegram/test", methods=["GET"])
def telegram_test():
    """Send a manual test Telegram alert to verify bot configuration.
    Useful for confirming the bot token and chat ID are correct
    without waiting for delta patterns.
    """
    if not TELEGRAM_ENABLED:
        return jsonify({
            "success": False,
            "error": "Telegram not configured.",
            "hint": "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables and restart the server.",
        }), 200

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": (
                "🚀 *Liquidity Identifier — Test Alert*\n\n"
                "✅ Your Telegram bot is working!\n"
                "Notifications will now be sent for:\n"
                "• New delta patterns detected\n"
                "• Liquidity sweep alerts\n"
                "• High-significance signals\n\n"
                f"⏰ " + time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()) + "\n"
                "— Liquidity Identifier v2.0"
            ),
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        resp = requests.post(url, data=payload, timeout=10)
        result = resp.json()

        if result.get("ok"):
            print(f"  [Telegram] Test alert sent! Message ID: {result.get('result', {}).get('message_id')}")
            return jsonify({
                "success": True,
                "sent": True,
                "to": TELEGRAM_CHAT_ID,
                "message": "Test Telegram alert sent successfully! Check your Telegram.",
            })
        else:
            error_desc = result.get("description", "Unknown error")
            print(f"  [Telegram] Test alert failed: {error_desc}")
            return jsonify({
                "success": False,
                "error": f"Telegram API error: {error_desc}",
                "hint": "Make sure you've messaged your bot first on Telegram (start a chat with it).",
            }), 200

    except Exception as e:
        print(f"  [Telegram] Test alert exception: {e}")
        return jsonify({"success": False, "error": str(e)}), 200


# ═══ Institutional Flow Endpoint ═══════════════════════════

@app.route("/api/institutional", methods=["POST"])
def institutional_scan():
    """Scan for institutional activity — whales, OI, funding, spoofing, netflow, CVD."""
    try:
        body = request.get_json(force=True) or {}
        symbol = body.get("symbol", "BTCUSDT")
        result = institutional_engine.analyze(symbol)
        result["success"] = True
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══ Indian Stock Market Endpoints ═══════════════════════════

@app.route("/api/indian/stocks", methods=["GET"])
def indian_stock_list():
    """Get list of available Indian stocks."""
    query = request.args.get("q", "")
    stocks = indian_engine.search_stocks(query)
    return jsonify({"success": True, "stocks": stocks})


@app.route("/api/indian/scan", methods=["POST"])
def indian_scan():
    """Scan an Indian stock for liquidity zones."""
    try:
        body = request.get_json(force=True) or {}
        symbol = body.get("symbol", "^NSEI")
        interval = body.get("interval", "15m")
        result = indian_engine.analyze(symbol, interval)
        result["success"] = True
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══ AI Assistant (Gemini + Groq Dual Provider) ═══════════

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto")  # "auto", "gemini", "groq"

SYSTEM_PROMPT = """You are LiquidityGPT, an expert AI trading assistant built into the Liquidity Identifier app. You help traders understand market structure, liquidity zones, order flow, and institutional activity.

Your expertise includes:
- Support & Resistance zones, Order Blocks (OB), Fair Value Gaps (FVG), Liquidity Sweeps
- Cumulative Volume Delta (CVD), order flow analysis, buyer/seller imbalance
- Volume Profile (POC, HVN, LVN, Value Area), institutional whale activity
- Open Interest, Funding Rates, spoofing/anomaly detection
- Delta patterns: Absorption Candle, Hidden Buying, Stop Hunt Reversal, Squeeze Explosion
- Indian stock market (NSE) liquidity analysis

Guidelines:
- Be concise, direct, and actionable. Traders need fast answers.
- Use formatting: bold for key terms, bullet points for lists.
- When analyzing data, give clear BUY/SELL/WAIT verdicts with reasoning.
- Always include risk disclaimers when giving trade ideas.
- If the user asks about current market data, reference the scanner's features.
- Support both crypto (BTC, ETH, SOL etc.) and Indian stocks (NSE).
- Use emoji sparingly for visual clarity (🟢 for bullish, 🔴 for bearish).
- Keep responses under 300 words unless the user asks for detailed analysis.
"""


def _call_gemini(contents):
    """Call Google Gemini API. Returns (reply_text, model_name) or raises."""
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API key not configured")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1024,
            "topP": 0.9,
        },
    }
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        error_msg = "Gemini API error"
        try:
            error_msg = resp.json().get("error", {}).get("message", error_msg)
        except Exception:
            pass
        raise ValueError(error_msg)

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("No response from Gemini")
    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    if not text:
        raise ValueError("Empty Gemini response")
    return text, GEMINI_MODEL


def _call_groq(contents):
    """Call Groq API (OpenAI-compatible). Returns (reply_text, model_name) or raises."""
    if not GROQ_API_KEY:
        raise ValueError("Groq API key not configured")

    url = "https://api.groq.com/openai/v1/chat/completions"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in contents:
        role = "assistant" if turn["role"] == "model" else turn["role"]
        messages.append({"role": role, "content": turn.get("parts", [{}])[0].get("text", "")})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1024,
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        error_msg = "Groq API error"
        try:
            error_msg = resp.json().get("error", {}).get("message", error_msg)
        except Exception:
            pass
        raise ValueError(error_msg)

    data = resp.json()
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not text:
        raise ValueError("Empty Groq response")
    return text, GROQ_MODEL


@app.route("/api/ai-chat", methods=["POST"])
def ai_chat():
    """Proxy to AI providers (Gemini primary, Groq fallback) for chat."""
    try:
        body = request.get_json(force=True) or {}
        user_message = body.get("message", "").strip()
        history = body.get("history", [])

        if not user_message:
            return jsonify({"success": False, "error": "Empty message"}), 400

        # Build conversation contents for Gemini / messages for Groq
        contents = []
        for turn in history:
            role = "user" if turn.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        # Determine provider order based on AI_PROVIDER setting
        providers = []
        if AI_PROVIDER in ("auto", "gemini") and GEMINI_API_KEY:
            providers.append("gemini")
        if AI_PROVIDER in ("auto", "groq") and GROQ_API_KEY:
            providers.append("groq")

        if not providers:
            return jsonify({
                "success": False,
                "error": "No AI provider configured.",
                "hint": "Set GEMINI_API_KEY or GROQ_API_KEY env var. Free keys: Gemini -> aistudio.google.com | Groq -> console.groq.com",
            }), 503

        # Try each provider in order
        last_error = None
        for provider in providers:
            try:
                if provider == "gemini":
                    reply_text, model_name = _call_gemini(contents)
                else:
                    reply_text, model_name = _call_groq(contents)
                return jsonify({"success": True, "reply": reply_text, "model": model_name})
            except Exception as e:
                last_error = str(e)
                print(f"  [AI] {provider} failed: {last_error}")
                continue

        return jsonify({"success": False, "error": f"All AI providers failed. Last error: {last_error}"}), 502

    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "AI request timed out. Try again."}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "Cannot reach AI service. Check internet connection."}), 502
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══ Market Phase Analysis Endpoint ═══════════════════════

@app.route("/api/market-phase", methods=["POST"])
def market_phase():
    """
    Analyze market regime: Consolidation / Trendy / Volatile / Silent / Transitioning.
    Uses multi-timeframe candle data with ADX, ATR, Bollinger Bands,
    volume profile, and candle body analysis.
    """
    try:
        body = request.get_json(force=True) or {}
        symbol = body.get("symbol", "BTCUSDT")
        interval = body.get("interval", "15m")

        # Fetch candles from Binance (primary)
        candles = engine.client.klines(symbol, interval, limit=200)
        if not candles or len(candles) < 30:
            return jsonify({"success": False, "error": "Insufficient candle data"}), 502

        result = _compute_market_phase(candles, symbol, interval)
        result["success"] = True
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


def _compute_market_phase(candles, symbol, interval):
    """
    Core market phase analysis engine.
    Computes ADX, ATR, Bollinger Bands, volume, candle body metrics,
    and classifies the market into a phase.
    """
    from datetime import datetime
    import math

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]
    n = len(closes)

    # ─── Helper: SMA ───
    def sma(data, period):
        if len(data) < period:
            return [None] * len(data)
        result = [None] * len(data)
        for i in range(period - 1, len(data)):
            result[i] = sum(data[i - period + 1:i + 1]) / period
        return result

    # ─── 1. ATR (Average True Range) ───
    atr_period = 14
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        trs.append(tr)

    atr_values = [None] * n
    if len(trs) >= atr_period:
        current_atr = sum(trs[:atr_period]) / atr_period
        atr_values[atr_period] = current_atr
        for i in range(atr_period, len(trs)):
            current_atr = (current_atr * (atr_period - 1) + trs[i]) / atr_period
            atr_values[i + 1] = current_atr

    current_atr = atr_values[-1] if atr_values[-1] else 0
    # ATR as % of price
    atr_pct = (current_atr / closes[-1] * 100) if closes[-1] > 0 else 0
    # ATR 20 candles ago for trend
    atr_prev = atr_values[-21] if len(atr_values) > 21 and atr_values[-21] else current_atr
    atr_expanding = current_atr > atr_prev * 1.1 if atr_prev > 0 else False
    atr_contracting = current_atr < atr_prev * 0.9 if atr_prev > 0 else False

    # ─── 2. ADX (Average Directional Index) ───
    adx_period = 14
    plus_dm = []
    minus_dm = []
    tr_list = []

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)

    if len(tr_list) >= adx_period and len(plus_dm) >= adx_period:
        # Smoothed TR, +DM, -DM
        smooth_tr = sum(tr_list[:adx_period])
        smooth_plus = sum(plus_dm[:adx_period])
        smooth_minus = sum(minus_dm[:adx_period])

        dx_values = []
        for i in range(adx_period - 1, len(tr_list)):
            if i > adx_period - 1:
                smooth_tr = smooth_tr - smooth_tr / adx_period + tr_list[i]
                smooth_plus = smooth_plus - smooth_plus / adx_period + plus_dm[i]
                smooth_minus = smooth_minus - smooth_minus / adx_period + minus_dm[i]

            plus_di = (smooth_plus / smooth_tr * 100) if smooth_tr > 0 else 0
            minus_di = (smooth_minus / smooth_tr * 100) if smooth_tr > 0 else 0

            di_sum = plus_di + minus_di
            dx = (abs(plus_di - minus_di) / di_sum * 100) if di_sum > 0 else 0
            dx_values.append({
                "dx": dx, "plus_di": plus_di, "minus_di": minus_di,
                "time": candles[i + 1]["time"]
            })

        # Smooth DX to get ADX
        if len(dx_values) >= adx_period:
            adx = sum(d["dx"] for d in dx_values[:adx_period]) / adx_period
            for i in range(adx_period, len(dx_values)):
                adx = (adx * (adx_period - 1) + dx_values[i]["dx"]) / adx_period
            dx_values[-1]["adx"] = round(adx, 2)
        else:
            adx = 0
            dx_values[-1]["adx"] = 0

        current_dx = dx_values[-1]
        plus_di = current_dx["plus_di"]
        minus_di = current_dx["minus_di"]
    else:
        adx = 0
        plus_di = 0
        minus_di = 0
        dx_values = []

    # ADX trend (compare current vs 20 candles ago)
    adx_prev = dx_values[-21]["adx"] if len(dx_values) > 21 and "adx" in dx_values[-21] else adx
    adx_rising = adx > adx_prev if adx_prev else False

    # ─── 3. Bollinger Bands ───
    bb_period = 20
    bb_std = 2
    sma20 = sma(closes, bb_period)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)

    bb_upper = [None] * n
    bb_lower = [None] * n
    bb_width = [None] * n
    bb_pctb = [None] * n  # %B — position within bands

    for i in range(bb_period - 1, n):
        window = closes[i - bb_period + 1:i + 1]
        mean = sum(window) / bb_period
        variance = sum((x - mean) ** 2 for x in window) / bb_period
        std = math.sqrt(variance)
        bb_upper[i] = mean + bb_std * std
        bb_lower[i] = mean - bb_std * std
        bw = (bb_upper[i] - bb_lower[i]) / mean * 100 if mean > 0 else 0
        bb_width[i] = bw
        band_range = bb_upper[i] - bb_lower[i]
        bb_pctb[i] = (closes[i] - bb_lower[i]) / band_range if band_range > 0 else 0.5

    current_bbw = bb_width[-1] if bb_width[-1] else 0
    bb_upper_val = bb_upper[-1] if bb_upper[-1] else closes[-1]
    bb_lower_val = bb_lower[-1] if bb_lower[-1] else closes[-1]
    current_pctb = bb_pctb[-1] if bb_pctb[-1] is not None else 0.5

    # BBW percentile (how narrow vs history)
    bbw_history = [w for w in bb_width if w is not None]
    if bbw_history:
        bbw_sorted = sorted(bbw_history)
        bbw_percentile = sum(1 for w in bbw_sorted if w <= current_bbw) / len(bbw_sorted) * 100
    else:
        bbw_percentile = 50

    # ─── 4. Volume Analysis ───
    vol_sma20 = sma(volumes, 20)
    current_vol = volumes[-1]
    avg_vol = vol_sma20[-1] if vol_sma20[-1] else sum(volumes[-20:]) / min(20, len(volumes))
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

    # Volume trend: compare last 10 avg vs previous 10 avg
    recent_vol = sum(volumes[-10:]) / min(10, len(volumes))
    prev_vol = sum(volumes[-20:-10]) / min(10, len(volumes) - 10) if len(volumes) > 20 else recent_vol
    vol_expanding = recent_vol > prev_vol * 1.2 if prev_vol > 0 else False
    vol_contracting = recent_vol < prev_vol * 0.8 if prev_vol > 0 else False

    # ─── 5. Candle Body Analysis ───
    body_ratios = []
    for i in range(-20, 0):
        if i + n >= 0 and i + n < n:
            idx = i + n if i < 0 else i
            idx = n + i
            candle_range = highs[idx] - lows[idx]
            candle_body = abs(closes[idx] - candles[idx]["open"])
            ratio = candle_body / candle_range if candle_range > 0 else 0
            body_ratios.append(ratio)

    avg_body_ratio = sum(body_ratios) / len(body_ratios) if body_ratios else 0.5

    # Recent body ratio (last 5 candles)
    recent_bodies = []
    for i in range(max(0, n - 5), n):
        candle_range = highs[i] - lows[i]
        candle_body = abs(closes[i] - candles[i]["open"])
        ratio = candle_body / candle_range if candle_range > 0 else 0
        recent_bodies.append(ratio)
    recent_body_ratio = sum(recent_bodies) / len(recent_bodies) if recent_bodies else 0.5

    # ─── 6. Price Action ───
    price = closes[-1]
    ma20_val = sma20[-1] if sma20[-1] else price
    ma50_val = sma50[-1] if sma50[-1] else price
    ma200_val = sma200[-1] if sma200[-1] else None

    # Higher highs / lower lows (last 20 candles)
    swing_highs = []
    swing_lows = []
    lookback = min(20, n)
    for i in range(max(0, n - lookback), n):
        swing_highs.append(highs[i])
        swing_lows.append(lows[i])

    recent_high = max(swing_highs)
    recent_low = min(swing_lows)
    range_pct = (recent_high - recent_low) / recent_low * 100 if recent_low > 0 else 0
    price_position = (price - recent_low) / (recent_high - recent_low) if (recent_high - recent_low) > 0 else 0.5

    # Directional bias
    if plus_di > minus_di + 5:
        di_bias = "bullish"
    elif minus_di > plus_di + 5:
        di_bias = "bearish"
    else:
        di_bias = "neutral"

    # MA alignment
    if price > ma20_val and ma20_val > ma50_val:
        ma_trend = "bullish"
    elif price < ma20_val and ma20_val < ma50_val:
        ma_trend = "bearish"
    else:
        ma_trend = "mixed"

    # ─── 7. Phase Classification ───
    scores = {
        "consolidation": 0,
        "trending_bullish": 0,
        "trending_bearish": 0,
        "volatile": 0,
        "silent": 0,
    }

    # Consolidation signals
    if adx < 20:
        scores["consolidation"] += 30
    elif adx < 25:
        scores["consolidation"] += 15
    if bbw_percentile < 30:
        scores["consolidation"] += 25
    elif bbw_percentile < 45:
        scores["consolidation"] += 10
    if atr_contracting:
        scores["consolidation"] += 15
    if range_pct < 3:
        scores["consolidation"] += 15
    elif range_pct < 5:
        scores["consolidation"] += 8
    if abs(price_position - 0.5) < 0.2:
        scores["consolidation"] += 10

    # Trending bullish signals
    if adx > 25:
        scores["trending_bullish"] += 20
        scores["trending_bearish"] += 20
    elif adx > 20:
        scores["trending_bullish"] += 10
        scores["trending_bearish"] += 10
    if di_bias == "bullish":
        scores["trending_bullish"] += 25
    if di_bias == "bearish":
        scores["trending_bearish"] += 25
    if ma_trend == "bullish":
        scores["trending_bullish"] += 20
    elif ma_trend == "bearish":
        scores["trending_bearish"] += 20
    if adx_rising and adx > 20:
        if di_bias == "bullish":
            scores["trending_bullish"] += 15
        elif di_bias == "bearish":
            scores["trending_bearish"] += 15
    if price > ma20_val:
        scores["trending_bullish"] += 5
    if price < ma20_val:
        scores["trending_bearish"] += 5
    if current_pctb > 0.8:
        scores["trending_bullish"] += 8
    elif current_pctb < 0.2:
        scores["trending_bearish"] += 8

    # Volatile signals
    if bbw_percentile > 70:
        scores["volatile"] += 25
    elif bbw_percentile > 55:
        scores["volatile"] += 10
    if atr_expanding:
        scores["volatile"] += 20
    if atr_pct > 2.5:
        scores["volatile"] += 20
    elif atr_pct > 1.5:
        scores["volatile"] += 10
    if recent_body_ratio > 0.65:
        scores["volatile"] += 15
    if vol_expanding and vol_ratio > 1.3:
        scores["volatile"] += 15
    elif vol_ratio > 2.0:
        scores["volatile"] += 15
    if range_pct > 6:
        scores["volatile"] += 10

    # Silent/dead signals
    if vol_ratio < 0.5:
        scores["silent"] += 25
    elif vol_ratio < 0.7:
        scores["silent"] += 12
    if vol_contracting:
        scores["silent"] += 15
    if atr_pct < 0.5:
        scores["silent"] += 20
    elif atr_pct < 0.8:
        scores["silent"] += 10
    if recent_body_ratio < 0.3:
        scores["silent"] += 15
    elif recent_body_ratio < 0.4:
        scores["silent"] += 8
    if adx < 15:
        scores["silent"] += 15
    if range_pct < 1.5:
        scores["silent"] += 10
    elif range_pct < 2.5:
        scores["silent"] += 5

    # Determine primary phase
    phase_order = ["consolidation", "trending_bullish", "trending_bearish", "volatile", "silent"]
    sorted_phases = sorted(phase_order, key=lambda p: scores[p], reverse=True)
    primary_phase = sorted_phases[0]
    secondary_phase = sorted_phases[1] if scores[sorted_phases[1]] > 20 else None

    # Normalize scores to 0-100
    max_score = max(scores.values()) if max(scores.values()) > 0 else 1
    normalized = {p: min(100, round(s / max_score * 100)) for p, s in scores.items()}

    # Phase display info
    phase_info = {
        "consolidation": {
            "label": "Consolidation",
            "icon": "↔",
            "color": "#f59e0b",
            "description": "Price is range-bound between support and resistance. Low directional conviction — ideal for range-trading strategies or waiting for a breakout.",
            "strategy": "Trade the range: buy at support, sell at resistance. Set tight stops outside the range. Prepare for breakout in either direction.",
        },
        "trending_bullish": {
            "label": "Trending — Bullish",
            "icon": "↑",
            "color": "#10b981",
            "description": "Strong upward momentum with higher highs and higher lows. Buyers are in control across multiple indicators.",
            "strategy": "Buy dips to MA20 or key support zones. Trail stops below recent swing lows. Avoid counter-trend shorts.",
        },
        "trending_bearish": {
            "label": "Trending — Bearish",
            "icon": "↓",
            "color": "#f43f5e",
            "description": "Strong downward momentum with lower highs and lower lows. Sellers are dominating the order flow.",
            "strategy": "Short rallies to resistance or MA20. Trail stops above recent swing highs. Avoid counter-trend longs.",
        },
        "volatile": {
            "label": "Volatile",
            "icon": "⚡",
            "color": "#8b5cf6",
            "description": "High volatility with expanding ranges and large candle bodies. Both buyers and sellers are aggressive — expect rapid price swings.",
            "strategy": "Wider stops required. Reduce position size. Best for scalp/swing trades with clear entries. Avoid market orders.",
        },
        "silent": {
            "label": "Silent / Dead",
            "icon": "○",
            "color": "#64748b",
            "description": "Minimal trading activity with tiny candles, low volume, and compressed volatility. Market is in a wait-and-see mode.",
            "strategy": "Stay flat or reduce exposure. Wait for volume spike or breakout. Good time for analysis, not trading.",
        },
    }

    info = phase_info[primary_phase]
    sec_info = phase_info.get(secondary_phase, {}) if secondary_phase else None

    # ─── 8. Key Levels from Phase ───
    key_levels = {
        "support": [
            {"price": round(bb_lower_val, 2), "label": "BB Lower"},
            {"price": round(ma20_val, 2), "label": "MA20"},
        ],
        "resistance": [
            {"price": round(bb_upper_val, 2), "label": "BB Upper"},
        ],
        "current_price": round(price, 2),
    }
    if ma50_val:
        key_levels["support"].append({"price": round(ma50_val, 2), "label": "MA50"})
    if ma200_val:
        key_levels["ma200"] = round(ma200_val, 2)

    # ─── 10. ADX history for mini-chart ───
    adx_history = []
    for d in dx_values[-30:]:
        adx_history.append({
            "time": d["time"],
            "adx": round(d.get("adx", 0), 2),
            "plus_di": round(d["plus_di"], 2),
            "minus_di": round(d["minus_di"], 2),
        })

    # ─── 9. BBW history for mini-chart ───
    bbw_hist_out = []
    for i in range(max(0, n - 30), n):
        if bb_width[i] is not None:
            bbw_hist_out.append({
                "time": candles[i]["time"],
                "bbw": round(bb_width[i], 4),
            })

    return {
        "symbol": symbol,
        "interval": interval,
        "marketPhase": {
            "primary": {
                "phase": primary_phase,
                "label": info["label"],
                "icon": info["icon"],
                "color": info["color"],
                "description": info["description"],
                "strategy": info["strategy"],
                "score": normalized[primary_phase],
            },
            "secondary": {
                "phase": secondary_phase,
                "label": sec_info["label"] if sec_info else None,
                "icon": sec_info["icon"] if sec_info else None,
                "color": sec_info["color"] if sec_info else None,
                "score": normalized.get(secondary_phase, 0) if secondary_phase else 0,
            } if secondary_phase else None,
            "allScores": normalized,
        },
        "indicators": {
            "adx": {
                "value": round(adx, 2),
                "trend": "rising" if adx_rising else "falling",
                "plusDI": round(plus_di, 2),
                "minusDI": round(minus_di, 2),
                "bias": di_bias,
            },
            "atr": {
                "value": round(current_atr, 2),
                "percent": round(atr_pct, 3),
                "trend": "expanding" if atr_expanding else ("contracting" if atr_contracting else "stable"),
            },
            "bollingerBands": {
                "upper": round(bb_upper_val, 2),
                "middle": round(ma20_val, 2),
                "lower": round(bb_lower_val, 2),
                "width": round(current_bbw, 4),
                "widthPercentile": round(bbw_percentile, 1),
                "percentB": round(current_pctb, 3),
            },
            "volume": {
                "current": round(current_vol, 4),
                "average": round(avg_vol, 4),
                "ratio": round(vol_ratio, 2),
                "trend": "expanding" if vol_expanding else ("contracting" if vol_contracting else "stable"),
            },
            "candleBody": {
                "recentRatio": round(recent_body_ratio, 3),
                "avgRatio": round(avg_body_ratio, 3),
                "assessment": "strong" if recent_body_ratio > 0.6 else ("weak" if recent_body_ratio < 0.35 else "moderate"),
            },
            "priceAction": {
                "price": round(price, 2),
                "ma20": round(ma20_val, 2),
                "ma50": round(ma50_val, 2),
                "ma200": round(ma200_val, 2) if ma200_val else None,
                "maTrend": ma_trend,
                "rangePercent": round(range_pct, 2),
                "positionInRange": round(price_position, 3),
            },
        },
        "keyLevels": key_levels,
        "adxHistory": adx_history,
        "bbwHistory": bbw_hist_out,
        "timestamp": int(time.time()),
    }


# ═══ Events Calendar Endpoint ═════════════════════════════

@app.route("/api/events", methods=["POST"])
def events_calendar():
    """
    Upcoming economic and crypto events with documented market impacts.
    All data from published government schedules and known crypto roadmaps.
    """
    try:
        result = get_events_data()
        result["success"] = True
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══ Static File Catch-All (must be LAST route) ═══
@app.route("/<path:path>")
def static_files(path):
    allowed_extensions = (".js", ".css", ".html", ".png", ".jpg", ".svg", ".ico", ".json")
    if any(path.endswith(ext) for ext in allowed_extensions):
        try:
            return send_from_directory(".", path)
        except Exception:
            return jsonify({"error": "Not found"}), 404
    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    print()
    print("  LIQUIDITY IDENTIFIER v2.0")
    print("  Server: http://localhost:" + str(PORT))
    print("  Cache TTL: 10s — Fast Refresh Enabled")
    print("  Delta Live TTL: 2s — Ultra-Fast Polling")
    print("  Indian Stocks: ENABLED (yfinance)")
    ai_providers = []
    if GEMINI_API_KEY: ai_providers.append(f"Gemini ({GEMINI_MODEL})")
    if GROQ_API_KEY: ai_providers.append(f"Groq ({GROQ_MODEL})")
    if ai_providers:
        print(f"  AI Assistant: ENABLED — {', '.join(ai_providers)}")
    else:
        print("  AI Assistant: DISABLED (set GEMINI_API_KEY or GROQ_API_KEY env var)")
        print("    Free keys: Gemini → aistudio.google.com  |  Groq → console.groq.com")
    print()
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=PORT, debug=debug_mode)
