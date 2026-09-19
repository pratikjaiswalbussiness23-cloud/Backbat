"""CSV data provider (P1-T2): the ``symbol`` parameter IS the file path.

Pipeline: read (dtype=str, no inference) → map header variants → parse dates
explicitly (ISO-8601, coerce) → DatetimeIndex UTC → sort by date → numeric
coercion with loud errors → calendar-day slice → ``validate_bars_shape``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from nlbt.data.models import OHLCV_COLUMNS, Bars, BarsMeta
from nlbt.data.validate import validate_bars_shape
from nlbt.errors import DataQualityError

__all__ = ["COLUMN_ALIASES", "CSVProvider"]

#: Case-insensitive header variants -> canonical column names (P1-T2).
COLUMN_ALIASES: dict[str, str] = {
    "date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "adj close": "close",
    "volume": "volume",
}


class CSVProvider:
    """:class:`nlbt.data.models.DataProvider` backed by a CSV file.

    Notes:

    * ``symbol`` is the file path (P1-T2).
    * ``adjusted`` is accepted for protocol compatibility but CSV files carry
      raw closes only; the returned ``BarsMeta.adjusted`` is always ``False``
      and a request for adjusted data is flagged in ``source_notes``.
    * Date filtering is calendar-day based, inclusive of both endpoints.
    """

    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "1d",
        adjusted: bool = False,
    ) -> tuple[Bars, BarsMeta]:
        """Load, clean, slice and validate OHLCV rows from a CSV file.

        Every failure raises ``E_DATA_QUALITY`` with the file name in the
        message/context.
        """
        path = Path(symbol)
        if not path.is_file():
            raise DataQualityError(
                f"CSV file not found: {path}",
                details={"path": str(path)},
                hint="for CSVProvider the symbol parameter must be an existing CSV file path",
            )

        try:
            raw = pd.read_csv(path, dtype=str)
        except (
            OSError,
            UnicodeDecodeError,
            pd.errors.ParserError,
            pd.errors.EmptyDataError,
        ) as exc:
            raise DataQualityError(
                f"failed to read CSV file: {path}",
                details={"path": str(path), "reason": str(exc)},
            ) from exc

        # Explicit header mapping — case-insensitive variants (P1-T2).
        targets = [COLUMN_ALIASES.get(str(col).strip().lower()) for col in raw.columns]
        mapped = [target for target in targets if target is not None]
        if len(set(mapped)) != len(mapped):
            ambiguous = sorted({target for target in mapped if mapped.count(target) > 1})
            raise DataQualityError(
                f"{path.name}: ambiguous header(s) mapping to the same column: {ambiguous}",
                details={"headers": [str(col) for col in raw.columns]},
                hint="e.g. provide either 'Close' or 'Adj Close', not both",
            )
        rename = {
            col: target
            for col, target in zip(raw.columns, targets, strict=True)
            if target is not None
        }
        df = raw.rename(columns=rename)

        required = ("date", *OHLCV_COLUMNS)
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise DataQualityError(
                f"{path.name}: missing required column(s): {missing}",
                details={
                    "missing": missing,
                    "present": [str(col) for col in df.columns],
                    "supported_variants": sorted(COLUMN_ALIASES),
                },
                hint="see COLUMN_ALIASES for accepted header spellings",
            )

        # Explicit date parsing — never pandas inference (P1-T2).
        parsed = pd.to_datetime(df["date"], format="ISO8601", errors="coerce", utc=True)
        bad_dates = df["date"][parsed.isna()]
        if len(bad_dates) > 0:
            raise DataQualityError(
                f"{path.name}: unparseable date value(s)",
                details={
                    "bad_values": [str(value) for value in bad_dates.head(5)],
                    "expected": "ISO-8601, e.g. 2024-01-02",
                },
            )
        df = df.drop(columns=["date"])
        df.index = pd.DatetimeIndex(parsed)
        df = df.sort_index()

        # Values: explicit numeric coercion; garbage becomes a loud error,
        # not a silent NaN that validate would have to mislabel.
        out = pd.DataFrame(index=df.index)
        for col in OHLCV_COLUMNS:
            raw_values = df[col]
            numeric = pd.to_numeric(raw_values, errors="coerce")
            newly_nan = numeric.isna() & raw_values.notna()
            if newly_nan.any():
                raise DataQualityError(
                    f"{path.name}: unparseable numeric value(s) in column '{col}'",
                    details={"bad_values": [str(value) for value in raw_values[newly_nan].head(5)]},
                )
            out[col] = numeric.astype("float64")

        # Calendar-day slice [start, end] inclusive. Bounds are built tz-aware:
        # pandas 3 raises TypeError on tz-naive vs tz-aware comparison
        # (verified — see docs/verified_apis.md).
        start_ts = pd.Timestamp(start, tz="UTC")
        end_exclusive = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        out = out[(out.index >= start_ts) & (out.index < end_exclusive)]
        if out.empty:
            raise DataQualityError(
                f"{path.name}: no rows within [{start}, {end}]",
                details={"start": str(start), "end": str(end), "file_rows": len(df)},
                hint="check the requested date range against the file's coverage",
            )

        bars = validate_bars_shape(out, context=str(path))
        source_notes = f"loaded from {path.name}"
        if adjusted:
            source_notes += "; adjusted=True was requested but CSV data is unadjusted"
        meta = BarsMeta(
            provider="csv",
            symbol=symbol,
            interval=interval,
            adjusted=False,  # always for CSV (P1-T2)
            timezone="UTC",
            fetched_at=datetime.now(UTC),
            source_notes=source_notes,
        )
        return bars, meta
