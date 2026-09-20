"""P1-T6 acceptance tests: frequency and ``bars_per_year`` inference.

Every expected value is hand-computed with the arithmetic shown in the test
docstring (AGENTS.md R4 / ROADMAP §2A R4). Frames are built directly as
``Bars`` over hand-crafted ``DatetimeIndex`` data (precedent:
``test_quality._raw_frame``) or loaded through the REAL ``CSVProvider``
(test 7). Frequency inference reads the index only, so directly-constructed
frames carry constant placeholder OHLCV values.

Metric under test (module docstring of ``nlbt/data/frequency.py``;
OQ-0011/OQ-0012 record the two task-text deviations and their evidence):

* ``median_gap_days``  = median of consecutive index day differences
* ``trading_days_per_week`` = MEDIAN of per-ISO-week bar counts (the task's
  "mean" wording makes its own test 8 unsatisfiable — shown arithmetically
  in :func:`test_consecutive_daily_bars_are_crypto`)
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nlbt.data.csv_provider import CSVProvider
from nlbt.data.frequency import BarFrequency, infer_frequency
from nlbt.data.models import OHLCV_COLUMNS, Bars

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "csv"

#: Every fixture CSV in tests/fixtures/csv (property test 10 covers all).
ALL_FIXTURES: list[str] = [
    "bad_dates.csv",
    "duplicate_dates.csv",
    "high_nan.csv",
    "large_return_bar.csv",
    "missing_column.csv",
    "negative_prices.csv",
    "ohlc_violation.csv",
    "sparse_volume.csv",
    "stale_last_bar.csv",
    "unsorted_dates.csv",
    "valid_daily.csv",
    "zero_volume_bars.csv",
]


def _bars_with_index(index: pd.DatetimeIndex) -> Bars:
    """Bars over *index* with constant placeholder values (frequency is index-only)."""
    return Bars(pd.DataFrame(1.0, index=index, columns=list(OHLCV_COLUMNS)))


def _equity_index() -> pd.DatetimeIndex:
    """260 Mon-Fri bars: 2023-01-02 (Mon) .. 2023-12-29 (Fri), ISO weeks 1..52."""
    all_days = pd.date_range("2023-01-02", periods=364, freq="D", tz="UTC")
    return all_days[all_days.weekday < 5]


# --------------------------------------------------------------------------
# 1. Daily equity detection
# --------------------------------------------------------------------------


def test_daily_equity_detection() -> None:
    """260 Mon-Fri bars over 52 ISO weeks -> DAILY_EQUITY, bars_per_year 252.

    Arithmetic (trading_days_per_week = median bars per ISO week):
    2023-01-02 is a Monday; 364 consecutive days end 2023-12-31 (Sunday) and
    cover ISO weeks 2023-W01..W52 exactly (52 x 7 = 364). Keeping weekdays
    < 5 leaves 52 weeks x 5 bars = 260, so every ISO-week count is 5 and the
    median is 5.0. Median gap: 259 gaps = 208 x 1 day (Mon-Tue .. Thu-Fri,
    4 per week x 52) + 51 x 3 days (Fri-Mon between weeks); sorted, the
    130th of 259 values (the median) falls in the 208 ones -> 1.0 day.
    5.0 >= 4.0 (and < 6.5) -> DAILY_EQUITY, bars_per_year = 252.
    """
    result = infer_frequency(_bars_with_index(_equity_index()), "1d")
    assert result.frequency is BarFrequency.DAILY_EQUITY
    assert result.bars_per_year == 252.0
    assert result.trading_days_per_week == 5.0
    assert result.median_gap_days == 1.0
    assert result.warning is None
    assert result.inferred is True


# --------------------------------------------------------------------------
# 2. Daily crypto detection
# --------------------------------------------------------------------------


def test_daily_crypto_detection() -> None:
    """364 consecutive daily bars (52 ISO weeks x 7) -> DAILY_CRYPTO, 365.25.

    Arithmetic: 2023-01-02 (Mon) + 364 days ends 2023-12-31 (Sun); 364 =
    52 x 7, so each ISO week 2023-W01..W52 holds exactly 7 bars -> median
    count = 7.0. Gaps: 363 consecutive differences, all 1 day -> median
    gap = 1.0. 7.0 >= 6.5 -> DAILY_CRYPTO, bars_per_year = 365.25.
    """
    index = pd.date_range("2023-01-02", periods=364, freq="D", tz="UTC")
    result = infer_frequency(_bars_with_index(index), "1d")
    assert result.frequency is BarFrequency.DAILY_CRYPTO
    assert result.bars_per_year == 365.25
    assert result.trading_days_per_week == 7.0
    assert result.median_gap_days == 1.0
    assert result.warning is None


# --------------------------------------------------------------------------
# 3. Weekly detection
# --------------------------------------------------------------------------


def test_weekly_detection() -> None:
    """52 Mondays, one bar per ISO week -> WEEKLY, 52, warning not None.

    Arithmetic: Mondays 2023-01-02 .. 2023-12-25 (periods=52, freq=7D) fall
    one-per-week into ISO weeks 2023-W01..W52 -> every count is 1, median =
    1.0. Median gap: 51 consecutive differences, all 7 days -> 7.0. The
    1.0 bars/week is below the 3.0 sparse-daily threshold, so classification
    goes through the weekly-spacing branch (median gap 7.0 >= 5.5, OQ-0012)
    -> WEEKLY, bars_per_year = 52, warning not None.
    """
    index = pd.date_range("2023-01-02", periods=52, freq="7D", tz="UTC")
    result = infer_frequency(_bars_with_index(index), "1d")
    assert result.frequency is BarFrequency.WEEKLY
    assert result.bars_per_year == 52.0
    assert result.trading_days_per_week == 1.0
    assert result.median_gap_days == 7.0
    assert result.warning is not None


# --------------------------------------------------------------------------
# 4. Override supplied
# --------------------------------------------------------------------------


def test_override_supplied() -> None:
    """override_bars_per_year=365.0 wins: bars_per_year 365.0, inferred=False.

    Arithmetic: the override branch returns the supplied value verbatim
    (365.0), never replaces it, and performs NO classification -> frequency
    UNKNOWN, warning None, inferred False. The data statistics are still
    computed from the actual index: the 260 Mon-Fri bars of test 1 give
    median gap 1.0 and median bars/ISO week 5.0.
    """
    result = infer_frequency(_bars_with_index(_equity_index()), "1d", 365.0)
    assert result.bars_per_year == 365.0
    assert result.inferred is False
    assert result.frequency is BarFrequency.UNKNOWN
    assert result.warning is None
    assert result.median_gap_days == 1.0
    assert result.trading_days_per_week == 5.0


# --------------------------------------------------------------------------
# 5. Unknown interval
# --------------------------------------------------------------------------


def test_unknown_interval() -> None:
    """interval='1h' -> UNKNOWN, conservative 252, warning set, inferred=True.

    Arithmetic: non-'1d' intervals take the not-supported branch, which
    emits bars_per_year = 252.0 (the documented conservative default of
    that branch — not a silent hardcode) and a warning naming the interval.
    The statistics still come from the index: 260 Mon-Fri bars -> gap 1.0,
    5.0 bars per ISO week (test 1).
    """
    result = infer_frequency(_bars_with_index(_equity_index()), "1h")
    assert result.frequency is BarFrequency.UNKNOWN
    assert result.warning is not None
    assert result.bars_per_year == 252.0
    assert result.inferred is True
    assert "1h" in result.warning


# --------------------------------------------------------------------------
# 6. Insufficient bars (1 row)
# --------------------------------------------------------------------------


def test_insufficient_bars_single_row() -> None:
    """1 row -> UNKNOWN, 252, warning, median_gap_days 0.0, bars/week 0.0.

    Arithmetic: with a single bar there are 0 consecutive gaps -> the
    median is undefined -> 0.0 by the task's edge-case rule; likewise 0
    ISO-week counts -> 0.0. No classification is possible -> UNKNOWN with
    the conservative 252 and the insufficient-bars warning.
    """
    index = pd.DatetimeIndex([pd.Timestamp("2024-01-02", tz="UTC")])
    result = infer_frequency(_bars_with_index(index), "1d")
    assert result.frequency is BarFrequency.UNKNOWN
    assert result.warning is not None
    assert result.median_gap_days == 0.0
    assert result.trading_days_per_week == 0.0
    assert result.bars_per_year == 252.0
    assert result.inferred is True


# --------------------------------------------------------------------------
# 7. valid_daily.csv through the real provider
# --------------------------------------------------------------------------


def test_valid_daily_fixture_is_daily_equity() -> None:
    """valid_daily.csv (10 rows, Tue-Sat over 2 ISO weeks) -> DAILY_EQUITY.

    Arithmetic (loaded through the real CSVProvider): rows are
    2024-01-02..06 and 2024-01-09..13. ISO 2024-W01 = Jan 1-7 holds Jan 2,
    3, 4, 5, 6 -> 5 bars; ISO 2024-W02 = Jan 8-14 holds Jan 9, 10, 11, 12,
    13 -> 5 bars. Counts [5, 5] -> median 5.0 >= 4.0 -> DAILY_EQUITY,
    bars_per_year = 252.
    """
    bars, _ = CSVProvider().get_bars(
        str(FIXTURES / "valid_daily.csv"), date(2023, 1, 1), date(2024, 12, 31), "1d", False
    )
    result = infer_frequency(bars, "1d")
    assert result.frequency is BarFrequency.DAILY_EQUITY
    assert result.bars_per_year == 252.0
    assert result.trading_days_per_week == 5.0
    assert result.warning is None


# --------------------------------------------------------------------------
# 8. Crypto-like fixture (30 consecutive daily bars)
# --------------------------------------------------------------------------


def test_consecutive_daily_bars_are_crypto() -> None:
    """30 consecutive daily bars -> DAILY_CRYPTO, 365.25 (task test 8).

    Arithmetic (and why the metric is the MEDIAN of per-ISO-week counts,
    OQ-0011): 2023-01-02..2023-01-31 spans ISO weeks 2023-W01..W05 with
    counts [7, 7, 7, 7, 2] (Jan 30-31 are only 2 of W05's 7 days).
    MEAN = (7 + 7 + 7 + 7 + 2) / 5 = 30/5 = 6.0 < 6.5 — with the task's
    "mean" wording this test is unsatisfiable, because 30 consecutive days
    always touch >= ceil(30/7) = 5 ISO weeks, so the mean can never exceed
    30/5 = 6.0. MEDIAN of [7, 7, 7, 7, 2] = 7.0 >= 6.5 -> DAILY_CRYPTO.
    Gaps: 29 consecutive differences, all 1 day -> median gap = 1.0.
    """
    index = pd.date_range("2023-01-02", periods=30, freq="D", tz="UTC")
    result = infer_frequency(_bars_with_index(index), "1d")
    assert result.frequency is BarFrequency.DAILY_CRYPTO
    assert result.bars_per_year == 365.25
    assert result.trading_days_per_week == 7.0
    assert result.median_gap_days == 1.0


# --------------------------------------------------------------------------
# 9. median_gap_days on the equity fixture
# --------------------------------------------------------------------------


def test_median_gap_days_for_equity_fixture() -> None:
    """valid_daily.csv -> median_gap_days == 1.0.

    Arithmetic: 10 rows -> 9 gaps. Week 1: Tue(2)-Wed(3) = 1, Wed-Thu = 1,
    Thu-Fri = 1, Fri(5)-Sat(6) = 1, Sat(6)-Tue(9) = 3 (crosses the weekend);
    week 2 mirrors the within-week gaps: 1, 1, 1, 1. Gaps = [1,1,1,1,3,
    1,1,1,1] -> sorted: eight 1s then one 3 -> the median (5th of 9) is 1.0.
    """
    bars, _ = CSVProvider().get_bars(
        str(FIXTURES / "valid_daily.csv"), date(2023, 1, 1), date(2024, 12, 31), "1d", False
    )
    result = infer_frequency(bars, "1d")
    assert result.median_gap_days == 1.0


# --------------------------------------------------------------------------
# 10. Property: bars_per_year never 0 / negative / NaN on every fixture
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_bars_per_year_positive_and_finite_for_every_fixture(fixture_name: str) -> None:
    """bars_per_year > 0 and finite for ALL 12 fixture CSVs.

    Frequency inference is index-only, so each fixture's date column is
    parsed (UTC, coercing failures) and the frame is filled with placeholder
    values. Two documented accommodations: bad_dates.csv's 'not-a-date' row
    becomes NaT and is dropped (the provider rejects that file outright —
    see test_csv_provider.py), and duplicate_dates.csv keeps its duplicate
    index (out of the Bars contract, but harmless for index statistics).
    NaN fails `> 0` by definition; isfinite additionally rejects inf.
    """
    raw = pd.read_csv(FIXTURES / fixture_name, dtype=str)
    parsed = pd.to_datetime(raw["date"], format="ISO8601", errors="coerce", utc=True)
    index = pd.DatetimeIndex(parsed.dropna()).sort_values()
    result = infer_frequency(_bars_with_index(index), "1d")
    assert result.bars_per_year > 0
    assert math.isfinite(result.bars_per_year)


# --------------------------------------------------------------------------
# 11. CANARY: exactly 3.5 bars/week (ambiguous, below the equity threshold)
# --------------------------------------------------------------------------


def test_canary_three_and_a_half_bars_per_week() -> None:
    """Exactly 3.5 bars/week -> WEEKLY (below the 4.0 threshold), warning set.

    Arithmetic: week 1 = Mon-Thu (2023-01-02..05, 4 bars), week 2 = Mon-Wed
    (2023-01-09..11, 3 bars) -> ISO-week counts [4, 3] -> median =
    (4 + 3) / 2 = 3.5 exactly. 3.5 < 4.0 (not DAILY_EQUITY) and >= 3.0 ->
    sparse WEEKLY, bars_per_year = 52, warning not None. Median gap:
    gaps = [1,1,1,4,1,1] (Thu 05 -> Mon 09 is 4 days) -> sorted
    [1,1,1,1,1,4] -> median 1.0, so the weekly-spacing branch (>= 5.5)
    does NOT fire first.
    """
    index = pd.DatetimeIndex(
        [
            "2023-01-02",
            "2023-01-03",
            "2023-01-04",
            "2023-01-05",
            "2023-01-09",
            "2023-01-10",
            "2023-01-11",
        ],
        tz="UTC",
    )
    result = infer_frequency(_bars_with_index(index), "1d")
    assert result.frequency is BarFrequency.WEEKLY
    assert result.trading_days_per_week == 3.5
    assert result.bars_per_year == 52.0
    assert result.warning is not None
    assert result.median_gap_days == 1.0
