"""P5-T3 benchmark (§4.7 / ROADMAP P5-T3): buy-and-hold via the same engine.

SC2's construction (test_engine_scenarios.py) is COPIED here — no private
test helper imports. Every expected value is hand-derived from SC2's own
arithmetic (OQ-0050-resolved chain), shown in the docstrings.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.engine.benchmark import compute_benchmark
from nlbt.spec.models import StrategySpec

# SC2 fixture: closes = opens = [100, 101, 102, 103, 104, 105],
# capital 10000, fee 5 bps, slippage 5 bps, 100% equity, fractional shares.
#
# SC2 hand chain (test_engine_scenarios.py docstring, OQ-0050 resolution):
#   shares    = 10000 / (101.0505 * 1.0005) = 98.910965297...
#   final cash (forced close at 105) = 10375.2683  (net_pnl 375.2683)
#   total_return = 10375.2683 / 10000 - 1 = 0.03752683
SC2_CLOSES = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
SC2_TOTAL_RETURN = 0.03752683  # 10375.2683/10000 - 1, from SC2's hand chain


def _bars(closes: list[float]) -> Bars:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="utc")
    return Bars(
        pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1.0 for c in closes],
                "low": [c - 1.0 for c in closes],
                "close": closes,
                "volume": [1000.0] * len(closes),
            },
            index=idx,
        )
    )


def _spec(
    *,
    entry: dict,
    exit_long: dict | None = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    fixed_fee: float = 0.0,
    capital: float = 10_000.0,
) -> StrategySpec:
    """SC2's spec shape, copied from test_engine_scenarios.SC2."""
    rules: dict = {"entry_long": entry}
    if exit_long is not None:
        rules["exit_long"] = exit_long
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "p5t3-benchmark",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {},
            "rules": rules,
            "risk": {},
            "sizing": {
                "method": "percent_of_equity",
                "value": 100.0,
                "allow_fractional": True,
            },
            "execution": {
                "fill": "next_open",
                "fee_bps": fee_bps,
                "slippage_bps": slippage_bps,
                "fixed_fee": fixed_fee,
            },
            "capital": {"initial": capital},
        }
    )


ALWAYS_LONG = {"all": [{"left": "close", "op": ">", "right": 0}]}


def test_benchmark_matches_sc2_hand_chain() -> None:
    """P5-T3 accept: benchmark total_return == 10375.2683/10000 - 1;
    round-trip final value == 10375.2683 (SC2's end-of-data net cash)."""
    spec = _spec(entry=ALWAYS_LONG)
    metrics, warnings = compute_benchmark(spec, _bars(SC2_CLOSES))
    assert metrics["total_return"] == pytest.approx(SC2_TOTAL_RETURN, abs=1e-7)
    # round-trip: 10000 * (1 + 0.03752683) = 10375.2683
    final = 10_000.0 * (1.0 + metrics["total_return"])
    assert final == pytest.approx(10375.2683, abs=1e-3)
    for value in metrics.values():
        assert value is None or math.isfinite(float(value)), value
    assert isinstance(warnings, list)


def test_always_long_strategy_return_metrics_equal_benchmark() -> None:
    """A strategy that IS buy-and-hold must match compute_benchmark exactly
    on every benchmark key (same engine, costs, capital, deterministic)."""
    spec = _spec(entry=ALWAYS_LONG)
    bars = _bars(SC2_CLOSES)
    result = run(spec, bars)
    bench, _ = compute_benchmark(spec, bars)
    assert result.trades[-1].exit_reason == "end_of_data"
    for key, value in bench.items():
        assert key in result.metrics, key
        assert result.metrics[key] == value, key  # exact, deterministic


def test_early_exit_strategy_differs_benchmark_unchanged() -> None:
    """entry close<101 (bar 0 only, fill bar 1), exit close>102 (fires bar 3,
    fill bar 4 open 104) -> flat at the end. Hand chain:
      shares = 10000 / (101.0505 * 1.0005) = 98.910965297...
      sell fill = 104 * (1 - 0.0005) = 103.948
      cash_after_entry ~= 0 (fee-inclusive sizing, SC2 chain)
      final = shares * 103.948 * (1 - 0.0005)  (proceeds minus exit fee)
      strategy total_return = final / 10000 - 1   (differs from B&H)
    Benchmark ignores the rules -> still SC2's 0.03752683."""
    spec = _spec(
        entry={"all": [{"left": "close", "op": "<", "right": 101}]},
        exit_long={"all": [{"left": "close", "op": ">", "right": 102}]},
    )
    bars = _bars(SC2_CLOSES)
    result = run(spec, bars)
    bench, _ = compute_benchmark(spec, bars)

    shares = 10_000.0 / (101.0 * (1 + 0.0005) * 1.0005)  # = 98.910965297...
    final = shares * (104.0 * (1 - 0.0005)) * (1 - 0.0005)
    expected_strategy = final / 10_000.0 - 1.0

    assert result.trades[-1].exit_reason != "end_of_data"  # exited early
    assert result.metrics["total_return"] == pytest.approx(expected_strategy, rel=1e-9)
    assert bench["total_return"] == pytest.approx(SC2_TOTAL_RETURN, abs=1e-7)
    assert result.metrics["total_return"] != bench["total_return"]


def test_benchmark_pays_strategy_costs() -> None:
    """Changing fee_bps in the strategy spec changes the benchmark:
    with fee 50 bps (slippage stays 5 bps = 0.0005),
      fill_buy  = 101 * (1 + 0.0005) = 101.0505
      shares    = 10000 / (101.0505 * (1 + 0.005))
      sell fill = 105 * (1 - 0.0005) = 104.9475
      final     = shares * 104.9475 * (1 - 0.005)   (exit fee at 50 bps)
      total_return = final/10000 - 1  — strictly worse than the 5 bps value."""
    bars = _bars(SC2_CLOSES)
    cheap, _ = compute_benchmark(_spec(entry=ALWAYS_LONG, fee_bps=5.0), bars)
    dearer, _ = compute_benchmark(_spec(entry=ALWAYS_LONG, fee_bps=50.0), bars)

    shares = 10_000.0 / (101.0 * (1 + 0.0005) * (1 + 0.005))
    final = shares * (105.0 * (1 - 0.0005)) * (1 - 0.005)
    expected_50bps = final / 10_000.0 - 1.0

    assert dearer["total_return"] == pytest.approx(expected_50bps, rel=1e-9)
    assert dearer["total_return"] < cheap["total_return"]
    assert dearer["risk_free_rate"] == cheap["risk_free_rate"]


def test_benchmark_no_nan_inf() -> None:
    metrics, _ = compute_benchmark(_spec(entry=ALWAYS_LONG), _bars(SC2_CLOSES))
    for key, value in metrics.items():
        assert value is None or math.isfinite(float(value)), (key, value)
    # benchmark dict carries the full §4.7 return set incl. risk_free_rate
    for key in (
        "total_return",
        "cagr",
        "annualised_volatility",
        "sharpe",
        "max_drawdown",
        "longest_drawdown_bars",
        "calmar",
        "risk_free_rate",
    ):
        assert key in metrics, key
