"""P5-T4a: warnings surfaced end-to-end by execute_run (OQ-0072 resolved).

Fixture (hand-derived): 5 flat business-day bars @150 (2024-01-02..01-08),
entry `close > 10000` never fires for the ENGINE — wait, entry `close > 0`
always fires but capital 10 cannot afford a single share, so the engine
records zero-size skips (hand-built strings below) and NEVER trades:
equity stays flat at 10 => zero-variance Sharpe null, zero-drawdown Calmar
null, no-trade trade-metrics null; 5 sparse bars classify frequency
UNKNOWN => infer_frequency warning. The benchmark DOES enter (100% equity,
fractional) but its equity is also flat => its own null warnings, prefixed
``benchmark: `` by execute_run.
"""

from __future__ import annotations

import pandas as pd

from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.results import execute_run
from nlbt.spec.models import StrategySpec

FREQ_WARNING = "Could not infer frequency reliably. Consider using override_bars_per_year."

# Hand-built engine warnings (OQ-0061 message format, §4.5 rules):
ENGINE_WARNINGS = [
    "Entry skipped on 2024-01-03: computed size 0 (cash 10, fill price 150, "
    "fixed_fee 0); entry signal from 2024-01-02.",
    "Entry skipped on 2024-01-04: computed size 0 (cash 10, fill price 150, "
    "fixed_fee 0); entry signal from 2024-01-03.",
    "Entry skipped on 2024-01-05: computed size 0 (cash 10, fill price 150, "
    "fixed_fee 0); entry signal from 2024-01-04.",
    "Entry skipped on 2024-01-08: computed size 0 (cash 10, fill price 150, "
    "fixed_fee 0); entry signal from 2024-01-05.",
    "Entry signal on the last bar (bar 4) ignored: no next bar to fill the "
    "order at (§4.5 edge rule).",
]

METRIC_WARNINGS = [
    "Metric 'sharpe' is null: zero variance in bar returns (std=0) (§4.7 null+warning rule)",
    "Metric 'calmar' is null: zero drawdown (max_drawdown == 0) (§4.7 null+warning rule)",
    "Metric 'trade metrics' is null: no trades (win_rate, profit_factor, "
    "expectancy, avg_win, avg_loss, longest_losing_streak) "
    "(§4.7 null+warning rule)",
    FREQ_WARNING,
]


def _flat_bars() -> Bars:
    idx = pd.bdate_range("2024-01-02", periods=5)
    return Bars(
        pd.DataFrame(
            {
                "open": [150.0] * 5,
                "high": [151.0] * 5,
                "low": [149.0] * 5,
                "close": [150.0] * 5,
                "volume": [1_000_000.0] * 5,
            },
            index=idx,
        )
    )


def _spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "p5t4a-warnings",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {},
            "rules": {"entry_long": {"all": [{"left": "close", "op": ">", "right": 0}]}},
            "risk": {},
            "sizing": {
                "method": "fixed_shares",
                "value": 100.0,
                "allow_fractional": False,
            },
            "execution": {
                "fill": "next_open",
                "fee_bps": 0.0,
                "slippage_bps": 0.0,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": 10.0},
        }
    )


def test_execute_run_surfaces_all_warning_channels() -> None:
    """Final warnings: engine warnings first in order, then metric/trade/
    frequency warnings, benchmark ones prefixed ``benchmark: ``, exact
    duplicates dropped (order preserved)."""
    result = execute_run(_spec(), _flat_bars(), persist=False)
    final = result.warnings

    # engine warnings come first and keep their order
    assert final[: len(ENGINE_WARNINGS)] == ENGINE_WARNINGS
    # metric + trade + frequency warnings are surfaced
    for expected in METRIC_WARNINGS:
        assert expected in final, expected
    # benchmark warnings are prefixed
    benchmark_lines = [w for w in final if w.startswith("benchmark: ")]
    assert len(benchmark_lines) >= 3, benchmark_lines
    assert any("zero variance" in w for w in benchmark_lines)
    assert any("zero drawdown" in w for w in benchmark_lines)
    assert any(FREQ_WARNING in w for w in benchmark_lines)
    # exact duplicates dropped, order preserved
    assert len(final) == len(set(final)), final
    # and the null metrics themselves are null, never 0/NaN
    assert result.metrics["sharpe"] is None
    assert result.metrics["calmar"] is None
    assert result.metrics["num_trades"] == 0.0


def test_run_keeps_warnings_unchanged_and_exposes_metric_warnings() -> None:
    """Regression: run() itself is untouched — warnings are EXACTLY the
    engine list (OQ-0061 strings), metric warnings live in the new
    defaulted metric_warnings field."""
    result = run(_spec(), _flat_bars())
    assert result.warnings == ENGINE_WARNINGS  # exact, order included
    assert result.metric_warnings == METRIC_WARNINGS
    assert result.metric_warnings is not result.warnings
