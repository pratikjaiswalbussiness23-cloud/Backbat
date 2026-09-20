"""Frequency and ``bars_per_year`` inference (P1-T6, ROADMAP §4.7).

``bars_per_year`` is derived from the bar index — never hardcoded silently.
Two independent signals are computed from the ``DatetimeIndex``:

* ``median_gap_days`` — median of consecutive day differences ("median bar
  spacing" in the ROADMAP P1-T6 Do line),
* ``trading_days_per_week`` — median number of bars per ISO week (weekday
  pattern).

The classifier then maps daily-equity → 252, 7-day-crypto → 365.25 and
weekly → 52; 252 is only ever emitted as the *documented conservative default
of a classification branch* (or comes from a caller-supplied override), never
assumed for data the classifier could read.

Deviations from the task text (logged as OQ-0011/OQ-0012; owner review
pending — ROADMAP §2A R7):

* ``trading_days_per_week`` is the **median** of per-ISO-week bar counts, not
  the mean. The task's own test 8 (30 consecutive daily bars → DAILY_CRYPTO)
  is unsatisfiable with the mean: 30 consecutive days always touch ≥ 5 ISO
  weeks, so the mean is ≤ 30/5 = 6.0 < the 6.5 crypto threshold. The median
  is robust to the unavoidable partial edge weeks ([7, 7, 7, 7, 2] → 7.0).
* A ``median_gap_days >= 5.5`` branch (true weekly bars, ~1 bar/week) maps to
  WEEKLY/52. The task's test 3 (one bar per week, ~1.0 bars/week → WEEKLY)
  contradicts the literal ``>= 3.0`` sparse-daily bucket (1.0 < 3.0 would be
  UNKNOWN), and ROADMAP P1-T6's acceptance criterion "weekly → 52" requires
  the weekly mapping. 5.5 separates cleanly: sparse-daily patterns have a
  median gap ≤ 3.5 days (e.g. Tue/Thu → 3.5), weekly bars exactly 7. The
  ``else`` → UNKNOWN/252 branch is preserved for erratic sparse patterns.
* With an override AND fewer than 2 bars, the override still wins for
  ``bars_per_year`` (§4.7: "explicitly supplied") while the insufficient-bars
  warning is still set, because the data statistics are 0.0.

Inputs are contract-validated ``Bars`` (tz-aware UTC ``DatetimeIndex``, sorted
and unique — enforced by ``validate_bars_shape``); no extra guarding here,
mirroring ``quality.py``.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd
from pydantic import BaseModel, ConfigDict

from nlbt.data.models import Bars
from nlbt.errors import DataQualityError

__all__ = ["BarFrequency", "FrequencyResult", "infer_frequency"]

#: Bars per year emitted by the classification branches (ROADMAP §4.7).
DAILY_EQUITY_BARS_PER_YEAR: float = 252.0
DAILY_CRYPTO_BARS_PER_YEAR: float = 365.25
WEEKLY_BARS_PER_YEAR: float = 52.0
#: Conservative default of the UNKNOWN branches (the "252-style" convention,
#: documented here rather than hardcoded silently at call sites).
CONSERVATIVE_DEFAULT_BARS_PER_YEAR: float = 252.0

#: Median bars per ISO week at/above this → 7-day crypto calendar.
CRYPTO_MIN_DAYS_PER_WEEK: float = 6.5
#: Median bars per ISO week at/above this (and below the crypto threshold)
#: → equity-style weekday calendar.
EQUITY_MIN_DAYS_PER_WEEK: float = 4.0
#: Median bars per ISO week at/above this (and below the equity threshold)
#: → sparse daily, classified WEEKLY.
SPARSE_DAILY_MIN_DAYS_PER_WEEK: float = 3.0
#: Median day gap at/above this → true weekly bars (OQ-0012).
WEEKLY_MIN_MEDIAN_GAP_DAYS: float = 5.5

#: Warning attached to every WEEKLY outcome (sparse-daily and weekly bars).
SPARSE_WARNING = "Sparse data: fewer than 4 trading days per week on average"
#: Warning of the UNKNOWN daily branch (erratic sparse patterns).
UNRELIABLE_WARNING = "Could not infer frequency reliably. Consider using override_bars_per_year."
#: Warning when there are too few bars for any statistic.
INSUFFICIENT_BARS_WARNING = "Insufficient bars to infer frequency"


# (str, Enum) rather than enum.StrEnum: the task text pins this exact form;
# behaviourally equivalent here (members are str, pydantic serialises by value).
class BarFrequency(str, Enum):  # noqa: UP042
    """Frequency classes recognised by nlbt (P1-T6)."""

    DAILY_EQUITY = "daily_equity"  # ~252 bars/year
    DAILY_CRYPTO = "daily_crypto"  # ~365 bars/year
    WEEKLY = "weekly"  # ~52 bars/year
    MONTHLY = "monthly"  # ~12 bars/year (enum member per task; no inference path yet)
    UNKNOWN = "unknown"


class FrequencyResult(BaseModel):
    """Outcome of :func:`infer_frequency` (P1-T6)."""

    model_config = ConfigDict(extra="forbid")

    frequency: BarFrequency
    bars_per_year: float
    median_gap_days: float
    trading_days_per_week: float
    inferred: bool  # True if inferred, False if supplied via override
    warning: str | None  # set if UNKNOWN or ambiguous


def _index_statistics(index: pd.DatetimeIndex) -> tuple[float, float]:
    """Return ``(median_gap_days, trading_days_per_week)`` of a sorted index.

    ``trading_days_per_week`` is the MEDIAN of per-ISO-week bar counts over
    the ISO weeks present in the index (OQ-0011 documents why the task's
    "mean" wording is unsatisfiable for its own tests). Weeks entirely absent
    from the data are not counted as zeros — the metric describes the cadence
    of the bars that exist.
    """
    series = index.to_series()
    gaps = series.diff().dropna()
    median_gap_days = float(gaps.dt.days.median()) if not gaps.empty else 0.0
    iso = series.dt.isocalendar()
    counts = iso.groupby(["year", "week"], sort=False).size()
    trading_days_per_week = float(counts.median()) if not counts.empty else 0.0
    return median_gap_days, trading_days_per_week


def _classify_daily(
    median_gap_days: float,
    trading_days_per_week: float,
) -> tuple[BarFrequency, float, str | None]:
    """Classify daily-interval data; returns ``(frequency, bars_per_year, warning)``."""
    if median_gap_days >= WEEKLY_MIN_MEDIAN_GAP_DAYS:
        # True weekly bars (~1 bar/week): the sparse-daily threshold cannot
        # see them (1.0 < 3.0) — see OQ-0012.
        return BarFrequency.WEEKLY, WEEKLY_BARS_PER_YEAR, SPARSE_WARNING
    if trading_days_per_week >= CRYPTO_MIN_DAYS_PER_WEEK:
        return BarFrequency.DAILY_CRYPTO, DAILY_CRYPTO_BARS_PER_YEAR, None
    if trading_days_per_week >= EQUITY_MIN_DAYS_PER_WEEK:
        return BarFrequency.DAILY_EQUITY, DAILY_EQUITY_BARS_PER_YEAR, None
    if trading_days_per_week >= SPARSE_DAILY_MIN_DAYS_PER_WEEK:
        return BarFrequency.WEEKLY, WEEKLY_BARS_PER_YEAR, SPARSE_WARNING
    return BarFrequency.UNKNOWN, CONSERVATIVE_DEFAULT_BARS_PER_YEAR, UNRELIABLE_WARNING


def infer_frequency(
    bars: Bars,
    interval: str,
    override_bars_per_year: float | None = None,
) -> FrequencyResult:
    """Infer the bar frequency and ``bars_per_year`` of *bars* (P1-T6).

    Decision order:

    1. Fewer than 2 rows → UNKNOWN, gap/week statistics 0.0,
       insufficient-bars warning; ``bars_per_year`` is the override when
       supplied (``inferred=False``), else the conservative 252.
    2. ``override_bars_per_year`` supplied → ``bars_per_year`` is the override
       (never silently replaced), ``frequency=UNKNOWN`` (nothing was
       classified), ``inferred=False``, ``warning=None``; the gap/week
       statistics are still computed from the actual index.
    3. ``interval in ("1d", "1D")`` → classification from the index
       (:func:`_classify_daily`): weekly-spacing → WEEKLY/52; ≥ 6.5 bars per
       ISO week → DAILY_CRYPTO/365.25; ≥ 4.0 → DAILY_EQUITY/252; ≥ 3.0 →
       sparse WEEKLY/52; else UNKNOWN/252 ("consider override").
    4. Any other interval → UNKNOWN/252 with a not-supported warning and
       ``inferred=True``.
    """
    if len(bars) < 2:
        return FrequencyResult(
            frequency=BarFrequency.UNKNOWN,
            bars_per_year=(
                override_bars_per_year
                if override_bars_per_year is not None
                else CONSERVATIVE_DEFAULT_BARS_PER_YEAR
            ),
            median_gap_days=0.0,
            trading_days_per_week=0.0,
            inferred=override_bars_per_year is None,
            warning=INSUFFICIENT_BARS_WARNING,
        )

    index = bars.index
    if not isinstance(index, pd.DatetimeIndex):
        # The Bars contract (P1-T1) guarantees a DatetimeIndex via
        # validate_bars_shape; reaching this line is an invariant violation.
        raise DataQualityError(
            "frequency inference requires a DatetimeIndex",
            details={"actual_index_type": type(index).__name__},
        )
    median_gap_days, trading_days_per_week = _index_statistics(index)

    if override_bars_per_year is not None:
        return FrequencyResult(
            frequency=BarFrequency.UNKNOWN,
            bars_per_year=override_bars_per_year,
            median_gap_days=median_gap_days,
            trading_days_per_week=trading_days_per_week,
            inferred=False,
            warning=None,
        )

    if interval in ("1d", "1D"):
        frequency, bars_per_year, warning = _classify_daily(median_gap_days, trading_days_per_week)
        return FrequencyResult(
            frequency=frequency,
            bars_per_year=bars_per_year,
            median_gap_days=median_gap_days,
            trading_days_per_week=trading_days_per_week,
            inferred=True,
            warning=warning,
        )

    return FrequencyResult(
        frequency=BarFrequency.UNKNOWN,
        bars_per_year=CONSERVATIVE_DEFAULT_BARS_PER_YEAR,
        median_gap_days=median_gap_days,
        trading_days_per_week=trading_days_per_week,
        inferred=True,
        warning=(
            f"Interval {interval} not supported for automatic inference. "
            "Use override_bars_per_year."
        ),
    )
