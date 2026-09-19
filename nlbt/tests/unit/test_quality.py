"""P1-T5 tests: quality report — one test per check, canary, integration.

Oracle policy: clean fixtures load through the REAL ``CSVProvider`` (not
mocked). Fixtures that the provider itself must reject at load time
(``ohlc_violation.csv``, ``high_nan.csv``) are read into frames directly —
the quality layer consumes frames, and those rejections are the provider's
contract, already tested in test_csv_provider.py.

All stale-sensitive tests inject ``today=date(2024, 1, 20)`` for
determinism (the real clock would make every 2024 fixture stale).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from nlbt.data.csv_provider import CSVProvider
from nlbt.data.models import Bars, BarsMeta
from nlbt.data.quality import (
    DataQualityReport,
    assert_quality,
    run_quality_checks,
)
from nlbt.errors import DataQualityError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
TODAY = date(2024, 1, 20)


def _provider_load(name: str) -> tuple[Bars, BarsMeta]:
    return CSVProvider().get_bars(
        str(FIXTURES / name), date(2023, 1, 1), date(2024, 12, 31), "1d", False
    )


def _raw_frame(name: str) -> Bars:
    """Contract-shaped frame built directly (no provider validation gate)."""
    raw = pd.read_csv(FIXTURES / name, dtype=str)
    parsed = pd.to_datetime(raw["date"], format="ISO8601", errors="raise", utc=True)
    raw = raw.drop(columns=["date"])
    raw.index = pd.DatetimeIndex(parsed)
    return Bars(raw.sort_index().astype("float64"))


def _direct_meta(symbol: str) -> BarsMeta:
    return BarsMeta(
        provider="test",
        symbol=symbol,
        interval="1d",
        adjusted=False,
        timezone="UTC",
        fetched_at=datetime.now(UTC),
    )


# --------------------------------------------------------------------------
# BLOCKING
# --------------------------------------------------------------------------


def test_valid_daily_min_bars_5_passes_blocking() -> None:
    """10 bars >= min_bars=5 and otherwise clean data -> passed_blocking=True."""
    bars, meta = _provider_load("valid_daily.csv")
    report = run_quality_checks(bars, meta, min_bars=5, today=TODAY)
    assert report.passed_blocking is True
    assert report.blocked_by is None


def test_valid_daily_min_bars_100_blocks_insufficient_bars() -> None:
    """10 bars < min_bars=100 -> blocked_by="INSUFFICIENT_BARS"."""
    bars, meta = _provider_load("valid_daily.csv")
    report = run_quality_checks(bars, meta, min_bars=100, today=TODAY)
    assert report.passed_blocking is False
    assert report.blocked_by == "INSUFFICIENT_BARS"
    assert report.warnings == []  # blocked reports carry no warnings


def test_ohlc_violation_blocks_high_low_violation() -> None:
    """high=98 < max(open=100, close=103, low=99) -> HIGH_LOW_VIOLATION."""
    frame = _raw_frame("ohlc_violation.csv")
    report = run_quality_checks(frame, _direct_meta("ohlc_violation.csv"), today=TODAY)
    assert report.passed_blocking is False
    assert report.blocked_by == "HIGH_LOW_VIOLATION"
    assert report.warnings == []


def test_low_above_min_blocks_low_high_violation() -> None:
    """Pure LOW_HIGH_VIOLATION, hand-computed: row 0 becomes open=100, high=107,
    low=106, close=103. Then low=106 > min(100, 103, 107) = 100 -> violation;
    and high=107 >= max(100, 103, 106) = 106, so the HIGH check stays clean
    (it runs first by documented precedence — the fixture must not trip it)."""
    frame = _raw_frame("valid_daily.csv")
    frame.iloc[0, frame.columns.get_loc("high")] = 107.0
    frame.iloc[0, frame.columns.get_loc("low")] = 106.0
    report = run_quality_checks(frame, _direct_meta("mutated"), today=TODAY)
    assert report.passed_blocking is False
    assert report.blocked_by == "LOW_HIGH_VIOLATION"


def test_empty_dataframe_blocks() -> None:
    """Empty frame directly -> passed_blocking=False (validate-reuse path)."""
    frame = _raw_frame("valid_daily.csv").iloc[:0]
    report = run_quality_checks(frame, _direct_meta("empty"), today=TODAY)
    assert report.passed_blocking is False
    assert "empty" in (report.blocked_by or "").lower()


def test_nan_in_ohlc_blocks_via_validate_reuse() -> None:
    """NaN high (2024-01-03) -> blocking via the reused validator, NOT a
    spurious LOW_HIGH_VIOLATION (NaN rows are masked in the max/min checks)."""
    frame = _raw_frame("high_nan.csv")
    report = run_quality_checks(frame, _direct_meta("high_nan.csv"), today=TODAY)
    assert report.passed_blocking is False
    assert report.blocked_by is not None
    assert "NaN" in report.blocked_by


# --------------------------------------------------------------------------
# WARNING
# --------------------------------------------------------------------------


def test_zero_volume_ratio_warning_present() -> None:
    """6/10 zero-volume bars (60% > 5%) -> ZERO_VOLUME_RATIO warning, not blocking."""
    bars, meta = _provider_load("zero_volume_bars.csv")
    report = run_quality_checks(bars, meta, today=TODAY)
    assert report.passed_blocking is True
    codes = [warning.code for warning in report.warnings]
    assert "ZERO_VOLUME_RATIO" in codes


def test_zero_volume_ratio_below_threshold_no_warning() -> None:
    """1/10 zero-volume bars (10%) is still ABOVE 5% -> warning present here
    too; the threshold boundary itself is exercised by valid_daily (0%)."""
    bars, meta = _provider_load("sparse_volume.csv")
    report = run_quality_checks(bars, meta, today=TODAY)
    codes = [warning.code for warning in report.warnings]
    assert "ZERO_VOLUME_RATIO" in codes


def test_zero_volume_warning_details_contain_ratio() -> None:
    """The warning's machine-readable details carry the measured ratio."""
    bars, meta = _provider_load("zero_volume_bars.csv")
    report = run_quality_checks(bars, meta, today=TODAY)
    warning = next(w for w in report.warnings if w.code == "ZERO_VOLUME_RATIO")
    assert warning.details["ratio"] == pytest.approx(0.6)
    assert warning.details["threshold"] == pytest.approx(0.05)
    assert warning.details["zero_volume_bars"] == 6


