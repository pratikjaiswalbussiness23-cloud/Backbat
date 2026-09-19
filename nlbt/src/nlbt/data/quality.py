"""Data quality report: blocking checks + non-raising warnings (P1-T5).

Two categories (ROADMAP P1-T5):

* BLOCKING — data unusable. ``run_quality_checks`` NEVER raises; it returns a
  report with ``passed_blocking=False`` and ``blocked_by`` set. The CALLER
  decides whether to raise (via :func:`assert_quality`).
* WARNING — suspicious but usable; recorded in ``report.warnings`` only.

Blocking precedence (derived from the task's own fixtures/tests): the
``HIGH_LOW_VIOLATION``/``LOW_HIGH_VIOLATION`` checks run FIRST because
``ohlc_violation.csv`` (high=98 < low=99) violates both the new max/min rule
and ``validate_bars_shape``'s older ``high < low`` rule; the report must name
the specific code. The remaining blocking faults (empty, unsorted, duplicates,
non-positive prices, NaN in OHLC) reuse ``validate_bars_shape`` verbatim — its
message text becomes the ``blocked_by`` value (OQ-0010: codes vs free text).

``today`` is injectable for deterministic tests; ``None`` means ``date.today()``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict

from nlbt.data.models import Bars, BarsMeta
from nlbt.data.validate import validate_bars_shape

__all__ = [
    "DataQualityReport",
    "DataQualityWarning",
    "assert_quality",
    "run_quality_checks",
]

#: |close/open - 1| above this is flagged as a possible unadjusted split.
LARGE_RETURN_THRESHOLD: float = 0.40
#: Ratio of zero-volume bars above this is flagged.
ZERO_VOLUME_RATIO_THRESHOLD: float = 0.05
#: Volume above this multiple of the median volume is flagged as an outlier.
VOLUME_OUTLIER_MULTIPLE: float = 10.0
#: Trading days between the last bar and today above this is flagged as stale.
STALE_TRADING_DAYS: int = 5


class DataQualityWarning(BaseModel):
    """A non-blocking observation about the data (P1-T5)."""

    model_config = ConfigDict(extra="forbid")

    code: str  # e.g. "ZERO_VOLUME_RATIO"
    message: str
    details: dict[str, Any] = {}


class DataQualityReport(BaseModel):
    """Outcome of :func:`run_quality_checks` (P1-T5)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    interval: str
    bars: int
    start: str  # ISO date of first bar
    end: str  # ISO date of last bar
    adjusted: bool
    warnings: list[DataQualityWarning] = []
    passed_blocking: bool
    blocked_by: str | None = None


def assert_quality(report: DataQualityReport) -> None:
    """Raise ``E_DATA_QUALITY`` if the report failed its blocking checks."""
    if not report.passed_blocking:
        from nlbt.errors import DataQualityError  # local: errors must not import data

        raise DataQualityError(
            f"Data quality check failed: {report.blocked_by}",
            details={"symbol": report.symbol, "blocked_by": report.blocked_by},
            hint="Check your data source and date range",
        )


def _blocked(
    meta: BarsMeta,
    bars_count: int,
    blocked_by: str,
) -> DataQualityReport:
    """A failing report: warnings list is empty by definition (P1-T5)."""
    return DataQualityReport(
        symbol=meta.symbol,
        interval=meta.interval,
        bars=bars_count,
        start="",
        end="",
        adjusted=meta.adjusted,
        warnings=[],
        passed_blocking=False,
        blocked_by=blocked_by,
    )


def _row_violation_codes(bars: Bars) -> str | None:
    """Return the code of the first row-level OHLC violation, or ``None``.

    Rows with NaN OHLC values are masked OUT here (pandas row max/min skip
    NaN, which would otherwise turn a NaN-high row into a bogus
    LOW_HIGH_VIOLATION — probed on pandas 3.0.6); NaN is caught separately by
    the validate-reuse check.
    """
    complete = bars.notna().all(axis=1)
    if not complete.any():
        return None
    valid = bars.loc[complete]
    high, low = valid["high"], valid["low"]
    upper = valid[["open", "close", "low"]].max(axis=1)
    lower = valid[["open", "close", "high"]].min(axis=1)
    if bool((high < upper).any()):
        return "HIGH_LOW_VIOLATION"
    if bool((low > lower).any()):
        return "LOW_HIGH_VIOLATION"
    return None


def _check_validate_reuse(bars: Bars) -> str | None:
    """Reuse ``validate_bars_shape`` for the blocking faults it already covers.

    Returns the validator's message text (minus context prefix) as the
    ``blocked_by`` value, or ``None`` when the frame passes (OQ-0010).
    """
    try:
        validate_bars_shape(bars, context="")
    except Exception as exc:  # reuse contract: any validator rejection blocks
        return str(getattr(exc, "message", exc))
    return None


