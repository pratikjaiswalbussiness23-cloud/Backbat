"""Highest-high / lowest-low channel indicators (ROADMAP P2-T6, §4.3).

Conventions (task text — the no-lookahead channel design):

* **HIGHEST**: ``highest[t] = max(high[t-period] .. high[t-1])`` — the rolling
  maximum of the HIGH column over the PREVIOUS ``period`` bars, EXCLUDING the
  current bar. ``warmup = period`` (first valid output at index ``period``;
  positions 0..period-1 are NaN). Purpose: breakout signals — by excluding
  the current bar, ``close[t] > highest[t]`` uses only PAST highs and can
  therefore never leak future information (an inclusive window would force
  ``close[t] > high[t]``, which validated OHLC data makes impossible).
  Our values equal ta's Donchian upper band shifted one bar right
  (ta's DonchianChannel INCLUDES the current bar — probed divergence,
  documented in docs/verified_apis.md).
* **LOWEST**: symmetric — ``lowest[t] = min(low[t-period] .. low[t-1])``,
  rolling minimum of the LOW column excluding the current bar; breakdown
  signals. Same warmup.

Both read ``bars["high"]`` / ``bars["low"]`` directly; the ``source``
parameter is a registration placeholder (``allowed_sources`` pins the
semantically correct column).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from nlbt.data.models import Bars
from nlbt.indicators.registry import IndicatorSpec, ParamSpec, register_indicator

__all__ = ["compute_highest", "compute_lowest"]


def _period_warmup(params: dict[str, Any]) -> int:
    """Window over the PREVIOUS period bars → first valid at index period."""
    return int(params["period"])


def compute_highest(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """Highest-high over the PREVIOUS ``period`` bars (excludes current).

    ``source`` is ignored by design (registration placeholder): the indicator
    always reads ``bars["high"]``.
    """
    del source  # reads the high column directly; source is a placeholder
    period = int(params["period"])
    shifted = bars["high"].shift(1)  # exclude the current bar
    highest = shifted.rolling(window=period, min_periods=period).max()
    return pd.DataFrame({"value": highest}, index=bars.index)


def compute_lowest(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """Lowest-low over the PREVIOUS ``period`` bars (excludes current).

    ``source`` is ignored by design (registration placeholder): the indicator
    always reads ``bars["low"]``.
    """
    del source  # reads the low column directly; source is a placeholder
    period = int(params["period"])
    shifted = bars["low"].shift(1)  # exclude the current bar
    lowest = shifted.rolling(window=period, min_periods=period).min()
    return pd.DataFrame({"value": lowest}, index=bars.index)


# ---------------------------------------------------------------------------
# Registration (P2-T1 contract: indicator modules register at import time).
# ---------------------------------------------------------------------------

register_indicator(
    IndicatorSpec(
        name="highest",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=500,
                default=20,
                description=(
                    "Lookback bars (PREVIOUS bars only, current excluded); "
                    "inclusive bounds [2, 500]."
                ),
            )
        },
        allowed_sources=("high",),
        warmup_fn=_period_warmup,
        compute_fn=compute_highest,
        description=(
            "Highest high of the PREVIOUS `period` bars (current bar "
            "excluded): highest[t] = max(high[t-period..t-1]); first valid "
            "output at index period. Breakout signals compare close[t] > "
            "highest[t] using only past highs — no lookahead by construction."
        ),
    )
)

register_indicator(
    IndicatorSpec(
        name="lowest",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=500,
                default=20,
                description=(
                    "Lookback bars (PREVIOUS bars only, current excluded); "
                    "inclusive bounds [2, 500]."
                ),
            )
        },
        allowed_sources=("low",),
        warmup_fn=_period_warmup,
        compute_fn=compute_lowest,
        description=(
            "Lowest low of the PREVIOUS `period` bars (current bar excluded): "
            "lowest[t] = min(low[t-period..t-1]); first valid output at index "
            "period. Breakdown signals compare close[t] < lowest[t] using "
            "only past lows — no lookahead by construction."
        ),
    )
)