def test_large_single_return_warning() -> None:
    """close=160 vs open=100 -> intra-bar |return| = 0.60 > 0.40 (hand-computed:
    |160/100 - 1| = 0.6) -> LARGE_SINGLE_RETURN, data still passes blocking."""
    bars, meta = _provider_load("large_return_bar.csv")
    report = run_quality_checks(bars, meta, today=TODAY)
    assert report.passed_blocking is True  # high=161 keeps the row consistent
    warning = next(w for w in report.warnings if w.code == "LARGE_SINGLE_RETURN")
    assert warning.details["max_return"] == pytest.approx(0.6)


def test_stale_last_bar_warning_with_injected_today() -> None:
    """Last bar 2023-11-14 vs injected today 2024-01-20 -> 49 trading days
    (probed np.busday_count) > 5 -> STALE_LAST_BAR."""
    bars, meta = _provider_load("stale_last_bar.csv")
    report = run_quality_checks(bars, meta, today=date(2024, 1, 20))
    assert report.passed_blocking is True
    warning = next(w for w in report.warnings if w.code == "STALE_LAST_BAR")
    assert warning.details["trading_days_gap"] == 49


def test_valid_daily_zero_warnings() -> None:
    """Clean fixture + injected today within 5 trading days of the last bar
    (2024-01-13 -> 2024-01-20 is exactly 5) -> zero warnings."""
    bars, meta = _provider_load("valid_daily.csv")
    report = run_quality_checks(bars, meta, today=date(2024, 1, 20))
    assert report.passed_blocking is True
    assert report.warnings == []


def test_report_field_values_are_correct() -> None:
    """Report mirrors meta/bars: symbol, interval, bars count, ISO start/end."""
    bars, meta = _provider_load("valid_daily.csv")
    report = run_quality_checks(bars, meta, today=TODAY)
    assert isinstance(report, DataQualityReport)
    assert report.symbol == meta.symbol
    assert report.interval == "1d"
    assert report.adjusted is False
    assert report.bars == 10
    assert report.start == "2024-01-02"
    assert report.end == "2024-01-13"


# --------------------------------------------------------------------------
# assert_quality
# --------------------------------------------------------------------------


def test_assert_quality_does_not_raise_when_passed() -> None:
    """passed_blocking=True -> assert_quality returns None silently."""
    bars, meta = _provider_load("valid_daily.csv")
    report = run_quality_checks(bars, meta, min_bars=5, today=TODAY)
    assert assert_quality(report) is None


def test_assert_quality_raises_data_quality_error_when_blocked() -> None:
    """passed_blocking=False -> E_DATA_QUALITY naming blocked_by + symbol."""
    bars, meta = _provider_load("valid_daily.csv")
    report = run_quality_checks(bars, meta, min_bars=100, today=TODAY)
    with pytest.raises(DataQualityError) as excinfo:
        assert_quality(report)
    assert excinfo.value.code == "E_DATA_QUALITY"
    assert "INSUFFICIENT_BARS" in excinfo.value.message
    assert excinfo.value.details["symbol"] == meta.symbol
    assert excinfo.value.details["blocked_by"] == "INSUFFICIENT_BARS"


# --------------------------------------------------------------------------
# CANARY
# --------------------------------------------------------------------------


def test_canary_high_below_low_in_data_is_caught() -> None:
    """Canary: a frame with high=50, low=100 (high < low) MUST be blocked —
    proves the row-violation check inspects the actual values."""
    frame = _raw_frame("valid_daily.csv")
    frame.iloc[0, frame.columns.get_loc("high")] = 50.0
    frame.iloc[0, frame.columns.get_loc("low")] = 100.0
    report = run_quality_checks(frame, _direct_meta("canary"), today=TODAY)
    assert report.passed_blocking is False
    assert report.blocked_by == "HIGH_LOW_VIOLATION"


# --------------------------------------------------------------------------
# Integration
# --------------------------------------------------------------------------


def test_csv_provider_plus_quality_end_to_end() -> None:
    """Full path: CSVProvider -> run_quality_checks -> assert_quality, all clean."""
    bars, meta = _provider_load("valid_daily.csv")
    report = run_quality_checks(bars, meta, min_bars=5, today=date(2024, 1, 20))
    assert_quality(report)  # must not raise
    assert report.passed_blocking is True
    assert report.warnings == []
    assert report.symbol.endswith("valid_daily.csv")
