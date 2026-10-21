"""Deeper validate_bars_shape behaviour: context plumbing, details, normalisation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.data.validate import validate_bars_shape
from nlbt.errors import DataQualityError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "csv"


def _valid_frame() -> pd.DataFrame:
    raw = pd.read_csv(FIXTURES / "valid_daily.csv", dtype=str)
    parsed = pd.to_datetime(raw["date"], format="ISO8601", errors="raise", utc=True)
    raw = raw.drop(columns=["date"])
    raw.index = pd.DatetimeIndex(parsed)
    return raw.sort_index().astype("float64")


def test_context_is_prefixed_into_every_message() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(_valid_frame().drop(columns=["open"]), context="provider:file.csv")
    assert excinfo.value.message.startswith("provider:file.csv: ")


def test_no_context_means_no_prefix() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(_valid_frame().drop(columns=["open"]))
    assert not excinfo.value.message.startswith(": ")


def test_details_are_machine_readable_on_missing_columns() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(_valid_frame().drop(columns=["volume", "close"]), context="c")
    details = excinfo.value.details
    assert details["missing"] == ["close", "volume"]
    assert set(details["present"]) == {"open", "high", "low"}  # 'date' is the index, not a column


def test_non_datetime_index_raises() -> None:
    frame = _valid_frame().reset_index(drop=True)
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="c")
    assert "DatetimeIndex" in excinfo.value.message


def test_extra_column_raises_with_details() -> None:
    frame = _valid_frame().assign(adj_close=1.0)
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="c")
    assert excinfo.value.details["extra"] == ["adj_close"]


def test_numeric_int_columns_are_normalised_to_float64() -> None:
    frame = _valid_frame().astype({"volume": "int64"})
    result = validate_bars_shape(frame, context="c")
    assert str(result["volume"].dtype) == "float64"
    # Value-preserving normalisation.
    assert result["volume"].iloc[0] == 1_000_000.0


def test_unsorted_and_duplicate_are_reported_with_sample_rows() -> None:
    frame = pd.concat([_valid_frame(), _valid_frame().iloc[[1]]]).sort_index()
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="c")
    samples = excinfo.value.details["duplicates"]
    assert samples and all("2024-01-03" in sample for sample in samples)


def test_validator_is_idempotent_on_valid_bars() -> None:
    once = validate_bars_shape(_valid_frame(), context="c")
    twice = validate_bars_shape(once, context="c")
    assert isinstance(twice, Bars)
    assert once.equals(twice)


# ---------------------------------------- OQ-0065: strict OHLC bounds checks

BOUND_HINT = (
    "OHLC must be internally consistent: low <= min(open, close) <= max(open, close) <= high"
)


def test_fault_open_below_low_is_rejected() -> None:
    frame = _valid_frame()
    frame.iloc[0, frame.columns.get_loc("open")] = frame["low"].iloc[0] - 1.0  # 98 < 99
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="bounds")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert excinfo.value.details["count"] == 1
    assert excinfo.value.details["rows"][0].startswith("2024-01-02")
    assert excinfo.value.hint == BOUND_HINT


def test_fault_close_above_high_is_rejected() -> None:
    frame = _valid_frame()
    frame.iloc[0, frame.columns.get_loc("close")] = frame["high"].iloc[0] + 1.0  # 106 > 105
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="bounds")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert excinfo.value.details["count"] == 1
    assert excinfo.value.details["rows"][0].startswith("2024-01-02")
    assert excinfo.value.hint == BOUND_HINT


def test_fault_open_above_high_is_rejected() -> None:
    frame = _valid_frame()
    frame.iloc[0, frame.columns.get_loc("open")] = frame["high"].iloc[0] + 1.0  # 106 > 105
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="bounds")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert excinfo.value.details["count"] == 1
    assert excinfo.value.hint == BOUND_HINT


def test_fault_close_below_low_is_rejected() -> None:
    frame = _valid_frame()
    frame.iloc[0, frame.columns.get_loc("close")] = frame["low"].iloc[0] - 1.0  # 98 < 99
    with pytest.raises(DataQualityError) as excinfo:
        validate_bars_shape(frame, context="bounds")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert excinfo.value.details["count"] == 1
    assert excinfo.value.hint == BOUND_HINT


def test_boundary_open_close_at_low_high_bounds_pass() -> None:
    """Inclusive bounds: open/close exactly equal to low/high (either order) is valid."""
    frame = _valid_frame()
    frame.iloc[0, frame.columns.get_loc("open")] = frame["low"].iloc[0]  # open == low
    frame.iloc[0, frame.columns.get_loc("close")] = frame["high"].iloc[0]  # close == high
    frame.iloc[1, frame.columns.get_loc("open")] = frame["high"].iloc[1]  # open == high
    frame.iloc[1, frame.columns.get_loc("close")] = frame["low"].iloc[1]  # close == low
    result = validate_bars_shape(frame, context="bounds")
    assert isinstance(result, Bars)
    assert result.attrs["nlbt_validated"] is True
