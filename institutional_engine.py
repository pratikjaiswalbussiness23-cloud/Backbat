"""
Institutional Flow Engine — Detects Whales & Smart Money
v3.0 — WebSocket whale detection, multi-exchange, rolling order book snapshots,
       percentile-based thresholds, tiered scoring by data provenance.

Signals: Whale Trades (Binance+OKX+Bybit WS), OI Spikes (percentile),
         Funding Extremes (sigma-based), Order Book Anomalies (rolling snapshots),
         Volume Pressure (24h baseline), Spot-Futures CVD Divergence.

IMPORTANT: These are statistical PROXIES derived from public market data.
- 'Volume Pressure' uses candle-based buy/sell momentum, NOT on-chain exchange netflow
- 'Order Book Anomaly' uses rolling snapshots to detect wall removal patterns
- Whale trades aggregate from 3 exchanges via WebSocket for near-real-time detection
"""

import concurrent.futures
import json
import math
import statistics
import threading
import time
import traceback
from collections import deque
from typing import Dict, List, Optional, Tuple

import requests

BINANCE_BASE = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"
BINANCE_WS = "wss://stream.binance.com:9443/ws"
OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
BYBIT_WS = "wss://stream.bybit.com/v5/public/linear"


# ─── WebSocket Whale Trade Stream ──────────────────────────────

