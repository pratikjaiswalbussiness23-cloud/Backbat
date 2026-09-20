"""P2-T6 tests: On-Balance Volume (ROADMAP P2-T6, §4.3).

Every expected value is HAND-COMPUTED with the arithmetic in the docstrings.
Convention under test (task text, classic Wilder OBV): seed OBV[0] =
volume[0]; up bars add volume, down bars subtract it, FLAT closes carry the
previous value. NOTE this is a real convention choice — ta 0.11.0 adds volume
on flats (probed + source read, verified_apis.md: ta = [100, 300, 150, 450,
550, 300, 700] on the task's own series, diverging at bars 4-6) — so the
task's "OBV is deterministic, no convention choices" premise is false
(OQ-0026). The oracle test asserts the trending-prefix agreement and
documents the flat-handling divergence explicitly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import ta as ta_lib

from nlbt.data.models import Bars
from nlbt.indicators import REGISTRY, compute_obv


def _bars(close: list[float], volume: list[float]) -> Bars:
    """Daily UTC bars over consecutive days with the given close/volume."""
    n = len(close)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return Bars(
        {
            "open": [float(c) for c in close],
            "high": [float(c) + 0.5 for c in close],
            "low": [float(c) - 0.5 for c in close],
            "close": [float(c) for c in close],
            "volume": [float(v) for v in volume],
        },
        index=idx,
    )


CLOSE7: list[float] = [10.0, 11.0, 10.0, 12.0, 12.0, 11.0, 13.0]
VOL7: list[float] = [100.0, 200.0, 150.0, 300.0, 100.0, 250.0, 400.0]

# ===========================================================================
# SECTION 1: OBV hand-computed tests
# ===========================================================================


def test_obv_hand_computed() -> None:
    """OBV on close=[10,11,10,12,12,11,13], volume=[100,200,150,300,100,250,400].

    OBV[0] = 100 (seed = first bar's volume)
    OBV[1]: 11 > 10 → 100 + 200 = 300
    OBV[2]: 10 < 11 → 300 - 150 = 150
    OBV[3]: 12 > 10 → 150 + 300 = 450
    OBV[4]: 12 == 12 → 450 (flat: carry, NEUTRAL — ta adds instead)
    OBV[5]: 11 < 12 → 450 - 250 = 200
    OBV[6]: 13 > 11 → 200 + 400 = 600
    """
    out = compute_obv(_bars(CLOSE7, VOL7), {}, "close")
    v = out["value"]
    assert v.iloc[0] == 100.0  # test 1: seed
    assert v.iloc[1] == 300.0  # test 2
    assert v.iloc[2] == 150.0  # test 3
    assert v.iloc[3] == 450.0  # test 4
    assert v.iloc[4] == 450.0  # test 5: flat close → carry
    assert v.iloc[5] == 200.0  # test 6
    assert v.iloc[6] == 600.0  # test 7


def test_obv_can_go_negative() -> None:
    """Declining closes drive OBV negative (test 8).

    close=[10,9,8,7], volume=[100,200,300,400]:
      OBV[0] = 100 (seed)
      OBV[1]: 9 < 10 → 100 - 200 = -100
      OBV[2]: 8 < 9  → -100 - 300 = -400
      OBV[3]: 7 < 8  → -400 - 400 = -800
    """
    out = compute_obv(_bars([10.0, 9.0, 8.0, 7.0], [100.0, 200.0, 300.0, 400.0]), {}, "close")
    v = out["value"]
    assert v.iloc[0] == 100.0
    assert v.iloc[1] == -100.0
    assert v.iloc[2] == -400.0
    assert v.iloc[3] == -800.0


def test_obv_no_nan_no_inf_clean_input() -> None:
    """Clean input → output fully finite, no NaN anywhere (tests 9-10).

    The recursion is closed-form finite arithmetic (add/subtract of finite
    volumes); the seed is volume[0]; no division anywhere → no inf possible.
    """
    out = compute_obv(_bars(CLOSE7, VOL7), {}, "close")["value"].to_numpy()
    assert not np.isnan(out).any()  # test 9
    assert np.isfinite(out).all()  # test 10


def test_obv_empty_and_nan_input_semantics() -> None:
    """Edge inputs: empty frame → empty all-NaN column; NaN close → NaN onward.

    Empty: n == 0 → the output is an empty "value" column (no crash, no
    fake seed).
    NaN close: OBV is CUMULATIVE — there is no way to reseed a running sum
    without restarting the whole accumulation, so a NaN close (or volume)
    at t makes OBV[t] NaN and every later value stays NaN (the carried
    obv[t-1] is NaN from then on). This is the honest propagation choice:
    it can never fabricate a value after losing the running total. ta's
    cumsum behaves identically for NaN volumes; NaN closes are silently
    treated as up-bars there (documented divergence, OQ-0026 family).
    """
    empty = compute_obv(
        Bars(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([], tz="UTC"),
        ),
        {},
        "close",
    )
    assert len(empty) == 0 and empty["value"].isna().all()

    nan_bars = _bars([10.0, 11.0, 12.0, float("nan"), 14.0], [100.0] * 5)
    out = compute_obv(nan_bars, {}, "close")["value"].to_numpy()
    assert out[0] == 100.0 and out[1] == 200.0 and out[2] == 300.0  # up-bars
    assert np.isnan(out[3])  # NaN close at t=3
    assert np.isnan(out[3:]).all()  # propagation is permanent (cumulative)


def test_obv_registry_contract() -> None:
    """Registry contract: no params, warmup 0, empty dict validates.

    validate_indicator_params fills nothing (there is nothing to fill) and
    must accept an empty dict — the P2-T1 validator's no-unknown-params rule
    also rejects any supplied param (OBV takes none).
    """
    from nlbt.indicators import validate_indicator_params

    spec = REGISTRY.get("obv")
    assert spec.warmup_fn({}) == 0
    assert spec.params == {}
    assert validate_indicator_params("obv", {}) == {}
    with pytest.raises(Exception, match="E_SPEC_RANGE"):
        validate_indicator_params("obv", {"period": 3})  # unknown param


# ===========================================================================
# SECTION 2: Oracle test
# ===========================================================================


def test_oracle_obv_trending_prefix_divergence_documented() -> None:
    """OBV oracle (test 11, adapted per OQ-0026 — divergence DOCUMENTED).

    The task's premise "exact match, no convention choices" is false: ta's
    flat bars ADD volume. Probed ta output (verified_apis.md):
      ta  = [100, 300, 150, 450, 550, 300, 700]
      ours= [100, 300, 150, 450, 450, 200, 600]
    Agreement holds wherever no flat PRECEDES the bar: bars 0-3 (the first
    flat is the 12==12 transition INTO bar 4) — asserted exactly. The
    divergence at bars 4-6 is asserted too, so the difference is pinned, not
    hidden: ta[4] = 450 + 100 = 550 (added), ours[4] = 450 (neutral).
    """
    ours = compute_obv(_bars(CLOSE7, VOL7), {}, "close")["value"].to_numpy()
    ref = (
        ta_lib.volume.OnBalanceVolumeIndicator(pd.Series(CLOSE7), pd.Series(VOL7))
        .on_balance_volume()
        .to_numpy()
    )
    assert np.array_equal(ours[:4], ref[:4])  # trending prefix: EXACT match
    # Flat-handling divergence (documented, OQ-0026):
    assert ours[4] == 450.0 and ref[4] == 550.0
    assert ours[5] == 200.0 and ref[5] == 300.0
    assert ours[6] == 600.0 and ref[6] == 700.0
    assert not np.array_equal(ours, ref)  # the conventions genuinely differ


# ===========================================================================
# SECTION 3: Truncation invariance + canary (marker: lookahead)
# ===========================================================================


def _rand_close_volume_bars(n: int, seed: int) -> Bars:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.uniform(-0.5, 0.5, n))
    # Flat closes occur with probability ~0 for continuous draws; force one
    # flat to exercise the neutral branch in the truncation frame.
    close_list = [float(c) for c in close]
    close_list[3] = close_list[2]
    volume = [float(v) for v in rng.integers(100, 500, n)]
    return _bars(close_list, volume)


@pytest.mark.lookahead
def test_obv_truncation_invariance() -> None:
    """Truncation invariance (test 12): bars[:5] == bars[:7][:5].

    OBV[t] reads close[t], close[t-1], volume[t] only — strictly causal.
    (The fixture has a forced flat at bar 3, inside the prefix, so the
    neutral branch is exercised in both frames.)
    """
    full = compute_obv(_rand_close_volume_bars(7, 888), {}, "close")["value"]
    trunc = compute_obv(_rand_close_volume_bars(7, 888)[:5], {}, "close")["value"]
    assert len(trunc) == 5
    assert np.array_equal(
        trunc.to_numpy(dtype=float), full.to_numpy(dtype=float)[:5], equal_nan=True
    )


def _leaky_obv(bars: Bars) -> np.ndarray:
    """CANARY: direction decided by close[t+1] — reads the FUTURE close.

    leaky[t] = leaky[t-1] + volume[t] * sign(close[t+1] - close[t]).
    On a truncated frame the last bar has no t+1 (direction forced 0), while
    the full frame does — the prefixes MUST diverge at exactly the last row.
    """
    close = bars["close"].to_numpy(dtype=float)
    volume = bars["volume"].to_numpy(dtype=float)
    n = len(close)
    out = np.full(n, np.nan)
    out[0] = volume[0]
    for t in range(1, n):
        direction = np.sign(close[t + 1] - close[t]) if t + 1 < n else 0.0
        out[t] = out[t - 1] + volume[t] * direction
    return out


@pytest.mark.lookahead
def test_canary_leaky_obv_is_caught_by_truncation() -> None:
    """CANARY (test 13): future-close OBV must FAIL the truncation test.

    Mechanism: leaky[4] = leaky[3] + volume[4]·sign(close[5] - close[4]).
    On bars[:7] close[5] exists (a real number); on bars[:5] it does not, so
    direction = 0 → leaky_trunc[4] = leaky[3] vs leaky_full[4] = leaky[3] ±
    volume[4] ≠ leaky[3] (volume[4] > 0). The divergence lands at exactly
    the last row of the truncated frame (t=4); rows 0-3 stay identical
    (their close[t+1] exists in both frames) — proving the harness isolates
    the leak instead of failing from general noise.
    """
    bars7 = _rand_close_volume_bars(7, 888)
    full = _leaky_obv(bars7)
    trunc = _leaky_obv(bars7[:5])
    # The truncation test FAILS for the leaky implementation:
    assert not np.array_equal(trunc, full[:5], equal_nan=True)
    # ...at exactly the leak position (t=4 needs close[5]), and only there:
    assert np.array_equal(trunc[:4], full[:4], equal_nan=True)
    assert trunc[4] == full[3]  # truncated frame: no future bar → no step
    assert trunc[4] != full[4]  # full frame took a volume-weighted step
