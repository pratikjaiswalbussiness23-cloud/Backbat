"""P1-T3 tests for YFinanceProvider — NO network in unit tests.

Mocking policy (AGENTS.md): only the ``yfinance.download`` boundary is
patched; nothing inside ``YFinanceProvider`` is touched. The recorded
response in ``tests/fixtures/recorded/aapl_2024_response.py`` is REAL probe
output from installed yfinance 1.7.0 (see docs/verified_apis.md).

The single ``network``-marked test at the bottom makes a real call and is
DESELECTED by default (pyproject addopts ``-m "not network and not llm_live"``).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import requests
import yfinance as yf

from nlbt.data.models import Bars
from nlbt.data.yf_provider import YFinanceProvider
from nlbt.errors import DataEmptyError, DataProviderError

# --------------------------------------------------------------------------
# Recorded fixture loading (plain module load — no package assumption)
# --------------------------------------------------------------------------

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "aapl_2024_response.py"
)
_spec = importlib.util.spec_from_file_location("aapl_2024_response", _FIXTURE_PATH)
assert _spec is not None and _spec.loader is not None
_recorded = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_recorded)

_FULL_RANGE = (date(2024, 1, 2), date(2024, 1, 5))


def _recorded_frame() -> pd.DataFrame:
    """The exact frame yfinance 1.7.0 returned in the probe run."""
    return _recorded.to_frame()


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep retry backoff out of the test clock (proves calls, not timing)."""
    monkeypatch.setattr("nlbt.data.yf_provider.time.sleep", lambda _seconds: None)


def _install_download(
    monkeypatch: pytest.MonkeyPatch,
    script: Callable[[int], pd.DataFrame | BaseException],
) -> list[dict[str, Any]]:
    """Patch yf.download with a per-call script; return the captured kwargs."""
    calls: list[dict[str, Any]] = []

    def fake_download(**kwargs: Any) -> pd.DataFrame:
        calls.append(kwargs)
        outcome = script(len(calls))
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, pd.DataFrame)  # narrowing for mypy
        return outcome

    monkeypatch.setattr(yf, "download", fake_download)
    return calls


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_response_returns_correct_bars_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_download(monkeypatch, lambda _n: _recorded_frame())
    bars, _meta = YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert isinstance(bars, Bars)
    assert bars.shape == (4, 5)


@pytest.mark.unit
def test_columns_normalised_to_lowercase_ohlcv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_download(monkeypatch, lambda _n: _recorded_frame())
    bars, _meta = YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]


@pytest.mark.unit
def test_index_is_utc_datetimeindex_sorted(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_download(monkeypatch, lambda _n: _recorded_frame())
    bars, _meta = YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert isinstance(bars.index, pd.DatetimeIndex)
    assert str(bars.index.tz) == "UTC"
    assert bars.index.is_monotonic_increasing
    # Values come from the REAL recorded response — first/last close checked
    # against the fixture, not invented here.
    assert bars["close"].iloc[0] == pytest.approx(183.403992)
    assert bars["close"].iloc[-1] == pytest.approx(178.997726)


@pytest.mark.unit
def test_inclusive_end_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """nlbt contract is inclusive; yfinance's end is exclusive (verified)."""
    calls = _install_download(monkeypatch, lambda _n: _recorded_frame())
    bars, _meta = YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    expected_days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
    assert list(bars.index.date) == expected_days
    assert calls[0]["end"] == "2024-01-06"  # requested end + 1 day passed to yfinance


@pytest.mark.unit
def test_meta_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_download(monkeypatch, lambda _n: _recorded_frame())
    _bars, meta = YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert meta.provider == "yfinance"
    assert meta.adjusted is False
    assert meta.timezone == "UTC"
    assert "unofficial" in meta.source_notes


# --------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_response_raises_data_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_download(monkeypatch, lambda _n: _recorded_frame().iloc[:0])
    with pytest.raises(DataEmptyError) as excinfo:
        YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert excinfo.value.code == "E_DATA_EMPTY"


@pytest.mark.unit
def test_network_exception_retries_then_raises_data_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_download(monkeypatch, lambda _n: requests.exceptions.ConnectionError("boom"))
    with pytest.raises(DataProviderError) as excinfo:
        YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert excinfo.value.code == "E_DATA_PROVIDER"
    assert excinfo.value.details["attempts"] == 3
    assert len(calls) == 3  # exactly max attempts, then mapped error


@pytest.mark.unit
def test_retry_fails_twice_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_download(
        monkeypatch,
        lambda n: requests.exceptions.Timeout("t") if n <= 2 else _recorded_frame(),
    )
    bars, _meta = YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert isinstance(bars, Bars)
    assert bars.shape == (4, 5)
    assert len(calls) == 3  # prove the retries actually happened


@pytest.mark.unit
def test_non_network_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_download(monkeypatch, lambda _n: ValueError("bad response"))
    with pytest.raises(DataProviderError) as excinfo:
        YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert excinfo.value.code == "E_DATA_PROVIDER"
    assert len(calls) == 1  # any other error: no retry (P1-T3)


# --------------------------------------------------------------------------
# adjusted passthrough
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_adjusted_true_passes_auto_adjust_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_download(monkeypatch, lambda _n: _recorded_frame())
    _bars, meta = YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", True)
    assert calls[0]["auto_adjust"] is True
    assert meta.adjusted is True


@pytest.mark.unit
def test_adjusted_false_passes_auto_adjust_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_download(monkeypatch, lambda _n: _recorded_frame())
    _bars, meta = YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert calls[0]["auto_adjust"] is False
    assert meta.adjusted is False


@pytest.mark.unit
def test_start_interval_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_download(monkeypatch, lambda _n: _recorded_frame())
    YFinanceProvider().get_bars("AAPL", *_FULL_RANGE, "1d", False)
    assert calls[0]["start"] == "2024-01-02"
    assert calls[0]["interval"] == "1d"
    assert calls[0]["tickers"] == "AAPL"


# --------------------------------------------------------------------------
# Real network test (excluded from default runs)
# --------------------------------------------------------------------------


@pytest.mark.network
def test_network_aapl_three_days_real_call() -> None:
    """REAL yfinance call — runs only with ``pytest -m network``."""
    provider = YFinanceProvider()
    bars, meta = provider.get_bars("AAPL", date(2024, 1, 2), date(2024, 1, 4), "1d", True)
    assert bars.shape == (3, 5)
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(bars.index, pd.DatetimeIndex)
    assert str(bars.index.tz) == "UTC"
    assert meta.provider == "yfinance"
