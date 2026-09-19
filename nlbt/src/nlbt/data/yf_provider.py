"""yfinance data provider (P1-T3).

yfinance is an unofficial API. It may break without notice.
Data quality varies. Not suitable for production or redistribution
without checking the provider's terms of use.

Verified against the INSTALLED yfinance 1.7.0 before implementation
(docs/verified_apis.md): ``download`` returns MultiIndex columns
``[('Close', ticker), ...]`` (level names ``['Price', 'Ticker']``), Volume is
``int64``, the index is a tz-naive ``DatetimeIndex`` named ``Date``, and the
``end`` parameter is EXCLUSIVE — nlbt's contract is inclusive, so ``end`` is
shifted one day here and the result is defensively re-sliced.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pandas as pd
import requests
import yfinance as yf

from nlbt.data.models import OHLCV_COLUMNS, Bars, BarsMeta
from nlbt.data.validate import validate_bars_shape
from nlbt.errors import DataEmptyError, DataProviderError

__all__ = ["YFinanceProvider"]

#: P1-T3: retry network failures up to 3 attempts with a 2 second backoff.
_MAX_ATTEMPTS: int = 3
_DEFAULT_BACKOFF_SECONDS: float = 2.0

#: Exceptions treated as retryable network failures (yfinance uses requests).
_NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    requests.exceptions.RequestException,
    TimeoutError,
    OSError,
)


class YFinanceProvider:
    """:class:`nlbt.data.models.DataProvider` backed by Yahoo Finance.

    Unit tests never touch the network: they patch the ``yf.download``
    boundary (and only that boundary) with recorded responses.
    """

    def __init__(self, backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS) -> None:
        self.backoff_seconds = backoff_seconds

    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "1d",
        adjusted: bool = False,
    ) -> tuple[Bars, BarsMeta]:
        """Fetch, normalise, slice and validate OHLCV bars for ``symbol``.

        Error mapping (P1-T3): empty result → ``E_DATA_EMPTY``; network/timeout
        (retried up to 3 attempts) → ``E_DATA_PROVIDER``; any other error →
        ``E_DATA_PROVIDER``.
        """
        raw_frame = self._download_with_retry(symbol, start, end, interval, adjusted)

        if raw_frame is None or raw_frame.empty:
            raise DataEmptyError(
                f"yfinance returned no rows for {symbol}",
                details={
                    "symbol": symbol,
                    "start": str(start),
                    "end": str(end),
                    "interval": interval,
                },
                hint="check the ticker spelling and the requested date range",
            )

        frame = _normalise(raw_frame, symbol)
        frame = _slice_inclusive(frame, start, end)
        if frame.empty:
            raise DataEmptyError(
                f"yfinance returned no rows for {symbol} within [{start}, {end}]",
                details={"symbol": symbol, "start": str(start), "end": str(end)},
            )

        bars = validate_bars_shape(frame, context=f"yfinance:{symbol}")
        meta = BarsMeta(
            provider="yfinance",
            symbol=symbol,
            interval=interval,
            adjusted=adjusted,
            timezone="UTC",
            fetched_at=datetime.now(UTC),
            source_notes="unofficial API, data quality varies",
        )
        return bars, meta

    def _download_with_retry(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str,
        adjusted: bool,
    ) -> pd.DataFrame | None:
        """Call ``yf.download``, retrying network failures (max 3 attempts)."""
        # Verified: yfinance's end is EXCLUSIVE; nlbt's contract is inclusive.
        yf_end_exclusive = (end + timedelta(days=1)).isoformat()
        raw_frame: pd.DataFrame | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                raw_frame = cast(
                    "pd.DataFrame | None",
                    yf.download(
                        tickers=symbol,
                        start=start.isoformat(),
                        end=yf_end_exclusive,
                        interval=interval,
                        auto_adjust=adjusted,
                        progress=False,
                        threads=False,
                    ),
                )
                break
            except _NETWORK_ERRORS as exc:
                if attempt >= _MAX_ATTEMPTS:
                    raise DataProviderError(
                        f"yfinance network failure for {symbol} after {attempt} attempts",
                        details={
                            "symbol": symbol,
                            "attempts": attempt,
                            "reason": str(exc),
                        },
                    ) from exc
                time.sleep(self.backoff_seconds)
            except Exception as exc:  # any other error: no retry (P1-T3)
                raise DataProviderError(
                    f"yfinance call failed for {symbol}",
                    details={"symbol": symbol, "reason": str(exc)},
                ) from exc
        if raw_frame is None:  # defensive: loop always breaks or raises
            raise DataProviderError(
                f"yfinance returned no data object for {symbol}",
                details={"symbol": symbol},
            )
        return raw_frame


def _normalise(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Flatten MultiIndex columns, lowercase, keep exactly the 5 OHLCV columns."""
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        # Verified structure: level 0 = Price names, level 1 = ticker(s).
        frame.columns = frame.columns.get_level_values(0)
    frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
    missing = [col for col in OHLCV_COLUMNS if col not in frame.columns]
    if missing:
        raise DataProviderError(
            f"yfinance response for {symbol} is missing column(s) {missing}",
            details={
                "symbol": symbol,
                "missing": missing,
                "present": [str(col) for col in frame.columns],
            },
        )
    return frame[list(OHLCV_COLUMNS)]  # drop dividends/splits and any extras


def _slice_inclusive(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """UTC-normalise the index and keep rows in inclusive [start, end]."""
    frame = frame.sort_index()
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        raise DataProviderError(
            "yfinance response index is not a DatetimeIndex",
            details={"actual_index_type": type(index).__name__},
        )
    if index.tz is None:
        frame.index = index.tz_localize("UTC")
    else:
        frame.index = index.tz_convert("UTC")
    start_ts = pd.Timestamp(start, tz="UTC")
    end_exclusive = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return frame[(frame.index >= start_ts) & (frame.index < end_exclusive)]
