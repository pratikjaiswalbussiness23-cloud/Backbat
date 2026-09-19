"""P1-T2 acceptance tests: CSVProvider behaviour against the six fixtures."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from nlbt.data.csv_provider import CSVProvider
from nlbt.data.models import Bars, DataProvider
from nlbt.errors import DataQualityError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
FULL_RANGE = (date(2024, 1, 1), date(2024, 12, 31))


def _load(name: str) -> tuple[Bars, object]:
    provider = CSVProvider()
    return provider.get_bars(str(FIXTURES / name), *FULL_RANGE, "1d", False)  # type: ignore[arg-type] # tests accept Bars|DataFrame tuple


def test_loads_valid_daily_correct_shape() -> None:
    bars, meta = _load("valid_daily.csv")
    assert bars.shape == (10, 5)
    assert isinstance(bars, Bars)
    assert meta.provider == "csv"  # type: ignore[attr-defined] # narrowed via tuple typing above


def test_index_is_sorted_utc_datetimeindex() -> None:
    bars, _ = _load("valid_daily.csv")
    assert isinstance(bars.index, pd.DatetimeIndex)
    assert bars.index.is_monotonic_increasing
    assert bars.index.tz is not None
    assert bars.index[0] == pd.Timestamp("2024-01-02", tz="UTC")
    assert bars.index[-1] == pd.Timestamp("2024-01-13", tz="UTC")


def test_columns_are_exactly_lowercase_ohlcv() -> None:
    bars, _ = _load("valid_daily.csv")
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]


def test_all_dtypes_are_float64() -> None:
    bars, _ = _load("valid_daily.csv")
    assert (bars.dtypes == "float64").all()


def test_meta_fields_for_csv_provider() -> None:
    _, meta = _load("valid_daily.csv")
    assert meta.provider == "csv"
    assert meta.adjusted is False
    assert meta.timezone == "UTC"
    assert meta.interval == "1d"
    assert isinstance(meta.fetched_at, datetime)
    assert meta.fetched_at.tzinfo is not None


def test_header_variants_map_to_canonical_names() -> None:
    # Write a variant-header CSV in tmp_path using the fixture's real values.
    source = (FIXTURES / "valid_daily.csv").read_text(encoding="utf-8")
    lines = source.strip().splitlines()
    swapped = ["Date,Open,High,Low,Adj Close,Volume", *lines[1:]]
    variant_path = FIXTURES.parent / "csv_variant_tmp.csv"
    try:
        variant_path.write_text("\n".join(swapped) + "\n", encoding="utf-8")
        provider = CSVProvider()
        bars, _ = provider.get_bars(
            str(variant_path), date(2024, 1, 1), date(2024, 12, 31), "1d", False
        )
        assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
        assert bars["close"].iloc[0] == 103.0  # from the real fixture's Adj Close column
    finally:
        variant_path.unlink(missing_ok=True)


def test_missing_column_raises_exact_code() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        _load("missing_column.csv")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert "missing_column.csv" in excinfo.value.message
    assert "volume" in excinfo.value.details["missing"]


def test_duplicate_dates_raises_exact_code() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        _load("duplicate_dates.csv")
    assert excinfo.value.code == "E_DATA_QUALITY"


def test_bad_dates_raises_exact_code() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        _load("bad_dates.csv")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert "not-a-date" in str(excinfo.value.details["bad_values"])


def test_negative_prices_raises_exact_code() -> None:
    with pytest.raises(DataQualityError) as excinfo:
        _load("negative_prices.csv")
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert "non-positive" in excinfo.value.message


def test_unsorted_dates_does_not_raise_and_matches_sorted_valid_load() -> None:
    unsorted_bars, _ = _load("unsorted_dates.csv")  # must not raise
    valid_bars, _ = _load("valid_daily.csv")
    assert unsorted_bars.index.is_monotonic_increasing
    assert unsorted_bars.equals(valid_bars)


def test_two_loads_are_identical() -> None:
    bars_a, meta_a = _load("valid_daily.csv")
    bars_b, meta_b = _load("valid_daily.csv")
    assert bars_a.equals(bars_b)
    assert meta_a.provider == meta_b.provider
    assert meta_a.symbol == meta_b.symbol
    assert meta_a.interval == meta_b.interval
    assert meta_a.adjusted == meta_b.adjusted
    assert meta_a.timezone == meta_b.timezone
    # fetched_at intentionally NOT compared: wall-clock differs between loads.


def test_date_range_slice_is_inclusive_on_both_ends() -> None:
    provider = CSVProvider()
    bars, _ = provider.get_bars(
        str(FIXTURES / "valid_daily.csv"), date(2024, 1, 4), date(2024, 1, 10), "1d", False
    )
    assert list(bars.index.date) == [
        date(2024, 1, 4),
        date(2024, 1, 5),
        date(2024, 1, 6),
        date(2024, 1, 9),
        date(2024, 1, 10),
    ]


def test_range_outside_file_raises_empty() -> None:
    provider = CSVProvider()
    with pytest.raises(DataQualityError) as excinfo:
        provider.get_bars(
            str(FIXTURES / "valid_daily.csv"), date(2030, 1, 1), date(2030, 12, 31), "1d", False
        )
    assert excinfo.value.code == "E_DATA_QUALITY"


def test_nonexistent_path_raises_exact_code() -> None:
    provider = CSVProvider()
    with pytest.raises(DataQualityError) as excinfo:
        provider.get_bars(str(FIXTURES / "nope.csv"), *FULL_RANGE, "1d", False)
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert "not found" in excinfo.value.message


def test_adjusted_request_is_recorded_but_csv_stays_unadjusted() -> None:
    provider = CSVProvider()
    _, meta = provider.get_bars(str(FIXTURES / "valid_daily.csv"), *FULL_RANGE, "1d", True)
    assert meta.adjusted is False
    assert "unadjusted" in meta.source_notes


def test_csvprovider_satisfies_dataprovider_protocol() -> None:
    assert isinstance(CSVProvider(), DataProvider)
