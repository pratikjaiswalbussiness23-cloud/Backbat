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
)
