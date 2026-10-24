"""P5-T1 return-based metrics (ROADMAP §4.7): hand-computed + numpy oracle.

Every expected value is HAND-DERIVED (R4): the arithmetic is shown in each
docstring and computed from the documented §4.7 formulas on the fixture —
never copied from the implementation. The independent oracle inside this
file uses only numpy (``np.maximum.accumulate``, ``np.std(ddof=1)``) and
calls no implementation helper.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.metrics import compute_return_metrics
from nlbt.spec.models import StrategySpec

# --------------------------------------------------------------------------- #
# Fixture: 6-bar equity curve (§4.7 "6-bar equity curve" acceptance case)
#
#   E      = [100, 110, 99, 108.9, 98.01, 107.811]
#   bar r  = e[t]/e[t-1] - 1 = [+0.1, -0.1, +0.1, -0.1, +0.1]
#   mean(r)= (0.1 - 0.1 + 0.1 - 0.1 + 0.1)/5 = 0.02
#   devs   = r - 0.02 = [0.08, -0.12, 0.08, -0.12, 0.08]
#   sum sq = 2*0.0064 + 2*0.0144 + 0.0064 = 0.048
#   var    = 0.048 / (5-1) = 0.012          (ddof=1)
#   std    = sqrt(0.012)
#   years  = (2024-01-06 - 2024-01-01).days / 365.25 = 5 / 365.25
# --------------------------------------------------------------------------- #

SIX = [100.0, 110.0, 99.0, 108.9, 98.01, 107.811]
BPY = 252.0
INDEX6 = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")

TOTAL_RETURN = 0.07811  # 107.811/100 - 1
STD = math.sqrt(0.012)
ANN_VOL = math.sqrt(0.012 * 252)  # = sqrt(3.024)
SHARPE_RF0 = 0.02 / math.sqrt(0.012) * math.sqrt(252)  # closed form: sqrt(8.4)
assert abs(SHARPE_RF0 - math.sqrt(8.4)) < 1e-15  # pins the closed form itself
SHARPE_RF02 = (0.02 - 0.02 / 252) / math.sqrt(0.012) * math.sqrt(252)
YEARS6 = 5.0 / 365.25
CAGR = (1.0 + TOTAL_RETURN) ** (1.0 / YEARS6) - 1.0  # (107.811/100)^(365.25/5) - 1
MAX_DD = 98.01 / 110.0 - 1.0  # min(E/cummax - 1) = -0.109 (cummax 110 from bar 1)
LONGEST_DD = 4.0  # bars 2..5 underwater, never recovers
CALMAR = CAGR / abs(MAX_DD)


def _oracle(e: np.ndarray, index: pd.DatetimeIndex, bpy: float, rf: float) -> dict[str, float]:
    """Independent numpy oracle — §4.7 formulas only, no implementation code."""
    e = np.asarray(e, dtype=float)
    peak = np.maximum.accumulate(e)
    dd = e / peak - 1.0
    r = e[1:] / e[:-1] - 1.0
    std = float(np.std(r, ddof=1))
    years = (index[-1] - index[0]).days / 365.25
    cagr = float((e[-1] / e[0]) ** (1.0 / years) - 1.0)
    longest = run_len = 0
    for v in dd:
        run_len = run_len + 1 if v < 0.0 else 0
        longest = max(longest, run_len)
    return {
        "total_return": float(e[-1] / e[0] - 1.0),
        "cagr": cagr,
        "annualised_volatility": std * math.sqrt(bpy),
        "sharpe": (float(np.mean(r)) - rf / bpy) / std * math.sqrt(bpy),
        "max_drawdown": float(np.min(dd)),
        "longest_drawdown_bars": float(longest),
        "calmar": cagr / abs(float(np.min(dd))),
    }


# --------------------------------------------------------------------------- #
# 1. Hand-computed 6-bar constants (MAIN assertions, rel=1e-12)
# --------------------------------------------------------------------------- #


def test_six_bar_total_return_cagr() -> None:
    """total_return = 107.811/100 - 1 = 0.07811.
    CAGR = (1 + 0.07811)^(365.25/5) - 1 with years = 5/365.25."""
    m, _ = compute_return_metrics(np.array(SIX), INDEX6, BPY, rf=0.0)
    assert m["total_return"] == pytest.approx(TOTAL_RETURN, rel=1e-12)
    assert m["cagr"] == pytest.approx(CAGR, rel=1e-12)


def test_six_bar_volatility_and_sharpe_rf0() -> None:
    """ann_vol = sqrt(0.012)*sqrt(252) = sqrt(3.024);
    Sharpe(rf=0) = 0.02/sqrt(0.012)*sqrt(252) = sqrt(8.4)."""
    m, _ = compute_return_metrics(np.array(SIX), INDEX6, BPY, rf=0.0)
    assert m["annualised_volatility"] == pytest.approx(math.sqrt(3.024), rel=1e-12)
    assert m["sharpe"] == pytest.approx(math.sqrt(8.4), rel=1e-12)


def test_six_bar_sharpe_with_rf() -> None:
    """Sharpe(rf=0.02) = (0.02 - 0.02/252)/sqrt(0.012)*sqrt(252);
    risk_free_rate is always reported alongside."""
    m, _ = compute_return_metrics(np.array(SIX), INDEX6, BPY, rf=0.02)
    assert m["sharpe"] == pytest.approx(SHARPE_RF02, rel=1e-12)
    assert m["risk_free_rate"] == 0.02
    m0, _ = compute_return_metrics(np.array(SIX), INDEX6, BPY, rf=0.0)
    assert m0["risk_free_rate"] == 0.0


def test_six_bar_drawdown_duration_calmar() -> None:
    """max_dd = 98.01/110 - 1 = -0.109; longest drawdown = 4 bars;
    Calmar = CAGR / 0.109."""
    m, _ = compute_return_metrics(np.array(SIX), INDEX6, BPY, rf=0.0)
    assert m["max_drawdown"] == pytest.approx(MAX_DD, rel=1e-12)
    assert m["longest_drawdown_bars"] == LONGEST_DD
    assert m["calmar"] == pytest.approx(CALMAR, rel=1e-12)


def test_six_bar_numpy_oracle_crosscheck_every_value() -> None:
    """The independent oracle (np.maximum.accumulate / np.std(ddof=1),
    no implementation helper) must agree with every returned metric."""
    m, _ = compute_return_metrics(np.array(SIX), INDEX6, BPY, rf=0.0)
    o = _oracle(np.array(SIX), INDEX6, BPY, rf=0.0)
    assert set(o) <= set(m)
    for key, expected in o.items():
        assert m[key] == pytest.approx(expected, rel=1e-12), key


# --------------------------------------------------------------------------- #
# 2. null + warning cases (§4.7: null, never 0/NaN/inf when undefined)
# --------------------------------------------------------------------------- #


def test_flat_equity_nulls_with_warnings() -> None:
    """Flat curve: Sharpe null (zero variance), Calmar null (zero drawdown);
    vol and total_return are legitimately 0.0 (defined, not null)."""
    e = np.full(6, 250.0)
    m, warnings = compute_return_metrics(e, INDEX6, BPY, rf=0.0)
    assert m["sharpe"] is None
    assert m["calmar"] is None
    assert m["annualised_volatility"] == 0.0
    assert m["total_return"] == 0.0
    assert m["max_drawdown"] == 0.0
    assert any("zero variance" in w for w in warnings), warnings
    assert any("zero drawdown" in w for w in warnings), warnings


def test_float_noise_flat_series_null_not_huge() -> None:
    """A 'flat' series built by ARITHMETIC whose variance is float noise must
    yield Sharpe null — not a huge number. e = 1000 + i*1e-13 gives bar
    returns ~1e-16 with std far below the zero-variance epsilon; a naive
    mean/std would blow up to ~1e15 instead of null."""
    e = 1000.0 + np.arange(6, dtype=float) * 1e-13
    r = e[1:] / e[:-1] - 1.0
    raw_std = float(np.std(r, ddof=1))  # numpy, independent of implementation
    assert raw_std <= 1e-12  # genuinely float-noise scale
    m, warnings = compute_return_metrics(e, INDEX6, BPY, rf=0.0)
    assert m["sharpe"] is None, f"noise produced a Sharpe: {m['sharpe']!r}"
    assert any("zero variance" in w for w in warnings), warnings
    assert m["sharpe"] is None or math.isfinite(float(m["sharpe"]))


def test_single_bar_all_null() -> None:
    """Fewer than 2 bars -> ALL return metrics null including total_return."""
    m, warnings = compute_return_metrics(np.array([100.0]), INDEX6[:1], BPY, rf=0.0)
    for key in (
        "total_return",
        "cagr",
        "annualised_volatility",
        "sharpe",
        "max_drawdown",
        "longest_drawdown_bars",
        "calmar",
    ):
        assert m[key] is None, key
    assert m["risk_free_rate"] == 0.0
    assert any("fewer than 2 bars" in w for w in warnings), warnings


def test_zero_years_cagr_null() -> None:
    """years == 0 (first == last date) -> CAGR null + warning; others fine."""
    same = pd.DatetimeIndex([INDEX6[0]] * 6)
    m, warnings = compute_return_metrics(np.array(SIX), same, BPY, rf=0.0)
    assert m["cagr"] is None
    assert m["total_return"] == pytest.approx(TOTAL_RETURN, rel=1e-12)
    assert m["sharpe"] is not None
    assert any("years" in w for w in warnings), warnings


def test_nonpositive_start_all_null() -> None:
    """E_start <= 0 -> ratios undefined: every return metric null + warning."""
    e = np.array([0.0, 100.0, 99.0, 101.0, 98.0, 102.0])
    m, warnings = compute_return_metrics(e, INDEX6, BPY, rf=0.0)
    for key in ("total_return", "cagr", "annualised_volatility", "sharpe", "calmar"):
        assert m[key] is None, key
    assert any("starting equity" in w for w in warnings), warnings


def test_nonfinite_input_all_null_never_nan_out() -> None:
    """Non-finite input -> null + warning; nothing NaN/inf ever escapes."""
    for bad in (math.inf, -math.inf, math.nan):
        e = np.array([*SIX[:-1], bad])
        m, warnings = compute_return_metrics(e, INDEX6, BPY, rf=0.0)
        for key, value in m.items():
            if value is None:
                continue
            assert math.isfinite(float(value)), (bad, key, value)
        assert any("non-finite" in w for w in warnings), (bad, warnings)


def test_two_bars_sample_std_null_never_nan() -> None:
    """2 bars = 1 return: the ddof=1 sample std is undefined -> volatility
    and Sharpe null + warning (never NaN, I13); the other metrics are still
    defined. Pins the numpy RuntimeWarning defect found by make all (E1)."""
    e = np.array([100.0, 105.0])
    m, warnings = compute_return_metrics(e, INDEX6[:2], BPY, rf=0.0)
    assert m["annualised_volatility"] is None
    assert m["sharpe"] is None
    assert m["total_return"] == pytest.approx(0.05, rel=1e-12)
    for value in m.values():
        assert value is None or math.isfinite(float(value))
    assert any("fewer than 3 bars" in w for w in warnings), warnings


def test_invalid_bars_per_year_raises() -> None:
    """bars_per_year <= 0 is a config error: fail fast, never silent."""
    with pytest.raises(ValueError):
        compute_return_metrics(np.array(SIX), INDEX6, 0.0, rf=0.0)
    with pytest.raises(ValueError):
        compute_return_metrics(np.array(SIX), INDEX6, -252.0, rf=0.0)


# --------------------------------------------------------------------------- #
# 3. Import boundary: nlbt.metrics must never import nlbt.engine (one-way dep)
# --------------------------------------------------------------------------- #


def test_metrics_package_never_imports_engine() -> None:
    """Follows tests/unit/test_import_boundaries.py: scan the real source."""
    metrics_dir = Path(__file__).resolve().parents[2] / "src" / "nlbt" / "metrics"
    assert metrics_dir.is_dir(), "nlbt.metrics package missing"
    sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(metrics_dir.glob("*.py"))}
    assert sources, "no metrics modules to scan"
    for name, text in sources.items():
        for line in text.splitlines():
            stripped = line.strip()
            # import statements only — prose/docstring mentions are fine
            assert "import nlbt.engine" not in stripped, (
                f"{name}: nlbt.metrics must not depend on nlbt.engine: {stripped!r}"
            )
            assert "from nlbt.engine" not in stripped, f"{name}: nlbt.engine import: {stripped!r}"


# --------------------------------------------------------------------------- #
# 4. Engine-level: run() merges values; total_return & settled max_drawdown
# --------------------------------------------------------------------------- #


def _ends_in_position_run(rf: float = 0.0):
    idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="utc")
    # rises to 108 then drops to 90: the settled last value sits below the
    # peak by more than the entry dip, so the SETTLED max_drawdown differs
    # from the stored curve's drawdown column (settled vs unsettled basis)
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 90.0]
    bars = Bars(
        pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1.0 for c in closes],
                "low": [c - 1.0 for c in closes],
                "close": closes,
                "volume": [1000.0] * len(closes),
            },
            index=idx,
        )
    )
    spec = StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "p5t1-engine",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {},
            "rules": {"entry_long": {"all": [{"left": "close", "op": ">", "right": 0}]}},
            "risk": {},
            "sizing": {"method": "percent_of_equity", "value": 50.0, "allow_fractional": True},
            "execution": {
                "fill": "next_open",
                "fee_bps": 5.0,
                "slippage_bps": 5.0,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": 10_000.0},
        }
    )
    return run(spec, bars, rf=rf)


def test_run_merges_metrics_total_return_and_settled_max_drawdown() -> None:
    """Ends in a forced close: total_return == final/initial - 1 (ONE place),
    max_drawdown computed on the SETTLED series (last value := final_equity),
    stored curve untouched, risk_free_rate always present."""
    res = _ends_in_position_run(rf=0.05)
    final = res.metrics["final_equity"]
    initial = res.metrics["initial_capital"]
    assert res.trades[-1].exit_reason == "end_of_data"

    # total_return reconciled: computed from the same final_equity
    assert res.metrics["total_return"] == pytest.approx(final / initial - 1.0, rel=1e-12)
    # new keys present, risk_free_rate always reported
    for key in (
        "cagr",
        "annualised_volatility",
        "sharpe",
        "max_drawdown",
        "longest_drawdown_bars",
        "calmar",
        "risk_free_rate",
    ):
        assert key in res.metrics, key
    assert res.metrics["risk_free_rate"] == 0.05

    # settled series: curve copy with last value replaced by final_equity
    settled = np.asarray(res.equity_curve["equity"], dtype=float).copy()
    settled[-1] = final
    peak = np.maximum.accumulate(settled)
    expected_dd = float(np.min(settled / peak - 1.0))
    assert res.metrics["max_drawdown"] == pytest.approx(expected_dd, rel=1e-12, abs=1e-15)
    # ...and provably NOT the unsettled curve's drawdown column
    unsettled_min = float(res.equity_curve["drawdown"].min())
    assert res.metrics["max_drawdown"] != unsettled_min
    # the stored curve itself was not modified (its last row is pre-settlement)
    assert float(res.equity_curve["equity"].iloc[-1]) != final
