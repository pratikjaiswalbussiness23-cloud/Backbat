"""
Algo Engine v1.0 — Configuration
All tunable parameters for the signal generation pipeline.
"""

# ─── Symbols ─────────────────────────────────────────
WATCHED_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_INTERVAL = "15m"

# ─── Component Base Weights (FVG + Swing + Delta) ─────
CONFLUENCE_WEIGHTS = {"FVG": 0.40, "Swing": 0.30, "Delta": 0.30}

# ─── Trend Gate Config ──────────────────────────────
TREND_GATE_THRESHOLD = 0.30
TREND_GATE_BULL_MULT = 1.5
TREND_GATE_BEAR_MULT = 0.5
TREND_REVERSE_BULL_MULT = 0.5
TREND_REVERSE_BEAR_MULT = 1.5

# ─── Quality / Confluence ──────────────────────────
QUALITY_SCORE_THRESH = 0.40
QUALITY_MIN_COMPONENTS = 2

# ─── State Machine ─────────────────────────────────
SIGNAL_MAX_AGE_CANDLES = 30
SIGNAL_MAX_AGE_SECONDS = 7200
SIGNAL_EXPIRY_CANDLES = 20
STALE_CANDLE_THRESHOLD = 5

# ─── Dynamic SL/TP ─────────────────────────────────
SL_ATR_BUFFER = 0.5
TP1_ATR_MIN = 1.2
TP2_ATR_MIN = 2.5
PARTIAL_EXIT_RATIO = 0.5
SWING_LOOKBACK_SL = 10
SWING_LOOKBACK_TP = 20

# ─── Risk Management ──────────────────────────────
RISK_PER_TRADE = 0.02
MAX_DAILY_LOSS = 0.05
MAX_CONCURRENT_TRADES = 2

# ─── WebSocket ────────────────────────────────────
BINANCE_WSS = "wss://stream.binance.com:9443/ws"
RECONNECT_DELAY = 5
PING_INTERVAL = 180

# ─── Trade Journal (SQLite) ──────────────────────────
DB_PATH = "data/trade_journal.db"

# ─── Server ────────────────────────────────────────
SERVER_PORT = 5003
SSE_KEEPALIVE = 15

# ─── Excluded Symbols ─────────────────────────────
EXCLUDED_SYMBOLS = ["BNBUSDT"]

# ─── Candles for Analysis ─────────────────────────
CANDLE_LIMIT = 250
CANDLE_LIMIT_STREAM = 100
