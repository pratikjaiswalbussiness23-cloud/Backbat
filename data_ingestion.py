"""
BACKBAT v3 -- Layer 1: Data Ingestion
Multi-Exchange CVD Aggregator, OI Delta, Funding Rate, Order Book
"""

import json
import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from config import DEFAULT_CONFIG

logger = logging.getLogger("backbat.data_ingestion")


class OrderBookSnapshot:
    """L2 order book snapshot with wall detection."""

    def __init__(self, exchange: str, price: float, bids: List[Tuple[float, float]],
                 asks: List[Tuple[float, float]], timestamp: float):
        self.exchange = exchange
        self.price = price
        self.bids = bids
        self.asks = asks
        self.timestamp = timestamp

    def find_walls(self, min_size: float = 10.0) -> Dict[str, list]:
        walls = {"bid_walls": [], "ask_walls": []}
        for p, s in self.bids:
            if s >= min_size:
                walls["bid_walls"].append({"price": p, "size": s})
        for p, s in self.asks:
            if s >= min_size:
                walls["ask_walls"].append({"price": p, "size": s})
        return walls

    def imbalance_ratio(self) -> float:
        bv = sum(s for _, s in self.bids) or 1
        av = sum(s for _, s in self.asks) or 1
        return (bv - av) / (bv + av)


class MultiExchangeCVD:
    """CVD aggregated across exchanges with timestamp alignment."""

    def __init__(self):
        self.exchanges: Dict[str, list] = {}

    def register(self, name: str):
        self.exchanges[name] = []

    def add_trade(self, exchange: str, ts: float, price: float, vol: float, buyer_agg: bool):
        if exchange not in self.exchanges:
            self.exchanges[exchange] = []
        delta = vol if buyer_agg else -vol
        self.exchanges[exchange].append({"ts": ts, "delta": delta, "buy": vol if buyer_agg else 0, "sell": vol if not buyer_agg else 0})
        cutoff = time.time() - 900
        self.exchanges[exchange] = [d for d in self.exchanges[exchange] if d["ts"] >= cutoff]

    def aggregate_cvd(self) -> float:
        return sum(sum(d["delta"] for d in hist) for hist in self.exchanges.values())

    def per_exchange_cvd(self) -> Dict[str, float]:
        return {n: sum(d["delta"] for d in h) for n, h in self.exchanges.items()}

    def detect_divergence(self, price_change_pct: float) -> Optional[str]:
        cvd = self.aggregate_cvd()
        if price_change_pct > 0.001 and cvd < 0:
            return "bearish"
        if price_change_pct < -0.001 and cvd > 0:
            return "bullish"
        return None


class OpenInterestTracker:
    """OI delta across exchanges."""

    def __init__(self):
        self.history: Dict[str, list] = defaultdict(list)

    def record(self, ex: str, oi: float, price: float, ts: float):
        self.history[ex].append({"oi": oi, "price": price, "ts": ts})
        if len(self.history[ex]) > 1000:
            self.history[ex] = self.history[ex][-1000:]

    def delta(self, ex: str, lookback: int = 20) -> float:
        h = self.history.get(ex, [])
        if len(h) < lookback + 1:
            return 0.0
        return h[-1]["oi"] - h[-(lookback + 1)]["oi"]

    def aggregate_delta(self, lookback: int = 20) -> float:
        return sum(self.delta(ex, lookback) for ex in self.history)


class FundingRateMonitor:
    """Funding rate tracking for crowded trade detection."""

    def __init__(self, extreme_threshold: float = 0.0008):
        self.threshold = extreme_threshold
        self.rates: Dict[str, list] = defaultdict(list)

    def record(self, ex: str, rate: float, ts: float):
        self.rates[ex].append({"rate": rate, "ts": ts})
        if len(self.rates[ex]) > 500:
            self.rates[ex] = self.rates[ex][-500:]

    def current(self, ex: str) -> float:
        h = self.rates.get(ex, [])
        return h[-1]["rate"] if h else 0.0

    def is_extreme(self, ex: str) -> bool:
        return abs(self.current(ex)) >= self.threshold

    def crowded_long(self, ex: str) -> bool:
        return self.current(ex) > self.threshold

    def crowded_short(self, ex: str) -> bool:
        return self.current(ex) < -self.threshold

    def aggregate_bias(self) -> float:
        vals = [self.current(ex) for ex in self.rates]
        return sum(vals) / len(vals) if vals else 0.0


