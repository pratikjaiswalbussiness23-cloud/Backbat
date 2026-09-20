"""ATR, Stochastic Oscillator and ADX (ROADMAP P2-T5, §4.3).

Conventions (task text; divergence notes vs the ``ta`` oracle probed in
docs/verified_apis.md):

* **ATR**: ``TR[t] = max(high-low, |high-prev_close|, |low-prev_close|)`` with
  ``TR[0] = NaN`` (no prev_close); Wilder smoothing ``alpha = 1/period``; the
  seed is the SMA of TR[1..period] placed at index ``period`` (so
  ``warmup = period``). Output >= 0, never inf.
  Unlike ta 0.11.0 — which seeds from TR[0..period-1] (its bar-0 value is the
  ``high-low`` filler) and emits ``0.0`` warmup filler — our warmup is NaN,
  and on common data the two chains agree from the convergence window.
* **Stochastic**: raw ``%K = 100*(close-LL)/(HH-LL)`` over the last
  ``k_period`` bars inclusive; ``smooth_period > 1`` SMA-smooths raw %K
  BEFORE %D; ``%D = SMA(%K, d_period)``. Flat window (HH == LL) → %K = 50.0
  (never NaN/0/inf). ``warmup = k_period - 1 + smooth_period - 1 + d_period - 1``.
  NOTE: ta 0.11.0's ``smooth_window`` smooths %D only, never %K (source read)
  and its flat windows produce NaN, then fillna(50) — different semantics.
* **ADX**: ``up = high-high[prev]``, ``down = low[prev]-low``;
  ``+DM = up if up > down and up > 0 else 0``; ``-DM = down if down > up and
  down > 0 else 0`` (so ``up == down`` → both 0). +DM/-DM/TR are smoothed
  Wilder-style with running sums seeded by the SUM of the first ``period``
  values (valid from index ``period``); ``+DI = 100*sm+DM/smTR``,
  ``-DI = 100*sm-DM/smTR`` (smTR == 0 → DI = 0);
  ``DX = 100*|+DI - -DI|/(+DI + -DI)`` (denominator 0 → DX = 0);
  ADX = Wilder smoothing of DX, seed = SMA of the first ``period`` DX values.
  The first ``period`` DX values exist from index ``period`` onward, so the
  seed lands at index ``2*period - 1`` → ``warmup = 2*period - 1``
  (OQ-0022: the task's "warmup = 2*period" is off by one against its own
  cascade arithmetic and against the ta probe, whose first real ADX is also
  at ``2*period - 1``). The ADX recursion reads DX[t-1] (ta-consistent lagged
  form), which is why it cannot reuse :func:`._wilders_rma` (same-bar reads).

Implemented from these formulas — no ``pandas ewm()``, no ``ta`` in
production code. NaN handling mirrors OQ-0016: a NaN input poisons the
outputs reachable from it; smoothing chains reseed on the next fully-valid
window. Bars validation blocks NaN OHLC upstream, so this is defensive.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from nlbt.data.models import Bars
from nlbt.indicators.momentum import _wilders_rma
from nlbt.indicators.registry import IndicatorSpec, ParamSpec, register_indicator
from nlbt.indicators.trend import _sma_vectorised

__all__ = ["compute_adx", "compute_atr", "compute_stoch"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _true_ranges(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """True Range per the task formula; ``TR[0]`` is NaN (no prev_close)."""
    n = len(high)
    tr = np.full(n, np.nan)
    for t in range(1, n):
        hl = high[t] - low[t]
        hc = abs(high[t] - close[t - 1])
        lc = abs(low[t] - close[t - 1])
        tr[t] = max(hl, hc, lc)
    return tr


def _atr_warmup(params: dict[str, Any]) -> int:
    """First TR is at index 1; the seed SMA covers TR[1..period]."""
    return int(params["period"])


def _stoch_warmup(params: dict[str, Any]) -> int:
    """k-1 (raw %K) + smooth-1 (smoothed %K) + d-1 (%D)."""
    k = int(params["k_period"])
    s = int(params["smooth_period"])
    d = int(params["d_period"])
    return k - 1 + s - 1 + d - 1


def _adx_warmup(params: dict[str, Any]) -> int:
    """First ADX at index 2*period - 1 — see module docstring / OQ-0022."""
    return 2 * int(params["period"]) - 1


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------


def compute_atr(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """ATR kernel — Wilder smoothing of True Range, SMA-seeded (task text).

    ``source`` is ignored by design (registration placeholder): ATR always
    reads ``bars["high"]``, ``bars["low"]``, ``bars["close"]``.
    """
    del source  # ATR reads high/low/close directly; source is a placeholder
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    period = int(params["period"])
    trs = _true_ranges(high, low, close)
    # trs has NaN at index 0, so _wilders_rma's first valid window is
    # trs[1..period] → seed (its mean) lands exactly at index `period`.
    atr = _wilders_rma(trs, period)
    return pd.DataFrame({"value": atr}, index=bars.index)


# ---------------------------------------------------------------------------
# Stochastic Oscillator
# ---------------------------------------------------------------------------


def compute_stoch(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """Stochastic %K/%D kernel — task conventions (smooth %K before %D).

    ``source`` is ignored by design (registration placeholder): Stochastic
    always reads ``bars["high"]``, ``bars["low"]``, ``bars["close"]``.
    """
    del source  # reads high/low/close directly; source is a placeholder
    k_period = int(params["k_period"])
    smooth = int(params["smooth_period"])
    d_period = int(params["d_period"])

    high = bars["high"]
    low = bars["low"]
    close = bars["close"]

    # min_periods=k_period: a window containing any NaN yields NaN (pandas
    # min_periods counts non-NaN observations) — matches OQ-0016 semantics.
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()

    denom = highest_high - lowest_low
    raw_k = 100.0 * (close - lowest_low) / denom
    flat = denom == 0.0  # flat window (incl. NaN-safe: NaN == 0.0 is False)
    raw_k = raw_k.mask(flat, 50.0)  # special case: HH == LL → 50.0

    k = _sma_vectorised(raw_k, smooth) if smooth > 1 else raw_k
    d = _sma_vectorised(k, d_period)
    return pd.DataFrame({"k": k, "d": d}, index=bars.index)


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------


def _wilder_adx_from_dx(dxi: np.ndarray, period: int) -> np.ndarray:
    """ADX = Wilder smoothing of DX with the ta-consistent lagged recursion.

    Seed = mean of the first ``period`` valid DX values (DX is valid from
    index ``period``), placed at ``2*period - 1``; then
    ``adx[t] = (1-alpha)*adx[t-1] + alpha*DX[t-1]`` (reads DX[t-1], unlike
    the same-bar reads of :func:`._wilders_rma`). NaN DX poisons the chain;
    it reseeds on the next fully-valid window (OQ-0016 semantics).
    """
    alpha = 1.0 / period
    n = len(dxi)
    adx = np.full(n, np.nan)
    running = np.nan
    seeded = False
    for t in range(2 * period - 1, n):
        if not seeded:
            window = dxi[t - period + 1 : t + 1]
            if not np.isnan(window).any():
                running = float(window.mean())
                adx[t] = running
                seeded = True
        elif np.isnan(dxi[t - 1]):
            seeded = False  # recursion reads DX[t-1]; contamination → reseed
        else:
            running = alpha * dxi[t - 1] + (1.0 - alpha) * running
            adx[t] = running
    return adx


def _wilder_running_sums(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder running-sum smoothing (unnormalised RMA), OQ-0016 reseeds.

    Seed = SUM of the first ``period`` valid values, placed at the index of
    the last element of that window; then
    ``out[t] = out[t-1] + values[t] - out[t-1]/period``.
    Used for +DM/-DM/TR in ADX (the seed is a sum, not a mean, and the DI
    ratio 100*sum/smTR is scale-invariant to that choice).
    """
    n = len(values)
    out = np.full(n, np.nan)
    running = np.nan
    seeded = False
    for t in range(period - 1, n):
        if not seeded:
            window = values[t - period + 1 : t + 1]
            if not np.isnan(window).any():
                running = float(window.sum())
                out[t] = running
                seeded = True
        elif np.isnan(values[t]):
            seeded = False
        else:
            running = running + values[t] - running / period
            out[t] = running
    return out


