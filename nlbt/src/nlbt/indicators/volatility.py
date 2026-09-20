"""MACD and Bollinger Bands (ROADMAP P2-T4, §4.3).

Conventions are FIXED by ADR-0002 (EMA seed) and ADR-0004
(docs/adr/ADR-0004-bollinger-sigma-convention.md):

* **MACD**: ``line = EMA(fast) - EMA(slow)``; ``signal = EMA(line, signal)``;
  ``hist = line - signal``; the EMA is the ADR-0002 SMA-seeded kernel from
  :func:`nlbt.indicators.trend.compute_ema` (imported, NOT reimplemented).
  Default fast=12, slow=26, signal=9; ``warmup = slow + signal - 2`` (the
  slow EMA contributes slow-1 bars, the signal EMA signal-1 on top); all
  three columns NaN through the warmup; source: close only.
* **Bollinger Bands**: ``middle = SMA(period)``; bands = middle ±
  ``k * std(period, ddof=1)`` — SAMPLE standard deviation. Default
  period=20, k=2.0; ``warmup = period - 1``. A NaN inside a window → NaN
  bands for that bar. SMA/std are implemented inline (the task forbids
  calling ``compute_sma`` here to avoid coupling; the std kernel is
  differential-tested against a literal reference loop in the tests).

Oracle reality (probed, docs/verified_apis.md): ta 0.11.0's MACD uses
first-value-seeded ewm — its line/signal/hist START at the same indices as
ours (line at slow-1, signal/hist at slow+signal-2) but the VALUES diverge
from the different seeds; its BBands use **ddof=0**. Both divergences are
documented and asserted in the tests (OQ-0017 pattern), not hidden. On a
linear ramp our MACD is exactly ``line = slow-fast ≡ 7.0`` for t ≥ slow-1
(EMA fixed-point arithmetic, hand-shown in the tests) — an exact,
implementation-independent oracle.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from nlbt.data.models import Bars
from nlbt.indicators.registry import IndicatorSpec, ParamSpec, register_indicator
from nlbt.indicators.trend import compute_ema

__all__ = ["compute_bbands", "compute_macd"]

_SOURCES_ALL: tuple[str, ...] = ("open", "high", "low", "close", "volume")


def _macd_warmup(params: dict[str, Any]) -> int:
    """slow EMA needs slow-1 bars, the signal EMA signal-1 more: slow+signal-2.

    (``fast`` does not appear: fast-1 <= slow-1 by construction, so the slow
    EMA always gates the line. See OQ-0021 for the fast < slow question.)
    """
    return int(params["slow"]) + int(params["signal"]) - 2


def _bbands_warmup(params: dict[str, Any]) -> int:
    """First full window of ``period`` values ends at index period-1."""
    return int(params["period"]) - 1


def compute_macd(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """MACD kernel — built entirely from the ADR-0002 EMA (no reimplementation).

    The signal EMA needs a Bars-like input for :func:`compute_ema`; the MACD
    line is wrapped in a minimal validated-shape frame (exact columns, the
    line duplicated into every column so any column access is well-defined).
    hist is NaN wherever line or signal is NaN (NaN arithmetic gives this
    for free; the assertion is only broken by -0.0 edge cases, none here).
    """
    fast = int(params["fast"])
    slow = int(params["slow"])
    signal_period = int(params["signal"])

    # Both line EMAs run on the PRICE series (ADR-0002 kernel, imported).
    fast_ema = compute_ema(bars, {"period": fast}, source)["value"]
    slow_ema = compute_ema(bars, {"period": slow}, source)["value"]
    line = fast_ema - slow_ema

    # The SIGNAL is an EMA of the line → wrap the line in a minimal
    # Bars-like carrier (compute_ema only reads bars[source] and bars.index;
    # every column carries the line so any column access is well-defined).
    line_np = line.to_numpy()
    line_frame = Bars(
        {
            "open": line_np,
            "high": line_np,
            "low": line_np,
            "close": line_np,
            "volume": np.zeros(len(bars)),
        },
        index=bars.index,
    )
    signal = compute_ema(line_frame, {"period": signal_period}, source)["value"]
    hist = line - signal
    return pd.DataFrame({"line": line, "signal": signal, "hist": hist}, index=bars.index)


def _rolling_sample_std_reference(values: np.ndarray, period: int) -> np.ndarray:
    """Literal reference loop: sample std (ddof=1) per window, NaN-poisoned.

    Kept beside the vectorised kernel (P2-T2 pattern) so the tests
    differential-test the two; ``compute_bbands`` itself does not use it.
    """
    out = np.full(len(values), np.nan)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if np.isnan(window).any():
            continue
        mean = window.mean()
        out[i] = float(np.sqrt(((window - mean) ** 2).sum() / (period - 1)))
    return out


def _rolling_sample_std(values: np.ndarray, period: int) -> np.ndarray:
    """Vectorised rolling sample std (ddof=1); NaN inside a window → NaN.

    pandas' ``rolling(...).std(ddof=1)`` with ``min_periods=period`` gives
    exactly these semantics.
    """
    return pd.Series(values).rolling(window=period, min_periods=period).std(ddof=1).to_numpy()


def compute_bbands(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """Bollinger Bands kernel — inline SMA + rolling sample std (ddof=1)."""
    period = int(params["period"])
    k = float(params["k"])
    values = bars[source].to_numpy(dtype=float)

    # Inline SMA (task: do not call compute_sma here).
    middle = pd.Series(values).rolling(window=period, min_periods=period).mean().to_numpy()
    std = _rolling_sample_std(values, period)
    upper = middle + k * std
    lower = middle - k * std
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower}, index=bars.index)


# ---------------------------------------------------------------------------
# Registration (P2-T1 contract: indicator modules register at import time).
# ---------------------------------------------------------------------------

register_indicator(
    IndicatorSpec(
        name="macd",
        outputs=("line", "signal", "hist"),
        params={
            "fast": ParamSpec(
                type="int",
                minimum=2,
                maximum=200,
                default=12,
                description="Fast EMA length; inclusive bounds [2, 200].",
            ),
            "slow": ParamSpec(
                type="int",
                minimum=2,
                maximum=200,
                default=26,
                description="Slow EMA length; inclusive bounds [2, 200].",
            ),
            "signal": ParamSpec(
                type="int",
                minimum=2,
                maximum=200,
                default=9,
                description="Signal EMA length on the MACD line; inclusive [2, 200].",
            ),
        },
        allowed_sources=("close",),
        warmup_fn=_macd_warmup,
        compute_fn=compute_macd,
        description=(
            "MACD: line = EMA(fast) - EMA(slow), signal = EMA(line, signal), "
            "hist = line - signal; SMA-seeded EMA per ADR-0002; warmup = "
            "slow + signal - 2; source close only."
        ),
    )
)

register_indicator(
    IndicatorSpec(
        name="bbands",
        outputs=("upper", "middle", "lower"),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=500,
                default=20,
                description="SMA/std window; inclusive bounds [2, 500].",
            ),
            "k": ParamSpec(
                type="float",
                minimum=0.1,
                maximum=10.0,
                default=2.0,
                description="Band width in standard deviations; inclusive [0.1, 10].",
            ),
        },
        allowed_sources=_SOURCES_ALL,
        warmup_fn=_bbands_warmup,
        compute_fn=compute_bbands,
        description=(
            "Bollinger Bands: middle = SMA(period), upper/lower = middle ± "
            "k * sample-std(period, ddof=1) per ADR-0004; warmup = period-1."
        ),
    )
)
