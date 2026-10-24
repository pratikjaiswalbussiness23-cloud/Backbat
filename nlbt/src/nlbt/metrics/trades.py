"""Trade-based metrics (ROADMAP §4.7, P5-T2; rulings OQ-0073 / OQ-0074).

Definitions (owner-ruled):

* ``win_rate`` — trades with ``net_pnl > 0`` over all trades (§4.7).
* ``profit_factor`` — **NET** basis: ``sum(net_pnl > 0) / abs(sum(net_pnl < 0))``
  (OQ-0074: consistent with win_rate); ``None`` + warning when there are no
  losses — the warning IS the §4.7 "flag" (no extra key).
* ``expectancy`` — mean ``return_pct`` over ALL trades (a breakeven trade
  with ``net_pnl == 0`` counts here).
* ``avg_win`` / ``avg_loss`` — means of ``return_pct`` split by
  ``net_pnl > 0`` / ``net_pnl < 0``; ``net_pnl == 0`` belongs to neither
  (OQ-0073).
* ``longest_losing_streak`` — consecutive trades with ``net_pnl < 0``; a
  breakeven trade resets the streak (OQ-0073).
* ``exposure`` — fraction of bars with an open position, from the boolean
  mask (equity-curve ``position_value > 0``).

null + warning policy (§4.7, I13): undefined → ``None`` + warning, never
``0``/``NaN``/``inf``. Warnings are returned, NOT appended to
``result.warnings`` (OQ-0072 ruling (a); surfaced in P5-T4).

MAE/MFE aggregates are OUT (OQ-0073 deferred): the per-trade fields already
exist on ``Trade``.

Pure module: must never import ``nlbt.engine`` (one-way dependency).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np

__all__ = ["TradeLike", "compute_trade_metrics"]


class TradeLike(Protocol):
    """Structural view of a trade — keeps this module engine-free."""

    net_pnl: float
    return_pct: float


_METRIC_KEYS: tuple[str, ...] = (
    "num_trades",
    "win_rate",
    "profit_factor",
    "expectancy",
    "avg_win",
    "avg_loss",
    "longest_losing_streak",
    "exposure",
)


def _null_warning(name: str, reason: str) -> str:
    """Warning text for a null metric (§4.7 null + warning rule)."""
    return f"Metric '{name}' is null: {reason} (§4.7 null+warning rule)"


def compute_trade_metrics(
    trades: Sequence[TradeLike],
    open_position_mask: np.ndarray,
) -> tuple[dict[str, float | None], list[str]]:
    """Compute the §4.7 trade-based metrics.

    Parameters
    ----------
    trades:
        Completed trades (engine ``Trade`` satisfies :class:`TradeLike`).
    open_position_mask:
        Boolean per-bar array — True where a position is open (engine:
        ``equity_curve["position_value"] > 0``).

    Returns
    -------
    (metrics, warnings) — every key in :data:`_METRIC_KEYS`; undefined
    metrics are ``None`` with a matching warning. Never NaN/inf (I13).
    """
    metrics: dict[str, float | None] = {key: None for key in _METRIC_KEYS}
    metrics["num_trades"] = float(len(trades))
    warnings: list[str] = []

    mask = np.asarray(open_position_mask, dtype=bool)
    if mask.size == 0:
        warnings.append(_null_warning("exposure", "empty bar series"))
    else:
        metrics["exposure"] = float(np.count_nonzero(mask)) / float(mask.size)

    if not trades:
        warnings.append(
            _null_warning(
                "trade metrics",
                "no trades (win_rate, profit_factor, expectancy, avg_win, "
                "avg_loss, longest_losing_streak)",
            )
        )
        return metrics, warnings

    net = np.fromiter((t.net_pnl for t in trades), dtype=float, count=len(trades))
    ret = np.fromiter((t.return_pct for t in trades), dtype=float, count=len(trades))
    wins = net > 0.0
    losses = net < 0.0
    n_trades = len(trades)

    metrics["win_rate"] = float(np.count_nonzero(wins)) / n_trades
    metrics["expectancy"] = float(np.mean(ret))

    if not np.any(losses):
        warnings.append(_null_warning("profit factor", "no losses (this warning is the §4.7 flag)"))
        warnings.append(_null_warning("avg_loss", "no losing trades"))
    else:
        metrics["profit_factor"] = float(np.sum(net[wins]) / abs(np.sum(net[losses])))
        metrics["avg_loss"] = float(np.mean(ret[losses]))

    if np.any(wins):
        metrics["avg_win"] = float(np.mean(ret[wins]))
    else:
        warnings.append(_null_warning("avg_win", "no winning trades"))

    longest = current = 0
    for value in net:
        current = current + 1 if value < 0.0 else 0  # breakeven (0) resets
        longest = max(longest, current)
    metrics["longest_losing_streak"] = float(longest)

    return metrics, warnings