def compute_adx(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """ADX/+DI/-DI kernel — Wilder DM/TR smoothing, task conventions.

    ``source`` is ignored by design (registration placeholder): ADX always
    reads ``bars["high"]``, ``bars["low"]``, ``bars["close"]``.
    """
    del source  # reads high/low/close directly; source is a placeholder
    period = int(params["period"])
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    n = len(high)

    up = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    # Task rule: +DM = max(up, 0) only when it strictly exceeds max(down, 0);
    # -DM symmetric (so up == down > 0 → both 0). NaN diffs propagate as NaN.
    # Index 0 is NaN (no previous bar): keeps the smoothing seed windows
    # aligned to values[1..period], i.e. ta's dropna-seed composition.
    pos_dm = np.full(n, np.nan)
    neg_dm = np.full(n, np.nan)
    pos_dm[1:] = np.where(np.isnan(up), np.nan, np.where(up > down, np.maximum(up, 0.0), 0.0))
    neg_dm[1:] = np.where(np.isnan(down), np.nan, np.where(down > up, np.maximum(down, 0.0), 0.0))

    trs = _true_ranges(high, low, close)

    sum_pdm = _wilder_running_sums(pos_dm, period)
    sum_ndm = _wilder_running_sums(neg_dm, period)
    sum_tr = _wilder_running_sums(trs, period)

    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    dxi = np.full(n, np.nan)
    for t in range(period, n):
        st = sum_tr[t]
        sp = sum_pdm[t]
        sn = sum_ndm[t]
        if np.isnan(st) or np.isnan(sp) or np.isnan(sn):
            continue  # warmup / contamination
        if st == 0.0:
            plus_di[t] = 0.0  # special case: smoothed_TR == 0 → DI = 0
            minus_di[t] = 0.0
        else:
            plus_di[t] = 100.0 * sp / st
            minus_di[t] = 100.0 * sn / st
        s = plus_di[t] + minus_di[t]
        dxi[t] = 0.0 if s == 0.0 else 100.0 * abs(plus_di[t] - minus_di[t]) / s

    adx = _wilder_adx_from_dx(dxi, period)
    return pd.DataFrame({"adx": adx, "plus_di": plus_di, "minus_di": minus_di}, index=bars.index)


# ---------------------------------------------------------------------------
# Registration (P2-T1 contract: indicator modules register at import time).
# ---------------------------------------------------------------------------

register_indicator(
    IndicatorSpec(
        name="atr",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=100,
                default=14,
                description="Lookback bars for Wilder ATR; inclusive bounds [2, 100].",
            )
        },
        allowed_sources=("close",),  # placeholder per task text; high/low/close read directly
        warmup_fn=_atr_warmup,
        compute_fn=compute_atr,
        description=(
            "Average true range: TR = max(high-low, |high-prev_close|, "
            "|low-prev_close|), TR[0] = NaN; Wilder smoothing alpha=1/period "
            "seeded with the SMA of TR[1..period]; first valid output at "
            "index period; output >= 0, never inf."
        ),
    )
)

