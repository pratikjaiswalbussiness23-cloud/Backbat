"""P2-T3 tests: RSI and ROC (ROADMAP P2-T3, §4.3; conventions per ADR-0003).

Every expected value is HAND-COMPUTED with the arithmetic shown in the
docstrings (AGENTS.md R2). External truth is limited to the oracle probes
recorded in docs/verified_apis.md (ta 0.11.0, probed 2026-09-20):

* RSI window=5 on the task's 10-value probe series
  → [nan, nan, nan, nan, 82.97872340425529, 62.27544910179636,
     75.17784830907297, 80.24519304052433, 68.57850024657816,
     78.3946327274705]
* RSI window=3 on the hand-test series
  → [nan, nan, 52.631578947368375, 80.43478260869564, 84.8739495798319,
     56.189151599443626, 76.25329815303425]
* ROC window=3 on [10..16]
  → [nan, nan, nan, 30.0, 27.27272727272727, 25.0, 23.076923076923077]

Known DIVERGENCE (documented, not hidden — task mandate, OQ-0017): ta's RSI
uses ewm(alpha=1/period, adjust=False) from index 0 (read from its installed
source), so it is valid from index period-1 with a phantom-zero seed; ours is
Wilder's SMA seed, valid from index period. The two converge (probed: max
diff after bar 100 = 0.000/0.006 for period 5/14 on a 300-bar walk).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
import ta as ta_lib

from nlbt.data.models import Bars
from nlbt.errors import SpecRangeError
from nlbt.indicators import REGISTRY, compute_roc, compute_rsi, validate_indicator_params

#: Task-mandated series for ALL RSI hand tests.
RSI_PRICES: list[float] = [10.0, 10.5, 10.2, 10.8, 11.0, 10.7, 11.2]
#: Task-mandated series for ROC hand tests.
ROC_PRICES: list[float] = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
#: Task-mandated probe series for the RSI oracle test (period=5).
RSI_PROBE_PRICES: list[float] = [10.0, 10.5, 10.2, 10.8, 11.0, 10.7, 11.2, 11.5, 11.3, 11.8]


def _bars(prices: list[float], column: str = "close") -> Bars:
    """Daily UTC bars over consecutive days, ``column`` set to ``prices``."""
    n = len(prices)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    data: dict[str, Any] = {c: [1.0] * n for c in ("open", "high", "low", "close")}
    data["volume"] = [0.0] * n
    data[column] = [float(p) for p in prices]
    return Bars(data, index=idx)


# ===========================================================================
# SECTION 1: RSI hand-computed tests (period=3, alpha = 1/3)
# ===========================================================================


def test_rsi_period3_hand_computed() -> None:
    """RSI(3) on [10, 10.5, 10.2, 10.8, 11.0, 10.7, 11.2], full arithmetic.

    Changes: +0.5, -0.3, +0.6, +0.2, -0.3, +0.5
    Gains:    0.5,  0.0,  0.6,  0.2,  0.0,  0.5
    Losses:   0.0,  0.3,  0.0,  0.0,  0.3,  0.0

    Seed (first 3 changes, at output index 3):
      avg_gain = (0.5 + 0.0 + 0.6)/3 = 1.1/3 = 11/30 ≈ 0.366667
      avg_loss = (0.0 + 0.3 + 0.0)/3 = 0.3/3 = 0.1
      RS = (11/30)/0.1 = 11/3 ≈ 3.666667
      RSI = 100 - 100/(1 + 11/3) = 100 - 100·3/14 = 100 - 150/7
          = 400/7 ≈ 78.5714   (≈ 78.57)

    index 4 (change +0.2 → gain 0.2, loss 0), alpha = 1/3:
      avg_gain = (1/3)·0.2 + (2/3)·(11/30) = 1/15 + 11/45 = 14/45 ≈ 0.311111
      avg_loss = (1/3)·0.0 + (2/3)·0.1 = 1/15 ≈ 0.066667
      RS = (14/45)/(1/15) = 14/3 ≈ 4.666667
      RSI = 100 - 100/(17/3) = 100 - 300/17 = 1400/17 ≈ 82.3529  (≈ 82.35)

    index 5 (change -0.3 → gain 0, loss 0.3):
      avg_gain = (1/3)·0 + (2/3)·(14/45) = 28/135 ≈ 0.207407
      avg_loss = (1/3)·0.3 + (2/3)·(1/15) = 1/10 + 2/45 = 13/90 ≈ 0.144444
      RS = (28/135)/(13/90) = (28·90)/(135·13) = 56/39 ≈ 1.435897
      RSI = 100 - 100/(95/39) = 100 - 3900/95 = 100 - 780/19
          = 1120/19 ≈ 58.9474  (≈ 58.95)

    index 6 (change +0.5 → gain 0.5, loss 0):
      avg_gain = (1/3)·0.5 + (2/3)·(28/135) = 1/6 + 56/405 = 247/810 ≈ 0.304938
      avg_loss = (1/3)·0 + (2/3)·(13/90) = 13/135 ≈ 0.096296
      RS = (247/810)/(13/135) = (247·135)/(810·13) = 247/78 ≈ 3.166667
      RSI = 100 - 100/(325/78) = 100 - 7800/325 = 100 - 24 = 76.00 EXACTLY.
    """
    out = compute_rsi(_bars(RSI_PRICES), {"period": 3}, "close")["value"]
    assert out.iloc[:3].isna().all()  # warmup = period = 3 (indices 0,1,2)
    assert out.iloc[3] == pytest.approx(78.57, abs=0.01)  # 400/7
    assert out.iloc[4] == pytest.approx(82.35, abs=0.01)  # 1400/17
    assert out.iloc[5] == pytest.approx(58.95, abs=0.01)  # 1120/19
    assert out.iloc[6] == pytest.approx(76.00, abs=0.01)  # exactly 76


def test_rsi_flat_prices_50() -> None:
    """RSI(3) on [10,10,10,10,10]: every change 0 → gains=losses=0.

    Seed avg_gain = avg_loss = 0 → special case RSI = 50.0 (no movement).
    Valid positions 3,4 → both 50.0.
    """
    out = compute_rsi(_bars([10.0, 10.0, 10.0, 10.0, 10.0]), {"period": 3}, "close")["value"]
    assert out.iloc[:3].isna().all()
    assert out.iloc[3:].tolist() == [50.0, 50.0]


def test_rsi_only_gains_100() -> None:
    """RSI(3) on [10..15]: all changes positive → avg_loss = 0 always.

    Special case avg_loss == 0 (and avg_gain > 0) → RSI = 100.0, never inf.
    Valid positions 3,4,5 → 100.0 each.
    """
    out = compute_rsi(_bars([10.0, 11.0, 12.0, 13.0, 14.0, 15.0]), {"period": 3}, "close")["value"]
    assert out.iloc[:3].isna().all()
    assert out.iloc[3:].tolist() == [100.0, 100.0, 100.0]


def test_rsi_only_losses_0() -> None:
    """RSI(3) on [15..10]: all changes negative → avg_gain = 0 always.

    RS = 0 → RSI = 100 - 100/(1+0) = 0.0. Valid positions 3,4,5.
    """
    out = compute_rsi(_bars([15.0, 14.0, 13.0, 12.0, 11.0, 10.0]), {"period": 3}, "close")["value"]
    assert out.iloc[:3].isna().all()
    assert out.iloc[3:].tolist() == [0.0, 0.0, 0.0]


def test_rsi_output_always_in_0_100() -> None:
    """Random 100-value series: every valid RSI value within [0, 100]."""
    rng = np.random.default_rng(3)  # fixed seed: deterministic
    prices = (100 + np.cumsum(rng.normal(0, 1, 100))).tolist()
    out = compute_rsi(_bars(prices), {"period": 14}, "close")["value"]
    valid = out.dropna()
    assert len(valid) > 0
    assert valid.min() >= 0.0
    assert valid.max() <= 100.0


def test_rsi_nan_contamination_reseeds() -> None:
    """RSI(3) on [10, 10.5, 10.2, NaN, 10.8, 11.0, 10.7, 11.2] (OQ-0016).

    Changes: +0.5, -0.3, NaN, NaN, +0.2, -0.3, +0.5
    No fully-valid 3-change window until changes 5,6,7 (+0.2, -0.3, +0.5):
      seed avg_gain = (0.2+0+0.5)/3 = 0.7/3 ≈ 0.233333
      seed avg_loss = (0+0.3+0)/3 = 0.1
      RSI = 100 - 100/(1 + (7/3)) = 100 - 100·3/10 = 70.0  (index 7)
    All earlier positions NaN (warmup or poisoned seed windows).
    """
    prices = [10.0, 10.5, 10.2, np.nan, 10.8, 11.0, 10.7, 11.2]
    out = compute_rsi(_bars(prices), {"period": 3}, "close")["value"]
    assert out.iloc[:7].isna().all()
    assert out.iloc[7] == pytest.approx(70.0, abs=1e-10)


def test_rsi_nan_after_seed_poisons_then_reseeds() -> None:
    """RSI(3) on [10, 11, 12, 13, NaN, 14, 15, 16, 17]: post-seed contamination.

    One NaN price makes TWO consecutive NaN changes (13→NaN and NaN→14):
    changes into prices 1..8: +1, +1, +1, NaN, NaN, +1, +1, +1.
    index 3: seed = SMA of changes into 1,2,3 → avg_gain = 3/3 = 1.0,
      avg_loss = 0/3 = 0.0 → special case avg_loss == 0 → RSI = 100.0.
    index 4: change NaN → smoothing contaminated → NaN (OQ-0016 reseed rule).
    indices 5,6,7: every candidate 3-change window still contains a NaN
      ([1,NaN,NaN], [NaN,NaN,1], [NaN,1,1]) → cannot reseed → NaN.
    index 8: window = changes into 6,7,8 = (+1, +1, +1) → reseed
      avg_gain = 3/3 = 1.0, avg_loss = 0.0 → RSI = 100.0.
    """
    prices = [10.0, 11.0, 12.0, 13.0, np.nan, 14.0, 15.0, 16.0, 17.0]
    out = compute_rsi(_bars(prices), {"period": 3}, "close")["value"]
    assert out.iloc[:3].isna().all()  # warmup
    assert out.iloc[3] == pytest.approx(100.0, abs=1e-10)  # seeded, all gains
    assert out.iloc[4:8].isna().all()  # poisoned + failed reseed windows
    assert out.iloc[8] == pytest.approx(100.0, abs=1e-10)  # reseeded


# ===========================================================================
# SECTION 2: ROC hand-computed tests (period=3)
# ===========================================================================


def test_roc_period3_hand_computed() -> None:
    """ROC(3) on [10..16]: (price[t]/price[t-3] - 1)·100 per position.

    index 3: (13/10 - 1)·100 = (1.3 - 1)·100 = 30.0      (exact)
    index 4: (14/11 - 1)·100 = (3/11)·100  = 300/11 ≈ 27.2727
    index 5: (15/12 - 1)·100 = (1/4)·100   = 25.0        (exact)
    index 6: (16/13 - 1)·100 = (3/13)·100  = 300/13 ≈ 23.0769
    Indices 0,1,2: warmup → NaN.
    """
    out = compute_roc(_bars(ROC_PRICES), {"period": 3}, "close")["value"]
    assert out.iloc[:3].isna().all()
    assert out.iloc[3] == pytest.approx(30.0, abs=1e-10)
    assert out.iloc[4] == pytest.approx(27.27, abs=0.01)  # 300/11
    assert out.iloc[5] == pytest.approx(25.0, abs=1e-10)
    assert out.iloc[6] == pytest.approx(23.08, abs=0.01)  # 300/13


def test_roc_zero_denominator_is_nan() -> None:
    """ROC(1) on [10, 0, 12, 13, 14]: zero base → NaN, never inf.

    index 1: base 10 → (0/10 - 1)·100 = -100.0 (valid, price dropped to 0)
    index 2: base 0 → NaN (division by zero suppressed)
    index 3: base 12 → (13/12 - 1)·100 = 100/12 ≈ 8.3333 (recovers)
    """
    out = compute_roc(_bars([10.0, 0.0, 12.0, 13.0, 14.0]), {"period": 1}, "close")["value"]
    assert out.iloc[0] != out.iloc[0]  # index 0: warmup → NaN
    assert out.iloc[1] == pytest.approx(-100.0, abs=1e-10)
    assert out.iloc[2] != out.iloc[2]  # NaN (zero denominator)
    assert out.iloc[3] == pytest.approx(8.3333, abs=0.001)


def test_roc_period1() -> None:
    """ROC(1) on [10, 11, 12]: one-bar rate of change.

    index 1: (11/10 - 1)·100 = 10.0        (exact)
    index 2: (12/11 - 1)·100 = 100/11 ≈ 9.0909
    """
    out = compute_roc(_bars([10.0, 11.0, 12.0]), {"period": 1}, "close")["value"]
    assert out.iloc[0] != out.iloc[0]  # warmup NaN
    assert out.iloc[1] == pytest.approx(10.0, abs=1e-10)
    assert out.iloc[2] == pytest.approx(9.09, abs=0.01)


# ===========================================================================
# SECTION 3: Oracle tests (ta 0.11.0 — probes recorded in verified_apis.md)
# ===========================================================================


def test_oracle_rsi_divergence_documented() -> None:
    """DIVERGENCE TEST (task-anticipated; analysed in OQ-0017).

    ta 0.11.0 RSI = ewm(alpha=1/period, adjust=False) from index 0 (source
    read) → valid from index period-1 = 4 on this series, phantom-zero seed.
    Ours (Wilder SMA seed, ADR-0003) → valid from index period = 5.

    Hand computation for OUR index 5 (first 5 changes: +0.5, -0.3, +0.6,
    +0.2, -0.3): avg_gain = 1.3/5 = 0.26; avg_loss = 0.6/5 = 0.12;
    RS = 0.26/0.12 = 13/6; RSI = 100 - 100/(19/6) = 100 - 600/19
       = 1300/19 ≈ 68.4211.
    OUR index 6 (change +0.5): avg_gain = 0.26 + (0.5-0.26)/5 = 0.308;
    avg_loss = 0.12·4/5 = 0.096; RS = 0.308/0.096 = 77/24;
    RSI = 100 - 100/(101/24) = 100 - 2400/101 = 7700/101 ≈ 76.2376.

    Assertions: (a) our hand values, (b) ta's probed values, (c) structural
    divergence (ours NaN at index 4 where ta is valid), (d) convergence on a
    300-bar walk after bar 100 < 0.05 (probed 0.000/0.0062 for period 5/14).
    """
    s = pd.Series(RSI_PROBE_PRICES, dtype=float)

    ours = compute_rsi(_bars(RSI_PROBE_PRICES), {"period": 5}, "close")["value"]
    oracle = ta_lib.momentum.RSIIndicator(s, window=5).rsi().reset_index(drop=True)

    # (a) OUR convention, hand-computed:
    assert ours.iloc[5] == pytest.approx(68.4211, abs=0.001)  # 1300/19
    assert ours.iloc[6] == pytest.approx(76.2376, abs=0.001)  # 7700/101
    # (b) ta's first-value/phantom-zero-seed values, from the recorded probe:
    assert oracle.iloc[4] == pytest.approx(82.97872340425529, abs=1e-9)
    assert oracle.iloc[5] == pytest.approx(62.27544910179636, abs=1e-9)
    # (c) Structural divergence: different warmup, different early values.
    assert pd.isna(ours.iloc[4]) and not pd.isna(oracle.iloc[4])
    assert abs(float(ours.iloc[5]) - float(oracle.iloc[5])) > 1.0
    # (d) Convergence far from the seed (property, not copied output):
    rng = np.random.default_rng(11)  # same seed as the recorded probe run
    walk = pd.Series(100 + np.cumsum(rng.normal(0, 1, 300)))
    ours_w = compute_rsi(_bars(walk.tolist()), {"period": 14}, "close")["value"]
    ta_w = ta_lib.momentum.RSIIndicator(walk, window=14).rsi().to_numpy()
    both = ~(np.isnan(ours_w.to_numpy()) | np.isnan(ta_w))
    tail = np.abs(ours_w.to_numpy() - ta_w)[both][100:]
    assert tail.max() < 0.05  # probed 0.006190; early-window diff was ~0.63


def test_oracle_roc_hand_and_ta() -> None:
    """ROC(3) vs hand computation (primary oracle) + ta cross-check.

    ta 0.11.0 DOES ship ROCIndicator (task text said otherwise — OQ-0018);
    its probe output matches the hand computation exactly:
    [nan, nan, nan, 30.0, 27.27272727272727, 25.0, 23.076923076923077].
    """
    s = pd.Series(ROC_PRICES, dtype=float)
    ours = compute_roc(_bars(ROC_PRICES), {"period": 3}, "close")["value"]
    oracle = ta_lib.momentum.ROCIndicator(s, window=3).roc().reset_index(drop=True)

    # Primary oracle: the hand computation (test_roc_period3_hand_computed).
    assert ours.iloc[:3].isna().all()
    assert ours.iloc[3:].tolist() == pytest.approx(
        [30.0, 300.0 / 11.0, 25.0, 300.0 / 13.0], abs=1e-9
    )
    # Cross-check: ta agrees to float precision, NaN positions identical.
    assert ours.isna().tolist() == oracle.isna().tolist()
    ours_np, oracle_np = ours.to_numpy(), oracle.to_numpy()
    mask = ~np.isnan(ours_np)  # numpy mask: the two indices are not alignable
    assert np.allclose(ours_np[mask], oracle_np[mask], atol=1e-9)


# ===========================================================================
# SECTION 4: Properties
# ===========================================================================


@pytest.mark.parametrize("indicator", ["rsi", "roc"])
def test_no_nan_after_warmup(indicator: str) -> None:
    """Random 50-value series, period=5: no NaN from index 5 onward.

    warmup = period = 5 for both indicators (RSI needs 5 changes + seed;
    ROC needs a base 5 bars back). Prices are 50-60, so no zero denominators.
    """
    rng = np.random.default_rng(42)
    prices = (50 + rng.uniform(0, 10, size=50)).tolist()
    out = REGISTRY.get(indicator).compute_fn(_bars(prices), {"period": 5}, "close")["value"]
    assert out.iloc[:5].isna().all()
    assert not out.iloc[5:].isna().any()


@pytest.mark.parametrize("indicator", ["rsi", "roc"])
def test_no_inf_anywhere(indicator: str) -> None:
    """No +inf/-inf in either output (random 50 values, period=5)."""
    rng = np.random.default_rng(7)
    prices = (50 + rng.uniform(0, 10, size=50)).tolist()
    out = REGISTRY.get(indicator).compute_fn(_bars(prices), {"period": 5}, "close")["value"]
    arr = out.to_numpy()
    finite = arr[~np.isnan(arr)]
    assert np.isfinite(finite).all()
    assert not np.isinf(arr).any()


@pytest.mark.parametrize("indicator", ["rsi", "roc"])
def test_output_index_equals_input_index(indicator: str) -> None:
    """Output index must equal the input bars index."""
    bars = _bars(ROC_PRICES)
    out = REGISTRY.get(indicator).compute_fn(bars, {"period": 3}, "close")
    assert out.index.equals(bars.index)


def test_warmup_lengths_and_sources_in_registry() -> None:
    """warmup = period for both: RSI 14 → 14, ROC 10 → 10; full source list.

    Arithmetic: RSI needs period changes = period+1 prices, seeded at index
    period; ROC needs price[t-period] → first valid at index period.
    """
    rsi_spec = REGISTRY.get("rsi")
    roc_spec = REGISTRY.get("roc")
    assert rsi_spec.warmup_fn({"period": 14}) == 14
    assert roc_spec.warmup_fn({"period": 10}) == 10
    assert rsi_spec.allowed_sources == ("open", "high", "low", "close", "volume")
    assert roc_spec.allowed_sources == ("open", "high", "low", "close", "volume")


def test_registry_bounds_and_defaults() -> None:
    """Registry guard rails: RSI period ∈ [2,100], ROC period ∈ [1,500].

    1 < 2 → below_minimum; 101 > 100 → above_minimum (above_maximum);
    True is not a strict numeric; defaults fill: RSI {} → 14, ROC {} → 10.
    """
    with pytest.raises(SpecRangeError):
        validate_indicator_params("rsi", {"period": 1})
    with pytest.raises(SpecRangeError):
        validate_indicator_params("rsi", {"period": 101})
    with pytest.raises(SpecRangeError):
        validate_indicator_params("rsi", {"period": True})
    with pytest.raises(SpecRangeError):
        validate_indicator_params("roc", {"period": 0})
    with pytest.raises(SpecRangeError):
        validate_indicator_params("roc", {"period": 501})
    assert validate_indicator_params("rsi", {}) == {"period": 14}
    assert validate_indicator_params("roc", {}) == {"period": 10}


# ===========================================================================
# SECTION 5: Truncation invariance (marker lookahead) + leaky canary
# ===========================================================================


def _truncation_inputs() -> list[float]:
    """40 deterministic prices (rule-based, never implementation-derived)."""
    return [100.0 + ((i * 7) % 13) - ((i % 5) * 2) for i in range(40)]


@pytest.mark.lookahead
@pytest.mark.parametrize("indicator", ["rsi", "roc"])
def test_truncation_invariance(indicator: str) -> None:
    """Outputs on bars[:20] and bars[:30] agree on the first 20 rows.

    RSI at t uses only changes up to t (seed window + recursion); ROC at t
    uses only price[t-period..t]. Appending future bars must change nothing
    in the past (§4.3, P2-T7). NaN-aware comparison.
    """
    prices = _truncation_inputs()
    short = REGISTRY.get(indicator).compute_fn(_bars(prices[:20]), {"period": 5}, "close")["value"]
    long_ = REGISTRY.get(indicator).compute_fn(_bars(prices[:30]), {"period": 5}, "close")["value"]
    a, b = short.to_numpy(), long_.to_numpy()[:20]
    assert np.array_equal(a, b, equal_nan=True)


class _LeakyRSI:
    """CANARY: RSI variant that peeks 3 bars into the FUTURE.

    At each t it adds gain/loss from change t+3 (price t+4) into its
    smoothed averages — future data, forbidden by §4.5.
    """

    LEAK = 3

    @staticmethod
    def compute_fn(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
        period = int(params["period"])
        prices = bars[source]
        diff = prices.diff()
        gain = diff.clip(lower=0.0)
        loss = (-diff).clip(lower=0.0)
        future_gain = gain.shift(-_LeakyRSI.LEAK)  # <-- THE LEAK
        future_loss = loss.shift(-_LeakyRSI.LEAK)
        sg = (gain + future_gain).rolling(period, min_periods=period).mean()
        sl = (loss + future_loss).rolling(period, min_periods=period).mean()
        value = pd.Series(np.nan, index=bars.index)
        for t in range(len(bars)):
            g, los = sg.iloc[t], sl.iloc[t]
            if pd.isna(g) or pd.isna(los):
                continue
            if g == 0 and los == 0:
                value.iloc[t] = 50.0
            elif los == 0:
                value.iloc[t] = 100.0
            else:
                value.iloc[t] = 100.0 - 100.0 / (1.0 + float(g) / float(los))
        return pd.DataFrame({"value": value}, index=bars.index)


@pytest.mark.lookahead
def test_canary_leaky_rsi_is_caught() -> None:
    """The truncation harness MUST fail for the future-peeking LeakyRSI.

    Concrete arithmetic: LeakyRSI at t uses change t+3, i.e. price t+4.
    bars[:20] has prices 0..19 → changes exist for indices 1..19 → future
    gain[t+3] is available iff t+3 <= 19, i.e. t <= 16; positions 17,18,19
    are NaN on the SHORT frame (their needed changes 20,21,22 don't exist).
    bars[:30] has changes 1..29 → positions 17..19 are finite on the LONG
    frame. The first-20-row comparison therefore differs at positions
    17..19 → the leak is CAUGHT. (Position 16 stays equal: change 19 is
    PAST data in both frames.)
    """
    prices = _truncation_inputs()
    short = _LeakyRSI.compute_fn(_bars(prices[:20]), {"period": 5}, "close")["value"]
    long_ = _LeakyRSI.compute_fn(_bars(prices[:30]), {"period": 5}, "close")["value"]
    a, b = short.to_numpy(), long_.to_numpy()[:20]

    # Premises (so the failure below is understood, not luck):
    assert not np.isnan(a[5:17]).any()  # short frame: valid through index 16
    assert np.isnan(a[17:20]).all()  # short frame: future run off the end
    assert not np.isnan(b[17:20]).any()  # long frame: future bars exist

    # The truncation assertion MUST fail here:
    with pytest.raises(AssertionError):
        assert np.array_equal(a, b, equal_nan=True)
