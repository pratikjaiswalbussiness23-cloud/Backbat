"""Return-based metrics (ROADMAP §4.7, P5-T1).

**Settled series (owner decision, OQ-0064):** every metric here is computed
on the SETTLED equity series the caller passes in — the engine's stored
equity curve with its last value replaced by the realized
``final_equity`` when a forced ``end_of_data`` close happened. The engine's
stored curve itself is NEVER modified (differential S1 depends on its
pre-settlement last row), so the curve's ``drawdown`` column may differ
slightly from the ``max_drawdown`` metric after a forced close — see
``docs/metrics.md``.

**null + warning (§4.7, I13):** an undefined metric is returned as ``None``
and a human-readable reason is appended to the returned warnings list —
never ``0``, ``NaN`` or ``inf`` when the metric is undefined. Warnings are
returned, not printed; surfacing them on ``BacktestResult`` is P5-T4's job
(OQ-0072, owner ruling (a)).

This module is pure numpy/pandas: it must never import ``nlbt.engine``
(dependency runs engine -> metrics only).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

__all__ = ["compute_return_metrics"]

#: Zero-variance threshold on the standard deviation of bar RETURNS.
#: Returns are dimensionless (relative to the equity level by construction),
#: so an absolute epsilon here is a relative one. Without it, a "flat" series
#: built from arithmetic (e.g. ``1000 + i*1e-13``) has std ~1e-32 and would
#: yield a meaningless huge Sharpe instead of null (owner adjustment, P5-T1).
_ZERO_VARIANCE_EPS = 1e-12

_METRIC_KEYS: tuple[str, ...] = (
    "total_return",
    "cagr",
    "annualised_volatility",
    "sharpe",
    "max_drawdown",
    "longest_drawdown_bars",
    "calmar",
)


def _null_warning(name: str, reason: str) -> str:
    """Warning text for a null metric (§4.7 null + warning rule)."""
    return f"Metric '{name}' is null: {reason} (§4.7 null+warning rule)"


def compute_return_metrics(
    settled_equity: np.ndarray | Sequence[float],
    index: pd.DatetimeIndex,
    bars_per_year: float,
    rf: float = 0.0,
) -> tuple[dict[str, float | None], list[str]]:
    """Compute the §4.7 return-based metrics on a SETTLED equity series.

    Parameters
    ----------
    settled_equity:
        Equity values, length >= 1, already settled (see module docstring).
    index:
        Bar dates of the same length (tz-aware), for the Years/CAGR formula.
    bars_per_year:
        From :func:`nlbt.data.frequency.infer_frequency` or explicitly
        supplied — never silently hardcoded (§4.7).
    rf:
        Annual risk-free rate, default 0; always reported as
        ``risk_free_rate`` next to Sharpe.

    Returns
    -------
    (metrics, warnings) — ``metrics`` always contains every §4.7 key plus
    ``risk_free_rate``; undefined metrics are ``None`` with a matching
    entry in ``warnings``. Never NaN/inf (I13).
    """
    if not np.isfinite(bars_per_year) or bars_per_year <= 0:
        raise ValueError(f"bars_per_year must be a positive finite number, got {bars_per_year!r}")

    metrics: dict[str, float | None] = {key: None for key in _METRIC_KEYS}
    metrics["risk_free_rate"] = float(rf)  # always present (§4.7 rf policy)
    warnings: list[str] = []

    e = np.asarray(settled_equity, dtype=float)
    n = int(e.size)

    if n == 0:
        warnings.append(_null_warning("all", "empty equity series"))
        return metrics, warnings
    if not np.isfinite(e).all():
        warnings.append(_null_warning("all", "non-finite value(s) in the equity series"))
        return metrics, warnings
    if e[0] <= 0.0:
        warnings.append(_null_warning("all", f"non-positive starting equity {e[0]!r}"))
        return metrics, warnings
    if n < 2:
        warnings.append(_null_warning("all", "fewer than 2 bars in the equity series"))
        return metrics, warnings

    r = e[1:] / e[:-1] - 1.0

    # ---- total return and CAGR (E_end / E_start over the settled series) ----
    metrics["total_return"] = float(e[-1] / e[0] - 1.0)
    years = float((pd.Timestamp(index[-1]) - pd.Timestamp(index[0])).days) / 365.25
    if years <= 0.0:
        warnings.append(_null_warning("cagr", "years == 0 (first and last bar dates are equal)"))
    elif e[-1] <= 0.0:
        warnings.append(_null_warning("cagr", f"non-positive ending equity {e[-1]!r}"))
    else:
        metrics["cagr"] = float((e[-1] / e[0]) ** (1.0 / years) - 1.0)

    # ---- annualised volatility and Sharpe ----
    if r.size < 2:
        # ddof=1 sample std needs >= 2 returns: undefined -> null, never
        # NaN (I13). A 2-bar run has exactly 1 return.
        reason = "fewer than 3 bars (sample std needs >= 2 bar returns)"
        warnings.append(_null_warning("annualised_volatility", reason))
        warnings.append(_null_warning("sharpe", reason))
    else:
        std = float(np.std(r, ddof=1))
        metrics["annualised_volatility"] = float(std * np.sqrt(bars_per_year))
        if std <= _ZERO_VARIANCE_EPS:
            warnings.append(_null_warning("sharpe", f"zero variance in bar returns (std={std:g})"))
        else:
            mean = float(np.mean(r))
            metrics["sharpe"] = float((mean - rf / bars_per_year) / std * np.sqrt(bars_per_year))

    # ---- max drawdown and longest drawdown duration (bars) ----
    peak = np.maximum.accumulate(e)
    drawdown = e / peak - 1.0
    max_dd = float(np.min(drawdown))
    metrics["max_drawdown"] = max_dd
    longest = current = 0
    for value in drawdown:
        current = current + 1 if value < 0.0 else 0
        longest = max(longest, current)
    metrics["longest_drawdown_bars"] = float(longest)

    # ---- Calmar ----
    cagr = metrics["cagr"]
    if max_dd == 0.0:
        warnings.append(_null_warning("calmar", "zero drawdown (max_drawdown == 0)"))
    elif cagr is None:
        warnings.append(_null_warning("calmar", "depends on a null CAGR"))
    else:
        metrics["calmar"] = float(cagr / abs(max_dd))

    return metrics, warnings
