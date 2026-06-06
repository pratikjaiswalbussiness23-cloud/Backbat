"""
Indian Stock Market Liquidity Engine
Uses Yahoo Finance (yfinance) to fetch NSE/BSE stock data and
reuses liquidity analysis algorithms from liq_engine.py.
"""

import time
import yfinance as yf

from liq_engine import (
    SwingPointDetector,
    OrderBlockDetector,
    FVGBalancer,
    LiquiditySweepDetector,
    VolumeProfileAnalyzer,
    CVDAnalyzer,
    DeltaPatternDetector,
    LiquidityMerger,
    RequestCache,
)

INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "4h": "60m",
    "1d": "1d",
}

INDIAN_STOCKS = [
    {"symbol": "^NSEI", "name": "NIFTY 50", "exchange": "NSE"},
    {"symbol": "^BSESN", "name": "SENSEX", "exchange": "BSE"},
    {"symbol": "^NSEBANK", "name": "BANK NIFTY", "exchange": "NSE"},
    {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "exchange": "NSE"},
    {"symbol": "TCS.NS", "name": "Tata Consultancy Services", "exchange": "NSE"},
    {"symbol": "HDFCBANK.NS", "name": "HDFC Bank", "exchange": "NSE"},
    {"symbol": "INFY.NS", "name": "Infosys", "exchange": "NSE"},
    {"symbol": "ICICIBANK.NS", "name": "ICICI Bank", "exchange": "NSE"},
    {"symbol": "HINDUNILVR.NS", "name": "Hindustan Unilever", "exchange": "NSE"},
    {"symbol": "ITC.NS", "name": "ITC Limited", "exchange": "NSE"},
    {"symbol": "SBIN.NS", "name": "State Bank of India", "exchange": "NSE"},
    {"symbol": "BHARTIARTL.NS", "name": "Bharti Airtel", "exchange": "NSE"},
    {"symbol": "KOTAKBANK.NS", "name": "Kotak Mahindra Bank", "exchange": "NSE"},
    {"symbol": "BAJFINANCE.NS", "name": "Bajaj Finance", "exchange": "NSE"},
    {"symbol": "LT.NS", "name": "Larsen & Toubro", "exchange": "NSE"},
    {"symbol": "WIPRO.NS", "name": "Wipro", "exchange": "NSE"},
    {"symbol": "TITAN.NS", "name": "Titan Company", "exchange": "NSE"},
    {"symbol": "ASIANPAINT.NS", "name": "Asian Paints", "exchange": "NSE"},
    {"symbol": "MARUTI.NS", "name": "Maruti Suzuki", "exchange": "NSE"},
    {"symbol": "SUNPHARMA.NS", "name": "Sun Pharmaceutical", "exchange": "NSE"},
    {"symbol": "NTPC.NS", "name": "NTPC Limited", "exchange": "NSE"},
    {"symbol": "AXISBANK.NS", "name": "Axis Bank", "exchange": "NSE"},
    {"symbol": "TATASTEEL.NS", "name": "Tata Steel", "exchange": "NSE"},
    {"symbol": "JSWSTEEL.NS", "name": "JSW Steel", "exchange": "NSE"},
    {"symbol": "ULTRACEMCO.NS", "name": "UltraTech Cement", "exchange": "NSE"},
    {"symbol": "HCLTECH.NS", "name": "HCL Technologies", "exchange": "NSE"},
    {"symbol": "TECHM.NS", "name": "Tech Mahindra", "exchange": "NSE"},
    {"symbol": "COALINDIA.NS", "name": "Coal India", "exchange": "NSE"},
    {"symbol": "HINDALCO.NS", "name": "Hindalco Industries", "exchange": "NSE"},
    {"symbol": "TATAMOTORS.NS", "name": "Tata Motors", "exchange": "NSE"},
    {"symbol": "M&M.NS", "name": "Mahindra & Mahindra", "exchange": "NSE"},
    {"symbol": "HEROMOTOCO.NS", "name": "Hero MotoCorp", "exchange": "NSE"},
    {"symbol": "EICHERMOT.NS", "name": "Eicher Motors", "exchange": "NSE"},
    {"symbol": "BRITANNIA.NS", "name": "Britannia Industries", "exchange": "NSE"},
    {"symbol": "NESTLEIND.NS", "name": "Nestle India", "exchange": "NSE"},
    {"symbol": "GRASIM.NS", "name": "Grasim Industries", "exchange": "NSE"},
    {"symbol": "CIPLA.NS", "name": "Cipla", "exchange": "NSE"},
    {"symbol": "DRREDDY.NS", "name": "Dr Reddy's Labs", "exchange": "NSE"},
    {"symbol": "APOLLOHOSP.NS", "name": "Apollo Hospitals", "exchange": "NSE"},
    {"symbol": "DIVISLAB.NS", "name": "Divi's Laboratories", "exchange": "NSE"},
    {"symbol": "SBILIFE.NS", "name": "SBI Life Insurance", "exchange": "NSE"},
    {"symbol": "HDFCLIFE.NS", "name": "HDFC Life Insurance", "exchange": "NSE"},
    {"symbol": "IOC.NS", "name": "Indian Oil Corporation", "exchange": "NSE"},
    {"symbol": "BPCL.NS", "name": "Bharat Petroleum", "exchange": "NSE"},
    {"symbol": "ADANIENT.NS", "name": "Adani Enterprises", "exchange": "NSE"},
    {"symbol": "ADANIPORTS.NS", "name": "Adani Ports & SEZ", "exchange": "NSE"},
    {"symbol": "DMART.NS", "name": "Avenue Supermarts (DMart)", "exchange": "NSE"},
    {"symbol": "POWERGRID.NS", "name": "Power Grid Corp", "exchange": "NSE"},
    {"symbol": "ONGC.NS", "name": "Oil & Natural Gas Corp", "exchange": "NSE"},
    {"symbol": "BAJAJFINSV.NS", "name": "Bajaj Finserv", "exchange": "NSE"},
]

