"""P2-T2 tests: SMA and EMA (ROADMAP P2-T2, §4.3; conventions per ADR-0002).

Every expected value is HAND-COMPUTED with the arithmetic shown in the
docstring (AGENTS.md R2) — nothing is copied from implementation output. The
only external truth is the oracle probe recorded in docs/verified_apis.md
(``ta`` 0.11.0, probed 2026-09-20): SMA3 = [nan, nan, 11.0, 12.0, ..., 19.0];
EMA3 = [nan, nan, 11.25, 12.125, ..., 19.0009765625].

The task's oracle library pandas-ta is uninstallable in this project (numba
pin requires numpy<2.3; nlbt requires numpy>=2.5 — see OQ-0015), so the
oracle is ``ta`` (bukosabino, MIT, dev-only). Its EMA seed convention
DIFFERS from ours (first-value vs SMA-seed) — Section 3 documents that
divergence instead of hiding it, exactly as the task text anticipates.

Truncation tests (Section 5) are marked ``lookahead`` (§4.5/P4-T10 marker)
and the canary proves the harness catches a deliberately leaky indicator.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
import ta as ta_lib

from nlbt.data.models import Bars
from nlbt.indicators import REGISTRY, compute_ema, compute_sma
from nlbt.indicators.trend import _sma_reference_loop

#: The task's exact test series.
PRICES: list[float] = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]


def _bars(prices: list[float], column: str = "close") -> Bars:
    """Daily UTC bars over consecutive days, ``column`` set to ``prices``.

    Other OHLCV columns are filled with 1.0 (volume 0.0) so the frame is a
    structurally valid OHLCV shape for the compute kernels.
    """
    n = len(prices)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    data: dict[str, Any] = {c: [1.0] * n for c in ("open", "high", "low", "close")}
    data["volume"] = [0.0] * n
    data[column] = [float(p) for p in prices]
    return Bars(data, index=idx)


def _actual(prices: list[float], col: str = "close") -> pd.Series:
    """``col`` of a bars frame built from ``prices`` (for reference-loop diffs)."""
    return _bars(prices)[col]


# ===========================================================================
# SECTION 1: SMA hand-computed tests
# ===========================================================================


def test_sma_period3_hand_computed() -> None:
    """SMA(3) on [10..20]: arithmetic for every non-NaN position.

    values[i] = (p[i-2] + p[i-1] + p[i]) / 3 for i >= 2:
      i=2:  (10+11+12)/3 = 33/3  = 11.0
      i=3:  (11+12+13)/3 = 36/3  = 12.0
      i=4:  (12+13+14)/3 = 39/3  = 13.0
      i=5:  (13+14+15)/3 = 42/3  = 14.0
      i=6:  (14+15+16)/3 = 45/3  = 15.0
      i=7:  (15+16+17)/3 = 48/3  = 16.0
      i=8:  (16+17+18)/3 = 51/3  = 17.0
      i=9:  (17+18+19)/3 = 54/3  = 18.0
      i=10: (18+19+20)/3 = 57/3  = 19.0
    Positions 0,1 are warmup → NaN (first valid at period-1 = 2).
    """
    out = compute_sma(_bars(PRICES), {"period": 3}, "close")["value"]
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].tolist() == [11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]


def test_sma_period1_identity() -> None:
    """SMA(1): each value is the mean of the last 1 value = the value itself.

    warmup = period-1 = 0 → no NaN anywhere; output == input elementwise:
    [10, 11, ..., 20].
    """
    out = compute_sma(_bars(PRICES), {"period": 1}, "close")["value"]
    assert out.tolist() == [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]


def test_sma_period_equals_length() -> None:
    """SMA(period=11) on 11 prices: only i=10 has a full window.

    i=10: mean of ALL 11 prices = (10+11+...+20)/11 = 165/11 = 15.0.
    i<10 have fewer than 11 observations → NaN (10 NaNs then one 15.0).
    """
    out = compute_sma(_bars(PRICES), {"period": 11}, "close")["value"]
    assert out.iloc[:10].isna().all()
    assert out.iloc[10] == pytest.approx(15.0)


def test_sma_with_nan_input() -> None:
    """SMA(3) on [10, NaN, 12, 13, 14]: windows containing NaN are NaN.

    i=0,1: warmup → NaN.
    i=2: window (10, NaN, 12) contains NaN → NaN.
    i=3: window (NaN, 12, 13) contains NaN → NaN.
    i=4: window (12, 13, 14) → 39/3 = 13.0.
    """
    out = compute_sma(_bars([10.0, np.nan, 12.0, 13.0, 14.0]), {"period": 3}, "close")["value"]
    assert out.iloc[:4].isna().all()
    assert out.iloc[4] == pytest.approx(13.0)


def test_sma_constant_prices() -> None:
    """SMA(3) on [5,5,5,5,5]: every full window is (5+5+5)/3 = 5.0.

    i=2,3,4 all equal 5.0; i=0,1 warmup NaN.
    """
    out = compute_sma(_bars([5.0, 5.0, 5.0, 5.0, 5.0]), {"period": 3}, "close")["value"]
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].tolist() == [5.0, 5.0, 5.0]


# ===========================================================================
# SECTION 2: EMA hand-computed tests (alpha = 2/(3+1) = 0.5)
# ===========================================================================


def test_ema_period3_hand_computed() -> None:
    """EMA(3), SMA-seeded: alpha = 2/(3+1) = 0.5; arithmetic per position.

    seed at i=2: SMA of (10,11,12) = 33/3 = 11.0
      i=3:  0.5·13 + 0.5·11.0 = 6.5 + 5.5 = 12.0
      i=4:  0.5·14 + 0.5·12.0 = 7.0 + 6.0 = 13.0
      i=5:  0.5·15 + 0.5·13.0 = 7.5 + 6.5 = 14.0
      i=6:  0.5·16 + 0.5·14.0 = 8.0 + 7.0 = 15.0
      i=7:  0.5·17 + 0.5·15.0 = 8.5 + 7.5 = 16.0
      i=8:  0.5·18 + 0.5·16.0 = 9.0 + 8.0 = 17.0
      i=9:  0.5·19 + 0.5·17.0 = 9.5 + 8.5 = 18.0
      i=10: 0.5·20 + 0.5·18.0 = 10.0 + 9.0 = 19.0
    (i>=2 the series is arithmetic with step 1; still asserted explicitly.)
    Positions 0,1 warmup → NaN.
    """
    out = compute_ema(_bars(PRICES), {"period": 3}, "close")["value"]
    expected = [11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].tolist() == pytest.approx(expected, abs=1e-10)


def test_ema_period1_identity() -> None:
    """EMA(1): alpha = 2/(1+1) = 1.0; seed = SMA(1) = 10.0 at i=0.

    i>=1: 1.0·p[i] + 0.0·prev = p[i] → output == input elementwise.
    """
    out = compute_ema(_bars(PRICES), {"period": 1}, "close")["value"]
    assert out.tolist() == pytest.approx(
        [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0], abs=1e-10
    )


def test_ema_nan_seed_window_reseeds() -> None:
    """EMA(3) on [NaN, 11, 12, 13, 14]: seed deferral then reseed arithmetic.

    i=2: first candidate window (NaN, 11, 12) contains NaN → seed fails → NaN.
    i=3: window (11, 12, 13) is fully valid → seed = 36/3 = 12.0.
    i=4: 0.5·14 + 0.5·12.0 = 7.0 + 6.0 = 13.0.
    """
    out = compute_ema(_bars([np.nan, 11.0, 12.0, 13.0, 14.0]), {"period": 3}, "close")["value"]
    assert out.iloc[:3].isna().all()
    assert out.iloc[3] == pytest.approx(12.0, abs=1e-10)
    assert out.iloc[4] == pytest.approx(13.0, abs=1e-10)


def test_ema_nan_after_seed_poisons_then_reseeds() -> None:
    """EMA(3) on [10, 11, 12, 13, NaN, 14, 15, 16]: OQ-0016 reseed semantics.

    i=2: seed = (10+11+12)/3 = 11.0
    i=3: 0.5·13 + 0.5·11.0 = 12.0
    i=4: input NaN → output NaN, chain contaminated (unseed).
    i=5: window (13, NaN, 14) contains NaN → cannot reseed → NaN.
    i=6: window (NaN, 14, 15) contains NaN → cannot reseed → NaN.
    i=7: window (14, 15, 16) fully valid → reseed = 45/3 = 15.0.
    """
    prices = [10.0, 11.0, 12.0, 13.0, np.nan, 14.0, 15.0, 16.0]
    out = compute_ema(_bars(prices), {"period": 3}, "close")["value"]
    assert out.iloc[:2].isna().all()  # warmup
    assert out.iloc[2] == pytest.approx(11.0, abs=1e-10)
    assert out.iloc[3] == pytest.approx(12.0, abs=1e-10)
    assert out.iloc[4:7].isna().all()  # poisoned step + failed reseed windows
    assert out.iloc[7] == pytest.approx(15.0, abs=1e-10)  # reseeded 45/3


# ===========================================================================
# SECTION 3: Oracle tests (vs `ta` 0.11.0 — pandas-ta uninstallable, OQ-0015)
# ===========================================================================

#: EXACT probe output (docs/verified_apis.md, 2026-09-20):
#:   SMA3: [nan, nan, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]
#:   EMA3: [nan, nan, 11.25, 12.125, 13.0625, 14.03125, 15.015625,
#:          16.0078125, 17.00390625, 18.001953125, 19.0009765625]


def test_oracle_sma_matches_ta() -> None:
    """Our SMA(3) vs ta.trend.SMAIndicator: agreement to 1e-10, NaN align.

    The probe recorded the oracle as [nan, nan, 11.0, ..., 19.0], which is
    also our hand computation in test_sma_period3_hand_computed — the two
    must agree everywhere.
    """
    s = pd.Series(PRICES, dtype=float)
    oracle = ta_lib.trend.SMAIndicator(close=s, window=3).sma_indicator()
    ours = compute_sma(_bars(PRICES), {"period": 3}, "close")["value"].reset_index(drop=True)
    assert ours.isna().tolist() == oracle.isna().tolist()
    valid = ~ours.isna()
    assert np.allclose(ours[valid].to_numpy(), oracle[valid].to_numpy(), atol=1e-10)


def test_oracle_ema_divergence_documented() -> None:
    """DIVERGENCE TEST (anticipated by the task text; fixed by ADR-0002).

    ``ta``'s EMA is FIRST-VALUE seeded (read from its installed source and
    confirmed arithmetically): e[0]=10.0; e[1]=0.5·11+0.5·10 = 10.5;
    e[2]=0.5·12+0.5·10.5 = 11.25 → probe shows [.., 11.25, 12.125, ..].
    Ours is SMA-seeded: value at i=2 is 11.0, i=3 is 12.0.

    Both are correct EMA recursions from their own seeds; they CONVERGE
    (probed: max |ours - ta| after a 30-bar window on 120 bars = 1.55e-9).
    We therefore assert (a) our hand-computed SMA-seed values exactly,
    (b) the oracle's first-value-seed values exactly where the probe showed
    them, and (c) that the two disagree early and agree after convergence.
    """
    s = pd.Series(PRICES, dtype=float)
    oracle = ta_lib.trend.EMAIndicator(close=s, window=3).ema_indicator()

    # (a) OUR convention (ADR-0002), hand-computed in test_ema_period3:
    ours = compute_ema(_bars(PRICES), {"period": 3}, "close")["value"].reset_index(drop=True)
    assert ours.iloc[2] == pytest.approx(11.0, abs=1e-10)  # SMA seed 33/3
    assert ours.iloc[3] == pytest.approx(12.0, abs=1e-10)  # 0.5·13+0.5·11

    # (b) ta's first-value-seed values, from the recorded probe:
    assert oracle.iloc[2] == pytest.approx(11.25, abs=1e-10)
    assert oracle.iloc[3] == pytest.approx(12.125, abs=1e-10)

    # (c) The conventions genuinely differ here …
    assert abs(float(ours.iloc[2]) - float(oracle.iloc[2])) > 1e-6
    # … but converge on a longer series (probe: 1.55e-9 after 30 bars).
    long_s = pd.Series([100.0 + ((-1) ** (i % 2)) * (i % 7) for i in range(120)])
    alpha, seed = 2.0 / 4, long_s.iloc[:3].mean()
    vals = [seed]
    for i in range(3, len(long_s)):  # hand-rolled SMA-seed recursion
        vals.append(alpha * long_s.iloc[i] + (1 - alpha) * vals[-1])
    ours_long = pd.Series([np.nan, np.nan, *vals])
    ref_long = ta_lib.trend.EMAIndicator(close=long_s, window=3).ema_indicator()
    tail = (ours_long - ref_long).iloc[30:]
    assert tail.abs().max() < 1e-8


# ===========================================================================
# SECTION 4: Properties
# ===========================================================================


@pytest.mark.parametrize("indicator", ["sma", "ema"])
def test_no_nan_after_warmup(indicator: str) -> None:
    """Random 50-value series, period=5: no NaN from index 4 onward.

    warmup = period-1 = 4; all 5-value windows of a NaN-free input are valid
    (§4.3: no NaN after warmup unless input is NaN). First 4 positions are
    warmup → NaN for BOTH indicators.
    """
    rng = np.random.default_rng(42)  # fixed seed: deterministic test
    prices = (100 + rng.uniform(-5, 5, size=50)).tolist()
    bars = _bars(prices)
    out = REGISTRY.get(indicator).compute_fn(bars, {"period": 5}, "close")["value"]
    assert out.iloc[:4].isna().all()
    assert not out.iloc[4:].isna().any()


@pytest.mark.parametrize("indicator", ["sma", "ema"])
def test_no_inf_anywhere(indicator: str) -> None:
    """No +inf/-inf in either output (random 50 values, period=5)."""
    rng = np.random.default_rng(7)
    prices = (50 + rng.uniform(0, 10, size=50)).tolist()
    bars = _bars(prices)
    out = REGISTRY.get(indicator).compute_fn(bars, {"period": 5}, "close")["value"]
    finite = out.to_numpy()[~np.isnan(out.to_numpy())]
    assert np.isfinite(finite).all()
    assert not np.isinf(out.to_numpy()).any()


@pytest.mark.parametrize("indicator", ["sma", "ema"])
def test_output_index_equals_input_index(indicator: str) -> None:
    """Output index must equal the input bars index, name and values."""
    bars = _bars(PRICES)
    out = REGISTRY.get(indicator).compute_fn(bars, {"period": 3}, "close")
    assert out.index.equals(bars.index)


def test_warmup_lengths_in_registry() -> None:
    """warmup_fn({"period": 20}) = 20 - 1 = 19 for both indicators."""
    assert REGISTRY.get("sma").warmup_fn({"period": 20}) == 19
    assert REGISTRY.get("ema").warmup_fn({"period": 20}) == 19


# ===========================================================================
# SECTION 5: Truncation invariance (marker lookahead) + leaky canary
# ===========================================================================


def _truncation_inputs() -> list[float]:
    """60 deterministic prices (rule-based, not implementation-derived)."""
    return [100.0 + ((i * 7) % 13) - ((i % 5) * 2) for i in range(60)]


@pytest.mark.lookahead
@pytest.mark.parametrize("indicator", ["sma", "ema"])
def test_truncation_invariance(indicator: str) -> None:
    """Outputs on bars[:15] and bars[:20] agree on the first 15 rows.

    Any change to a past output after appending future bars is lookahead
    (§4.3, P2-T7). NaN-aware comparison: NaN == NaN at the same position.
    """
    prices = _truncation_inputs()
    short = REGISTRY.get(indicator).compute_fn(_bars(prices[:15]), {"period": 5}, "close")["value"]
    long_ = REGISTRY.get(indicator).compute_fn(_bars(prices[:20]), {"period": 5}, "close")["value"]
    a, b = short.to_numpy(), long_.to_numpy()[:15]
    assert np.array_equal(a, b, equal_nan=True)


class _LeakySMA:
    """CANARY: centred rolling window — deliberately reads FUTURE values."""

    @staticmethod
    def compute_fn(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
        period = int(params["period"])
        centred = bars[source].rolling(window=period, center=True, min_periods=period).mean()
        return pd.DataFrame({"value": centred}, index=bars.index)


@pytest.mark.lookahead
def test_canary_leaky_sma_is_caught() -> None:
    """The truncation harness MUST fail for a leaky (centred-window) SMA.

    Concrete arithmetic for the failure: centred SMA(5) at position 2 needs
    prices 0..4, so on bars[:15] value[2] = mean(p0..p4) = (100+105+103+108+106)/5
    = 522/5 = 104.4 — but on bars[:20] position 2 is UNCHANGED (same window),
    while positions near the END of the short frame (12, 13, 14) need prices
    14..16, 15..17, 16..18 which DON'T EXIST in bars[:15] → NaN on the short
    frame but finite on the long frame. The first-15 comparison therefore
    fails at positions 12..14: the leak is CAUGHT.
    """
    prices = _truncation_inputs()
    short = _LeakySMA.compute_fn(_bars(prices[:15]), {"period": 5}, "close")["value"]
    long_ = _LeakySMA.compute_fn(_bars(prices[:20]), {"period": 5}, "close")["value"]
    a, b = short.to_numpy(), long_.to_numpy()[:15]

    # Premises of the canary (so the failure below is understood, not luck):
    assert np.isnan(a[12:15]).any()  # short frame: centred windows run off the end
    assert not np.isnan(b[12:15]).any()  # long frame: future bars exist

    # The truncation assertion MUST fail here:
    with pytest.raises(AssertionError):
        assert np.array_equal(a, b, equal_nan=True)


# ===========================================================================
# Differential tests: vectorised kernels vs the task's literal reference loop
# (task mandate: at least 3 inputs)
# ===========================================================================


@pytest.mark.parametrize(
    "prices",
    [
        PRICES,  # the canonical 11-value series
        [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],  # steady 0.5 steps
        [50.0, 48.0, 52.0, np.nan, 51.0, 49.0, 53.0, 55.0, 54.0],  # NaN in input
    ],
    ids=["canonical", "half-steps", "with-nan"],
)
def test_sma_vectorised_matches_reference_loop(prices: list[float]) -> None:
    """Vectorised rolling SMA == the task's literal reference loop.

    The loop is the normative definition (imported from trend.py); the
    rolling-mean kernel must reproduce it exactly, NaN-for-NaN, on three
    different inputs (task mandate: >= 3).
    """
    series = _actual(prices)
    loop = _sma_reference_loop(series, 3)
    vec = compute_sma(_bars(prices), {"period": 3}, "close")["value"]
    assert np.array_equal(loop.to_numpy(), vec.to_numpy(), equal_nan=True)


def test_period_bounds_rejected_by_validator() -> None:
    """Registry-level guard rails: period 1/501/true/"5" all violate.

    Registry bounds [2, 500] (§4.3 catalog): 1 < 2 → below_minimum;
    501 > 500 → above_maximum; True/"5" are not strict numerics (OQ-0014).
    """
    from nlbt.errors import SpecRangeError
    from nlbt.indicators import validate_indicator_params

    for bad in ({"period": 1}, {"period": 501}, {"period": True}, {"period": "5"}):
        with pytest.raises(SpecRangeError):
            validate_indicator_params("sma", bad)
    # Defaults fill: {} → {"period": 20}.
    assert validate_indicator_params("sma", {}) == {"period": 20}