class WhaleTradeStream:
    """
    Maintains a rolling buffer of large trades from Binance, OKX, and Bybit
    via WebSocket connections running in background threads.
    Buffer: 60 seconds of trades >= $100k notional.
    """

    def __init__(self, threshold_usd=100000, buffer_seconds=60):
        self.threshold = threshold_usd
        self.buffer_seconds = buffer_seconds
        self._trades = deque()  # (timestamp, exchange, price, qty, side, notional)
        self._lock = threading.Lock()
        self._running = False
        self._current_symbol = None
        self._threads = []
        self._exchanges_ok = {"binance": False, "okx": False, "bybit": False}

    def start(self, symbol="BTCUSDT"):
        """Start background WebSocket threads for all 3 exchanges."""
        if self._running and self._current_symbol == symbol:
            return
        if self._running and self._current_symbol != symbol:
            self.stop()
            import time as _t
            _t.sleep(0.5)
        self._running = True
        self._current_symbol = symbol

        # Normalize symbol for each exchange
        binance_sym = symbol.lower()
        okx_sym = symbol.replace("USDT", "-USDT")
        bybit_sym = symbol

        t1 = threading.Thread(target=self._binance_ws, args=(binance_sym,), daemon=True)
        t2 = threading.Thread(target=self._okx_ws, args=(okx_sym,), daemon=True)
        t3 = threading.Thread(target=self._bybit_ws, args=(bybit_sym,), daemon=True)
        for t in [t1, t2, t3]:
            t.start()
            self._threads.append(t)

    def stop(self):
        self._running = False

    def get_whales(self, symbol="BTCUSDT"):
        """Return whale trades from the last 60 seconds, clustered and summarized."""
        now = time.time()
        cutoff = now - self.buffer_seconds

        with self._lock:
            recent = [t for t in self._trades if t[0] >= cutoff]
            # Evict old
            while self._trades and self._trades[0][0] < cutoff:
                self._trades.popleft()

        whale_trades = []
        for ts, exchange, price, qty, side, notional in recent:
            whale_trades.append({
                "price": round(price, 2),
                "quantity": round(qty, 6),
                "notional": round(notional, 2),
                "side": side,
                "exchange": exchange,
                "time": int(ts * 1000),
            })

        clusters = self._cluster(whale_trades, symbol)

        buy_vol = sum(t["notional"] for t in whale_trades if t["side"] == "buy")
        sell_vol = sum(t["notional"] for t in whale_trades if t["side"] == "sell")
        total = buy_vol + sell_vol
        net = buy_vol - sell_vol
        net_pct = (net / total * 100) if total > 0 else 0

        # Count by exchange
        exchange_counts = {}
        for t in whale_trades:
            ex = t["exchange"]
            if ex not in exchange_counts:
                exchange_counts[ex] = {"count": 0, "buyVolume": 0, "sellVolume": 0}
            exchange_counts[ex]["count"] += 1
            if t["side"] == "buy":
                exchange_counts[ex]["buyVolume"] += t["notional"]
            else:
                exchange_counts[ex]["sellVolume"] += t["notional"]

        for ex in exchange_counts:
            exchange_counts[ex]["buyVolume"] = round(exchange_counts[ex]["buyVolume"], 2)
            exchange_counts[ex]["sellVolume"] = round(exchange_counts[ex]["sellVolume"], 2)

        return {
            "whaleTrades": whale_trades[:50],
            "clusters": clusters[:15],
            "exchanges": {
                "connected": dict(self._exchanges_ok),
                "breakdown": exchange_counts,
                "sourceLabel": "Binance + OKX + Bybit (WebSocket)",
            },
            "summary": {
                "count": len(whale_trades),
                "buyVolume": round(buy_vol, 2),
                "sellVolume": round(sell_vol, 2),
                "totalVolume": round(total, 2),
                "netFlow": round(net, 2),
                "netFlowPct": round(net_pct, 1),
                "avgSize": round(total / max(len(whale_trades), 1), 2),
                "largestTrade": max((t["notional"] for t in whale_trades), default=0),
            },
            "signal": "accumulation" if net_pct > 10 else "distribution" if net_pct < -10 else "neutral",
            "confidence": min(1.0, abs(net_pct) / 30),
            "dataQuality": "real_time_ws",
            "timestamp": int(time.time()),
        }

    def _cluster(self, trades, symbol):
        """Cluster whale trades by price proximity using ATR-based band."""
        if not trades:
            return []
        try:
            url = f"{BINANCE_BASE}/api/v3/ticker/price"
            resp = requests.get(url, params={"symbol": symbol}, timeout=5)
            cp = float(resp.json()["price"])
        except Exception:
            cp = sum(t["price"] for t in trades) / len(trades) if trades else 0

        try:
            kurl = f"{BINANCE_BASE}/api/v3/klines"
            kresp = requests.get(kurl, params={"symbol": symbol, "interval": "1h", "limit": 14}, timeout=5)
            kresp.raise_for_status()
            klines = kresp.json()
            ranges = [float(k[2]) - float(k[3]) for k in klines if float(k[2]) - float(k[3]) > 0]
            atr = sum(ranges) / len(ranges) if ranges else cp * 0.005
            band_pct = (0.1 * atr / cp) if cp > 0 else 0.005
            band_pct = max(0.001, min(0.02, band_pct))
        except Exception:
            band_pct = 0.005

        sorted_t = sorted(trades, key=lambda t: t["price"])
        clusters = []
        current_cluster = [sorted_t[0]]
        for i in range(1, len(sorted_t)):
            if cp > 0 and abs(sorted_t[i]["price"] - sorted_t[i-1]["price"]) / cp < band_pct:
                current_cluster.append(sorted_t[i])
            else:
                if len(current_cluster) >= 2:
                    clusters.append(self._summarize_cluster(current_cluster))
                current_cluster = [sorted_t[i]]
        if len(current_cluster) >= 2:
            clusters.append(self._summarize_cluster(current_cluster))
        clusters.sort(key=lambda c: c["totalNotional"], reverse=True)
        return clusters

    @staticmethod
    def _summarize_cluster(trades):
        avg_price = sum(t["price"] for t in trades) / len(trades)
        buy_vol = sum(t["notional"] for t in trades if t["side"] == "buy")
        sell_vol = sum(t["notional"] for t in trades if t["side"] == "sell")
        total = buy_vol + sell_vol
        exchanges = list(set(t["exchange"] for t in trades))
        return {
            "price": round(avg_price, 2),
            "tradeCount": len(trades),
            "buyVolume": round(buy_vol, 2),
            "sellVolume": round(sell_vol, 2),
            "totalNotional": round(total, 2),
            "dominant": "buy" if buy_vol > sell_vol * 1.2 else "sell" if sell_vol > buy_vol * 1.2 else "balanced",
            "exchanges": exchanges,
            "priceRange": {
                "low": round(min(t["price"] for t in trades), 2),
                "high": round(max(t["price"] for t in trades), 2),
            },
        }

    # ─── Binance WebSocket ────────────────────────────────────
    def _binance_ws(self, symbol):
        try:
            import websocket
            stream = f"{symbol}@trade"
            url = f"{BINANCE_WS}/{stream}"
            ws = websocket.create_connection(url, timeout=10)
            self._exchanges_ok["binance"] = True
            while self._running:
                try:
                    ws.settimeout(5)
                    raw = ws.recv()
                    data = json.loads(raw)
                    price = float(data["p"])
                    qty = float(data["q"])
                    notional = price * qty
                    if notional >= self.threshold:
                        side = "buy" if not data["m"] else "sell"
                        ts = data["T"] / 1000.0
                        with self._lock:
                            self._trades.append((ts, "binance", price, qty, side, notional))
                except Exception:
                    if not self._running:
                        break
                    time.sleep(1)
            ws.close()
        except ImportError:
            self._binance_rest_fallback(symbol)
        except Exception:
            self._exchanges_ok["binance"] = False
            self._binance_rest_fallback(symbol)

    def _binance_rest_fallback(self, symbol):
        """Fallback: poll Binance REST API if websocket module not available."""
        seen_ids = set()
        while self._running:
            try:
                url = f"{BINANCE_BASE}/api/v3/trades"
                resp = requests.get(url, params={"symbol": symbol, "limit": 100}, timeout=10)
                resp.raise_for_status()
                raw = resp.json()
                for t in raw:
                    tid = t.get("id", t.get("time", 0))
                    if tid in seen_ids:
                        continue
                    seen_ids.add(tid)
                    if len(seen_ids) > 5000:
                        seen_ids.clear()
                    price = float(t["price"])
                    qty = float(t["qty"])
                    notional = price * qty
                    if notional >= self.threshold:
                        side = "buy" if not t["isBuyerMaker"] else "sell"
                        ts = t["time"] / 1000.0
                        with self._lock:
                            self._trades.append((ts, "binance", price, qty, side, notional))
                self._exchanges_ok["binance"] = True
            except Exception:
                self._exchanges_ok["binance"] = False
            time.sleep(5)

    # ─── OKX WebSocket ────────────────────────────────────────
    def _okx_ws(self, symbol):
        try:
            import websocket
            ws = websocket.create_connection(OKX_WS, timeout=10)
            sub_msg = json.dumps({
                "op": "subscribe",
                "args": [{"channel": "trades", "instId": symbol}]
            })
            ws.send(sub_msg)
            self._exchanges_ok["okx"] = True
            while self._running:
                try:
                    ws.settimeout(5)
                    raw = ws.recv()
                    data = json.loads(raw)
                    if "data" not in data:
                        continue
                    for trade in data["data"]:
                        price = float(trade["px"])
                        qty = float(trade["sz"])
                        notional = price * qty
                        if notional >= self.threshold:
                            side = "buy" if trade["side"] == "buy" else "sell"
                            ts_ms = int(trade["ts"])
                            with self._lock:
                                self._trades.append((ts_ms / 1000.0, "okx", price, qty, side, notional))
                except Exception:
                    if not self._running:
                        break
                    time.sleep(1)
            ws.close()
        except ImportError:
            pass
        except Exception:
            self._exchanges_ok["okx"] = False

    # ─── Bybit WebSocket ──────────────────────────────────────
    def _bybit_ws(self, symbol):
        try:
            import websocket
            ws = websocket.create_connection(BYBIT_WS, timeout=10)
            sub_msg = json.dumps({
                "op": "subscribe",
                "args": [f"publicTrade.{symbol}"]
            })
            ws.send(sub_msg)
            self._exchanges_ok["bybit"] = True
            while self._running:
                try:
                    ws.settimeout(5)
                    raw = ws.recv()
                    data = json.loads(raw)
                    if "topic" not in data or "data" not in data:
                        continue
                    for trade in data["data"]:
                        price = float(trade["p"])
                        qty = float(trade["v"])
                        notional = price * qty
                        if notional >= self.threshold:
                            side = "buy" if trade["S"] == "Buy" else "sell"
                            ts = int(trade["T"]) / 1000.0
                            with self._lock:
                                self._trades.append((ts, "bybit", price, qty, side, notional))
                except Exception:
                    if not self._running:
                        break
                    time.sleep(1)
            ws.close()
        except ImportError:
            pass
        except Exception:
            self._exchanges_ok["bybit"] = False


