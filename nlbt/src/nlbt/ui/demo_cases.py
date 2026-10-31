"""Stable prompts and StrategySpec payloads used by the offline demo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["DEMO_CASES", "DemoCase"]


@dataclass(frozen=True)
class DemoCase:
    prompt: str
    title: str
    status: str
    spec: dict[str, Any] | None = None
    questions: tuple[dict[str, str], ...] = ()
    unsupported: tuple[str, ...] = ()


START = "2024-01-02"
END = "2025-12-31"

DEMO_CASES: tuple[DemoCase, ...] = (
    DemoCase(
        title="SMA 50/200 crossover",
        prompt=(
            "Buy SPY when the 50-day SMA crosses above the 200-day SMA, and sell when "
            "the 50-day SMA crosses below the 200-day SMA, from 2024-01-02 to 2025-12-31."
        ),
        status="ok",
        spec={
            "spec_version": "1.0",
            "name": "SPY SMA 50/200 crossover",
            "universe": {"symbols": ["SPY"], "interval": "1d"},
            "period": {"start": START, "end": END},
            "indicators": {
                "fast": {"type": "sma", "params": {"period": 50}, "source": "close"},
                "slow": {"type": "sma", "params": {"period": 200}, "source": "close"},
            },
            "rules": {
                "entry_long": {
                    "all": [
                        {
                            "left": {"name": "fast"},
                            "op": "crosses_above",
                            "right": {"name": "slow"},
                        }
                    ]
                },
                "exit_long": {
                    "all": [
                        {
                            "left": {"name": "fast"},
                            "op": "crosses_below",
                            "right": {"name": "slow"},
                        }
                    ]
                },
            },
            "sizing": {"method": "percent_of_equity", "value": 100.0},
            "capital": {"initial": 100000.0},
        },
    ),
    DemoCase(
        title="RSI mean reversion with stop",
        prompt=(
            "Buy SPY when RSI(14) is below 30, sell when RSI(14) is above 70, and use a "
            "5% stop loss from 2024-01-02 to 2025-12-31."
        ),
        status="ok",
        spec={
            "spec_version": "1.0",
            "name": "SPY RSI 14 mean reversion",
            "universe": {"symbols": ["SPY"], "interval": "1d"},
            "period": {"start": START, "end": END},
            "indicators": {"rsi": {"type": "rsi", "params": {"period": 14}, "source": "close"}},
            "rules": {
                "entry_long": {"all": [{"left": {"name": "rsi"}, "op": "<", "right": 30.0}]},
                "exit_long": {"all": [{"left": {"name": "rsi"}, "op": ">", "right": 70.0}]},
            },
            "risk": {"stop_loss_pct": 5.0},
            "sizing": {"method": "percent_of_equity", "value": 100.0},
            "capital": {"initial": 100000.0},
        },
    ),
    DemoCase(
        title="20-day high breakout",
        prompt=(
            "Buy SPY when it closes above its previous 20-day high and use an 8% trailing "
            "stop, from 2024-01-02 to 2025-12-31."
        ),
        status="ok",
        spec={
            "spec_version": "1.0",
            "name": "SPY 20-day high breakout",
            "universe": {"symbols": ["SPY"], "interval": "1d"},
            "period": {"start": START, "end": END},
            "indicators": {
                "prior_high": {
                    "type": "highest",
                    "params": {"period": 20},
                    "source": "high",
                }
            },
            "rules": {
                "entry_long": {
                    "all": [{"left": "close", "op": ">", "right": {"name": "prior_high", "lag": 1}}]
                }
            },
            "risk": {"trailing_stop_pct": 8.0},
            "sizing": {"method": "percent_of_equity", "value": 100.0},
            "capital": {"initial": 100000.0},
        },
    ),
    DemoCase(
        title="Ambiguous moving averages",
        prompt="Buy SPY when the moving averages cross.",
        status="needs_clarification",
        questions=(
            {
                "id": "indicator_period_missing",
                "question": "Which moving-average lengths should cross (for example 50 and 200)?",
            },
        ),
    ),
    DemoCase(
        title="Unsupported options and sentiment",
        prompt="Buy SPY call options before earnings when sentiment is bullish.",
        status="unsupported",
        unsupported=("options", "earnings events", "sentiment analysis"),
    ),
    # New interval-aware strategy templates:
    DemoCase(
        title="Connors RSI-2 Pullback above 200 SMA",
        prompt=(
            "Buy SPY when RSI(2) is below 10 and close is above SMA(200), "
            "exit on RSI(2) above 70, 5% stop loss, 10-bar max hold, from 2024-01-02 to 2025-12-31."
        ),
        status="ok",
        spec={
            "spec_version": "1.0",
            "name": "SPY Connors RSI-2 Pullback",
            "universe": {"symbols": ["SPY"], "interval": "1d"},
            "period": {"start": START, "end": END},
            "indicators": {
                "rsi2": {"type": "rsi", "params": {"period": 2}, "source": "close"},
                "slow": {"type": "sma", "params": {"period": 200}, "source": "close"},
            },
            "rules": {
                "entry_long": {
                    "all": [
                        {"left": {"name": "rsi2"}, "op": "<", "right": 10.0},
                        {"left": {"name": "slow"}, "op": ">", "right": {"name": "close"}},
                    ]
                },
                "exit_long": {"all": [{"left": {"name": "rsi2"}, "op": ">", "right": 70.0}]},
            },
            "risk": {"stop_loss_pct": 5.0},
            "sizing": {"method": "percent_of_equity", "value": 100.0},
            "capital": {"initial": 100000.0},
        },
    ),
    DemoCase(
        title="Lower BB Reclaim + ROC Slope + ATR Floor",
        prompt=(
            "Buy SPY when low <= BB lower AND close > BB lower AND ROC(3) > -2, "
            "exit when close >= BB middle, 2% stop 5% target 3-bar max hold, "
            "from 2024-01-02 to 2025-12-31."
        ),
        status="ok",
        spec={
            "spec_version": "1.0",
            "name": "SPY Lower BB Reclaim + ROC + ATR",
            "universe": {"symbols": ["SPY"], "interval": "1d"},
            "period": {"start": START, "end": END},
            "indicators": {
                "bb": {"type": "bbands", "params": {"period": 20, "std": 2.0}, "source": "close"},
                "roc3": {"type": "roc", "params": {"period": 3}, "source": "close"},
                "atr14": {"type": "atr", "params": {"period": 14}, "source": "close"},
            },
            "rules": {
                "entry_long": {
                    "all": [
                        {"left": {"name": "bb"}, "op": "<=", "right": {"name": "bb.lower"}},
                        {"left": {"name": "close"}, "op": ">", "right": {"name": "bb.lower"}},
                        {"left": {"name": "roc3"}, "op": ">", "right": -2.0},
                    ]
                },
                "exit_long": {
                    "all": [{"left": {"name": "close"}, "op": ">=", "right": {"name": "bb.middle"}}]
                },
            },
            "risk": {"stop_loss_pct": 2.0, "take_profit_pct": 5.0},
            "sizing": {"method": "percent_of_equity", "value": 100.0},
            "capital": {"initial": 100000.0},
        },
    ),
    DemoCase(
        title="Wilder ADX +DI/-DI Crossover",
        prompt=(
            "Buy SPY when ADX +DI crosses above -DI AND ADX(14) > 20, "
            "exit on 5% stop loss, from 2024-01-02 to 2025-12-31."
        ),
        status="ok",
        spec={
            "spec_version": "1.0",
            "name": "SPY ADX +DI/-DI Crossover",
            "universe": {"symbols": ["SPY"], "interval": "1d"},
            "period": {"start": START, "end": END},
            "indicators": {
                "adx": {"type": "adx", "params": {"period": 14}, "source": "close"},
            },
            "rules": {
                "entry_long": {
                    "all": [
                        {
                            "left": {"name": "adx.plus_di"},
                            "op": "crosses_above",
                            "right": {"name": "adx.minus_di"},
                        },
                        {"left": {"name": "adx.adx"}, "op": ">", "right": 20.0},
                    ]
                }
            },
            "risk": {"stop_loss_pct": 5.0},
            "sizing": {"method": "percent_of_equity", "value": 100.0},
            "capital": {"initial": 100000.0},
        },
    ),
    DemoCase(
        title="MACD Histogram + 50 EMA Trend",
        prompt=(
            "Buy SPY when MACD histogram crosses above 0 AND close > EMA(50), "
            "exit when MACD histogram crosses below 0, 4% stop 10% target, "
            "from 2024-01-02 to 2025-12-31."
        ),
        status="ok",
        spec={
            "spec_version": "1.0",
            "name": "SPY MACD Histogram + EMA 50",
            "universe": {"symbols": ["SPY"], "interval": "1d"},
            "period": {"start": START, "end": END},
            "indicators": {
                "macd": {
                    "type": "macd",
                    "params": {"fast": 12, "signal": 9, "slow": 26},
                    "source": "close",
                },
                "ema50": {"type": "ema", "params": {"period": 50}, "source": "close"},
            },
            "rules": {
                "entry_long": {
                    "all": [
                        {"left": {"name": "macd.hist"}, "op": ">", "right": 0},
                        {"left": {"name": "close"}, "op": ">", "right": {"name": "ema50"}},
                    ]
                },
                "exit_long": {"all": [{"left": {"name": "macd.hist"}, "op": "<", "right": 0}]},
            },
            "risk": {"stop_loss_pct": 4.0, "take_profit_pct": 10.0},
            "sizing": {"method": "percent_of_equity", "value": 100.0},
            "capital": {"initial": 100000.0},
        },
    ),
)
