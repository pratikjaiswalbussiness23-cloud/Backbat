"""P1-T1 acceptance tests: Bars contract, BarsMeta model, DataProvider Protocol.

Fault-type tests here follow the acceptance list (one test per fault, exact
error code asserted); deeper validator behaviour lives in
test_data_validate.py, provider behaviour in test_csv_provider.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from nlbt.data.models import OHLCV_COLUMNS, Bars, BarsMeta, DataProvider
from nlbt.data.validate import validate_bars_shape
from nlbt.errors import DataQualityError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "csv"

VALID_META_KWARGS: dict[str, Any] = {
    "provider": "csv",
    "symbol": "tests/fixtures/csv/valid_daily.csv",
    "interval": "1d",
    "adjusted": False,
    "timezone": "UTC",
    "fetched_at": datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC),
}


def _valid_frame() -> pd.DataFrame:
    """Build the fixture frame directly (independent of CSVProvider)."""
    raw = pd.read_csv(FIXTURES / "valid_daily.csv", dtype=str)
    parsed = pd.to_datetime(raw["date"], format="ISO8601", errors="raise", utc=True)
    raw = raw.drop(columns=["date"])
    raw.index = pd.DatetimeIndex(parsed)
    return raw.sort_index().astype("float64")


# ---------------------------------------------------------------- BarsMeta


def test_barsmeta_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BarsMeta(**VALID_META_KWARGS, not_a_field="nope")
    assert "not_a_field" in str(excinfo.value)


@pytest.mark.parametrize(
    "mandatory",
    ["provider", "symbol", "interval", "adjusted", "timezone", "fetched_at"],
)
def test_barsmeta_requires_all_mandatory_fields(mandatory: str) -> None:
    kwargs = {key: value for key, value in VALID_META_KWARGS.items() if key != mandatory}
    with pytest.raises(ValidationError) as excinfo:
        BarsMeta(**kwargs)
    assert mandatory in str(excinfo.value)


def test_barsmeta_source_notes_defaults_to_empty() -> None:
    meta = BarsMeta(**VALID_META_KWARGS)
    assert meta.source_notes == ""


def test_barsmeta_parses_iso_datetime_and_keeps_tz() -> None:
    meta = BarsMeta(**{**VALID_META_KWARGS, "fetched_at": "2026-09-19T12:00:00+00:00"})
    assert isinstance(meta.fetched_at, datetime)
    assert meta.fetched_at.tzinfo is not None


# ------------------------------------------------------------- DataProvider


def test_dataprovider_is_a_protocol_not_abstract_class() -> None:
    from abc import ABC
    from typing import Protocol

    assert issubclass(DataProvider, Protocol)
    assert not issubclass(DataProvider, ABC)
    with pytest.raises(TypeError):
        DataProvider()  # type: ignore[abstract] # Protocols cannot be instantiated


def test_runtime_checkable_protocol_accepts_only_get_bars_implementations() -> None:
    class WithGetBars:
        def get_bars(
            self, symbol: str, start: Any, end: Any, interval: str, adjusted: bool
        ) -> tuple:
            return (), None

    class WithoutGetBars:
        pass

    assert isinstance(WithGetBars(), DataProvider)
    assert not isinstance(WithoutGetBars(), DataProvider)


# ------------------------------------------------------ validate_bars_shape


def test_validate_passes_on_valid_daily_fixture() -> None:
    result = validate_bars_shape(_valid_frame(), context="valid_daily.csv")
    assert isinstance(result, Bars)
    assert list(result.columns) == list(OHLCV_COLUMNS)
    assert result.attrs["nlbt_validated"] is True


def test_fault_not_a_dataframe_raises_exact_code() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape([1, 2, 3], context="f1")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert "f1" in excinfo.value.message


def test_fault_missing_column_raises_exact_code() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(_valid_frame().drop(columns=["volume"]), context="f2")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert excinfo.value.details["missing"] == ["volume"]


def test_fault_wrong_dtype_raises_exact_code() -> None:
    frame = _valid_frame().assign(close=_valid_frame()["close"].astype("string"))
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="f3")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert excinfo.value.details["columns"][0]["column"] == "close"


def test_fault_unsorted_index_raises_exact_code() -> None:
    frame = _valid_frame().iloc[[3, 1, 0, 2, 4, 5, 6, 7, 8, 9]]  # fixed permutation
    assert not frame.index.is_monotonic_increasing
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="f4")
    assert excinfo.value.code == "E_DATA_QUALITY"


def test_fault_duplicate_index_raises_exact_code() -> None:
    frame = pd.concat([_valid_frame(), _valid_frame().iloc[[1]]]).sort_index()
    assert frame.index.duplicated().any()
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="f5")
    assert excinfo.value.code == "E_DATA_QUALITY"


def test_fault_empty_frame_raises_exact_code() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(_valid_frame().iloc[:0], context="f6")
    assert excinfo.value.code == "E_DATA_QUALITY"


def test_fault_nonpositive_price_raises_exact_code() -> None:
    frame = _valid_frame()
    frame.iloc[0, frame.columns.get_loc("close")] = -5.0
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="f7")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert "non-positive" in excinfo.value.message


def test_fault_high_below_low_raises_exact_code() -> None:
    frame = _valid_frame()
    frame.iloc[2, frame.columns.get_loc("high")] = 90.0  # low that day is 104.0
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="f8")
    assert excinfo.value.code == "E_DATA_QUALITY"


def test_fault_nan_in_ohlc_raises_exact_code() -> None:
    frame = _valid_frame()
    frame.iloc[3, frame.columns.get_loc("open")] = float("nan")
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="f9")
    assert excinfo.value.code == "E_DATA_QUALITY"


def test_volume_nan_is_tolerated() -> None:
    frame = _valid_frame()
    frame.iloc[0, frame.columns.get_loc("volume")] = float("nan")
    result = validate_bars_shape(frame, context="tolerated")
    assert isinstance(result, Bars)