class WallPersistenceTracker:
    """Spoof detection via wall persistence tracking."""

    def __init__(self, min_size: float = 10.0, persist_sec: int = 30, approach_pct: float = 0.001):
        self.min_size = min_size
        self.persist_sec = persist_sec
        self.approach_pct = approach_pct
        self.walls: Dict[str, dict] = {}

    def update(self, ex: str, bids: list, asks: list, price: float, now: float):
        active = set()
        for p, s in bids:
            if s >= self.min_size:
                k = f"{ex}:bid:{p}"
                active.add(k)
                if k in self.walls:
                    self.walls[k].update({"size": s, "last_seen": now})
                else:
                    self.walls[k] = {"ex": ex, "side": "bid", "price": p, "size": s, "first": now, "last": now}
        for p, s in asks:
            if s >= self.min_size:
                k = f"{ex}:ask:{p}"
                active.add(k)
                if k in self.walls:
                    self.walls[k].update({"size": s, "last_seen": now})
                else:
                    self.walls[k] = {"ex": ex, "side": "ask", "price": p, "size": s, "first": now, "last": now}
        expired = [k for k in self.walls if k not in active and (now - self.walls[k]["last"]) > 10]
        for k in expired:
            wall = self.walls[k]
            age = now - wall["first"]
            dist = abs(wall["price"] - price) / price
            if age >= self.persist_sec and dist <= self.approach_pct:
                logger.warning(f"SPOOF: {wall['side']} wall {wall['price']:.1f} vanished on approach")
            del self.walls[k]

    def real_walls(self, ex: str) -> list:
        now = time.time()
        return [w for w in self.walls.values() if w["ex"] == ex and (now - w["first"]) >= self.persist_sec]


class BinanceFetcher:
    """REST fetcher for Binance data."""

    BASE = "https://api.binance.com"

    def klines(self, symbol="BTCUSDT", interval="15m", limit=500, start=None, end=None):
        params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
        if start: params["startTime"] = str(start)
        url = f"{self.BASE}/api/v3/klines?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        candles = []
        for k in data:
            t = int(k[0]) // 1000
            candles.append({"time": t, "open": float(k[1]), "high": float(k[2]),
                            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
        return candles

    def open_interest(self, symbol="BTCUSDT"):
        url = f"{self.BASE}/fapi/v1/openInterest?symbol={symbol}"
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as r:
            return float(json.loads(r.read().decode()).get("openInterest", 0))

    def funding_rate(self, symbol="BTCUSDT"):
        url = f"{self.BASE}/fapi/v1/fundingRate?symbol={symbol}&limit=1"
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as r:
            data = json.loads(r.read().decode())
            return float(data[0]["fundingRate"]) if data else 0.0

    def order_book(self, symbol="BTCUSDT", limit=50):
        url = f"{self.BASE}/api/v3/depth?symbol={symbol}&limit={limit}"
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as r:
            d = json.loads(r.read().decode())
        bids = [(float(p), float(s)) for p, s in d["bids"]]
        asks = [(float(p), float(s)) for p, s in d["asks"]]
        mp = (bids[0][0] + asks[0][0]) / 2 if bids and asks else 0
        return {"bids": bids, "asks": asks, "price": mp, "ts": time.time()}


class DataIngestionLayer:
    """Layer 1 orchestrator: manages all data feeds."""

    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        self.cvd = MultiExchangeCVD()
        self.oi = OpenInterestTracker()
        self.funding = FundingRateMonitor(self.cfg.data_ingestion.funding_rate_extreme_threshold)
        self.walls = WallPersistenceTracker(
            self.cfg.detection_filter.spoof_wall_min_size_btc,
            self.cfg.detection_filter.spoof_persistence_seconds,
            self.cfg.detection_filter.spoof_approach_threshold_pct)
        self.binance = BinanceFetcher()
        for ex in self.cfg.active_exchanges:
            self.cvd.register(ex)
        self.latest = {"price": 0.0, "ob": None}

    def feed_ob(self, ex: str, bids: list, asks: list, price: float, ts: float) -> OrderBookSnapshot:
        snap = OrderBookSnapshot(ex, price, bids, asks, ts)
        self.walls.update(ex, bids, asks, price, ts)
        self.latest["ob"] = snap
        self.latest["price"] = price
        return snap

    def feed_trade(self, ex: str, ts: float, price: float, vol: float, buyer_agg: bool):
        self.cvd.add_trade(ex, ts, price, vol, buyer_agg)

    def feed_oi(self, ex: str, oi: float, price: float, ts: float):
        self.oi.record(ex, oi, price, ts)

    def feed_funding(self, ex: str, rate: float, ts: float):
        self.funding.record(ex, rate, ts)

    def snapshot(self) -> dict:
        ob = self.latest["ob"]
        return {
            "price": self.latest["price"],
            "cvd": {"aggregated": self.cvd.aggregate_cvd(), "per_exchange": self.cvd.per_exchange_cvd()},
            "oi_delta": {"aggregated": self.oi.aggregate_delta()},
            "funding": {
                "bias": self.funding.aggregate_bias(),
                "extreme": any(self.funding.is_extreme(e) for e in self.cfg.active_exchanges),
                "crowded_long": any(self.funding.crowded_long(e) for e in self.cfg.active_exchanges),
                "crowded_short": any(self.funding.crowded_short(e) for e in self.cfg.active_exchanges),
            },
            "ob_imbalance": ob.imbalance_ratio() if ob else 0,
            "real_walls": self.walls.real_walls("binance") if ob else [],
        }
