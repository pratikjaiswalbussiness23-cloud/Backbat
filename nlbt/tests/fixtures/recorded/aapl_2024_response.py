"""Recorded yfinance response for AAPL 2024-01-02 .. 2024-01-05 (P1-T3).

Captured from a REAL probe run on 2026-09-19 against the INSTALLED yfinance
1.7.0 (see docs/verified_apis.md):

    yf.download('AAPL', start='2024-01-02', end='2024-01-06',
                auto_adjust=True, progress=False, threads=False)

Values are the probe's full-precision output (displayed to 6 decimals).
Structure mirrors exactly what yfinance 1.7.0 returns for a single ticker:
MultiIndex columns (names ['Price', 'Ticker']), OHLC float64, Volume int64,
tz-naive DatetimeIndex named 'Date' (yfinance's ``end`` is EXCLUSIVE, so the
last row is 2024-01-05). Unit tests use this instead of the network.
"""

from __future__ import annotations

import pandas as pd

#: DatetimeIndex labels exactly as returned (tz-naive daily stamps).
RECORDED_INDEX: list[str] = [
    "2024-01-02",
    "2024-01-03",
    "2024-01-04",
    "2024-01-05",
]

#: MultiIndex column tuples exactly as returned, incl. yfinance's ordering.
RECORDED_COLUMNS: list[tuple[str, str]] = [
    ("Close", "AAPL"),
    ("High", "AAPL"),
    ("Low", "AAPL"),
    ("Open", "AAPL"),
    ("Volume", "AAPL"),
]

#: MultiIndex level names exactly as returned.
RECORDED_COLUMN_NAMES: list[str] = ["Price", "Ticker"]

#: Row values exactly as returned (Close, High, Low, Open, Volume per row).
RECORDED_DATA: list[list[float | int]] = [
    [183.403992, 186.170269, 181.67507, 184.895799, 82488700],
    [182.030746, 183.641118, 181.220616, 182.001109, 58414500],
    [179.718948, 180.884728, 178.701356, 179.956048, 71983600],
    [178.997726, 180.558698, 177.999897, 179.797983, 62379700],
]


def to_frame() -> pd.DataFrame:
    """Rebuild the exact frame yfinance 1.7.0 returned in the probe run."""
    index = pd.DatetimeIndex(pd.to_datetime(RECORDED_INDEX), name="Date")
    columns = pd.MultiIndex.from_tuples(
        RECORDED_COLUMNS,
        names=RECORDED_COLUMN_NAMES,
    )
    return pd.DataFrame(RECORDED_DATA, index=index, columns=columns)
