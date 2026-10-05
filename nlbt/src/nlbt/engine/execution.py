"""Order and fill model (ROADMAP P4-T3, §4.5 price adjustment + gap rule).

Pure functions, no state — the arithmetic every fill goes through:

* :func:`apply_slippage` — adverse slippage in basis points: a buy fills
  ABOVE the quoted price, a sell BELOW it (§4.5 "adjusted adversely by
  slippage").
* :func:`compute_fee` — percentage fee plus an optional flat fee
  (``execution.fixed_fee``), exactly the §4.5/P4-T3 formula
  ``shares*price*fee_bps/10000 + fixed_fee``.
* :func:`resolve_exit_fill` — the §4.5 gap rule for intrabar risk exits:
  if the bar's open gapped *beyond* the level, fill at the open (worse for
  a stop, better for a take-profit); otherwise fill exactly at the level.

Every expected value in tests/unit/test_engine_execution.py is hand-computed
from these three formulas (arithmetic in each test docstring).
"""

from __future__ import annotations

from typing import Literal

__all__ = ["apply_slippage", "compute_fee", "resolve_exit_fill"]

#: One basis point is 1/10_000 of price (§4.5 costs are quoted in bps).
_BPS = 10_000.0

#: The two sides of a fill; slippage is always adverse to the trader.
Side = Literal["buy", "sell"]

#: Risk-exit kinds resolved by :func:`resolve_exit_fill` (§4.5 gap rule).
ExitKind = Literal["stop", "take_profit"]


def apply_slippage(price: float, side: Side, bps: float) -> float:
    """Return ``price`` shifted ADVERSELY by ``bps`` basis points.

    ``side="buy"``  → ``price * (1 + bps/10000)`` (you pay more).
    ``side="sell"`` → ``price * (1 - bps/10000)`` (you receive less).

    ``bps = 0`` returns the price unchanged (``price * 1.0`` / ``price * 0.0``
    adjustments are exact), which is why the slippage-free scenario tests can
    assert raw opens/closes as fill prices.
    """
    if side == "buy":
        return price * (1.0 + bps / _BPS)
    if side == "sell":
        return price * (1.0 - bps / _BPS)
    raise ValueError(f"Unknown side {side!r}: expected 'buy' or 'sell'")


def compute_fee(shares: float, price: float, fee_bps: float, fixed_fee: float = 0.0) -> float:
    """Total fee for a fill: percentage part plus flat part (P4-T3 E4/E5).

    ``fee = shares * price * fee_bps/10000 + fixed_fee``

    ``fixed_fee`` defaults to 0.0 (``execution.fixed_fee`` in §4.1); every
    pinned criterion passes 0, so the percentage term alone drives the
    tested arithmetic (E4: ``100 * 52.026 * 0.0005 = 2.6013``).
    """
    return shares * price * fee_bps / _BPS + fixed_fee


def resolve_exit_fill(open_price: float, level: float, kind: ExitKind) -> float:
    """Resolve the pre-slippage fill for ONE intrabar risk exit (§4.5 gap rule).

    ``kind="stop"`` (long stop / trailing stop):
        open already BELOW the level → the bar gapped through the stop →
        fill at ``open_price`` (worse than the level, realistic pessimism);
        otherwise the level was touched intrabar → fill at ``level``.

    ``kind="take_profit"``:
        open already ABOVE the level → gap fill at ``open_price`` (you
        actually got the better price); otherwise fill at ``level``.

    Touching the level with the open (``open == level``) is NOT a gap —
    both branches return the same value there, so the classification is
    immaterial to the fill.
    """
    if kind == "stop":
        return open_price if open_price < level else level
    if kind == "take_profit":
        return open_price if open_price > level else level
    raise ValueError(f"Unknown exit kind {kind!r}: expected 'stop' or 'take_profit'")
