"""
Liquidity-Based Backtesting Engine
Tests zone bounce and CVD divergence strategies on historical data
Uses free Binance API - no API keys required, fetches live data
"""

import json
import math
import sys
import time
from datetime import datetime, timezone

import numpy as np
import requests

BINANCE_BASE = "https://api.binance.com"


class DataFetcher:
    """Fetches historical klines from Binance free API (no API keys needed)."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LiquidityBT/1.0"})

    def fetch_klines(self, symbol, interval, limit=1000):
        """Fetch historical klines with pagination support."""
        all_candles = []
        remaining = limit
        end_time = None
        while remaining > 0:
            params = {"symbol": symbol, "interval": interval, "limit": min(500, remaining)}
            if end_time:
                params["endTime"] = end_time
            try:
                resp = self.session.get(f"{BINANCE_BASE}/api/v3/klines", params=params, timeout=15)
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                for k in batch:
                    all_candles.append({
                        "time": k[0] // 1000,
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    })
                remaining -= len(batch)
                end_time = batch[-1][0]
                if len(batch) < 500:
                    break
                time.sleep(0.15)
            except Exception as e:
                print(f"  Fetch error: {e}", file=sys.stderr)
                break
        return all_candles

    def fetch_order_book_snapshot(self, symbol):
        """Get current order book snapshot."""
        resp = self.session.get(
            f"{BINANCE_BASE}/api/v3/depth",
            params={"symbol": symbol, "limit": 20},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "bids": [[float(p), float(q)] for p, q in data["bids"]],
            "asks": [[float(p), float(q)] for p, q in data["asks"]],
        }



class ZoneDetector:
    """Detect liquidity zones from swing points, volume clusters, and CVD."""

    @staticmethod
    def detect_swing_zones(candles, lookback=5, lookforward=3):
        if len(candles) < lookback + lookforward + 1:
            return {"supports": [], "resistances": []}
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        swing_highs = []
        swing_lows = []
        for i in range(lookback, len(candles) - lookforward):
            is_high = all(highs[i] >= highs[i - j] for j in range(1, lookback + 1))
            is_high = is_high and all(highs[i] >= highs[i + j] for j in range(1, lookforward + 1))
            is_low = all(lows[i] <= lows[i - j] for j in range(1, lookback + 1))
            is_low = is_low and all(lows[i] <= lows[i + j] for j in range(1, lookforward + 1))
            if is_high:
                swing_highs.append({"index": i, "price": highs[i], "time": candles[i]["time"]})
            if is_low:
                swing_lows.append({"index": i, "price": lows[i], "time": candles[i]["time"]})
        return {"supports": swing_lows, "resistances": swing_highs}

    @staticmethod
    def cluster_zones(swing_zones, price_tolerance=0.002):
        """Merge swing points within price tolerance into weighted zones."""
        zones = []
        for zone_type, points in [("support", swing_zones["supports"]), ("resistance", swing_zones["resistances"])]:
            if not points:
                continue
            sorted_pts = sorted(points, key=lambda x: x["price"])
            current_cluster = [sorted_pts[0]]
            for p in sorted_pts[1:]:
                avg_price = sum(x["price"] for x in current_cluster) / len(current_cluster)
                if abs(p["price"] - avg_price) / avg_price <= price_tolerance:
                    current_cluster.append(p)
                else:
                    avg_p = sum(x["price"] for x in current_cluster) / len(current_cluster)
                    zones.append({"type": zone_type, "price": avg_p, "strength": len(current_cluster), "touches": len(current_cluster)})
                    current_cluster = [p]
            if current_cluster:
                avg_p = sum(x["price"] for x in current_cluster) / len(current_cluster)
                zones.append({"type": zone_type, "price": avg_p, "strength": len(current_cluster), "touches": len(current_cluster)})
        return zones

    @staticmethod
    def simulate_order_book_walls(candles, num_levels=10):
        """Simulate order book walls from volume profile on last 20 candles."""
        recent = candles[-50:] if len(candles) >= 50 else candles
        vp = {}
        for c in recent:
            price_range = np.linspace(c["low"], c["high"], num_levels)
            vol_per_level = c["volume"] / num_levels
            for p in price_range:
                rounded = round(p, 1)
                vp[rounded] = vp.get(rounded, 0) + vol_per_level
        sorted_prices = sorted(vp.keys())
        current_price = candles[-1]["close"]
        bid_walls = [{"price": p, "volume": vp[p]} for p in sorted_prices if p <= current_price]
        ask_walls = [{"price": p, "volume": vp[p]} for p in sorted_prices if p > current_price]
        return {"bid_walls": bid_walls[-20:] if len(bid_walls) > 20 else bid_walls, "ask_walls": ask_walls[:20] if len(ask_walls) > 20 else ask_walls}



class TradeEngine:
    """Simulates trades based on liquidity zone interactions.
    LONG: Price touches support zone + bullish divergence
    SHORT: Price touches resistance zone + bearish divergence
    """

    def __init__(self, atr_mult_sl=1.5, atr_mult_tp=3.0, risk_percent=0.02):
        self.atr_sl = atr_mult_sl
        self.atr_tp = atr_mult_tp
        self.risk_percent = risk_percent

    @staticmethod
    def calculate_atr(candles, period=14):
        if len(candles) < period + 1:
            return 0
        trs = []
        for i in range(len(candles) - period, len(candles)):
            h, l = candles[i]["high"], candles[i]["low"]
            pc = candles[i-1]["close"] if i > 0 else candles[i]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        return float(np.mean(trs))

    @staticmethod
    def compute_cvd_divergence(candles, lookback=12):
        """Compute CVD divergence signal. Negative = bearish, Positive = bullish."""
        if len(candles) < lookback * 2:
            return 0
        recent = candles[-lookback:]
        prev = candles[-(lookback*2):-lookback]
        cvd_recent = sum((c["close"] - c["open"]) * c["volume"] for c in recent)
        cvd_prev = sum((c["close"] - c["open"]) * c["volume"] for c in prev)
        price_change_recent = recent[-1]["close"] - recent[0]["close"]
        price_change_prev = prev[-1]["close"] - prev[0]["close"]
        if price_change_recent > 0 and cvd_recent < cvd_prev:
            return -1  # bearish divergence (price up, CVD down)
        if price_change_recent < 0 and cvd_recent > cvd_prev:
            return 1   # bullish divergence (price down, CVD up)
        return 0

    @staticmethod
    def is_touching_zone(price, zones, zone_type, threshold=0.003):
        """Check if price is touching a zone within threshold."""
        for z in zones:
            if z["type"] == zone_type:
                if abs(price - z["price"]) / z["price"] <= threshold:
                    return True, z
        return False, None

    def evaluate_candle(self, candles, zones, balance):
        """Evaluate the latest candle for trade signals."""
        if len(candles) < 30:
            return None
        latest = candles[-1]
        close = latest["close"]
        high = latest["high"]
        low = latest["low"]
        atr = self.calculate_atr(candles)
        if atr == 0:
            return None
        # Minimum ATR filter to avoid noise on small-move candles
        if atr < candles[-1]["close"] * 0.0005:
            return None
        cvd_div = self.compute_cvd_divergence(candles)
        touching_support, sup_zone = self.is_touching_zone(low, zones, "support")
        touching_resistance, res_zone = self.is_touching_zone(high, zones, "resistance")
        if touching_support and cvd_div == 1:
            sl = low - atr * self.atr_sl
            tp = close + atr * self.atr_tp
            pos_size = balance * self.risk_percent / (abs(close - sl) + 0.01)
            if pos_size < 0.0001:
                pos_size = 0.001
            return {"type": "long", "entry": close, "sl": sl, "tp": tp, "size": pos_size, "atr": atr, "zone_price": sup_zone["price"], "zone_strength": sup_zone["strength"]}
        if touching_resistance and cvd_div == -1:
            sl = high + atr * self.atr_sl
            tp = close - atr * self.atr_tp
            if tp >= sl:
                return None
            pos_size = balance * self.risk_percent / (abs(close - sl) + 0.01)
            if pos_size < 0.0001:
                pos_size = 0.001
            return {"type": "short", "entry": close, "sl": sl, "tp": tp, "size": pos_size, "atr": atr, "zone_price": res_zone["price"], "zone_strength": res_zone["strength"]}
        return None

    @staticmethod
    def simulate_trade(trade, future_candles):
        """Simulate a trade against future candles to see if SL or TP is hit first."""
        for c in future_candles:
            if trade["type"] == "long":
                if c["low"] <= trade["sl"]:
                    exit_price = trade["sl"]
                    return {"exit": exit_price, "result": "loss", "bars_held": future_candles.index(c) + 1}
                if c["high"] >= trade["tp"]:
                    exit_price = trade["tp"]
                    return {"exit": exit_price, "result": "win", "bars_held": future_candles.index(c) + 1}
            else:
                if c["high"] >= trade["sl"]:
                    exit_price = trade["sl"]
                    return {"exit": exit_price, "result": "loss", "bars_held": future_candles.index(c) + 1}
                if c["low"] <= trade["tp"]:
                    exit_price = trade["tp"]
                    return {"exit": exit_price, "result": "win", "bars_held": future_candles.index(c) + 1}
        last = future_candles[-1]
        exit_price = last["close"]
        if trade["type"] == "long":
            result = "win" if exit_price > trade["entry"] else "loss"
        else:
            result = "win" if exit_price < trade["entry"] else "loss"
        return {"exit": exit_price, "result": result, "bars_held": len(future_candles)}



class BacktestRunner:
    """Orchestrates the full backtest across multiple symbols and timeframes."""

    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.zone_detector = ZoneDetector()
        self.trade_engine = TradeEngine()

    def run_single(self, symbol, interval, max_candles=1000, hold_candles=20):
        """Run backtest for a single symbol + interval combination."""
        candles = self.data_fetcher.fetch_klines(symbol, interval, limit=max_candles)
        if len(candles) < 100:
            return {"symbol": symbol, "interval": interval, "error": "Not enough data", "trades": [], "total_trades": 0}

        trades = []
        balance = 10000.0
        initial_balance = balance
        peak_balance = balance
        low_balance = balance
        min_window = 60
        in_position = False

        for i in range(min_window, len(candles) - hold_candles - 1):
            if in_position:
                continue
            window = candles[:i+1]
            future = candles[i+1:i+1+hold_candles]
            swing_zones = self.zone_detector.detect_swing_zones(window)
            zones = self.zone_detector.cluster_zones(swing_zones)
            signal = self.trade_engine.evaluate_candle(window, zones, balance)
            if signal is None:
                continue
            in_position = True
            result = self.trade_engine.simulate_trade(signal, future)
            if signal["type"] == "long":
                pnl = signal["size"] * (result["exit"] - signal["entry"])
            else:
                pnl = signal["size"] * (signal["entry"] - result["exit"])
            pnl_pct = pnl / balance
            balance += pnl
            in_position = False
            if balance > peak_balance:
                peak_balance = balance
            if balance < low_balance:
                low_balance = balance
            trades.append({
                "time": candles[i]["time"],
                "type": signal["type"],
                "entry": signal["entry"],
                "exit": result["exit"],
                "result": result["result"],
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "atr": signal["atr"],
                "zone_strength": signal["zone_strength"],
                "bars_held": result["bars_held"],
                "balance": balance
            })

        total_pnl = balance - initial_balance
        total_pnl_pct = (balance / initial_balance - 1) * 100
        wins = [t for t in trades if t["result"] == "win"]
        losses = [t for t in trades if t["result"] == "loss"]
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        gross_profit = sum(t["pnl"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0)
        dd = max(0, (peak_balance - low_balance) / peak_balance * 100)
        returns = [t["pnl_pct"] for t in trades]
        avg_return = np.mean(returns) if returns else 0
        std_return = np.std(returns) if len(returns) > 1 else 0.001
        sharpe = (avg_return / std_return) * np.sqrt(len(returns)) if std_return > 0 else 0

        return {
            "symbol": symbol,
            "interval": interval,
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown_pct": dd,
            "sharpe_ratio": sharpe,
            "final_balance": balance,
            "trades": trades
        }

    def run_multi(self, configs):
        """Run backtest across multiple symbol/interval combinations."""
        results = []
        for cfg in configs:
            print(f"  Running {cfg['symbol']} {cfg['interval']}...")
            try:
                result = self.run_single(cfg["symbol"], cfg["interval"], cfg.get("candles", 1000), cfg.get("hold", 20))
                results.append(result)
                print(f"    -> {result['total_trades']} trades, Win rate: {result['win_rate']:.1f}%, PnL: {result['total_pnl_pct']:.2f}%")
            except Exception as e:
                print(f"    -> ERROR: {e}")
                results.append({"symbol": cfg["symbol"], "interval": cfg["interval"], "error": str(e), "total_trades": 0})
            time.sleep(0.5)
        return results

    def print_summary(self, results):
        """Print a formatted summary of all backtest results."""
        print("\n" + "="*80)
        print("  LIQUIDITY BACKTEST RESULTS SUMMARY")
        print("="*80)
        total_trades = 0
        total_wins = 0
        total_losses = 0
        combined_pnl = 0
        for r in results:
            if r.get("error"):
                print(f"  {r['symbol']:10s} {r['interval']:5s} | ERROR: {r['error']}")
                continue
            total_trades += r["total_trades"]
            total_wins += r["wins"]
            total_losses += r["losses"]
            combined_pnl += r["total_pnl"]
            bars = "#" * int(r["win_rate"] / 5) if r["win_rate"] > 0 else ""
            print(f"  {r['symbol']:10s} {r['interval']:5s} | {r['total_trades']:4d} trades | Win: {r['win_rate']:5.1f}% {bars:20s} | PnL: {r['total_pnl_pct']:+7.2f}% | PF: {r['profit_factor']:5.2f} | Sharpe: {r['sharpe_ratio']:5.2f} | DD: {r['max_drawdown_pct']:5.1f}%")
        overall_win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0
        print("-"*80)
        print(f"  COMBINED: {total_trades:4d} trades | Win: {overall_win_rate:5.1f}% | Total PnL: ${combined_pnl:+.2f}")
        print("="*80)
        print()


def main():
    print("="*80)
    print("  LIQUIDITY BACKTEST ENGINE")
    print("  Analyzing zone bounce + CVD divergence strategy across markets")
    print("="*80)
    print()

    configs = [
        # Major pairs on multiple timeframes
        {"symbol": "BTCUSDT", "interval": "15m", "candles": 1000, "hold": 30},
        {"symbol": "BTCUSDT", "interval": "1h", "candles": 1000, "hold": 48},
        {"symbol": "ETHUSDT", "interval": "15m", "candles": 1000, "hold": 30},
        {"symbol": "ETHUSDT", "interval": "1h", "candles": 1000, "hold": 48},
        {"symbol": "SOLUSDT", "interval": "15m", "candles": 1000, "hold": 30},
        {"symbol": "SOLUSDT", "interval": "1h", "candles": 1000, "hold": 48},
        {"symbol": "BNBUSDT", "interval": "15m", "candles": 1000, "hold": 30},
        {"symbol": "BNBUSDT", "interval": "1h", "candles": 1000, "hold": 48},
    ]

    runner = BacktestRunner()
    results = runner.run_multi(configs)
    runner.print_summary(results)

    # Write detailed results to file
    with open("liq_backtest_results.json", "w") as f:
        serializable = []
        for r in results:
            entry = {k: v for k, v in r.items() if k != "trades"}
            entry["trades"] = r.get("trades", [])[:10]  # First 10 trades for inspection
            serializable.append(entry)
        json.dump(serializable, f, indent=2, default=str)
    print(f"Detailed results written to liq_backtest_results.json")


if __name__ == "__main__":
    main()
