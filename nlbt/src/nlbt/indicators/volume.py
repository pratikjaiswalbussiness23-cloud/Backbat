"""On-Balance Volume (ROADMAP P2-T6, §4.3).

Convention (task text — classic Wilder OBV):

* ``OBV[0] = volume[0]`` (seeded with the first bar's volume)
* for ``t > 0``:
  - ``close[t] > close[t-1]`` → ``OBV[t] = OBV[t-1] + volume[t]``
  - ``close[t] < close[t-1]`` → ``OBV[t] = OBV[t-1] - volume[t]``
  - ``close[t] == close[t-1]`` → ``OBV[t] = OBV[t-1]`` (NEUTRAL on flats)
* ``warmup = 0`` (valid from the first bar); no NaN in the output for clean
  input (NaN close/volume propagate — Bars validation blocks those upstream);
  output can be negative; no params.

NOT ta's convention: ta 0.11.0 computes
``np.where(close < close.shift(1), -volume, volume).cumsum()`` — its flat
closes ADD volume (the ``==`` case falls into the ``+volume`` else-branch).
Probed on the task's own 7-value series: ta = [100, 300, 150, 450, 550, 300,
700] vs the neutral-flat convention [100, 300, 150, 450, 450, 200, 600] —
diverges exactly at bars 4-6 (after the flat). Documented in
docs/verified_apis.md and OQ-0026; ours follows the task text.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from nlbt.data.models import Bars
from nlbt.indicators.registry import IndicatorSpec, register_indicator

__all__ = ["compute_obv"]


def _zero_warmup(_params: dict[str, Any]) -> int:
    """OBV is valid from the first bar (seeded with volume[0])."""
    return 0


def compute_obv(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
    """OBV kernel — classic Wilder OBV, neutral on flat closes (task text).

    ``source`` is ignored by design (registration placeholder): OBV always
    reads ``bars["close"]`` and ``bars["volume"]``.
    """
    del source, params  # OBV takes no params; reads close+volume directly
    close = bars["close"].to_numpy(dtype=float)
    volume = bars["volume"].to_numpy(dtype=float)
    n = len(close)

    obv = np.full(n, np.nan)
    if n == 0:
        return pd.DataFrame({"value": obv}, index=bars.index)
    obv[0] = volume[0]  # seed with the first bar's volume
    for t in range(1, n):
        if np.isnan(close[t]) or np.isnan(close[t - 1]) or np.isnan(volume[t]):
            continue  # NaN input → NaN output (never silently skipped)
        if close[t] > close[t - 1]:
            obv[t] = obv[t - 1] + volume[t]
        elif close[t] < close[t - 1]:
            obv[t] = obv[t - 1] - volume[t]
        else:
            obv[t] = obv[t - 1]  # flat close: carry unchanged (neutral)
    return pd.DataFrame({"value": obv}, index=bars.index)


# ---------------------------------------------------------------------------
# Registration (P2-T1 contract: indicator modules register at import time).
# ---------------------------------------------------------------------------

register_indicator(
    IndicatorSpec(
        name="obv",
        outputs=("value",),
        params={},  # OBV takes no parameters
        allowed_sources=("close",),  # placeholder; reads close + volume directly
        warmup_fn=_zero_warmup,
        compute_fn=compute_obv,
        description=(
            "On-balance volume: OBV[0] = volume[0]; up bars add volume, down "
            "bars subtract it, FLAT closes carry the previous value (neutral "
            "— classic Wilder convention, NOT ta's flat-adds convention); "
            "valid from the first bar (warmup 0); can be negative."
        ),
    )
)
