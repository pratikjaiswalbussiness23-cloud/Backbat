"""
Algo Engine v1.0 - WebSocket Stream Manager
Binance REST polling with callback system.
"""
import json, time, threading, requests
from typing import Dict, List, Optional, Callable


class BinanceStream:
    def __init__(self, symbols=None, poll_interval=5):
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        self.poll_interval = poll_interval
        self._running = False
        self._thread = None
        self._prices = {}
        self._candles = {}
        self.callbacks: List[Callable] = []
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "AlgoEngine/1.0"})

    def add_callback(self, cb: Callable):
        self.callbacks.append(cb)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f"[Stream] Polling {len(self.symbols)} symbols every {self.poll_interval}s")

    def stop(self):
        self._running = False

    def get_latest_price(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol.upper())

    def get_latest_candles(self, symbol: str) -> List[Dict]:
        return self._candles.get(symbol.upper(), [])

    def _fetch_klines(self, symbol, interval="15m", limit=100):
        try:
            r = self.session.get("https://api.binance.com/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
            r.raise_for_status()
            return [{"time": k[0] // 1000, "open": float(k[1]), "high": float(k[2]),
                     "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in r.json()]
        except Exception as e:
            print(f"[Stream] Klines error {symbol}: {e}")
            return self._candles.get(symbol, [])

    def _fetch_price(self, symbol):
        try:
            r = self.session.get("https://api.binance.com/api/v3/ticker/price",
                params={"symbol": symbol}, timeout=5)
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception:
            return self._prices.get(symbol)

    def _poll_loop(self):
        while self._running:
            for symbol in self.symbols:
                candles = self._fetch_klines(symbol)
                price = self._fetch_price(symbol)
                if candles:
                    self._candles[symbol] = candles
                if price:
                    self._prices[symbol] = price
                if candles and self.callbacks:
                    p = price or (candles[-1]["high"] + candles[-1]["low"]) / 2
                    for cb in self.callbacks:
                        try:
                            cb(symbol, candles, p)
                        except Exception as e:
                            print(f"[Stream] CB error: {e}")
            time.sleep(self.poll_interval)