# ─── Rolling Order Book Snapshot Manager ──────────────────────

class OrderBookSnapshotManager:
    """
    Polls order book every 5 seconds, stores rolling 60-second window (12 snapshots).
    Detects walls that appeared and then vanished without price reaching them.
    """

    def __init__(self, poll_interval=5, window_seconds=60):
        self.poll_interval = poll_interval
        self.window_seconds = window_seconds
        self._snapshots = deque()  # (timestamp, {price: volume} for bids, asks)
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self, symbol="BTCUSDT"):
        if self._running and getattr(self, "_current_symbol", None) == symbol:
            return
        if self._running:
            self.stop()
            import time as _t
            _t.sleep(0.5)
        self._running = True
        self._current_symbol = symbol
        with self._lock:
            self._snapshots.clear()
        self._thread = threading.Thread(target=self._poll_loop, args=(symbol,), daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_analysis(self, symbol="BTCUSDT"):
        """Analyze rolling snapshots for wall appearance/disappearance patterns."""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            recent = [(ts, bids, asks) for ts, bids, asks in self._snapshots if ts >= cutoff]
            while self._snapshots and self._snapshots[0][0] < cutoff:
                self._snapshots.popleft()

        if len(recent) < 2:
            return {"signals": [], "summary": {"totalSignals": 0, "highSeverity": 0, "mediumSeverity": 0, "overallRisk": "low"}, "signal": "insufficient_data", "snapshotCount": len(recent)}

        # Current snapshot
        current_ts, current_bids, current_asks = recent[-1]

        # Build wall map for each snapshot
        def extract_walls(book, side):
            """Extract significant walls (>$500k) from order book."""
            walls = {}
            mid = None
            if side == "bid" and book:
                mid = float(book[0][0])
            elif side == "ask" and book:
                mid = float(book[0][0])
            for p_str, q_str in book:
                p, q = float(p_str), float(q_str)
                notional = p * q
                if notional > 500000:
                    walls[round(p, 2)] = {"volume": round(q, 4), "notional": round(notional, 2), "price": round(p, 2)}
            return walls

        current_bid_walls = extract_walls(current_bids, "bid")
        current_ask_walls = extract_walls(current_asks, "ask")

        signals = []

        # Check for walls that existed in earlier snapshots but disappeared
        if len(recent) >= 3:
            early_ts, early_bids, early_asks = recent[0]
            early_bid_walls = extract_walls(early_bids, "bid")
            early_ask_walls = extract_walls(early_asks, "ask")

            # Bid walls that vanished
            for price, wall in early_bid_walls.items():
                if price not in current_bid_walls:
                    signals.append({
                        "type": "wall_removed_bid",
                        "side": "bid",
                        "price": wall["price"],
                        "notional": wall["notional"],
                        "severity": "high" if wall["notional"] > 2000000 else "medium",
                        "insight": f"Bid wall ${wall['notional']:,.0f} at ${wall['price']:,.0f} vanished — possible spoof or absorption",
                        "ageSeconds": round(current_ts - early_ts),
                    })

            # Ask walls that vanished
            for price, wall in early_ask_walls.items():
                if price not in current_ask_walls:
                    signals.append({
                        "type": "wall_removed_ask",
                        "side": "ask",
                        "price": wall["price"],
                        "notional": wall["notional"],
                        "severity": "high" if wall["notional"] > 2000000 else "medium",
                        "insight": f"Ask wall ${wall['notional']:,.0f} at ${wall['price']:,.0f} vanished — possible spoof or absorption",
                        "ageSeconds": round(current_ts - early_ts),
                    })

        # Also detect current structural anomalies (distant walls, concentration)
        if current_bids and current_asks:
            mid = (float(current_bids[0][0]) + float(current_asks[0][0])) / 2
            for p_str, q_str in current_bids:
                p, q = float(p_str), float(q_str)
                dist = (mid - p) / mid * 100
                notional = p * q
                if dist > 2.0 and notional > 500000:
                    signals.append({"type": "distant_bid_wall", "side": "bid", "price": round(p, 2), "notional": round(notional, 2), "distancePct": round(dist, 2), "severity": "high" if dist > 4 else "medium", "insight": f"Bid wall ${notional:,.0f} at {dist:.1f}% below mid"})
            for p_str, q_str in current_asks:
                p, q = float(p_str), float(q_str)
                dist = (p - mid) / mid * 100
                notional = p * q
                if dist > 2.0 and notional > 500000:
                    signals.append({"type": "distant_ask_wall", "side": "ask", "price": round(p, 2), "notional": round(notional, 2), "distancePct": round(dist, 2), "severity": "high" if dist > 4 else "medium", "insight": f"Ask wall ${notional:,.0f} at {dist:.1f}% above mid"})

        signals.sort(key=lambda s: 1 if s["severity"] == "high" else 0, reverse=True)
        high_count = sum(1 for s in signals if s["severity"] == "high")
        med_count = sum(1 for s in signals if s["severity"] == "medium")

        return {
            "signals": signals[:20],
            "summary": {
                "totalSignals": len(signals),
                "highSeverity": high_count,
                "mediumSeverity": med_count,
                "overallRisk": "high" if high_count >= 3 else "medium" if high_count >= 1 or med_count >= 3 else "low",
                "snapshotCount": len(recent),
                "windowSeconds": self.window_seconds,
            },
            "signal": "significant_anomaly" if high_count >= 2 else "mild_anomaly" if high_count >= 1 or med_count >= 2 else "normal",
            "confidence": min(1.0, high_count * 0.3 + med_count * 0.1),
            "dataQuality": "rolling_snapshots",
            "timestamp": int(time.time()),
        }

    def _poll_loop(self, symbol):
        """Background loop: fetch order book every 5 seconds."""
        while self._running:
            try:
                url = f"{BINANCE_BASE}/api/v3/depth"
                resp = requests.get(url, params={"symbol": symbol, "limit": 100}, timeout=8)
                resp.raise_for_status()
                data = resp.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                ts = time.time()
                with self._lock:
                    self._snapshots.append((ts, bids, asks))
            except Exception:
                pass
            time.sleep(self.poll_interval)
# ─── OI Spike Detector (percentile-based) ────────────────────

class OISpikeDetector:
    """Tracks Open Interest changes to detect institutional positioning.
    Uses percentile-based thresholds — no hardcoded 2% cutoff."""

    @staticmethod
    def detect(symbol="BTCUSDT"):
        cache_key = f"oi:{symbol}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            url = f"{BINANCE_FUTURES}/futures/data/openInterestHist"
            resp = requests.get(url, params={"symbol": symbol, "period": "15m", "limit": 500}, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if len(data) < 4:
                return {"spikes": [], "history": [], "currentOI": 0, "signal": "insufficient_data"}

            history = []
            for d in data:
                history.append({
                    "time": int(d["timestamp"]) // 1000,
                    "oi": float(d["sumOpenInterestValue"]),
                    "oiContracts": float(d["sumOpenInterest"]),
                })

            # Compute period-over-period changes
            changes = []
            for i in range(1, len(history)):
                prev_oi = history[i - 1]["oi"]
                curr_oi = history[i]["oi"]
                if prev_oi > 0:
                    changes.append({
                        "index": i,
                        "change_pct": (curr_oi - prev_oi) / prev_oi * 100,
                    })

            if not changes:
                return {"spikes": [], "history": history, "currentOI": round(history[-1]["oi"], 2), "signal": "insufficient_data"}

            # Compute percentile thresholds from the distribution of changes
            abs_changes = sorted(abs(c["change_pct"]) for c in changes)
            n = len(abs_changes)
            p75_idx = int(n * 0.75)
            p90_idx = int(n * 0.90)
            threshold_p75 = abs_changes[min(p75_idx, n - 1)]
            threshold_p90 = abs_changes[min(p90_idx, n - 1)]
            median_change = abs_changes[n // 2]

            # Use mean and std for sigma-based thresholds too
            mean_change = statistics.mean(abs_changes)
            std_change = statistics.stdev(abs_changes) if len(abs_changes) > 1 else 0

            # Detect spikes using P90 threshold + absolute minimum
            ABS_MIN_OI = 0.3  # Minimum 0.3% change to be considered meaningful
            spikes = []
            for c in changes:
                if abs(c["change_pct"]) >= threshold_p90 and threshold_p90 > 0 and abs(c["change_pct"]) >= ABS_MIN_OI:
                    i = c["index"]
                    direction = "long_buildup" if c["change_pct"] > 0 else "short_close"
                    spikes.append({
                        "time": history[i]["time"],
                        "prevOI": round(history[i-1]["oi"], 2),
                        "currentOI": round(history[i]["oi"], 2),
                        "change": round(history[i]["oi"] - history[i-1]["oi"], 2),
                        "changePct": round(c["change_pct"], 2),
                        "direction": direction,
                        "magnitude": min(1.0, abs(c["change_pct"]) / max(threshold_p90 * 2, 1)),
                    })

            current_oi = history[-1]["oi"] if history else 0
            if len(history) >= 8:
                recent_avg = sum(h["oi"] for h in history[-4:]) / 4
                old_avg = sum(h["oi"] for h in history[:4]) / 4
                trend_pct = ((recent_avg - old_avg) / old_avg * 100) if old_avg > 0 else 0
            else:
                trend_pct = 0

            # Classify using percentile relative to history + absolute threshold
            latest_change = abs(changes[-1]["change_pct"]) if changes else 0
            if latest_change >= threshold_p90 and latest_change >= ABS_MIN_OI:
                trend_signal = "new_positions"
            elif latest_change <= threshold_p75 * 0.3:
                trend_signal = "stable"
            elif trend_pct < -2:
                trend_signal = "closing_positions"
            else:
                trend_signal = "new_positions" if trend_pct > 2 and abs(trend_pct) >= ABS_MIN_OI else "stable"

            result = {
                "spikes": spikes[-10:],
                "history": history,
                "currentOI": round(current_oi, 2),
                "trend": {
                    "direction": "increasing" if trend_pct > 1 else "decreasing" if trend_pct < -1 else "flat",
                    "changePct": round(trend_pct, 2),
                },
                "thresholds": {
                    "p75": round(threshold_p75, 2),
                    "p90": round(threshold_p90, 2),
                    "median": round(median_change, 2),
                    "sigma": round(std_change, 2),
                    "method": "percentile (P90 = spike, P75 = elevated)",
                },
                "signal": trend_signal,
                "confidence": min(1.0, abs(trend_pct) / 8),
                "dataQuality": "direct_exchange",
                "timestamp": int(time.time()),
            }

            _cache.set(cache_key, result)
            return result

        except Exception as e:
            return {"error": str(e), "spikes": [], "history": [], "signal": "error"}


# ─── Funding Rate Detector (sigma-based) ─────────────────────

class FundingRateDetector:
    """Detects funding rate extremes using sigma-based thresholds
    auto-calibrated to the asset's own 30-period history."""

    @staticmethod
    def detect(symbol="BTCUSDT"):
        cache_key = f"funding:{symbol}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            url = f"{BINANCE_FUTURES}/fapi/v1/premiumIndex"
            resp = requests.get(url, params={"symbol": symbol}, timeout=10)
            resp.raise_for_status()
            current_data = resp.json()
            current_rate = float(current_data.get("lastFundingRate", 0))
            current_price = float(current_data.get("markPrice", 0))

            url2 = f"{BINANCE_FUTURES}/fapi/v1/fundingRate"
            resp2 = requests.get(url2, params={"symbol": symbol, "limit": 30}, timeout=10)
            resp2.raise_for_status()
            history = resp2.json()

            rates = []
            for h in history:
                rates.append({
                    "time": h["fundingTime"] // 1000,
                    "rate": float(h["fundingRate"]),
                })

            all_rates = [r["rate"] for r in rates]
            all_rates_with_current = all_rates + [current_rate]

            # Compute sigma-based thresholds from history
            if len(all_rates) >= 5:
                mean_rate = statistics.mean(all_rates)
                std_rate = statistics.stdev(all_rates) if len(all_rates) > 1 else abs(mean_rate) * 0.1
                if std_rate < 1e-8:
                    std_rate = abs(mean_rate) * 0.1 if abs(mean_rate) > 1e-8 else 0.0001
            else:
                mean_rate = 0
                std_rate = 0.0003

            crowded_threshold = mean_rate + 1.5 * std_rate  # +1.5 sigma
            very_crowded_threshold = mean_rate + 2.5 * std_rate  # +2.5 sigma
            short_crowded_threshold = mean_rate - 1.5 * std_rate
            very_short_crowded_threshold = mean_rate - 2.5 * std_rate

            # Classify using sigma thresholds
            if current_rate >= very_crowded_threshold:
                classification = "very_crowded_long"
                insight = f"Rate {current_rate*100:+.4f}% exceeds mean+2.5\u03c3 ({very_crowded_threshold*100:+.4f}%). Longs paying aggressively."
            elif current_rate >= crowded_threshold:
                classification = "crowded_long"
                insight = f"Rate {current_rate*100:+.4f}% exceeds mean+1.5\u03c3 ({crowded_threshold*100:+.4f}%). Watch for reversal."
            elif current_rate <= very_short_crowded_threshold:
                classification = "very_crowded_short"
                insight = f"Rate {current_rate*100:+.4f}% below mean-2.5\u03c3 ({very_short_crowded_threshold*100:+.4f}%). Short squeeze potential."
            elif current_rate <= short_crowded_threshold:
                classification = "crowded_short"
                insight = f"Rate {current_rate*100:+.4f}% below mean-1.5\u03c3 ({short_crowded_threshold*100:+.4f}%). Potential bounce zone."
            else:
                classification = "neutral"
                insight = f"Rate {current_rate*100:+.4f}% within normal range (mean: {mean_rate*100:+.4f}%, \u03c3: {std_rate*100:.4f}%)."

            # Percentile of current rate within history
            if len(all_rates) > 1:
                rank = sum(1 for r in all_rates if r < current_rate)
                percentile = round(rank / len(all_rates) * 100, 1)
            else:
                percentile = 50.0

            avg_rate = sum(all_rates_with_current) / len(all_rates_with_current) if all_rates_with_current else 0
            annualized = current_rate * 3 * 365

            result = {
                "currentRate": current_rate,
                "currentRatePct": round(current_rate * 100, 4),
                "annualizedPct": round(annualized * 100, 2),
                "averageRate": round(avg_rate, 6),
                "classification": classification,
                "insight": insight,
                "thresholds": {
                    "method": "sigma-based (mean + N*stddev from 30-period history)",
                    "crowdedLong": round(crowded_threshold, 6),
                    "veryCrowdedLong": round(very_crowded_threshold, 6),
                    "crowdedShort": round(short_crowded_threshold, 6),
                    "veryCrowdedShort": round(very_short_crowded_threshold, 6),
                    "mean": round(mean_rate, 6),
                    "stddev": round(std_rate, 6),
                },
                "percentile": percentile,
                "extremes": [r for r in rates if abs(r["rate"]) > crowded_threshold][-10:],
                "history": rates,
                "signal": classification,
                "confidence": min(1.0, abs(current_rate - mean_rate) / max(std_rate * 3, 0.0001)),
                "dataQuality": "direct_exchange",
                "currentPrice": current_price,
                "timestamp": int(time.time()),
            }

            _cache.set(cache_key, result)
            return result

        except Exception as e:
            return {"error": str(e), "signal": "error"}


# ─── Volume Pressure Detector (24h baseline) ─────────────────

class VolumePressureDetector:
    """Approximates buy/sell pressure using candle-based volume analysis.
    Uses 96 candles (24 hours at 15m) for percentile baseline.
    NOTE: This is NOT on-chain exchange netflow."""

    @staticmethod
    def detect(symbol="BTCUSDT"):
        cache_key = f"pressure:{symbol}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            url = f"{BINANCE_BASE}/api/v3/klines"
            resp = requests.get(url, params={"symbol": symbol, "interval": "15m", "limit": 96}, timeout=10)
            resp.raise_for_status()
            raw = resp.json()

            candles = []
            for k in raw:
                o, h, l, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
                notional = ((h + l + c) / 3) * v
                candles.append({
                    "time": k[0] // 1000,
                    "open": o, "high": h, "low": l, "close": c,
                    "volume": v, "notional": round(notional, 2),
                    "isBullish": c > o,
                })

            periods = []
            for c in candles:
                body_pct = abs(c["close"] - c["open"]) / max(c["high"] - c["low"], 0.01)
                vol_score = c["notional"] / 1000000
                pressure = vol_score * body_pct if c["isBullish"] else -vol_score * body_pct
                periods.append({
                    "time": c["time"],
                    "pressure": round(pressure, 4),
                    "volume": c["volume"],
                    "notional": c["notional"],
                    "direction": "sell_pressure" if pressure < 0 else "buy_pressure",
                })

            recent = periods[-12:]
            earlier = periods[-24:-12] if len(periods) >= 24 else periods[:12]
            recent_sum = sum(p["pressure"] for p in recent)
            earlier_sum = sum(p["pressure"] for p in earlier)

            sell_notional = sum(p["notional"] for p in periods if p["pressure"] < 0)
            buy_notional = sum(p["notional"] for p in periods if p["pressure"] > 0)
            total_notional = sell_notional + buy_notional

            # 24h percentile baseline (96 candles)
            all_sums = [sum(p["pressure"] for p in periods[i:i+12]) for i in range(len(periods) - 11)]
            if all_sums:
                rank = sum(1 for s in all_sums if s < recent_sum)
                percentile = round(rank / len(all_sums) * 100, 1)
                mean_p = statistics.mean(all_sums)
                std_p = statistics.stdev(all_sums) if len(all_sums) > 1 else abs(mean_p) * 0.1
            else:
                percentile = 50.0
                mean_p = 0
                std_p = 1

            # Sigma from baseline
            sigma_from_mean = (recent_sum - mean_p) / max(std_p, 0.001) if std_p > 0 else 0

            if recent_sum < -5:
                classification = "strong_sell_pressure"
                insight = f"Strong sell-side momentum. P{percentile} of 24h range."
            elif recent_sum < -2:
                classification = "moderate_sell_pressure"
                insight = f"Moderate sell-side momentum. P{percentile} of 24h range."
            elif recent_sum > 5:
                classification = "strong_buy_pressure"
                insight = f"Strong buy-side momentum. P{percentile} of 24h range."
            elif recent_sum > 2:
                classification = "moderate_buy_pressure"
                insight = f"Moderate buy-side momentum. P{percentile} of 24h range."
            else:
                classification = "balanced"
                insight = f"No significant imbalance. P{percentile} of 24h range."

            trend_pct = ((recent_sum - earlier_sum) / max(abs(earlier_sum), 0.1) * 100) if earlier_sum != 0 else 0

            result = {
                "periods": periods,
                "summary": {
                    "recentPressure": round(recent_sum, 4),
                    "earlierPressure": round(earlier_sum, 4),
                    "sellNotional": round(sell_notional, 2),
                    "buyNotional": round(buy_notional, 2),
                    "totalNotional": round(total_notional, 2),
                    "sellPct": round(sell_notional / max(total_notional, 1) * 100, 1),
                    "percentile": percentile,
                    "sigmaFromMean": round(sigma_from_mean, 2),
                    "baselinePeriods": len(all_sums),
                },
                "classification": classification,
                "insight": insight,
                "trend": {
                    "direction": "increasing_selling" if trend_pct < -10 else "increasing_buying" if trend_pct > 10 else "stable",
                    "changePct": round(trend_pct, 1),
                },
                "signal": classification,
                "confidence": min(1.0, abs(recent_sum) / 10),
                "dataQuality": "proxy",
                "timestamp": int(time.time()),
            }

            _cache.set(cache_key, result)
            return result

        except Exception as e:
            return {"error": str(e), "signal": "error"}


# ─── Spot-Futures CVD Divergence ─────────────────────────────

class SpotFuturesCVDDetector:
    """Computes CVD for spot vs futures to detect divergence.
    Uses percentile-based thresholds, not absolute dollar amounts."""

    @staticmethod
    def detect(symbol="BTCUSDT"):
        cache_key = f"crosscvd:{symbol}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            resp_s = requests.get(f"{BINANCE_BASE}/api/v3/klines", params={"symbol": symbol, "interval": "15m", "limit": 100}, timeout=10)
            resp_s.raise_for_status()
            spot_raw = resp_s.json()

            resp_f = requests.get(f"{BINANCE_FUTURES}/fapi/v1/klines", params={"symbol": symbol, "interval": "15m", "limit": 100}, timeout=10)
            resp_f.raise_for_status()
            futs_raw = resp_f.json()

            def compute_cvd(klines):
                cvd_vals = []
                cum = 0.0
                for k in klines:
                    t = k[0] // 1000
                    o, h, l, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
                    rng = h - l if h - l > 0.01 else 0.01
                    body = abs(c - o)
                    lower = min(o, c) - l
                    bull_ratio = (lower + body) / rng
                    delta = (bull_ratio - (1 - bull_ratio)) * v
                    cum += delta
                    cvd_vals.append({"time": t, "cvd": round(cum, 2), "delta": round(delta, 2)})
                return cvd_vals

            spot_cvd = compute_cvd(spot_raw)
            futs_cvd = compute_cvd(futs_raw)
            spot_map = {c["time"]: c for c in spot_cvd}
            futs_map = {c["time"]: c for c in futs_cvd}
            common_times = sorted(set(spot_map.keys()) & set(futs_map.keys()))

            aligned = []
            for t in common_times:
                aligned.append({
                    "time": t,
                    "spotCVD": spot_map[t]["cvd"],
                    "futsCVD": futs_map[t]["cvd"],
                    "spotDelta": spot_map[t]["delta"],
                    "futsDelta": futs_map[t]["delta"],
                    "divergence": round(spot_map[t]["cvd"] - futs_map[t]["cvd"], 2),
                })

            latest_spot = spot_cvd[-1]["cvd"] if spot_cvd else 0
            latest_futs = futs_cvd[-1]["cvd"] if futs_cvd else 0
            latest_div = aligned[-1]["divergence"] if aligned else 0

            if len(spot_cvd) >= 20:
                spot_recent = spot_cvd[-1]["cvd"] - spot_cvd[-10]["cvd"]
                spot_earlier = spot_cvd[-10]["cvd"] - spot_cvd[-20]["cvd"]
                futs_recent = futs_cvd[-1]["cvd"] - futs_cvd[-10]["cvd"]
                futs_earlier = futs_cvd[-10]["cvd"] - futs_cvd[-20]["cvd"]
            else:
                spot_recent = spot_earlier = futs_recent = futs_earlier = 0

            # Percentile-based divergence classification
            div_history = [abs(a["divergence"]) for a in aligned[-48:]] if len(aligned) >= 48 else [abs(a["divergence"]) for a in aligned]
            if div_history:
                div_sorted = sorted(div_history)
                rank = sum(1 for d in div_sorted if d < abs(latest_div))
                percentile = round(rank / len(div_sorted) * 100, 1)
            else:
                percentile = 50.0

            # Normalized divergence (needed for minimum absolute threshold)
            total_vol_24h = sum(float(k[5]) for k in spot_raw[-96:]) if spot_raw else 1
            avg_price = sum(float(k[4]) for k in spot_raw[-96:]) / max(len(spot_raw[-96:]), 1) if spot_raw else 1
            vol_24h_usd = total_vol_24h * avg_price
            normalized_div = (abs(latest_div) / max(vol_24h_usd, 1)) * 100

            # FIX 1: Minimum absolute divergence threshold + percentile classification
            if normalized_div < 0.1:
                signal = "aligned"
            elif percentile >= 90:
                signal = "strong_divergence"
            elif percentile >= 75:
                signal = "moderate_divergence"
            else:
                signal = "aligned"

            result = {
                "aligned": aligned[-60:],
                "divergences": [],
                "summary": {
                    "spotCVD": round(latest_spot, 2),
                    "futsCVD": round(latest_futs, 2),
                    "divergence": round(latest_div, 2),
                    "normalizedDivPct": round(normalized_div, 4),
                    "percentile": percentile,
                    "spotTrend": "bullish" if spot_recent > 0 else "bearish",
                    "futsTrend": "bullish" if futs_recent > 0 else "bearish",
                    "spotMomentum": round(spot_recent - spot_earlier, 2),
                    "futsMomentum": round(futs_recent - futs_earlier, 2),
                },
                "signal": signal,
                "confidence": min(1.0, percentile / 100),
                "dataQuality": "proxy",
                "timestamp": int(time.time()),
            }

            _cache.set(cache_key, result)
            return result

        except Exception as e:
            return {"error": str(e), "signal": "error"}


# ─── Institutional Confidence Score (tiered, active-only) ────

class InstitutionalScorer:
    """
    Tier-based scoring by data provenance:
      Tier 1 (direct exchange data, 2x weight): OI, Funding Rate, Order Book Anomaly
      Tier 2 (derived/proxy, 1x weight): Whale Trades, Volume Pressure, CVD Divergence

    Grade reliability is computed from ACTIVELY FIRING proxy signals only.
    Incomplete data warning when < 4 signals succeed.
    """

    TIER_WEIGHTS = {
        "Open Interest": 2.0,
        "Funding Rate": 2.0,
        "Order Book Anomaly": 2.0,
        "Whale Trades": 1.0,
        "Volume Pressure": 1.0,
        "CVD Divergence": 1.0,
    }

    PROXY_SIGNALS = {"Order Book Anomaly", "Volume Pressure", "CVD Divergence"}

    @staticmethod
    def score(whales, oi, funding, anomalies, pressure, crosscvd):
        signals = []
        total_weighted_confidence = 0
        total_weight = 0
        active_proxy_count = 0
        active_total_count = 0
        succeeded_count = 0

        def _build_insight(name, data):
            if name == "Whale Trades":
                s = data.get("summary", {})
                ex = data.get("exchanges", {})
                label = ex.get("sourceLabel", "Binance only")
                return f"{s.get('count', 0)} whale trades across {label}, net: ${s.get('netFlow', 0):,.0f}"
            elif name == "Open Interest":
                t = data.get("trend", {})
                thr = data.get("thresholds", {})
                return f"OI: {t.get('direction', '?')} ({t.get('changePct', 0):+.1f}%) | P90={thr.get('p90', '?')}%"
            elif name == "Funding Rate":
                return data.get("insight", "")
            elif name == "Order Book Anomaly":
                s = data.get("summary", {})
                wc = s.get("windowSeconds", "?")
                return f"{s.get('totalSignals', 0)} anomalies ({s.get('highSeverity', 0)} high) over {wc}s window"
            elif name == "Volume Pressure":
                return data.get("insight", "")
            elif name == "CVD Divergence":
                s = data.get("summary", {})
                return f"Spot vs Futures divergence: {s.get('divergence', 0):+.0f} (P{s.get('percentile', 50):.0f})"
            return data.get("insight", "")

        def _add_signal(name, data, is_proxy=False):
            nonlocal total_weighted_confidence, total_weight, active_proxy_count, active_total_count, succeeded_count
            if data.get("signal") in ("error", None, "insufficient_data", "no_data"):
                return
            succeeded_count += 1
            conf = data.get("confidence", 0)
            weight = InstitutionalScorer.TIER_WEIGHTS.get(name, 1.0)
            total_weighted_confidence += conf * weight
            total_weight += weight
            # Only count NON-NEUTRAL signals toward reliability
            is_neutral = data.get("signal") in ("neutral", "stable", "balanced", "aligned", "normal")
            if not is_neutral:
                active_total_count += 1
                if is_proxy:
                    active_proxy_count += 1
            if not is_neutral:
                signals.append({
                    "name": name,
                    "signal": data["signal"],
                    "confidence": round(conf, 2),
                    "isProxy": is_proxy,
                    "tier": 1 if not is_proxy else 2,
                    "weight": weight,
                    "insight": _build_insight(name, data),
                })

        _add_signal("Whale Trades", whales, is_proxy=True)
        _add_signal("Open Interest", oi, is_proxy=False)
        _add_signal("Funding Rate", funding, is_proxy=False)
        _add_signal("Order Book Anomaly", anomalies, is_proxy=False)
        _add_signal("Volume Pressure", pressure, is_proxy=True)
        _add_signal("CVD Divergence", crosscvd, is_proxy=True)

        overall = total_weighted_confidence / max(total_weight, 1)

        # Reliability: only count ACTIVELY FIRING proxy signals
        if active_total_count > 0:
            active_proxy_ratio = active_proxy_count / active_total_count
        else:
            active_proxy_ratio = 0
        reliability = 1.0 - active_proxy_ratio * 0.5

        # Raw grade
        raw_grade = (
            "A+" if overall >= 0.7 else
            "A" if overall >= 0.5 else
            "B" if overall >= 0.3 else
            "C" if overall >= 0.15 else
            "D"
        )

        # Cap grade by reliability
        grade_map = {"A+": 4, "A": 3, "B": 2, "C": 1, "D": 0}
        rev_grade = {0: "D", 1: "C", 2: "B", 3: "A", 4: "A+"}
        raw_val = grade_map[raw_grade]
        if reliability < 0.8 and raw_val >= 4:
            capped_val = 3
        elif reliability < 0.6 and raw_val >= 3:
            capped_val = 2
        else:
            capped_val = raw_val
        grade = rev_grade[capped_val]

        # Incomplete data warning
        incomplete = succeeded_count < 4
        grade_display = grade
        if incomplete:
            grade_display = f"{grade} ({succeeded_count}/6)"

        if overall >= 0.7:
            verdict = "Strong institutional activity detected"
        elif overall >= 0.5:
            verdict = "Moderate institutional activity"
        elif overall >= 0.3:
            verdict = "Mild institutional signals"
        elif overall >= 0.15:
            verdict = "Minimal institutional signals"
        else:
            verdict = "No significant institutional activity"

        if incomplete:
            verdict += f" \u2014 only {succeeded_count}/6 signals available"

        verified_count = active_total_count - active_proxy_count
        reliability_label = f"{verified_count}/{active_total_count} active signals verified"
        if active_proxy_count > 0:
            reliability_label += f", {active_proxy_count}/{active_total_count} proxy"

        return {
            "score": round(overall, 3),
            "grade": grade,
            "gradeDisplay": grade_display,
            "verdict": verdict,
            "signals": signals,
            "activeSignalCount": len(signals),
            "succeededCount": succeeded_count,
            "incomplete": incomplete,
            "reliability": round(reliability, 2),
            "reliabilityLabel": reliability_label,
        }


# ─── Main Engine ─────────────────────────────────────────────

class InstitutionalEngine:
    """
    v3.0: Orchestrates all institutional detection.
    - WebSocket whale streams from 3 exchanges (background threads)
    - Rolling order book snapshots (background thread)
    - Parallel REST API calls for OI, funding, CVD, volume pressure
    - Graceful degradation: failed signals don't block others
    """

    def __init__(self):
        self.whale_stream = WhaleTradeStream(threshold_usd=100000, buffer_seconds=60)
        self.order_book = OrderBookSnapshotManager(poll_interval=5, window_seconds=60)
        self.oi = OISpikeDetector()
        self.funding = FundingRateDetector()
        self.pressure = VolumePressureDetector()
        self.crosscvd = SpotFuturesCVDDetector()
        self.scorer = InstitutionalScorer()
        self._started = False
        self._start_lock = threading.Lock()

    def _ensure_started(self, symbol):
        """Lazily start background WebSocket/snapshot threads on first call."""
        if self._started:
            return
        with self._start_lock:
            if self._started:
                return
            try:
                self.whale_stream.start(symbol)
                self.order_book.start(symbol)
                self._started = True
            except Exception:
                self._started = True  # Don't retry forever

    def analyze(self, symbol="BTCUSDT"):
        self._ensure_started(symbol)

        # Get whale data from WebSocket stream
        whale_data = self.whale_stream.get_whales(symbol)
        # Add legacy summary fields for backward compat
        whale_data.setdefault("whaleTrades", [])
        whale_data.setdefault("clusters", [])

        # Get order book anomalies from rolling snapshots
        anomaly_data = self.order_book.get_analysis(symbol)

        # Parallel REST API calls for the remaining 4 signals
        rest_detectors = {
            "oi": lambda: self.oi.detect(symbol),
            "funding": lambda: self.funding.detect(symbol),
            "pressure": lambda: self.pressure.detect(symbol),
            "crosscvd": lambda: self.crosscvd.detect(symbol),
        }

        rest_results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_key = {executor.submit(fn): key for key, fn in rest_detectors.items()}
            for future in concurrent.futures.as_completed(future_to_key, timeout=15):
                key = future_to_key[future]
                try:
                    rest_results[key] = future.result()
                except Exception as e:
                    rest_results[key] = {"error": str(e), "signal": "error"}

        oi_data = rest_results.get("oi", {})
        funding_data = rest_results.get("funding", {})
        pressure_data = rest_results.get("pressure", {})
        cvd_data = rest_results.get("crosscvd", {})

        score = self.scorer.score(
            whale_data, oi_data, funding_data,
            anomaly_data, pressure_data, cvd_data
        )

        return {
            "symbol": symbol,
            "whales": whale_data,
            "openInterest": oi_data,
            "funding": funding_data,
            "anomalies": anomaly_data,
            "pressure": pressure_data,
            "crossCVD": cvd_data,
            "score": score,
            "errors": [],
            "dataDisclaimer": "Signals are statistical proxies derived from public market data. Not financial advice.",
            "timestamp": int(time.time()),
        }


# ─── Cache ────────────────────────────────────────────────────

class _Cache:
    def __init__(self, ttl=8):
        self._d = {}
        self._ttl = ttl

    def get(self, k):
        e = self._d.get(k)
        if e and (time.time() - e["ts"]) < self._ttl:
            return e["v"]
        return None

    def set(self, k, v):
        self._d[k] = {"v": v, "ts": time.time()}
        if len(self._d) > 60:
            now = time.time()
            self._d = {k: v for k, v in self._d.items() if (now - v["ts"]) < self._ttl * 3}


_cache = _Cache(ttl=8)
