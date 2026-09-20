"""SMA and EMA — the first two catalog indicators (ROADMAP P2-T2, §4.3).

Conventions are FIXED by ADR-0002 (docs/adr/ADR-0002-ema-sma-seed-convention.md):

* **SMA**: mean of the last ``period`` source values; first valid output at
  index ``period - 1`` (0-based); positions ``0 .. period-2`` are NaN;
  ``warmup = period - 1``.
* **EMA**: ``alpha = 2 / (period + 1)``; SEEDED with the SMA of the first
  ``period`` values (placed at index ``period - 1``); then
  ``ema[t] = alpha * price[t] + (1 - alpha) * ema[t-1]``; ``warmup =
  period - 1``. Implemented from these formulas — deliberately NOT
  ``pandas ewm()``, whose seed rule is an implementation detail that drifts
  across versions (on this stack the reference library's first-value seeding
  diverges from ours; probe recorded in docs/verified_apis.md).

NaN handling: §4.3 — "no NaN after warm-up unless the input is NaN". A NaN in
the input poisons exactly the outputs reachable from it: for SMA every window
containing it; for EMA the seed window containing it (or one recursion step
after a seeded NaN), after which the recursion RESEEDS on the next
fully-valid window (documented in OQ-0016; owner may tighten to
permanent-NaN).

The vectorised kernels are differential-tested against the literal reference
loops from the task text (mandate: ≥ 3 inputs) — see
tests/unit/test_indicators_trend.py.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from nlbt.data.models import Bars
from nlbt.indicators.registry import IndicatorSpec, ParamSpec, register_indicator

__all__ = ["compute_ema", "compute_sma"]

#: Every indicator in this module accepts each OHLCV column as source (§4.3).
_SOURCES: tuple[str, ...] = ("open", "high", "low", "close", "volume")


def _warmup(params: dict[str, Any]) -> int:
    """Both conventions put the first valid output at index ``period - 1``."""
    return int(params["period"]) - 1


def _sma_reference_loop(prices: pd.Series, period: int) -> pd.Series:
    """Literal transcription of the P2-T2 reference loop (differential oracle).

    Kept here (not in the test file) so the tests import the SAME reference
    the task text specifies; ``compute_sma`` itself does not use it.
    """
    result = pd.Series(np.nan, index=prices.index, dtype=float)
    for i in range(period - 1, len(prices)):
        window = prices.iloc[i - period + 1 : i + 1]
        result.iloc[i] = np.nan if window.isna().any() else window.mean()
    return result


def _sma_vectorised(prices: pd.Series, period: int) -> pd.Series:
    """Rolling mean with ``min_periods=period``.

    ``min_periods=period`` (stricter than pandas' default) makes a single NaN
    inside a window produce NaN — identical to the reference loop's
    ``window.isna().any()`` gate.
    """
    return prices.rolling(window=period, min_periods=period).mean()


def compute_sma(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """SMA kernel — mean of the last ``period`` source values (ADR-0002)."""
    period = int(params["period"])
    return pd.DataFrame(
        {"value": _sma_vectorised(bars[source], period)},
        index=bars.index,
    )


def compute_ema(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """EMA kernel — ``alpha = 2/(period+1)``, SMA-seeded (ADR-0002), no ewm().

    NaN rule (OQ-0016): a NaN input poisons the outputs reachable from it —
    the seed window containing it, or exactly one recursion step after a
    seeded NaN — after which the recursion reseeds on the next fully-valid
    window. A NaN-free input therefore produces NaN only during warmup.
    """
    period = int(params["period"])
    alpha = 2.0 / (period + 1)
    valid = bars[source].to_numpy(dtype=float)

    values = np.full(len(valid), np.nan)
    running = np.nan
    seeded = False
    for i in range(period - 1, len(valid)):
        if not seeded:
            # Seed search: first fully-valid window of `period` values.
            window = valid[i - period + 1 : i + 1]
            if not np.isnan(window).any():
                running = float(window.mean())
                values[i] = running
                seeded = True
        elif np.isnan(valid[i]):
            # Recursion contaminated: output NaN, chain must reseed.
            seeded = False
        else:
            running = alpha * valid[i] + (1.0 - alpha) * running
            values[i] = running
    return pd.DataFrame({"value": values}, index=bars.index)


# ---------------------------------------------------------------------------
# Registration (P2-T1 contract: indicator modules register at import time).
# ---------------------------------------------------------------------------

register_indicator(
    IndicatorSpec(
        name="sma",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=500,
                default=20,
                description="Window length in bars; inclusive bounds [2, 500].",
            )
        },
        allowed_sources=_SOURCES,
        warmup_fn=_warmup,
        compute_fn=compute_sma,
        description=(
            "Simple moving average: mean of the last `period` source values; "
            "first valid output at index period-1 (ADR-0002)."
        ),
    )
)

register_indicator(
    IndicatorSpec(
        name="ema",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=500,
                default=20,
                description="Window length in bars; inclusive bounds [2, 500].",
            )
        },
        allowed_sources=_SOURCES,
        warmup_fn=_warmup,
        compute_fn=compute_ema,
        description=(
            "Exponential moving average: alpha = 2/(period+1), seeded with the "
            "SMA of the first `period` values (ADR-0002); first valid output "
            "at index period-1."
        ),
    )
)
