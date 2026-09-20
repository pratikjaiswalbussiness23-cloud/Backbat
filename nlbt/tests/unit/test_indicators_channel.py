"""P2-T6 tests: highest/lowest channel indicators (ROADMAP P2-T6, §4.3).

Every expected value is HAND-COMPUTED with the arithmetic in the docstrings.
The convention under test is the whole point: our windows EXCLUDE the current
bar (`shift(1)` then rolling), so `close[t] > highest[t]` is a valid
no-lookahead breakout signal. ta's DonchianChannel INCLUDES the current bar —
probed (exact output in verified_apis.md): its upper band is OURS SHIFTED ONE
BAR RIGHT (ours[t] == ta[t-1]); the oracle test asserts that shift relationship
directly instead of hiding the divergence.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
import ta as ta_lib

from nlbt.data.models import Bars
from nlbt.indicators import REGISTRY, compute_highest, compute_lowest


def _bars(high: list[float], low: list[float], close: list[float]) -> Bars:
    """Daily UTC bars over consecutive days with the given OHLC columns."""
    n = len(close)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return Bars(
        {
            "open": [1.0] * n,
            "high": [float(h) for h in high],
            "low": [float(v) for v in low],
            "close": [float(c) for c in close],
            "volume": [0.0] * n,
        },
        index=idx,
    )


def _rand_bars(n: int, seed: int) -> Bars:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.uniform(-0.5, 0.5, n))
    high = close + rng.uniform(0.0, 1.0, n)
    low = close - rng.uniform(0.0, 1.0, n)
    return _bars(high.tolist(), low.tolist(), close.tolist())


# ===========================================================================
# SECTION 1: HIGHEST hand-computed tests (period=3)
# ===========================================================================


def test_highest_hand_computed() -> None:
    """highest on high=[10,12,11,15,13,16,14], period=3 — EXCLUDES current bar.

    highest[t] = max(high[t-3..t-1]); windows for t < 3 are incomplete → NaN:
      t=3: max(high[0..2]) = max(10,12,11) = 12
      t=4: max(high[1..3]) = max(12,11,15) = 15
      t=5: max(high[2..4]) = max(11,15,13) = 15
      t=6: max(high[3..5]) = max(15,13,16) = 16
    """
    out = compute_highest(
        _bars(
            [10.0, 12.0, 11.0, 15.0, 13.0, 16.0, 14.0],
            [9.0, 11.0, 10.0, 14.0, 12.0, 15.0, 13.0],
            [9.5, 11.5, 10.5, 14.5, 12.5, 15.5, 13.5],
        ),
        {"period": 3},
        "high",
    )
    v = out["value"]
    assert v.iloc[:3].isna().all()  # tests 1
    assert v.iloc[3] == 12.0  # test 2: max(10,12,11)
    assert v.iloc[4] == 15.0  # test 3: max(12,11,15)
    assert v.iloc[5] == 15.0  # test 4: max(11,15,13)
    assert v.iloc[6] == 16.0  # test 5: max(15,13,16)


def test_highest_excludes_current_bar() -> None:
    """The current bar's own high must NOT enter its window (convention core).

    high = [10, 100, 10], period=2:
      t=2: max(high[0..1]) = max(10, 100) = 100 — uses PAST bars only.
      An inclusive window would give max(100, 10) = 100 too, but at t=1
      inclusive = max(10, 100) = 100 ≠ ours (NaN) — warmup proves exclusion.
      Sharper: t=2 with high[2]=1000: inclusive → 1000; ours stays 100.
    """
    out = compute_highest(
        _bars([10.0, 100.0, 10.0], [5.0, 95.0, 5.0], [7.0, 97.0, 7.0]),
        {"period": 2},
        "high",
    )
    v = out["value"].to_numpy()
    assert np.isnan(v[0]) and np.isnan(v[1])  # inclusive would emit 10, 100
    assert v[2] == 100.0  # max of PAST highs only


# ===========================================================================
# SECTION 2: LOWEST hand-computed tests (period=3)
# ===========================================================================


def test_lowest_hand_computed() -> None:
    """lowest on low=[8,10,9,13,11,14,12], period=3 — EXCLUDES current bar.

    lowest[t] = min(low[t-3..t-1]); windows for t < 3 are incomplete → NaN:
      t=3: min(low[0..2]) = min(8,10,9) = 8
      t=4: min(low[1..3]) = min(10,9,13) = 9
      t=5: min(low[2..4]) = min(9,13,11) = 9
      t=6: min(low[3..5]) = min(13,11,14) = 11
    """
    out = compute_lowest(
        _bars(
            [9.0, 11.0, 10.0, 14.0, 12.0, 15.0, 13.0],
            [8.0, 10.0, 9.0, 13.0, 11.0, 14.0, 12.0],
            [8.5, 10.5, 9.5, 13.5, 11.5, 14.5, 12.5],
        ),
        {"period": 3},
        "low",
    )
    v = out["value"]
    assert v.iloc[:3].isna().all()  # test 6
    assert v.iloc[3] == 8.0  # test 7: min(8,10,9)
    assert v.iloc[4] == 9.0  # test 8: min(10,9,13)
    assert v.iloc[5] == 9.0  # test 9: min(9,13,11)
    assert v.iloc[6] == 11.0  # test 10: min(13,11,14)


# ===========================================================================
# SECTION 3: Breakout signal semantics (the no-lookahead design point)
# ===========================================================================


def test_breakout_signal_fires_without_lookahead() -> None:
    """close[t] > highest[t] is a VALID breakout signal (test 11, adapted).

    Fixture (OQ-0025): the task's close=15 > high=12 bar is invalid OHLC
    (Bars validation blocks close > high); the SAME arithmetic works with a
    validation-clean bar. high=[10, 11, 12.5], close=[9, 10, 12.4], period=2:
      highest[2] = max(high[0], high[1]) = max(10, 11) = 11.0 (past highs only)
      close[2] = 12.4 > 11.0 → breakout fires.
    WHY exclude the current bar: an inclusive highest[2] would be
    max(11, 12.5) = 12.5 >= close[2] = 12.4 ALWAYS (close <= high on valid
    bars) → the signal could never fire — the exclusion is what makes
    `close[t] > highest[t]` a meaningful, lookahead-free condition.
    """
    out = compute_highest(
        _bars([10.0, 11.0, 12.5], [9.0, 10.0, 11.5], [9.0, 10.0, 12.4]),
        {"period": 2},
        "high",
    )
    highest = out["value"]
    assert highest.iloc[2] == 11.0  # max(10, 11) — past highs only
    assert float(highest.iloc[2]) < 12.4  # breakout signal FIRES


def test_registry_warmups_and_contracts() -> None:
    """Registry contract: warmup = period; allowed_sources pin the right column.

    Window over the PREVIOUS `period` bars → first valid at index period:
    warmup(3) == 3, warmup(default 20) == 20.
    """
    assert REGISTRY.get("highest").warmup_fn({"period": 3}) == 3
    assert REGISTRY.get("highest").warmup_fn({"period": 20}) == 20
    assert REGISTRY.get("lowest").warmup_fn({"period": 3}) == 3
    assert REGISTRY.get("lowest").allowed_sources == ("low",)
    assert REGISTRY.get("highest").allowed_sources == ("high",)


def test_oracle_donchian_shift_relationship() -> None:
    """Oracle (ta Donchian INCLUDES current): ours[t] == ta[t-1] EXACTLY.

    ta probe (verified_apis.md), window=3 on the 10-bar ramp:
      upper = [nan, nan, 12, 15, 15, 16, 16, 17, 17, 18]
      lower = [nan, nan, 8, 9, 9, 11, 11, 12, 10, 10]
    Our windows exclude the current bar → identical VALUES one bar later:
      ours[3..9] must equal ta[2..8] elementwise.
    (The extra leading NaN is our warmup semantics, not a value change.)
    """
    high = [10.0, 12.0, 11.0, 15.0, 13.0, 16.0, 14.0, 17.0, 12.0, 18.0]
    low = [8.0, 10.0, 9.0, 13.0, 11.0, 14.0, 12.0, 15.0, 10.0, 16.0]
    close = [9.0, 11.0, 10.0, 14.0, 12.0, 15.0, 13.0, 16.0, 11.0, 17.0]
    bars = _bars(high, low, close)
    ours_hi = compute_highest(bars, {"period": 3}, "high")["value"].to_numpy()
    ours_lo = compute_lowest(bars, {"period": 3}, "low")["value"].to_numpy()
    dc = ta_lib.volatility.DonchianChannel(
        pd.Series(high), pd.Series(low), pd.Series(close), window=3, offset=0
    )
    ta_hi = dc.donchian_channel_hband().to_numpy()
    ta_lo = dc.donchian_channel_lband().to_numpy()
    assert np.allclose(ours_hi[3:], ta_hi[2:-1], atol=0.0)  # shift-by-one
    assert np.allclose(ours_lo[3:], ta_lo[2:-1], atol=0.0)
    # And the divergence at the same index is real (not hidden):
    assert ta_hi[2] == 12.0 and np.isnan(ours_hi[2])  # ta valid earlier


# ===========================================================================
# SECTION 4: Truncation invariance + canary (marker: lookahead)
# ===========================================================================


def _assert_prefix_equal(a: pd.DataFrame, b: pd.DataFrame, n: int) -> None:
    va = a["value"].iloc[:n].to_numpy(dtype=float)
    vb = b["value"].iloc[:n].to_numpy(dtype=float)
    assert np.array_equal(va, vb, equal_nan=True)


@pytest.mark.lookahead
@pytest.mark.parametrize(
    "fn,params",
    [
        (compute_highest, {"period": 3}),
        (compute_lowest, {"period": 3}),
    ],
)
def test_truncation_invariance(fn: Any, params: dict[str, Any]) -> None:
    """Truncation invariance (tests 12-13): bars[:10] == bars[:15][:10].

    Rolling windows over PREVIOUS bars are causal by construction: output[t]
    reads rows t-period..t-1 only.
    """
    full = fn(_rand_bars(15, 777), params, "high")
    trunc = fn(_rand_bars(15, 777)[:10], params, "high")
    assert len(trunc) == 10
    _assert_prefix_equal(trunc, full, 10)


@pytest.mark.lookahead
def test_canary_inclusive_convention_breaks_breakout_semantics() -> None:
    """CANARY (test 14): the inclusive convention is caught by SEMANTICS, not
    truncation — and the docstring records WHY (task hint honored).

    The inclusive window (ta-Donchian style) is still causal — each output
    reads only rows <= t — so a truncation test CANNOT distinguish the two
    conventions (both are self-consistent; both pass truncation invariance).
    What it breaks is the breakout contract: on valid bars close <= high, so
        close[t] > max(high[t-period+1..t])  requires close[t] > high[t]
        → IMPOSSIBLE on validated data.
    Proof: same fixture as test_breakout_signal_fires_without_lookahead —
    the inclusive version's value at t=2 is max(11, 12.5) = 12.5, and
    close[2] = 12.4 <= 12.5 → the signal NEVER fires. The exclusion design
    is therefore load-bearing for P3/P4 signal logic, and this test pins it.
    """
    bars = _bars([10.0, 11.0, 12.5], [9.0, 10.0, 11.5], [9.0, 10.0, 12.4])
    params: dict[str, Any] = {"period": 2}
    ours = compute_highest(bars, params, "high")["value"]

    # Inclusive variant (wrong convention, ta-Donchian style):
    inclusive = bars["high"].rolling(window=2, min_periods=2).max()

    assert float(ours.iloc[2]) == 11.0  # exclusion → past highs only
    assert float(inclusive.iloc[2]) == 12.5  # inclusion → includes own high
    # The breakout signal fires under OUR convention and CANNOT under theirs:
    assert float(ours.iloc[2]) < 12.4
    assert not (float(inclusive.iloc[2]) < 12.4)
    # Truncation sanity for the inclusive variant (it is causal, just wrong):
    full_inc = bars["high"].rolling(window=2, min_periods=2).max()
    trunc_inc = bars[:2]["high"].rolling(window=2, min_periods=2).max()
    assert np.array_equal(
        trunc_inc.to_numpy(dtype=float), full_inc.to_numpy(dtype=float)[:2], equal_nan=True
    )  # passes truncation → proves truncation alone can NOT police this bug
