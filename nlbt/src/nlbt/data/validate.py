"""Runtime validation of the Bars contract (P1-T1: ``validate_bars_shape``).

Every fault raises ``E_DATA_QUALITY`` with the ``context`` string prefixed to
the message plus machine-readable ``details``. The validator never silently
repairs data — the one documented normalisation is dtype: numeric-but-not-
float64 columns are converted to float64 (deterministic, value-preserving).
"""

from __future__ import annotations

from typing import Any, NoReturn

import pandas as pd

from nlbt.data.models import OHLCV_COLUMNS, Bars
from nlbt.errors import DataQualityError

__all__ = ["validate_bars_shape"]

#: Price columns subject to the NaN / > 0 / high>=low rules.
_OHLC: tuple[str, str, str, str] = ("open", "high", "low", "close")


def _fail(context: str, message: str, details: dict[str, Any], hint: str = "") -> NoReturn:
    """Raise ``E_DATA_QUALITY`` with the context prefix baked in (never returns)."""
    prefix = f"{context}: " if context else ""
    raise DataQualityError(f"{prefix}{message}", details=details, hint=hint)


def _samples(index: pd.Index) -> list[str]:
    """First few offending index labels, stringified for error details."""
    return [str(value) for value in index[:5]]


def validate_bars_shape(bars: Any, context: str = "") -> Bars:
    """Validate ``bars`` against the Bars contract and return it as :class:`Bars`.

    Raises ``E_DATA_QUALITY`` for each of:

    * not a pandas DataFrame
    * missing any of the 5 required columns (and unexpected extra columns,
      see OQ-0005)
    * non-numeric price/volume dtypes (numeric values are normalised to
      float64 — documented, value-preserving)
    * index is not a ``DatetimeIndex``
    * empty frame
    * duplicate index entries
    * non-monotonic (unsorted) index
    * NaN in any OHLC column (volume NaN is tolerated)
    * any OHLC price <= 0
    * ``high < low`` on any row

    ``context`` is prefixed into every message so callers can identify the
    data source (e.g. the CSV path) in errors.
    """
    if not isinstance(bars, pd.DataFrame):
        actual = type(bars).__name__
        _fail(
            context,
            f"expected a pandas DataFrame, got {actual}",
            {"actual_type": actual},
        )

    missing = [col for col in OHLCV_COLUMNS if col not in bars.columns]
    if missing:
        _fail(
            context,
            f"missing required column(s): {missing}",
            {
                "missing": missing,
                "present": [str(col) for col in bars.columns],
            },
            hint="data providers must emit open, high, low, close, volume",
        )
    extra = [str(col) for col in bars.columns if col not in OHLCV_COLUMNS]
    if extra:
        _fail(context, f"unexpected extra column(s): {extra}", {"extra": extra})  # OQ-0005

    if not isinstance(bars.index, pd.DatetimeIndex):
        actual = type(bars.index).__name__
        _fail(
            context,
            f"index must be a DatetimeIndex, got {actual}",
            {"actual_index_type": actual},
            hint="set the frame index to parsed datetimes (UTC)",
        )

    if bars.empty:
        _fail(context, "frame is empty (0 rows)", {"rows": 0})

    non_numeric: list[dict[str, str]] = []
    for col in OHLCV_COLUMNS:
        if not pd.api.types.is_numeric_dtype(bars[col]):
            non_numeric.append({"column": col, "dtype": str(bars[col].dtype)})
    if non_numeric:
        _fail(
            context,
            "non-numeric column(s) detected",
            {"columns": non_numeric},
            hint="coerce prices/volume to numeric before validation",
        )

    # Documented normalisation: numeric -> float64 (value-preserving, explicit).
    bars = bars.astype({col: "float64" for col in OHLCV_COLUMNS})

    if not bars.index.is_monotonic_increasing:
        _fail(
            context,
            "index is not sorted ascending",
            {"rows": len(bars)},
            hint="sort by date before validating (providers sort; raw data may not)",
        )

    dup_mask = bars.index.duplicated()
    if dup_mask.any():
        _fail(
            context,
            "duplicate timestamps in index",
            {"duplicates": _samples(bars.index[dup_mask])},
            hint="drop or aggregate duplicate dates before validation",
        )

    ohlc = bars[list(_OHLC)]
    rows_with_nan = ohlc.isna().any(axis=1)
    if rows_with_nan.any():
        _fail(
            context,
            "NaN value(s) in OHLC column(s)",
            {
                "rows_with_nan": _samples(bars.index[rows_with_nan]),
                "count": int(rows_with_nan.sum()),
            },
            hint="OHLC cannot contain NaN (volume NaN is tolerated by the contract)",
        )

    nonpositive = ohlc <= 0
    rows_nonpositive = nonpositive.any(axis=1)
    if rows_nonpositive.any():
        _fail(
            context,
            "non-positive price value(s) (prices must be > 0)",
            {
                "rows": _samples(bars.index[rows_nonpositive]),
                "count": int(rows_nonpositive.sum()),
            },
        )

    inverted = bars["high"] < bars["low"]
    if inverted.any():
        _fail(
            context,
            "high < low on one or more rows",
            {"rows": _samples(bars.index[inverted]), "count": int(inverted.sum())},
        )

    validated = Bars(bars)
    validated.attrs["nlbt_validated"] = True
    return validated