def _warning_checks(bars: Bars, meta: BarsMeta, today: date) -> list[DataQualityWarning]:
    """All warning checks; never raises (P1-T5)."""
    warnings: list[DataQualityWarning] = []

    # --- ZERO_VOLUME_RATIO -------------------------------------------------
    volume = bars["volume"]
    zero_mask = volume == 0
    zero_ratio = float(zero_mask.sum()) / float(len(bars))
    if zero_ratio > ZERO_VOLUME_RATIO_THRESHOLD:
        warnings.append(
            DataQualityWarning(
                code="ZERO_VOLUME_RATIO",
                message=f"{zero_ratio:.1%} of bars have zero volume (threshold 5%)",
                details={
                    "ratio": zero_ratio,
                    "threshold": ZERO_VOLUME_RATIO_THRESHOLD,
                    "zero_volume_bars": int(zero_mask.sum()),
                    "total_bars": len(bars),
                },
            )
        )

    # --- LARGE_SINGLE_RETURN (intra-bar |close/open - 1|; OQ-0008) ---------
    complete = bars[["open", "close"]].notna().all(axis=1)
    if complete.any():
        returns = (bars.loc[complete, "close"] / bars.loc[complete, "open"] - 1).abs()
        big = returns[returns > LARGE_RETURN_THRESHOLD]
        if not big.empty:
            warnings.append(
                DataQualityWarning(
                    code="LARGE_SINGLE_RETURN",
                    message=f"{len(big)} bar(s) with |close/open - 1| > 40% "
                    "(possible unadjusted split)",
                    details={
                        "threshold": LARGE_RETURN_THRESHOLD,
                        "dates": [str(timestamp.date()) for timestamp in big.index[:5]],
                        "max_return": float(big.max()),
                    },
                )
            )

    # --- STALE_LAST_BAR ------------------------------------------------------
    gap_days = int(np.busday_count(bars.index[-1].date(), today))
    if gap_days > STALE_TRADING_DAYS:
        warnings.append(
            DataQualityWarning(
                code="STALE_LAST_BAR",
                message=f"last bar is {gap_days} trading days before {today.isoformat()} "
                f"(threshold {STALE_TRADING_DAYS})",
                details={
                    "last_bar_date": str(bars.index[-1].date()),
                    "today": str(today),
                    "trading_days_gap": gap_days,
                    "threshold": STALE_TRADING_DAYS,
                },
            )
        )

    # --- VOLUME_OUTLIER ------------------------------------------------------
    positive_volume = volume[volume > 0]
    if len(positive_volume) > 0:
        median_volume = float(positive_volume.median())
        if median_volume > 0:
            outlier_mask = volume > VOLUME_OUTLIER_MULTIPLE * median_volume
            if bool(outlier_mask.any()):
                warnings.append(
                    DataQualityWarning(
                        code="VOLUME_OUTLIER",
                        message=f"{int(outlier_mask.sum())} bar(s) with volume > "
                        f"{VOLUME_OUTLIER_MULTIPLE:g}x median volume",
                        details={
                            "multiple": VOLUME_OUTLIER_MULTIPLE,
                            "median_volume": median_volume,
                            "dates": [
                                str(bars.index[position].date())
                                for position in np.flatnonzero(outlier_mask.to_numpy())[:5]
                            ],
                        },
                    )
                )

    # --- VOLUME_NAN ------------------------------------------------------------
    volume_nan_mask = volume.isna()
    if bool(volume_nan_mask.any()):
        warnings.append(
            DataQualityWarning(
                code="VOLUME_NAN",
                message=f"{int(volume_nan_mask.sum())} bar(s) have NaN volume",
                details={
                    "count": int(volume_nan_mask.sum()),
                    "dates": [
                        str(bars.index[position].date())
                        for position in np.flatnonzero(volume_nan_mask.to_numpy())[:5]
                    ],
                },
            )
        )
    return warnings


def run_quality_checks(
    bars: Bars,
    meta: BarsMeta,
    min_bars: int = 0,
    today: date | None = None,
) -> DataQualityReport:
    """Run blocking checks first, then warning checks; NEVER raises.

    ``today`` is used only for the stale-bar check; ``None`` falls back to
    ``date.today()`` — inject a fixed date for deterministic tests.
    """
    if len(bars) < min_bars:
        return _blocked(meta, len(bars), "INSUFFICIENT_BARS")

    violation = _row_violation_codes(bars)
    if violation is not None:
        return _blocked(meta, len(bars), violation)

    validator_message = _check_validate_reuse(bars)
    if validator_message is not None:
        return _blocked(meta, len(bars), validator_message)

    effective_today = today if today is not None else date.today()
    return DataQualityReport(
        symbol=meta.symbol,
        interval=meta.interval,
        bars=len(bars),
        start=str(bars.index[0].date()),
        end=str(bars.index[-1].date()),
        adjusted=meta.adjusted,
        warnings=_warning_checks(bars, meta, effective_today),
        passed_blocking=True,
        blocked_by=None,
    )
