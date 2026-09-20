"""RSI and ROC — momentum indicators (ROADMAP P2-T3, §4.3).

Conventions are FIXED by ADR-0003 (docs/adr/ADR-0003-rsi-seed-convention.md):

* **RSI** (Wilder 1978): ``gain[t] = max(price[t]-price[t-1], 0)``;
  ``loss[t] = max(price[t-1]-price[t], 0)`` (always positive); Wilder
  smoothing ``alpha = 1/period``; the smoothed averages are SEEDED with the
  SMA of the first ``period`` gains/losses (placed at index ``period``,
  since ``period`` changes need ``period+1`` prices); then
  ``avg[t] = alpha*value[t] + (1-alpha)*avg[t-1]``; ``RS = avg_gain/avg_loss``;
  ``RSI = 100 - 100/(1+RS)``. Special cases: ``avg_loss == 0`` → 100.0;
  ``avg_gain == 0 and avg_loss == 0`` → 50.0 (flat). Output always in
  [0, 100]; ``warmup = period``.
* **ROC**: ``(price[t]/price[t-period] - 1) * 100``; zero or NaN base price →
  NaN (never inf); ``warmup = period``.

Implemented from these formulas — no ``pandas ewm()``, no ``ta`` in
production code (``ta`` is a dev-only oracle; probed divergence documented in
docs/verified_apis.md and OQ-0017: ta's RSI uses ``ewm(adjust=False)`` from
index 0 and is valid from ``period-1``, one bar earlier than Wilder's seed).

NaN handling mirrors P2-T2 (OQ-0016): a NaN change poisons the smoothed
averages reachable from it; the recursion reseeds on the next fully-valid
window. Bars validation blocks NaN OHLC upstream, so this is defensive.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from nlbt.data.models import Bars
from nlbt.indicators.registry import IndicatorSpec, ParamSpec, register_indicator
from nlbt.indicators.trend import _SOURCES

__all__ = ["compute_roc", "compute_rsi"]


def _wilder_warmup(params: dict[str, Any]) -> int:
    """Both conventions put the first valid output at index ``period``."""
    return int(params["period"])


def _wilders_rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder smoothing in *values* space: SMA seed, then alpha=1/period.

    The SMA of the first ``period`` values lands at values-index
    ``period - 1``; the recursion continues from there. A NaN poisons the
    reachable outputs; the chain reseeds on the next fully-valid window
    (same semantics as the P2-T2 EMA, OQ-0016).
    """
    alpha = 1.0 / period
    out = np.full(len(values), np.nan)
    running = np.nan
    seeded = False
    for t in range(period - 1, len(values)):
        if not seeded:
            window = values[t - period + 1 : t + 1]
            if not np.isnan(window).any():
                running = float(window.mean())
                out[t] = running
                seeded = True
        elif np.isnan(values[t]):
            seeded = False  # recursion contaminated; must reseed
        else:
            running = alpha * values[t] + (1.0 - alpha) * running
            out[t] = running
    return out


def compute_rsi(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """RSI kernel — Wilder's SMA-seeded smoothing (ADR-0003), from formulas."""
    period = int(params["period"])
    prices = bars[source].to_numpy(dtype=float)
    n = len(prices)

    diff = np.diff(prices) if n > 1 else np.empty(0)
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    nan_change = np.isnan(diff)
    gain[nan_change] = np.nan  # preserve NaN changes (np.where would zero them)
    loss[nan_change] = np.nan

    # gains[i]/losses[i] describe the change INTO price index i+1; the
    # smoothed arrays are therefore read at t-1 for output index t.
    avg_gain = _wilders_rma(gain, period)
    avg_loss = _wilders_rma(loss, period)

    rsi = np.full(n, np.nan)
    for t in range(period, n):
        ag = avg_gain[t - 1]
        al = avg_loss[t - 1]
        if np.isnan(ag) or np.isnan(al):
            continue  # warmup / contaminated (§4.3: NaN only while input NaN)
        if ag == 0.0 and al == 0.0:
            rsi[t] = 50.0  # flat prices: no movement (task-mandated case)
        elif al == 0.0:
            rsi[t] = 100.0  # only gains: RS = inf is NOT representable → 100
        else:
            rsi[t] = 100.0 - 100.0 / (1.0 + ag / al)
    return pd.DataFrame({"value": rsi}, index=bars.index)


def compute_roc(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """ROC kernel — ``(price[t]/price[t-period] - 1) * 100``, zero-safe."""
    period = int(params["period"])
    prices = bars[source].to_numpy(dtype=float)
    out = np.full(len(prices), np.nan)
    for t in range(period, len(prices)):
        base = prices[t - period]
        if np.isnan(base) or base == 0.0 or np.isnan(prices[t]):
            continue  # zero/NaN denominator → NaN, never inf
        out[t] = (prices[t] / base - 1.0) * 100.0
    return pd.DataFrame({"value": out}, index=bars.index)


# ---------------------------------------------------------------------------
# Registration (P2-T1 contract: indicator modules register at import time).
# ---------------------------------------------------------------------------

register_indicator(
    IndicatorSpec(
        name="rsi",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=100,
                default=14,
                description="Lookback bars for Wilder RSI; inclusive bounds [2, 100].",
            )
        },
        allowed_sources=_SOURCES,
        warmup_fn=_wilder_warmup,
        compute_fn=compute_rsi,
        description=(
            "Relative strength index: Wilder smoothing alpha=1/period, seeded "
            "with the SMA of the first `period` gains/losses (ADR-0003); first "
            "valid output at index period; flat prices -> 50, only gains -> "
            "100, only losses -> 0; output always in [0, 100]."
        ),
    )
)

register_indicator(
    IndicatorSpec(
        name="roc",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=1,
                maximum=500,
                default=10,
                description="Lookback bars for rate of change; inclusive bounds [1, 500].",
            )
        },
        allowed_sources=_SOURCES,
        warmup_fn=_wilder_warmup,
        compute_fn=compute_roc,
        description=(
            "Rate of change: (price[t]/price[t-period] - 1) * 100; zero or NaN "
            "base price -> NaN (never inf); first valid output at index period."
        ),
    )
)
