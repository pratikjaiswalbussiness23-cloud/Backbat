"""P2-T5 tests: ATR, Stochastic, ADX (ROADMAP P2-T5, §4.3).

Every expected value is HAND-COMPUTED with the arithmetic shown in the
docstrings (AGENTS.md R2) — nothing is copied from implementation output.
The ta 0.11.0 oracle probes (exact output in docs/verified_apis.md, recorded
2026-09-20 BEFORE coding) anchor the oracle section; divergences are asserted
and documented, never hidden:

* ta ATR seeds from TR[0..window-1] where its TR[0] is the high-low filler,
  and leaves np.zeros warmup (0.0, not NaN) — ours is NaN through warmup.
* ta Stochastic has no %K smoothing at all; its ``smooth_window`` parameter
  is exactly our ``d_period`` (SMA of %K → %D). Its mandated probe used
  smooth_window=1, which makes ta's %D identical to its %K.
* ta ADX probes confirm +DI = 50.0 on the task's uptrend (NOT 100.0 — the
  task's test-14 premise "+DM = TR always" is contradicted by its own tables,
  +DM=1 vs TR=2 → 100·1/2) and first real ADX at index 2*period-1 (OQ-0022).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
import ta as ta_lib

from nlbt.data.models import Bars
from nlbt.indicators import REGISTRY, compute_adx, compute_atr, compute_stoch

RAMP10_H: list[float] = [11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
RAMP10_L: list[float] = [9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0]
RAMP10_C: list[float] = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]


def _bars(
    high: list[float],
    low: list[float],
    close: list[float],
) -> Bars:
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


def _loc(series: pd.Series, i: int) -> float:
    """Positional getter that works on both DatetimeIndex and RangeIndex."""
    return float(series.iloc[i])


# ===========================================================================
# SECTION 1: ATR hand-computed tests (period=3)
# ===========================================================================


def test_atr_hand_computed() -> None:
    """ATR on h=[11..15], l=[9..13], c=[10..14], period=3 — arithmetic.

    TR[t] = max(h-l, |h-c[t-1]|, |l-c[t-1]|); TR[0] = NaN (no prev_close):
      TR[1] = max(12-10, |12-10|, |10-10|) = max(2,2,0) = 2.0
      TR[2] = max(13-11, |13-11|, |11-11|) = max(2,2,0) = 2.0
      TR[3] = max(14-12, |14-12|, |12-12|) = max(2,2,0) = 2.0
      TR[4] = max(15-13, |15-13|, |13-13|) = max(2,2,0) = 2.0
    Seed = SMA of TR[1..3] = (2+2+2)/3 = 2.0 at index 3 (warmup = period = 3):
      ATR[3] = 2.0
      ATR[4] = (1/3)·TR[4] + (2/3)·2.0 = 2/3 + 4/3 = 2.0
    """
    out = compute_atr(_bars(RAMP10_H[:5], RAMP10_L[:5], RAMP10_C[:5]), {"period": 3}, "close")
    atr = out["value"]
    assert atr.iloc[:3].isna().all()  # test 1: indices 0,1,2 NaN
    assert _loc(atr, 3) == pytest.approx(2.0, abs=1e-12)  # test 2: exact by hand
    assert _loc(atr, 4) == pytest.approx(2.0, abs=1e-12)  # test 3: exact by hand


def test_atr_nonnegative_and_finite() -> None:
    """ATR is a max of absolute values / nonneg smoothed averages → >= 0 (test 4).

    300-bar seeded random walk (values 100±5): every TR[t] = max(h-l, |h-pc|, |l-pc|) >= 0,
    and Wilder smoothing of nonneg values with nonneg seed stays nonneg.
    """
    rng = np.random.default_rng(20260920)
    n = 300
    close = 100.0 + np.cumsum(rng.uniform(-0.5, 0.5, n))
    high = close + rng.uniform(0.0, 1.0, n)
    low = close - rng.uniform(0.0, 1.0, n)
    out = compute_atr(_bars(high.tolist(), low.tolist(), close.tolist()), {"period": 14}, "close")
    valid = out["value"].dropna()
    assert len(valid) == n - 14  # no NaN after warmup (test 22a)
    assert (valid >= 0.0).all()  # test 4
    assert np.isfinite(valid.to_numpy()).all()  # test 22b: never inf


# ===========================================================================
# SECTION 2: Stochastic hand-computed tests (k=3, smooth=1, d=3)
# ===========================================================================


def test_stoch_hand_computed() -> None:
    """Stochastic on h=[10,12,14,13,15], l=[8,10,11,10,12], c=[9,11,13,12,14].

    k=3, smooth=1 (no %K smoothing), d=3. Raw %K windows (inclusive of t):
      t=2: high window [10,12,14] → HH=14; low window [8,10,11] → LL=8;
           close=13 → %K = 100·(13-8)/(14-8) = 100·5/6 = 83.333...
      t=3: HH=14 ([12,14,13]), LL=10 ([10,11,10]), close=12
           → %K = 100·(12-10)/(14-10) = 100·2/4 = 50.0
      t=4: HH=15 ([14,13,15]), LL=10 ([11,10,12]), close=14
           → %K = 100·(14-10)/(15-10) = 100·4/5 = 80.0
    %D = SMA(%K, 3): needs 3 %K values → %D[4] = (83.333+50+80)/3
         = 213.333/3 = 71.111...
    """
    out = compute_stoch(
        _bars(
            [10.0, 12.0, 14.0, 13.0, 15.0],
            [8.0, 10.0, 11.0, 10.0, 12.0],
            [9.0, 11.0, 13.0, 12.0, 14.0],
        ),
        {"k_period": 3, "smooth_period": 1, "d_period": 3},
        "close",
    )
    k, d = out["k"], out["d"]
    assert k.iloc[:2].isna().all()  # test 5
    assert _loc(k, 2) == pytest.approx(83.33, abs=0.01)  # test 6: 500/6 = 83.3333
    assert _loc(k, 3) == 50.0  # test 7: exact
    assert _loc(k, 4) == 80.0  # test 8: exact
    assert d.iloc[:4].isna().all()  # test 9
    assert _loc(d, 4) == pytest.approx(71.11, abs=0.01)  # test 10: 640/3 / 3 = 71.111


def test_stoch_flat_prices_k_is_50() -> None:
    """Flat window HH == LL → denominator 0 → %K = 50.0 by convention (test 11).

    h=l=c=5: every window has HH=LL=5, close=5 → 0/0; convention says 50.0,
    not NaN (ta 0.11.0 differs: its raw 0/0 is NaN — divergence documented).
    """
    out = compute_stoch(
        _bars([5.0] * 6, [5.0] * 6, [5.0] * 6),
        {"k_period": 3, "smooth_period": 1, "d_period": 3},
        "close",
    )
    k = out["k"]
    valid = k.dropna()
    assert len(valid) == 4  # indices 2..5
    assert (valid == 50.0).all()  # special case, exact


def test_stoch_smooth_k_before_d() -> None:
    """smooth_period=3 smooths %K BEFORE %D — hand-computed (task convention).

    Same data as test_stoch_hand_computed. Raw %K: [·, ·, 83.333, 50, 80].
    Smoothed %K = SMA(raw %K, 3) — valid from (k-1)+(s-1) = 4:
      t=4: (83.333 + 50 + 80)/3 = 213.333/3 = 71.111
    %D = SMA(smoothed %K, 3) needs 3 smoothed values, which exist only from
    t=4 → on the 5-bar frame %D is all NaN (warmup k+s+d-3 = 6 > 4).
    Extended frame (bars 5,6 repeat bar 4: h=15, l=12, c=14):
      t=5 raw: window bars 3-5 → HH=15, LL=10, c=14 → %K = 100·4/5 = 80
      t=6 raw: window bars 4-6 → HH=15, LL=12, c=14 → %K = 100·2/3 = 66.667
      smoothed: k[5] = (50+80+80)/3 = 70.0; k[6] = (80+80+66.667)/3 = 226.667/3
      = 75.556 (680/9)
      %D[6] = (71.111 + 70 + 75.556)/3 = 216.667/3 = 72.222 (650/9)
    """
    out = compute_stoch(
        _bars(
            [10.0, 12.0, 14.0, 13.0, 15.0],
            [8.0, 10.0, 11.0, 10.0, 12.0],
            [9.0, 11.0, 13.0, 12.0, 14.0],
        ),
        {"k_period": 3, "smooth_period": 3, "d_period": 3},
        "close",
    )
    assert out["k"].iloc[:4].isna().all()  # smoothed %K warmup = 4
    assert _loc(out["k"], 4) == pytest.approx(71.11, abs=0.01)  # 213.333/3
    assert out["d"].isna().all()  # %D warmup 6 > 4 on this frame
    out2 = compute_stoch(
        _bars(
            [10.0, 12.0, 14.0, 13.0, 15.0, 15.0, 15.0],
            [8.0, 10.0, 11.0, 10.0, 12.0, 12.0, 12.0],
            [9.0, 11.0, 13.0, 12.0, 14.0, 14.0, 14.0],
        ),
        {"k_period": 3, "smooth_period": 3, "d_period": 3},
        "close",
    )
    assert _loc(out2["k"], 5) == pytest.approx(70.0, abs=1e-12)  # 210/3
    assert _loc(out2["k"], 6) == pytest.approx(75.56, abs=0.01)  # 680/9
    assert out2["d"].iloc[:6].isna().all()  # %D needs 3 smoothed values
    assert _loc(out2["d"], 6) == pytest.approx(72.22, abs=0.01)  # 650/9


# ===========================================================================
# SECTION 3: ADX hand-computed tests (ramp 8 bars, period=3)
# ===========================================================================


def test_adx_hand_computed() -> None:
    """ADX on h=[11..18], l=[9..16], c=[10..17], period=3 — full cascade.

    up[t] = h[t]-h[t-1] = 1; down[t] = l[t-1]-l[t] = -1 for all t>=1:
      +DM[t] = max(1,0)=1 (> max(-1,0)=0 and > 0); -DM[t] = 0 (down <= 0).
      So +DM = [·,1,1,1,1,1,1,1], -DM = [·,0,0,0,0,0,0,0].
    TR[t] = max(2, 1, 1) = 2.0 for t>=1 (h-l=2 dominates): TR = [·,2,2,2,2,2,2,2].
    Wilder running sums (seed = SUM of first 3 values, valid from t=3):
      t=3: sp=3, sn=0, st=6
      t=4: sp = 3 + 1 - 3/3 = 3 (running-sum fixed point: x + 1 - x/3 = 3
           when x=3) → +DI = 100·3/6 = 50.0; -DI = 0; DX = 100·50/50 = 100
      t>=4: sums stay 3/0/6 → +DI = 50, -DI = 0, DX = 100 forever.
    ADX = Wilder smoothing of DX, seed = SMA of first 3 DX values:
      DX[3]=DX[4]=DX[5]=100 → ADX[5] = 100.0 (first valid at 2·period-1 = 5).
      ADX[6] = (2/3)·100 + (1/3)·DX[5] = 100; ADX[7] = 100.
    NOTE vs the task text (tests 12-15): the task's "+DI = 100.0" premise
    contradicts its own tables (+DM=1, TR=2 → 100·1/2 = 50.0, as ta's probe
    shows), and its "ADX[0..5] NaN / warmup = 2·period" is off by one against
    its own cascade (seed SMA of DX[3..5] lands at index 5). OQ-0022/0023.
    """
    out = compute_adx(_bars(RAMP10_H[:8], RAMP10_L[:8], RAMP10_C[:8]), {"period": 3}, "close")
    adx, pdi, mdi = out["adx"], out["plus_di"], out["minus_di"]
    assert adx.iloc[:5].isna().all()  # test 12 (corrected): warmup = 5 = 2·3-1
    assert _loc(adx, 5) == pytest.approx(100.0, abs=1e-12)  # test 13: (100+100+100)/3
    assert _loc(pdi, 3) == pytest.approx(50.0, abs=1e-12)  # test 14 corrected: 100·3/6
    assert _loc(mdi, 3) == 0.0  # test 15: no down-moves → -DI = 0 exactly
    assert _loc(pdi, 5) == pytest.approx(50.0, abs=1e-12)  # running-sum fixed point
    assert _loc(adx, 6) == pytest.approx(100.0, abs=1e-12)  # (2/3)·100+(1/3)·100


@pytest.mark.parametrize("col", ["adx", "plus_di", "minus_di"])
def test_adx_output_bounds(col: str) -> None:
    """ADX/+DI/-DI all in [0, 100] on a 300-bar seeded random walk (tests 16-18).

    +DI = 100·sp/st with sp <= st (because +DM <= TR elementwise: +DM is
    either 0 or h[t]-h[t-1] <= |h[t]-c[t-1]| <= TR) → 0 <= +DI <= 100;
    -DI symmetric; DX = 100·|p-m|/(p+m) <= 100 for p, m >= 0; ADX = convex
    combination of DX values → also in [0, 100]. Random data never trips the
    degenerate branches (st > 0 always), which the dedicated tests cover.
    """
    rng = np.random.default_rng(20260921)
    n = 300
    close = 100.0 + np.cumsum(rng.uniform(-0.5, 0.5, n))
    high = close + rng.uniform(0.0, 1.0, n)
    low = close - rng.uniform(0.0, 1.0, n)
    out = compute_adx(_bars(high.tolist(), low.tolist(), close.tolist()), {"period": 14}, "close")
    valid = out[col].dropna()
    assert len(valid) > 0
    assert (valid >= 0.0).all() and (valid <= 100.0).all()
    assert np.isfinite(valid.to_numpy()).all()  # test 24b: never inf


# ===========================================================================
# SECTION 4: Oracle tests (ta 0.11.0 — probes recorded in verified_apis.md)
# ===========================================================================


def test_oracle_atr() -> None:
    """ATR oracle (test 19): period=3, mandated probe data.

    ta probe (recorded): [0.0, 0.0, 2.0, 2.0, ...] — ta seeds from TR[0..2]
    (its TR[0] = high-low filler = 2.0 here, so the same seed value) and
    emits np.zeros warmup. Ours: NaN through idx 2 (no prev_close at 0),
    seed at 3. Agreement is expected from idx 3 on (identical recursion,
    aligned values from idx 1 — the fillers differ only in the warmup).
    Divergence asserted, not hidden: ta[0] = ta[1] = 0.0 vs ours NaN.
    """
    bars = _bars(RAMP10_H, RAMP10_L, RAMP10_C)
    ours = compute_atr(bars, {"period": 3}, "close")["value"].to_numpy()
    ref = ta_lib.volatility.AverageTrueRange(
        pd.Series(RAMP10_H), pd.Series(RAMP10_L), pd.Series(RAMP10_C), window=3
    ).average_true_range()
    refv = ref.to_numpy()
    assert np.allclose(ours[3:], refv[3:], atol=1e-9)  # identical from idx 3
    assert refv[0] == 0.0 and refv[1] == 0.0  # ta's warmup FILLER (documented)
    assert np.isnan(ours[:3]).all()  # ours: honest NaN warmup
    # Probed-exact anchor (verified_apis.md): the recursion value is 2.0.
    assert refv[2] == 2.0 and ours[3] == pytest.approx(2.0, abs=1e-12)


def test_oracle_stochastic() -> None:
    """Stochastic oracle (test 20): ta(window=3, smooth_window=3) ≡ ours(d=3).

    Parameter mapping (source-read, verified_apis.md): ta NEVER smooths %K;
    its ``smooth_window`` IS our ``d_period`` (SMA of %K → %D). The task's
    probe #2 used smooth_window=1, which makes ta's %D = %K — not comparable
    to ours with d_period=3.

    Hand derivation on the ramp h=[11..20], l=[9..18], c=[10..19], k=3:
    the 3-window ending at t (t >= 2) has HH = h[t] = t+3, LL = l[t-2] = t-1
    (both series are unit ramps), close = t+2 →
      %K = 100·(close-LL)/(HH-LL) = 100·(t+2-(t-1))/((t+3)-(t-1)) = 100·3/4
         = 75.0 — constant for ALL t >= 2.
    %D = SMA(%K, 3) = 75.0 from t = 4. Both match the ta probe exactly.
    """
    bars = _bars(RAMP10_H, RAMP10_L, RAMP10_C)
    ours = compute_stoch(bars, {"k_period": 3, "smooth_period": 1, "d_period": 3}, "close")
    ref = ta_lib.momentum.StochasticOscillator(
        pd.Series(RAMP10_H),
        pd.Series(RAMP10_L),
        pd.Series(RAMP10_C),
        window=3,
        smooth_window=3,
    )
    refk = ref.stoch().to_numpy()
    refd = ref.stoch_signal().to_numpy()
    # %K: identical semantics (ta has no %K smoothing; ours smooth=1 → none)
    assert np.allclose(ours["k"].to_numpy()[2:], refk[2:], atol=1e-9)
    assert np.allclose(ours["k"].to_numpy()[2:], 75.0, atol=1e-9)  # 100·3/4 by hand
    # %D: ours = SMA(%K, 3) → valid from t=4; ta's smooth_window=3 = same SMA
    assert np.allclose(ours["d"].to_numpy()[4:], refd[4:], atol=1e-9)
    assert np.allclose(refd[4:], 75.0, atol=1e-9)
    # ta's mandated probe (smooth_window=1) had d ≡ k — its %D IS that SMA(1).
    # array_equal(equal_nan=True): both series carry the same NaN warmup.
    probe1 = (
        ta_lib.momentum.StochasticOscillator(
            pd.Series(RAMP10_H),
            pd.Series(RAMP10_L),
            pd.Series(RAMP10_C),
            window=3,
            smooth_window=1,
        )
        .stoch_signal()
        .to_numpy()
    )
    assert np.array_equal(probe1, refk, equal_nan=True)  # d ≡ k when smooth_window=1


def test_oracle_adx() -> None:
    """ADX oracle (test 21): period=3, mandated probe data — divergence-documented.

    ta probe (recorded): adx = [0.0]*5 then [100.0]*5; plus_di = [0.0]*4 then
    [50.0]*6; minus_di = [0.0]*10. The 0.0s are np.zeros warmup fillers (source
    read),
    NOT computed values. Real-tail agreement (identical Wilder running sums
    and the same lagged ADX recursion, aligned from t=period):
      ours[5:] == ta[5:] for adx (both first real at 2·period-1 = 5);
      ours[4:] == ta[4:] for +DI/-DI (ta emits its first sum-based DI at
      window+1 = 4, ours at period = 3 — one bar EARLIER; values agree).
    Divergences asserted, not hidden: ta's 0.0 fillers vs our NaN warmup.
    """
    bars = _bars(RAMP10_H, RAMP10_L, RAMP10_C)
    ours = compute_adx(bars, {"period": 3}, "close")
    ref = ta_lib.trend.ADXIndicator(
        pd.Series(RAMP10_H), pd.Series(RAMP10_L), pd.Series(RAMP10_C), window=3
    )
    refadx = ref.adx().to_numpy()
    refpdi = ref.adx_pos().to_numpy()
    refmdi = ref.adx_neg().to_numpy()
    assert np.allclose(ours["adx"].to_numpy()[5:], refadx[5:], atol=1e-9)
    assert np.allclose(ours["adx"].to_numpy()[5:], 100.0, atol=1e-9)  # pure uptrend
    assert np.allclose(ours["plus_di"].to_numpy()[4:], refpdi[4:], atol=1e-9)
    assert np.allclose(ours["plus_di"].to_numpy()[4:], 50.0, atol=1e-9)  # 100·1/2
    assert np.allclose(ours["minus_di"].to_numpy()[4:], refmdi[4:], atol=1e-9)
    assert np.allclose(refmdi, 0.0, atol=0.0)  # -DI = 0 everywhere on this data
    # Filler divergence: ta's np.zeros warmup vs our NaN (documented).
    assert (refadx[:5] == 0.0).all() and (refpdi[:4] == 0.0).all()
    assert ours["adx"].iloc[:5].isna().all() and ours["plus_di"].iloc[:3].isna().all()


# ===========================================================================
# SECTION 5: Properties
# ===========================================================================


@pytest.mark.parametrize(
    "name,params",
    [
        ("atr", {"period": 14}),
        ("stoch", {"k_period": 14, "smooth_period": 3, "d_period": 3}),
        ("adx", {"period": 14}),
    ],
)
def test_output_index_equals_input_index(name: str, params: dict[str, Any]) -> None:
    """Output index equals input index for all three indicators (test 25)."""
    rng = np.random.default_rng(7)
    n = 60
    close = 100.0 + np.cumsum(rng.uniform(-0.5, 0.5, n))
    bars = _bars((close + 1.0).tolist(), (close - 1.0).tolist(), close.tolist())
    out = REGISTRY.get(name).compute_fn(bars, params, "close")
    assert out.index.equals(bars.index)


def test_stoch_bounds() -> None:
    """%K and %D in [0, 100] on a 300-bar seeded random walk (test 23).

    %K = 100·(c-LL)/(HH-LL) with LL <= c <= HH → in [0, 100] (flat → 50);
    %D = SMA of values in [0, 100] → also in [0, 100].
    """
    rng = np.random.default_rng(20260922)
    n = 300
    close = 100.0 + np.cumsum(rng.uniform(-0.5, 0.5, n))
    high = close + rng.uniform(0.0, 1.0, n)
    low = close - rng.uniform(0.0, 1.0, n)
    out = compute_stoch(
        _bars(high.tolist(), low.tolist(), close.tolist()),
        {"k_period": 14, "smooth_period": 3, "d_period": 3},
        "close",
    )
    for col in ("k", "d"):
        valid = out[col].dropna()
        assert len(valid) > 0
        assert (valid >= 0.0).all() and (valid <= 100.0).all()
        assert np.isfinite(valid.to_numpy()).all()


def test_registry_warmups() -> None:
    """Registry warmup contracts (test 26): atr=3, stoch=4, adx=5 for period 3.

    atr: first TR at 1, seed SMA(TR[1..3]) at 3 → warmup = period = 3.
    stoch: (k-1)+(smooth-1)+(d-1) = 2+0+2 = 4 for k=3, smooth=1, d=3.
    adx: 2·period-1 = 5 (OQ-0022 corrected; the task text said 6).
    """
    assert REGISTRY.get("atr").warmup_fn({"period": 3}) == 3
    assert REGISTRY.get("stoch").warmup_fn({"k_period": 3, "smooth_period": 1, "d_period": 3}) == 4
    assert REGISTRY.get("adx").warmup_fn({"period": 3}) == 5
    # Defaults, cross-checked against the task's registration table:
    assert REGISTRY.get("atr").warmup_fn({"period": 14}) == 14
    # stoch defaults: (k-1)+(smooth-1)+(d-1) = 13+2+2 = 17 (== k+s+d-3)
    stoch_defaults = {"k_period": 14, "smooth_period": 3, "d_period": 3}
    assert REGISTRY.get("stoch").warmup_fn(stoch_defaults) == 17
    assert REGISTRY.get("adx").warmup_fn({"period": 14}) == 27  # 2·14-1


# ===========================================================================
# SECTION 6: Truncation invariance (marker: lookahead) + canary
# ===========================================================================


def _random_ohlc_bars(n: int, seed: int) -> Bars:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.uniform(-0.5, 0.5, n))
    high = close + rng.uniform(0.0, 1.0, n)
    low = close - rng.uniform(0.0, 1.0, n)
    return _bars(high.tolist(), low.tolist(), close.tolist())


def _assert_prefix_equal(a: pd.DataFrame, b: pd.DataFrame, n: int, cols: tuple[str, ...]) -> None:
    """NaN-aware equality of the first n rows (float-exact, per P2-T2/T3 style)."""
    for col in cols:
        va = a[col].iloc[:n].to_numpy(dtype=float)
        vb = b[col].iloc[:n].to_numpy(dtype=float)
        assert np.array_equal(va, vb, equal_nan=True), f"prefix differs in column {col}"


@pytest.mark.lookahead
@pytest.mark.parametrize(
    "name,params,cols",
    [
        ("atr", {"period": 5}, ("value",)),
        ("stoch", {"k_period": 5, "smooth_period": 3, "d_period": 3}, ("k", "d")),
        ("adx", {"period": 5}, ("adx", "plus_di", "minus_di")),
    ],
)
def test_truncation_invariance(name: str, params: dict[str, Any], cols: tuple[str, ...]) -> None:
    """Truncation invariance (tests 27-29): outputs on bars[:40] == bars[:60][:40].

    All three kernels are causal: every output at t depends only on rows <= t
    (rolling windows end at t; Wilder recursions read t-1 or earlier). The
    first 40 rows must therefore be identical, NaN-aware.
    """
    full = REGISTRY.get(name).compute_fn(_random_ohlc_bars(60, 555), params, "close")
    trunc = REGISTRY.get(name).compute_fn(_random_ohlc_bars(60, 555)[:40], params, "close")
    assert len(trunc) == 40
    _assert_prefix_equal(trunc, full, 40, cols)


class _LeakyATR:
    """CANARY: deliberately looks ahead — centering the TR window reads future
    highs/lows. Must FAIL the truncation test above (red-on-leak proof)."""

    @staticmethod
    def compute(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
        del source
        period = int(params["period"])
        high = bars["high"]
        low = bars["low"]
        close = bars["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        # LEAK: centered window — the value at t uses TRs from t-1 to t+period-2,
        # i.e. future bars beyond t.
        leaky = tr.shift(-(period - 1)).rolling(window=period, min_periods=period).mean()
        return pd.DataFrame({"value": leaky}, index=bars.index)


@pytest.mark.lookahead
def test_canary_leaky_atr_is_caught() -> None:
    """CANARY (test 30): the centered-window LeakyATR must FAIL truncation.

    Mechanism: the shift(-4) makes leaky[t] = mean(TR[t .. t+4]) — every
    output consumes `period-1` future bars. Outputs with t <= 35 only need
    TRs up to index 39 (identical in both frames); t = 36..39 need TRs from
    rows 40..43, which do not exist in bars[:40] (pandas yields NaN there)
    but are real numbers on the full frame → the prefixes diverge at exactly
    t = 36..39. Assert the divergence exists in that zone AND that identical
    prefixes hold before it (proving the canary isolates the leak).
    """
    params: dict[str, Any] = {"period": 5}
    full = _LeakyATR.compute(_random_ohlc_bars(60, 555), params, "close")["value"]
    trunc = _LeakyATR.compute(_random_ohlc_bars(60, 555)[:40], params, "close")["value"]
    va = trunc.to_numpy(dtype=float)
    vb = full.to_numpy(dtype=float)[:40]
    leak_zone = slice(36, 40)  # t = 36..39: windows reach past row 39
    # The truncation harness MUST catch this: prefixes are not identical.
    assert not np.array_equal(va, vb, equal_nan=True)
    # The canary isolates the leak: identical before the tail, divergent in it.
    assert np.array_equal(va[:36], vb[:36], equal_nan=True)
    assert not np.array_equal(va[leak_zone], vb[leak_zone], equal_nan=True)


# ===========================================================================
# Coverage extras: NaN-contamination reseed paths (OQ-0016 semantics) and
# the degenerate special cases mandated by the task text.
# ===========================================================================


def test_atr_nan_reseed() -> None:
    """A NaN high poisons the reachable ATR outputs; the chain reseeds.

    h = [11,12,nan,14,15,16,17], l = [9..15], c = [10..16], period=2.
    TR[1]=2, TR[2]=max(nan-10... → NaN (nan high), TR[3]=2, TR[4]=2.
    Seed SMA(TR[1..2]) impossible (TR[2] NaN) → reseed: SMA(TR[3..4]) = 2.0
    at index 4. ATR = [·, ·, ·, ·, 2.0] — valid again WITHOUT an all-NaN tail.
    """
    out = compute_atr(
        _bars(
            [11.0, 12.0, np.nan, 14.0, 15.0],
            [9.0, 10.0, 11.0, 12.0, 13.0],
            [10.0, 11.0, 12.0, 13.0, 14.0],
        ),
        {"period": 2},
        "close",
    )
    atr = out["value"].to_numpy()
    assert np.isnan(atr[:4]).all()
    assert atr[4] == pytest.approx(2.0, abs=1e-12)


def test_adx_zero_smoothed_tr_di_is_zero() -> None:
    """smoothed_TR == 0 → DI = 0 (task special case; exact-degenerate bars).

    Constant OHLC (h=l=c=10): TR[t] = max(0, 0, 0) = 0 for t>=1 → the running
    sum of TR is 0 from its seed → DI = 0 (never NaN, never 0/0), DX = 0
    (denominator 0), ADX = Wilder of DX-0s = 0.
    Timing: DI valid from t=period=3 (seed windows [NaN,0,0] invalid →
    [0,0,0] at t=3); ADX valid from 2·period-1 = 5.
    """
    n = 12
    out = compute_adx(_bars([10.0] * n, [10.0] * n, [10.0] * n), {"period": 3}, "close")
    for col in ("plus_di", "minus_di"):
        s = out[col]
        assert s.iloc[:3].isna().all()  # DI warmup = period = 3
        assert (s.iloc[3:] == 0.0).all()  # degenerate → 0.0, never NaN/inf
    adx = out["adx"]
    assert adx.iloc[:5].isna().all()  # ADX warmup = 2·period-1 = 5
    assert (adx.iloc[5:] == 0.0).all()


def test_adx_nan_contamination_reseed() -> None:
    """A NaN bar poisons the reachable ADX outputs; all chains reseed.

    Unit ramp h=11+t, l=9+t, c=10+t (t=0..19) with bar 10 fully NaN, period=3.
    Clean start (as test_adx_hand_computed): sums seeded at t=3 → +DI[3]=50,
    DX[3..]=100; ADX seeded at t=5 = 100.
    Bar 10 NaN ⇒ the changes INTO bars 10 AND 11 are NaN (10→NaN and
    NaN→11), so DM[10]=DM[11]=NaN and TR[10]=TR[11]=NaN.
      DM/TR sums: contaminated at t=10..11; first fully-valid 3-window is
      [12,13,14] → reseed at t=14 (line: running-sum reseed branch):
      sp = 1+1+1 = 3, st = 2+2+2 = 6 → +DI[14] = 50, -DI = 0, DX[14] = 100.
      DI at t=10..13 = NaN (sums NaN → the DI-loop continue branch fires).
      ADX: seeded at 5; the LAGGED recursion at t reads DX[t-1] only, so
      ADX[10] = (2/3)·100 + (1/3)·DX[9] = 100 stays VALID (DX[9] is
      pre-contamination); at t=11 it reads DX[10] = NaN → reseed branch
      fires; ADX[11..15] = NaN; first fully-valid 3-window of DX is
      [14,15,16] (DX[12..13] still NaN from the un-reseeded sums) →
      ADX[16] = (100+100+100)/3 = 100.
    """
    n = 20
    high = [11.0 + t for t in range(n)]
    low = [9.0 + t for t in range(n)]
    close = [10.0 + t for t in range(n)]
    high[10] = np.nan
    low[10] = np.nan
    close[10] = np.nan
    out = compute_adx(_bars(high, low, close), {"period": 3}, "close")
    pdi, mdi, adx = out["plus_di"], out["minus_di"], out["adx"]
    # Clean start
    assert _loc(pdi, 3) == pytest.approx(50.0, abs=1e-12)
    assert _loc(adx, 5) == pytest.approx(100.0, abs=1e-12)
    # Contamination: DI reads same-bar sums → NaN from t=10; the lagged ADX
    # still reads DX[9] at t=10 → valid one bar longer.
    assert pdi.iloc[10:14].isna().all()
    assert _loc(adx, 10) == pytest.approx(100.0, abs=1e-12)
    assert adx.iloc[11:16].isna().all()
    # Reseeded chains: identical values to the pre-contamination regime
    assert _loc(pdi, 14) == pytest.approx(50.0, abs=1e-12)  # 100·3/6
    assert _loc(mdi, 14) == 0.0
    assert _loc(adx, 16) == pytest.approx(100.0, abs=1e-12)  # mean(DX[14..16])


def test_adx_equal_moves_both_dm_zero() -> None:
    """up == down (both positive) → +DM = -DM = 0 (task tie rule).

    EXPANDING bars: h = [10, 11, 12, 13], l = [9, 8, 7, 6], c = midpoints.
    up[t] = h[t]-h[t-1] = +1 and down[t] = l[t-1]-l[t] = +1 for all t>=1
    → neither strictly dominates → +DM = -DM = 0 (the tie rule; note a
    rising-low series would give down = -1 and NOT exercise the tie).
    TR[t] = max(h-l=3, |h-c[t-1]|=1.5, |l-c[t-1]|=1.5) = 3 for t>=1.
    period=2: seed windows [NaN,x] invalid → sums seeded at t=2:
      sp = 0+0 = 0, st = 3+3 = 6 → +DI[2] = 100·0/6 = 0, -DI = 0,
      DX = 0 (denominator rule); t=3: st = 6+3-3 = 6 → same.
      ADX seed = SMA(DX[2..3]) = 0 at t=3 (warmup 2·2-1 = 3).
    """
    out = compute_adx(
        _bars([10.0, 11.0, 12.0, 13.0], [9.0, 8.0, 7.0, 6.0], [9.5, 10.5, 11.5, 12.5]),
        {"period": 2},
        "close",
    )
    assert (out["plus_di"].iloc[2:] == 0.0).all()
    assert (out["minus_di"].iloc[2:] == 0.0).all()
    assert (out["adx"].iloc[3:] == 0.0).all()  # ADX warmup = 2·2-1 = 3


def test_stoch_flat_then_trend_k_recovery() -> None:
    """Flat window (→ %K = 50) followed by trending bars — hand-computed.

    h=l=c=5 for t=0..2 (flat: windows ending at t=2,3 are flat → 50);
    then h=[...,8], l=[...,4], c=[...,7]: window at t=4 = h[2..4]=[5,5,8],
    l[2..4]=[5,5,4], close=7 → HH=8, LL=4 → %K = 100·(7-4)/4 = 75.0.
    %D = SMA(50, 50, 75)/3 → 175/3 = 58.333 at t=4 (d=3).
    """
    out = compute_stoch(
        _bars([5.0, 5.0, 5.0, 5.0, 8.0], [5.0, 5.0, 5.0, 5.0, 4.0], [5.0, 5.0, 5.0, 5.0, 7.0]),
        {"k_period": 3, "smooth_period": 1, "d_period": 3},
        "close",
    )
    k, d = out["k"], out["d"]
    assert _loc(k, 2) == 50.0  # flat → 50 by convention
    assert _loc(k, 3) == 50.0  # still flat window
    assert _loc(k, 4) == pytest.approx(75.0, abs=1e-12)  # 100·3/4
    assert _loc(d, 4) == pytest.approx(58.33, abs=0.01)  # 175/3
