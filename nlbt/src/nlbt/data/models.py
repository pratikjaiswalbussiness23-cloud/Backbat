"""Bars data contract and provider protocol (ROADMAP P1-T1).

The Bars contract is a pandas DataFrame with exactly the lowercase OHLCV
columns, a sorted/unique tz-aware UTC ``DatetimeIndex`` and float64 values.
Enforcement lives in :func:`nlbt.data.validate.validate_bars_shape`, which
returns a ``Bars`` instance; ``Bars`` itself is a lightweight DataFrame
subclass so the type is runtime-checkable with ``isinstance`` and survives
pandas operations intact (verified on pandas 3.0.6 — see docs/verified_apis.md).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import ClassVar, Protocol, runtime_checkable

import pandas as pd
from pydantic import BaseModel, ConfigDict

__all__ = ["OHLCV_COLUMNS", "Bars", "BarsMeta", "DataProvider"]

#: The exact lowercase column contract (ROADMAP P1-T1).
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


class Bars(pd.DataFrame):
    """Validated OHLCV frame — the runtime-checkable form of the Bars contract.

    Guarantees (enforced by ``validate_bars_shape`` before any ``Bars`` is
    handed out):

    * exactly the five lowercase columns ``open high low close volume``
    * tz-aware UTC ``DatetimeIndex``, sorted ascending, unique
    * every column ``float64``
    * no NaN in OHLC (volume NaN tolerated); all prices > 0; ``high >= low``

    ``_metadata``/``_constructor`` keep the subclass alive through pandas
    operations so ``Bars``-ness survives slicing/selection.
    """

    # Preserved through pandas ops (pandas subclass contract). ClassVar keeps
    # ruff's mutable-default check (RUF012) satisfied; pandas reads the value.
    _metadata: ClassVar[list[str]] = []

    @property
    def _constructor(self) -> type[Bars]:
        return Bars


class BarsMeta(BaseModel):
    """Provenance metadata for a :class:`Bars` frame (P1-T1)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    symbol: str
    interval: str
    adjusted: bool
    timezone: str
    fetched_at: datetime
    source_notes: str = ""


@runtime_checkable
class DataProvider(Protocol):
    """Source of historical bars (P1-T1).

    A structural Protocol on purpose: providers (CSV, yfinance, parquet cache)
    inherit from nothing — they only need ``get_bars`` with this exact
    signature. ``runtime_checkable`` lets tests assert conformance via
    ``isinstance`` (method presence only; it does NOT validate types).
    """

    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str,
        adjusted: bool,
    ) -> tuple[Bars, BarsMeta]:
        """Return validated bars for ``symbol`` within ``[start, end]`` inclusive."""
        ...
