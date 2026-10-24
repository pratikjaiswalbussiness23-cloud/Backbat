"""Buy-and-hold benchmark via the same engine (ROADMAP P5-T3).

``compute_benchmark`` builds a PRIVATE always-long spec from the strategy
spec — same universe, period, execution costs (``fee_bps``,
``slippage_bps``, ``fixed_fee``) and capital; ``entry_long = close > 0``,
no exit, no risk rules, ``percent_of_equity`` 100 with fractional shares —
runs it through :func:`nlbt.engine.backtest.run` and returns the §4.7
return-metrics dict plus warnings, exactly like
:func:`nlbt.metrics.compute_return_metrics`.

Caveats (also documented in ``docs/metrics.md``):

* the benchmark buys at the FIRST fill (bar 1 open, as in SC2), NOT at the
  strategy's own start after warm-up;
* it uses fractional shares (fully invested);
* it pays the same fee/slippage/fixed_fee as the strategy spec;
* at end of data it is closed by the same forced ``end_of_data`` close
  (exit costs included), so its metrics are settled like the strategy's.

Warnings are returned, NOT appended to any ``result.warnings``
(OQ-0072 ruling (a); surfaced in P5-T4). ``run()`` and ``BacktestResult``
are unchanged — P5-T4 attaches the benchmark to the result.

This module lives in ``nlbt.engine`` and imports the engine;
``nlbt.metrics`` must never import back (one-way dependency).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nlbt.data.frequency import infer_frequency
from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.metrics import compute_return_metrics
from nlbt.spec.models import StrategySpec

__all__ = ["compute_benchmark"]


def _buy_and_hold_spec(spec: StrategySpec) -> StrategySpec:
    """Private always-long spec mirroring SC2's shape (P5-T3 owner ruling).

    Everything except the RULES/sizing/indicators is copied verbatim from
    the strategy spec (universe, period, execution costs, capital).
    """
    payload = spec.model_dump()
    payload["name"] = "benchmark"
    payload["indicators"] = {}
    payload["rules"] = {"entry_long": {"all": [{"left": "close", "op": ">", "right": 0}]}}
    payload["risk"] = {}
    payload["sizing"] = {
        "method": "percent_of_equity",
        "value": 100.0,
        "allow_fractional": True,
    }
    return StrategySpec.model_validate(payload)


def compute_benchmark(
    spec: StrategySpec,
    bars: Bars,
    rf: float = 0.0,
) -> tuple[dict[str, float | None], list[str]]:
    """Return ``(return_metrics, warnings)`` for buy-and-hold on ``bars``.

    Same engine, same costs, same initial capital as ``spec``; settled the
    same way as ``run()`` (last curve value replaced by the realized
    ``final_equity`` when the forced end-of-data close ran).
    """
    result = run(_buy_and_hold_spec(spec), bars, rf=rf)

    settled = np.asarray(result.equity_curve["equity"], dtype=float).copy()
    final_equity = result.metrics["final_equity"]
    position_open = (
        bool(settled.size) and float(result.equity_curve["position_value"].iloc[-1]) > 0.0
    )
    if position_open and final_equity is not None:
        settled[-1] = final_equity

    freq = infer_frequency(bars, spec.universe.interval)
    metrics, warnings = compute_return_metrics(
        settled,
        pd.DatetimeIndex(result.equity_curve.index),
        freq.bars_per_year,
        rf=rf,
    )
    if freq.warning is not None:
        warnings = [freq.warning, *warnings]
    return metrics, warnings
