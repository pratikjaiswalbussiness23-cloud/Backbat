"""P2-T4 tests: MACD and Bollinger Bands (ROADMAP P2-T4, §4.3, ADR-0002/0004).

Every expected value is HAND-DERIVED with the arithmetic in the docstrings.
The strongest oracle here is EXACT and implementation-independent: on a unit
ramp p[t] = t+1, an SMA-seeded EMA with span m sits ON its fixed point from
the seed bar onward, because the seed SMA(1..m) = (m+1)/2 = p[m-1] - (m-1)/2
and the fixed-point lag of a span-m EMA on a unit ramp is exactly (m-1)/2:

  EMA3[t]  = p[t] - 1    for t >= 2   (seed SMA(1,2,3)   = 2 = 3 - 1)
  EMA5[t]  = p[t] - 2    for t >= 4   (seed SMA(1..5)    = 3 = 5 - 2)
  EMA12[t] = p[t] - 5.5  for t >= 11  (seed SMA(1..12)   = 6.5)
  EMA26[t] = p[t] - 12.5 for t >= 25  (seed SMA(1..26)   = 13.5)

Hence on prices 1..40: MACD(fast=3,slow=5) line ≡ 1.0 from index 4;
MACD(12,26,9) line ≡ 7.0 from index 25; both signals seed to the constant
line value (signal ≡ line, hist ≡ 0). ta 0.11.0 (first-value ewm seeds)
does NOT have these exact values — probe recorded in verified_apis.md —
and its BBands use ddof=0 while ours use the mandated ddof=1 (OQ-0020).
Divergences are asserted and documented, never hidden.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
import ta as ta_lib

from nlbt.data.models import Bars
from nlbt.errors import SpecRangeError
from nlbt.indicators import REGISTRY, compute_bbands, compute_macd, validate_indicator_params
from nlbt.indicators.volatility import (
    _rolling_sample_std,
    _rolling_sample_std_reference,
)

RAMP40: list[float] = [float(i) for i in range(1, 41)]
RAMP21: list[float] = [float(i) for i in range(1, 22)]


def _bars(prices: list[float], column: str = "close") -> Bars:
    """Daily UTC bars over consecutive days, ``column`` set to ``prices``."""
    n = len(prices)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    data: dict[str, Any] = {c: [1.0] * n for c in ("open", "high", "low", "close")}
    data["volume"] = [0.0] * n
    data[column] = [float(p) for p in prices]
    return Bars(data, index=idx)


# ===========================================================================
# SECTION 1: MACD hand-computed tests (fast=3, slow=5, signal=3, ramp 1..40)
# ===========================================================================


def test_macd_line_hand_computed() -> None:
    """MACD line, fast=3/slow=5 on the ramp: exact fixed-point arithmetic.

    alpha3 = 2/(3+1) = 0.5; alpha5 = 2/(5+1) = 1/3.
    EMA3 seed at idx 2: SMA(1,2,3) = 2.0; recursion: EMA3[3] = 0.5·4+0.5·2 = 3,
    EMA3[4] = 0.5·5+0.5·3 = 4 → EMA3[t] = p[t] - 1 for t >= 2 (seed IS the
    fixed point, lag (3-1)/2 = 1).
    EMA5 seed at idx 4: SMA(1,2,3,4,5) = 3.0 = p[4] - 2 → fixed point
    (lag (5-1)/2 = 2) → EMA5[t] = p[t] - 2 for t >= 4.
    line[t] = (p[t]-1) - (p[t]-2) = 1.0 EXACTLY for t >= 4; NaN for t <= 3
    (EMA5 warmup). The task's check: line[4] = EMA3[4] - EMA5[4] = 4 - 3 = 1.0.
    NOTE on equality: exact in real arithmetic; in float, alpha5 = 1/3 is
    not representable, so line[t] = 1.0 ± a few ulp (<= 1e-12) — asserted
    with allclose(1e-12), not ==.
    """
    out = compute_macd(_bars(RAMP40), {"fast": 3, "slow": 5, "signal": 3}, "close")
    line = out["line"]
    assert line.iloc[:4].isna().all()  # test 1
    assert line.iloc[4] == pytest.approx(1.0, abs=1e-10)  # test 2
    assert np.allclose(line.iloc[4:].to_numpy(), 1.0, atol=1e-12)  # fixed point


def test_macd_signal_hist_hand_computed() -> None:
    """Signal = EMA3 of the line; hist = line - signal (arithmetic).

    The line is NaN through idx 3 and exactly 1.0 from idx 4. The signal's
    seed search needs a fully-valid 3-window of the LINE: indices 4,5,6 →
    seed at idx 6 = (1+1+1)/3 = 1.0. Constant input → signal ≡ 1.0 for
    t >= 6; hist = line - signal = 0.0 for t >= 6. warmup = 5+3-2 = 6.
    (Float ulp caveat as in test_macd_line_hand_computed: allclose 1e-12.)
    """
    out = compute_macd(_bars(RAMP40), {"fast": 3, "slow": 5, "signal": 3}, "close")
    assert out["signal"].iloc[:6].isna().all()  # test 3
    assert out["hist"].iloc[:6].isna().all()  # test 3
    assert np.allclose(out["signal"].iloc[6:].to_numpy(), 1.0, atol=1e-12)
    assert np.allclose(out["hist"].iloc[6:].to_numpy(), 0.0, atol=1e-12)
    assert not out["signal"].iloc[6:].isna().any()  # test 6
    assert not out["hist"].iloc[6:].isna().any()  # test 6


def test_macd_hist_identity_invariant() -> None:
    """hist == line - signal EXACTLY wherever defined (test 4; also 16)."""
    out = compute_macd(_bars(RAMP40), {"fast": 3, "slow": 5, "signal": 3}, "close")
    assert np.array_equal(
        out["hist"].to_numpy(),
        (out["line"] - out["signal"]).to_numpy(),
        equal_nan=True,
    )


def test_macd_no_nan_after_warmup() -> None:
    """No NaN in line after index slow-1 = 4; signal/hist after 6 (tests 5,6)."""
    out = compute_macd(_bars(RAMP40), {"fast": 3, "slow": 5, "signal": 3}, "close")
    assert not out["line"].iloc[4:].isna().any()
    assert not out["signal"].iloc[6:].isna().any()
    assert not out["hist"].iloc[6:].isna().any()


def test_macd_defaults_on_ramp_exact_seven() -> None:
    """MACD(12,26,9) on the ramp: line ≡ 7.0 from idx 25 (independent oracle).

    EMA12: seed SMA(1..12) = 78/12 = 6.5 = p[11] - 5.5 → fixed point
    (lag (12-1)/2 = 5.5) → EMA12[t] = p[t] - 5.5 for t >= 11.
    EMA26: seed SMA(1..26) = 351/26 = 13.5 = p[25] - 12.5 → fixed point
    → EMA26[t] = p[t] - 12.5 for t >= 25.
    line[t] = (p[t]-5.5) - (p[t]-12.5) = 7.0 EXACTLY for t >= 25.
    Signal: line NaN through 24, constant 7.0 after; EMA9 seed needs nine
    valid line values: indices 25..33 → seed at idx 33 = 7.0 → signal ≡ 7.0
    from 33; hist ≡ 0.0 from 33. warmup = 26+9-2 = 33. (Float ulp caveat:
    alpha12 = 2/13 and alpha26 = 2/27 are not exact in binary — allclose
    1e-12 rather than ==.)
    """
    out = compute_macd(_bars(RAMP40), {"fast": 12, "slow": 26, "signal": 9}, "close")
    assert out["line"].iloc[:25].isna().all()
    assert np.allclose(out["line"].iloc[25:].to_numpy(), 7.0, atol=1e-12)
    assert out["signal"].iloc[:33].isna().all()
    assert np.allclose(out["signal"].iloc[33:].to_numpy(), 7.0, atol=1e-12)
    assert np.allclose(out["hist"].iloc[33:].to_numpy(), 0.0, atol=1e-12)


# ===========================================================================
# SECTION 2: Bollinger Bands hand-computed tests (period=3, k=2.0)
# ===========================================================================


def test_bbands_hand_computed() -> None:
    """BBands(3, k=2) on [1,2,3,4,5]: full ddof=1 arithmetic per window.

    idx 2: window [1,2,3]: middle = 6/3 = 2.0; deviations (-1,0,1);
      sample var = (1+0+1)/(3-1) = 1.0 → std = 1.0
      upper = 2 + 2·1 = 4.0; lower = 2 - 2·1 = 0.0
    idx 3: window [2,3,4]: middle = 3.0; deviations (-1,0,1) → std = 1.0
      upper = 5.0; lower = 1.0
    idx 4: window [3,4,5]: middle = 4.0; std = 1.0 → upper = 6.0, lower = 2.0
    idx 0,1: warmup → NaN (all three columns).
    """
    out = compute_bbands(_bars([1.0, 2.0, 3.0, 4.0, 5.0]), {"period": 3, "k": 2.0}, "close")
    for col in ("upper", "middle", "lower"):
        assert out[col].iloc[:2].isna().all()  # test 7
    assert out["middle"].iloc[2] == pytest.approx(2.0, abs=1e-12)  # test 8
    assert out["upper"].iloc[2] == pytest.approx(4.0, abs=1e-12)
    assert out["lower"].iloc[2] == pytest.approx(0.0, abs=1e-12)
    assert out["middle"].iloc[3] == pytest.approx(3.0, abs=1e-12)  # test 9
    assert out["upper"].iloc[3] == pytest.approx(5.0, abs=1e-12)
    assert out["lower"].iloc[3] == pytest.approx(1.0, abs=1e-12)
    assert out["middle"].iloc[4] == pytest.approx(4.0, abs=1e-12)  # test 10
    assert out["upper"].iloc[4] == pytest.approx(6.0, abs=1e-12)
    assert out["lower"].iloc[4] == pytest.approx(2.0, abs=1e-12)


def test_bbands_ordering_and_symmetry() -> None:
    """upper > lower where std > 0 (test 11); middle == (upper+lower)/2 (12).

    Random walk windows have std > 0 a.s.; symmetry holds by construction
    (upper+lower = 2·middle), asserted on real output.
    """
    rng = np.random.default_rng(9)
    prices = (50 + np.cumsum(rng.normal(0, 1, 60))).tolist()
    out = compute_bbands(_bars(prices), {"period": 5, "k": 2.0}, "close")
    valid = out["middle"].notna()
    assert (out["upper"][valid] > out["lower"][valid]).all()
    assert np.allclose(
        out["middle"][valid].to_numpy(),
        ((out["upper"][valid] + out["lower"][valid]) / 2).to_numpy(),
        atol=1e-9,
    )


def test_bbands_constant_prices_flat_bands() -> None:
    """Constant 5.0, period=3: std = 0 → upper == middle == lower == 5.0 (13).

    Deviations all zero → sample var 0/2 = 0 → std 0 → bands collapse.
    """
    out = compute_bbands(_bars([5.0, 5.0, 5.0, 5.0, 5.0]), {"period": 3, "k": 2.0}, "close")
    assert out["middle"].iloc[:2].isna().all()
    assert (out["upper"].iloc[2:] == 5.0).all()
    assert (out["middle"].iloc[2:] == 5.0).all()
    assert (out["lower"].iloc[2:] == 5.0).all()


# ===========================================================================
# SECTION 3: Oracle tests (ta 0.11.0; probes in verified_apis.md)
# ===========================================================================


def test_oracle_macd_divergence_documented() -> None:
    """DIVERGENCE TEST: ta's ewm-seeded MACD vs our SMA-seeded MACD (14).

    ta probe (defaults, prices 1..40): line[33] = 6.036080072596107,
    signal[33] = 5.737527795403894, hist[33] = 0.29855227719221275
    (the earlier probe printout mislabelled signal/hist as idx-33 values
    when they were idx-34: signal[34] = 5.811164490368373,
    hist[34] = 0.29454677985791733 — noted, not hidden);
    tails line = [6.286554470535641, 6.33849480365166, 6.386727317589834].
    Ours (hand-derived): line ≡ 7.0 from idx 25 (EMA fixed points, see
    test_macd_defaults_on_ramp_exact_seven); signal[33] = 7.0; hist[33] = 0.0.
    Structural facts: ta's line starts at idx 25 = slow-1 and its signal/hist
    at idx 33 = slow-1 + signal-1 = slow+signal-2 — the SAME indices as ours
    (timing agrees); the VALUES diverge because ta's first-value-seeded ewm
    chain differs from our SMA-seeded chain. Assertions: (a) ta probe values
    reproduced (tolerance 0.01 as mandated), (b) our exact values, (c) the
    divergence is real (> 0.5 at idx 33), (d) convergence on a 600-bar walk
    (probed max |ours - ta| line = 2.6e-5 at bar 150, 2.6e-10 at bar 300).
    """
    s = pd.Series(RAMP40)
    macd = ta_lib.trend.MACD(s, window_fast=12, window_slow=26, window_sign=9)
    # (a) recorded probe reproduced (ta is stable across runs on fixed input):
    assert macd.macd().loc[33] == pytest.approx(6.036080072596107, abs=0.01)
    assert macd.macd_signal().loc[33] == pytest.approx(5.737527795403894, abs=0.01)
    assert macd.macd_diff().loc[33] == pytest.approx(0.29855227719221275, abs=0.01)

    # (b) OUR exact values on the same data (ours carries a DatetimeIndex →
    # positional .iloc; ta's output carries the RangeIndex of the input):
    ours = compute_macd(_bars(RAMP40), {"fast": 12, "slow": 26, "signal": 9}, "close")
    assert ours["line"].iloc[33] == pytest.approx(7.0, abs=1e-10)
    assert ours["signal"].iloc[33] == pytest.approx(7.0, abs=1e-10)
    assert ours["hist"].iloc[33] == pytest.approx(0.0, abs=1e-10)

    # (c) documented divergence at idx 33:
    assert abs(float(ours["line"].iloc[33]) - float(macd.macd().loc[33])) > 0.5

    # (d) convergence far from the seeds (fixed walk, probed magnitudes):
    rng = np.random.default_rng(5)  # same seed as the recorded probe run
    walk = pd.Series(100 + np.cumsum(rng.normal(0, 1, 600)))
    ours_w = compute_macd(_bars(walk.tolist()), {"fast": 12, "slow": 26, "signal": 9}, "close")
    ta_w = ta_lib.trend.MACD(walk, window_fast=12, window_slow=26, window_sign=9)
    d = ours_w["line"].to_numpy() - ta_w.macd().to_numpy()
    tail = np.abs(d[~np.isnan(d)])[300:]
    assert tail.max() < 1e-6  # probed 2.56e-10 at bar 300


def test_oracle_bbands_middle_matches_ta_bands_diverge() -> None:
    """BBands oracle: middle matches ta EXACTLY; upper/lower diverge by ddof.

    Ours (ddof=1, hand): idx 19 middle = 210/20 = 10.5;
      std = sqrt(665/19) = sqrt(35) ≈ 5.916079783099616
      upper = 10.5 + 2·sqrt(35) ≈ 22.332159566199232
    ta probe (ddof=0, from source): upper[19] = 22.032562594670797;
      arithmetic proof of ddof=0: (22.032562594670797 - 10.5)/2
      = 5.7662812973353985 = sqrt(33.25) = sqrt(665/20).
    Divergence = 2(sqrt(35) - sqrt(33.25)) ≈ 0.2996 (OQ-0020). A ddof=0
    recomputation INSIDE this test (independent of our production code)
    reproduces ta to float precision — proving the ONLY difference is ddof.
    """
    s = pd.Series(RAMP21)
    bb = ta_lib.volatility.BollingerBands(s, window=20, window_dev=2)
    ours = compute_bbands(_bars(RAMP21), {"period": 20, "k": 2.0}, "close")

    # Middle: SMA — must match ta exactly (tolerance 1e-6 per task; exact).
    assert ours["middle"].iloc[19] == pytest.approx(10.5, abs=1e-9)
    assert ours["middle"].iloc[19] == pytest.approx(float(bb.bollinger_mavg().loc[19]), abs=1e-6)
    assert ours["middle"].iloc[20] == pytest.approx(float(bb.bollinger_mavg().loc[20]), abs=1e-6)

    # Ours, hand-computed ddof=1 values:
    assert ours["upper"].iloc[19] == pytest.approx(10.5 + 2 * np.sqrt(35), abs=1e-9)
    assert ours["lower"].iloc[19] == pytest.approx(10.5 - 2 * np.sqrt(35), abs=1e-9)

    # Documented divergence against ta's ddof=0 probe:
    assert float(bb.bollinger_hband().loc[19]) == pytest.approx(22.032562594670797, abs=1e-9)
    assert abs(float(ours["upper"].iloc[19]) - float(bb.bollinger_hband().loc[19])) > 0.29

    # Isolation proof: an independent ddof=0 recomputation == ta (1e-9).
    ddof0_upper = s.rolling(20, min_periods=20).mean() + 2 * s.rolling(20, min_periods=20).std(
        ddof=0
    )
    assert ddof0_upper.loc[19] == pytest.approx(float(bb.bollinger_hband().loc[19]), abs=1e-9)


# ===========================================================================
# SECTION 4: Properties (tests 16-23)
# ===========================================================================


def test_macd_properties_on_random_walk() -> None:
    """hist == line - signal exact (16); no inf anywhere (17); index equal (21)."""
    rng = np.random.default_rng(21)
    prices = (100 + np.cumsum(rng.normal(0, 1, 80))).tolist()
    bars = _bars(prices)
    out = compute_macd(bars, {"fast": 12, "slow": 26, "signal": 9}, "close")
    assert np.array_equal(
        out["hist"].to_numpy(),
        (out["line"] - out["signal"]).to_numpy(),
        equal_nan=True,
    )
    for col in ("line", "signal", "hist"):
        arr = out[col].to_numpy()
        assert not np.isinf(arr[~np.isnan(arr)]).any()
    assert out.index.equals(bars.index)


def test_bbands_properties_on_random_walk() -> None:
    """upper >= middle >= lower (18); no inf (19); index equals input (20)."""
    rng = np.random.default_rng(22)
    prices = (100 + np.cumsum(rng.normal(0, 1, 80))).tolist()
    bars = _bars(prices)
    out = compute_bbands(bars, {"period": 20, "k": 2.0}, "close")
    valid = out["middle"].notna().to_numpy()
    assert (out["upper"].to_numpy()[valid] >= out["middle"].to_numpy()[valid] - 1e-12).all()
    assert (out["middle"].to_numpy()[valid] >= out["lower"].to_numpy()[valid] - 1e-12).all()
    for col in ("upper", "middle", "lower"):
        arr = out[col].to_numpy()
        assert not np.isinf(arr[~np.isnan(arr)]).any()
    assert out.index.equals(bars.index)


def test_warmup_lengths_in_registry() -> None:
    """macd warmup = slow+signal-2 = 26+9-2 = 33 (22); bbands = period-1 = 19 (23)."""
    assert REGISTRY.get("macd").warmup_fn({"fast": 12, "slow": 26, "signal": 9}) == 33
    assert REGISTRY.get("bbands").warmup_fn({"period": 20, "k": 2.0}) == 19
    # Fast does not gate the warmup while fast <= slow:
    assert REGISTRY.get("macd").warmup_fn({"fast": 5, "slow": 26, "signal": 9}) == 33


def test_registry_shapes_bounds_defaults() -> None:
    """Outputs/sources per task; bounds enforced; defaults filled.

    macd outputs ("line","signal","hist"), source close only; bbands outputs
    ("upper","middle","lower"), all 5 sources. fast=1 < 2 → below_minimum;
    slow=201 > 200 → above_maximum; signal=True not strict numeric;
    k=0.05 < 0.1 → below; k=10.0 inclusive-pass; defaults: macd {} →
    fast=12, slow=26, signal=9; bbands {} → period=20, k=2.0.
    """
    macd_spec = REGISTRY.get("macd")
    bb_spec = REGISTRY.get("bbands")
    assert macd_spec.outputs == ("line", "signal", "hist")
    assert macd_spec.allowed_sources == ("close",)
    assert bb_spec.outputs == ("upper", "middle", "lower")
    assert bb_spec.allowed_sources == ("open", "high", "low", "close", "volume")

    with pytest.raises(SpecRangeError):
        validate_indicator_params("macd", {"fast": 1})
    with pytest.raises(SpecRangeError):
        validate_indicator_params("macd", {"slow": 201})
    with pytest.raises(SpecRangeError):
        validate_indicator_params("macd", {"signal": True})
    with pytest.raises(SpecRangeError):
        validate_indicator_params("bbands", {"k": 0.05})
    with pytest.raises(SpecRangeError):
        validate_indicator_params("bbands", {"period": 1})
    assert validate_indicator_params("bbands", {"k": 10.0}) == {"period": 20, "k": 10.0}
    assert validate_indicator_params("macd", {}) == {"fast": 12, "slow": 26, "signal": 9}
    assert validate_indicator_params("bbands", {}) == {"period": 20, "k": 2.0}


# ===========================================================================
# Differential test: vectorised sample-std kernel vs literal reference loop
# ===========================================================================


@pytest.mark.parametrize(
    "values",
    [
        np.arange(1.0, 11.0),  # 1..10
        np.full(8, 3.25),  # constant → std 0
        np.array([2.0, np.nan, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]),  # NaN-poisoned
    ],
    ids=["ramp", "constant", "with-nan"],
)
def test_sample_std_vectorised_matches_reference(values: np.ndarray) -> None:
    """Vectorised rolling std(ddof=1) == literal reference loop, NaN-for-NaN.

    Hand spot-check (ramp, period=3, idx 2): window [1,2,3] →
    sqrt(((1-2)²+(2-2)²+(3-2)²)/2) = sqrt(1.0) = 1.0 — both kernels.
    """
    got = _rolling_sample_std(values, 3)
    want = _rolling_sample_std_reference(values, 3)
    assert np.array_equal(got, want, equal_nan=True)


# ===========================================================================
# SECTION 5: Truncation invariance (marker lookahead) + leaky canary
# ===========================================================================


def _truncation_inputs(n: int = 60) -> list[float]:
    """Deterministic rule-based prices (never implementation-derived)."""
    return [100.0 + ((i * 7) % 13) - ((i % 5) * 2) for i in range(n)]


@pytest.mark.lookahead
def test_macd_truncation_invariance() -> None:
    """MACD on bars[:40] vs bars[:60]: first 40 rows identical (24).

    line/signal/hist at t use only prices ≤ t (causal EMA chain); appending
    future bars must not change the past. NaN-aware comparison.
    """
    prices = _truncation_inputs()
    params: dict[str, Any] = {"fast": 3, "slow": 5, "signal": 3}
    short = compute_macd(_bars(prices[:40]), params, "close")
    long_ = compute_macd(_bars(prices[:60]), params, "close")
    for col in ("line", "signal", "hist"):
        assert np.array_equal(short[col].to_numpy(), long_[col].to_numpy()[:40], equal_nan=True)


@pytest.mark.lookahead
def test_bbands_truncation_invariance() -> None:
    """BBands on bars[:25] vs bars[:40]: first 25 rows identical (25)."""
    prices = _truncation_inputs()
    short = compute_bbands(_bars(prices[:25]), {"period": 5, "k": 2.0}, "close")
    long_ = compute_bbands(_bars(prices[:40]), {"period": 5, "k": 2.0}, "close")
    for col in ("upper", "middle", "lower"):
        assert np.array_equal(short[col].to_numpy(), long_[col].to_numpy()[:25], equal_nan=True)


class _LeakyBBands:
    """CANARY: centred rolling windows — deliberately reads FUTURE values."""

    @staticmethod
    def compute_fn(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
        period = int(params["period"])
        k = float(params["k"])
        s = bars[source]
        middle = s.rolling(window=period, center=True, min_periods=period).mean()
        std = s.rolling(window=period, center=True, min_periods=period).std(ddof=1)
        return pd.DataFrame(
            {"upper": middle + k * std, "middle": middle, "lower": middle - k * std},
            index=bars.index,
        )


@pytest.mark.lookahead
def test_canary_leaky_bbands_is_caught() -> None:
    """The truncation harness MUST fail for centred-window BBands (26).

    Arithmetic: centred window(5) at t needs prices t-2..t+2. bars[:25]
    (indices 0..24): at t=23 needs 21..25 → index 25 missing → NaN;
    t=24 needs 22..26 → NaN. bars[:40] has them → finite. The first-25-row
    comparison therefore differs at t=23,24 in ALL THREE columns → caught.
    """
    prices = _truncation_inputs()
    short = _LeakyBBands.compute_fn(_bars(prices[:25]), {"period": 5, "k": 2.0}, "close")
    long_ = _LeakyBBands.compute_fn(_bars(prices[:40]), {"period": 5, "k": 2.0}, "close")

    for col in ("upper", "middle", "lower"):
        a = short[col].to_numpy()
        b = long_[col].to_numpy()[:25]
        # Premises (understood failure, not luck):
        assert np.isnan(a[23:25]).all()  # centred windows run off the short end
        assert not np.isnan(b[23:25]).any()  # long frame has the future bars
        # The truncation assertion MUST fail:
        with pytest.raises(AssertionError):
            assert np.array_equal(a, b, equal_nan=True)