register_indicator(
    IndicatorSpec(
        name="stoch",
        outputs=("k", "d"),
        params={
            "k_period": ParamSpec(
                type="int",
                minimum=2,
                maximum=100,
                default=14,
                description="Raw %K lookback bars; inclusive bounds [2, 100].",
            ),
            "d_period": ParamSpec(
                type="int",
                minimum=2,
                maximum=100,
                default=3,
                description="%D = SMA(%K, d_period); inclusive bounds [2, 100].",
            ),
            "smooth_period": ParamSpec(
                type="int",
                minimum=1,
                maximum=10,
                default=3,
                description=(
                    "SMA smoothing applied to raw %K before %D "
                    "(1 = no smoothing); inclusive bounds [1, 10]."
                ),
            ),
        },
        allowed_sources=("close",),  # placeholder per task text; high/low/close read directly
        warmup_fn=_stoch_warmup,
        compute_fn=compute_stoch,
        description=(
            "Stochastic oscillator: %K = 100*(close-lowest_low)/"
            "(highest_high-lowest_low) over k_period bars; smooth_period > 1 "
            "SMA-smooths %K BEFORE %D; %D = SMA(%K, d_period); flat windows "
            "(HH == LL) -> %K = 50; outputs k and d, first valid at "
            "k_period+smooth_period+d_period-3."
        ),
    )
)

register_indicator(
    IndicatorSpec(
        name="adx",
        outputs=("adx", "plus_di", "minus_di"),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=100,
                default=14,
                description="Wilder smoothing period for DM/TR/DI/ADX; inclusive bounds [2, 100].",
            )
        },
        allowed_sources=("close",),  # placeholder per task text; high/low/close read directly
        warmup_fn=_adx_warmup,
        compute_fn=compute_adx,
        description=(
            "Average directional index: +DM/-DM per the strict-dominance rule "
            "(equal moves -> both 0), Wilder running-sum smoothing seeded with "
            "the first `period` values; +DI/-DI = 100*smoothed_DM/smoothed_TR "
            "(smTR == 0 -> DI = 0); DX = 100*|+DI - -DI|/(+DI + -DI) "
            "(denominator 0 -> DX = 0); ADX = Wilder smoothing of DX with the "
            "first valid output at index 2*period-1; all outputs in [0, 100]."
        ),
    )
)