class IndianStockClient:
    """Client for fetching Indian stock market data via Yahoo Finance."""

    def __init__(self):
        self.cache = RequestCache(ttl=10)

    def klines(self, symbol="^NSEI", interval="15m", period=None):
        yf_interval = INTERVAL_MAP.get(interval, "15m")
        if interval in ("1m", "5m"):
            period = period or "1d"
        elif interval in ("15m", "30m"):
            period = period or "5d"
        elif interval == "1h":
            period = period or "1mo"
        elif interval == "4h":
            period = period or "1mo"
        elif interval == "1d":
            period = period or "3mo"
        else:
            period = period or "5d"

        cache_key = f"in_klines:{symbol}:{interval}:{period}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            stock = yf.Ticker(symbol)
            df = stock.history(period=period, interval=yf_interval)
            if df.empty:
                raise RuntimeError(f"No data returned for {symbol}")

            if interval == "4h" and len(df) >= 4:
                df = df.resample('4h').agg({
                    'Open': 'first', 'High': 'max', 'Low': 'min',
                    'Close': 'last', 'Volume': 'sum',
                }).dropna()

            result = []
            for idx, row in df.iterrows():
                ts = int(idx.timestamp())
                result.append({
                    "time": ts,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                })
            result = [c for c in result if c["high"] > 0 and c["low"] > 0]
            if not result:
                raise RuntimeError(f"Invalid price data for {symbol}")
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            raise RuntimeError(f"Yahoo Finance error for {symbol}: {e}")

    def ticker_info(self, symbol="^NSEI"):
        cache_key = f"in_info:{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            stock = yf.Ticker(symbol)
            info = stock.info or {}
            result = {
                "name": info.get("longName", info.get("shortName", symbol)),
                "sector": info.get("sector", ""),
                "marketCap": info.get("marketCap", 0),
                "previousClose": info.get("previousClose", 0),
                "change": info.get("regularMarketChange", 0),
                "changePercent": info.get("regularMarketChangePercent", 0),
            }
            self.cache.set(cache_key, result)
            return result
        except Exception:
            return {"name": symbol, "sector": "", "marketCap": 0, "previousClose": 0}


class IndianLiquidityEngine:
    """Liquidity engine for Indian stocks using Yahoo Finance."""

    def __init__(self):
        self.client = IndianStockClient()
        self.swing = SwingPointDetector()
        self.ob_detector = OrderBlockDetector()
        self.fvg = FVGBalancer()
        self.sweep = LiquiditySweepDetector()
        self.vp = VolumeProfileAnalyzer()
        self.cvd = CVDAnalyzer()
        self.delta_patterns = DeltaPatternDetector()
        self.merger = LiquidityMerger()

    def search_stocks(self, query=""):
        """Search available Indian stocks by symbol or name."""
        if not query:
            return INDIAN_STOCKS[:20]
        q = query.lower().strip()
        results = []
        for s in INDIAN_STOCKS:
            if q in s["symbol"].lower() or q in s["name"].lower():
                results.append(s)
        return results[:20]

    def analyze(self, symbol="^NSEI", interval="15m", period=None):
        """Run full liquidity analysis on an Indian stock."""
        try:
            candles = self.client.klines(symbol, interval, period=period)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch Indian stock data: {e}")

        cp = (candles[-1]["high"] + candles[-1]["low"]) / 2 if candles else 0

        # Run all analyses
        swing_result = self.swing.detect(candles)
        ob_result = self.ob_detector.detect(candles)
        fvg_result = self.fvg.detect(candles)
        sweep_result = self.sweep.detect(candles)
        vpd = self.vp.calculate(candles)
        cvd_d = self.cvd.calculate(candles)
        delta_patterns = self.delta_patterns.detect(candles, cvd_d.get("perCandleDelta", []))

        # Collect all raw zones
        raw = []
        raw.extend(swing_result.get("zones", []))
        raw.extend(ob_result.get("zones", []))
        raw.extend(fvg_result.get("zones", []))
        raw.extend(sweep_result.get("zones", []))
        raw.extend(vpd.get("zones", []))

        # Merge and score
        merged = self.merger.merge(raw, threshold=0.0015)
        zones = self.merger.score_zones(merged, cp)

        # Get ticker info
        info = self.client.ticker_info(symbol)

        return {
            "symbol": symbol,
            "interval": interval,
            "currentPrice": cp,
            "timestamp": int(time.time()),
            "zones": zones[:25],
            "zoneCounts": {
                "support": len([z for z in zones if z["type"] == "support"]),
                "resistance": len([z for z in zones if z["type"] == "resistance"]),
                "total": min(len(zones), 25),
            },
            "marketSummary": {
                "totalBidLiquidity": 0,
                "totalAskLiquidity": 0,
                "imbalance": 0,
                "bidAskRatio": 0,
                "activeWalls": 0,
            },
            "info": info,
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
