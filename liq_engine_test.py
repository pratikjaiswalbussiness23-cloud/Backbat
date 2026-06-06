"""
Liquidity Identifier Engine
Detects liquidity zones, order book clusters, volume profiles, and CVD.
"""

import json, math, time, requests, numpy as np
from typing import Dict, List, Optional, Tuple

BINANCE_BASE = "https://api.binance.com"

class BinanceClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LiquidityIdentifier/1.0"})
    
    def klines(self, symbol="BTCUSDT", interval="15m", limit=200):
        resp = self.session.get(f"{BINANCE_BASE}/api/v3/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        resp.raise_for_status()
        return [{"time": k[0]//1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in resp.json()]
    
    def depth(self, symbol="BTCUSDT", limit=100):
        resp = self.session.get(f"{BINANCE_BASE}/api/v3/depth", params={"symbol": symbol, "limit": limit}, timeout=10)
        resp.raise_for_status()
        d = resp.json()
        return {"bids": [[float(p),float(q)] for p,q in d["bids"]], "asks": [[float(p),float(q)] for p,q in d["asks"]]}
    
    def ticker_price(self, symbol="BTCUSDT"):
        resp = self.session.get(f"{BINANCE_BASE}/api/v3/ticker/price", params={"symbol": symbol}, timeout=10)
        resp.raise_for_status()
        return float(resp.json()["price"])

print("BinanceClient defined OK")
