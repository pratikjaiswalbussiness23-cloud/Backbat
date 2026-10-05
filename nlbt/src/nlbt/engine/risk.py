"""Risk exits (ROADMAP P4-T5, §4.5 step 2 + P4-T6 max_holding_bars).

Pinned API (tests/unit/test_engine_risk.py, OQ-0049):

    RiskManager(entry_price, *, stop_loss_pct=None, take_profit_pct=None,
                trailing_stop_pct=None, max_holding_bars=None, entry_bar=None)
        .trail_level -> float | None    # ratcheted UP only
        .check(bar, index=None) -> ExitDecision | None
        .update_trailing(high) -> None  # explicit ratchet
        .time_exit_due(index) -> bool   # max_holding_bars reached (R11)
    ExitDecision:
        .reason -> "stop_loss" | "take_profit" | "trailing_stop" | "time_exit"
        .price  -> float | None   # pre-slippage fill level (gap → open);
                                  # None for "time_exit" (fills next open)

Level arithmetic (§4.5, long side), all from the ENTRY FILL price:

    stop_level     = entry * (1 - stop_loss_pct/100)
    take_profit    = entry * (1 + take_profit_pct/100)
    trailing_level = trail_high * (1 - trailing_stop_pct/100)
                     where trail_high starts at entry_price and ratchets
                     UP to each bar's high ONLY AFTER that bar's check
                     (a bar's own high can never raise the stop that its
                     own low then hits — R10; never moves down — R8).

Reachability and fills per bar:

    stop / trailing:  min(open, low) <= level  (a gap-down open beyond the
                     level counts — low <= open always, so this also covers
                     the gap case); fill = open if open < level (gap) else
                     the level (R1/R6).
    take profit:      max(open, high) >= level; fill = open if open > level
                     else the level (R3/R7).
    tie-break:        STOP wins when stop and take-profit are both reachable
                     in the same bar (§4.5 "conservative", R5) — stop is
                     checked first.
    time exit:        ``index - entry_bar >= max_holding_bars`` → decision
                     with ``price=None`` (§4.5 step 4 creates the pending
                     order; the FILL is the next bar's open — SC12).

``check`` evaluates price-based exits first, then the time exit, and
ratchets the trailing stop with this bar's high ONLY when it returns None —
so the ratchet can never affect the bar it is derived from (R8/R9/R10).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from nlbt.engine.execution import resolve_exit_fill

__all__ = ["ExitDecision", "RiskManager"]


@dataclass
class ExitDecision:
    """One intrabar (or time-forced) exit decision, pre-slippage.

    ``price`` is the fill LEVEL unless the bar's open gapped beyond it (then
    the open — §4.5 gap rule); ``None`` for ``time_exit`` because that order
    fills at the NEXT bar's open, not intrabar (§4.5 step 4).
    """

    reason: str
    price: float | None


class RiskManager:
    """Stop loss / take profit / trailing stop / max-holding for ONE position."""

    def __init__(
        self,
        entry_price: float,
        *,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        trailing_stop_pct: float | None = None,
        max_holding_bars: int | None = None,
        entry_bar: int | None = None,
    ) -> None:
        """Levels derive from the entry fill ``entry_price`` (§4.5).

        The trailing ``trail_high`` starts at ``entry_price`` itself (the
        "highest high since entry" before any bar has elapsed — SC7 note:
        at entry the trail is ``entry * (1 - pct/100)``), NOT at the entry
        bar's high: the entry bar's high participates in the ratchet only
        AFTER the entry bar's own check.
        """
        self._entry_price = entry_price
        self._stop_level = (
            None if stop_loss_pct is None else entry_price * (1.0 - stop_loss_pct / 100.0)
        )
        self._take_profit_level = (
            None if take_profit_pct is None else entry_price * (1.0 + take_profit_pct / 100.0)
        )
        self._trailing_stop_pct = trailing_stop_pct
        self._trail_high = entry_price
        self._trail_level = (
            None if trailing_stop_pct is None else entry_price * (1.0 - trailing_stop_pct / 100.0)
        )
        self._max_holding_bars = max_holding_bars
        self._entry_bar = entry_bar

    @property
    def trail_level(self) -> float | None:
        """Current trailing-stop level (None when no trailing stop configured)."""
        return self._trail_level

    @property
    def entry_bar(self) -> int | None:
        """Bar index of the entry fill (None if not supplied)."""
        return self._entry_bar

    @property
    def max_holding_bars(self) -> int | None:
        """Configured holding limit in bars (None if unlimited)."""
        return self._max_holding_bars

    def update_trailing(self, high: float) -> None:
        """Ratchet the trail UP to ``high * (1 - pct/100)``; never down (R8).

        No-op when no trailing stop is configured.
        """
        if self._trail_level is None or self._trailing_stop_pct is None:
            return
        if high > self._trail_high:
            self._trail_high = high
            self._trail_level = high * (1.0 - self._trailing_stop_pct / 100.0)

    def time_exit_due(self, index: int) -> bool:
        """True when ``max_holding_bars`` is configured and reached at ``index``.

        Bars held = ``index - entry_bar``; the exit is due when it reaches
        the limit (R11: entry 5, max 3 → due from index 8 on; index 7 with
        2 bars held is not).
        """
        if self._max_holding_bars is None or self._entry_bar is None:
            return False
        return index - self._entry_bar >= self._max_holding_bars

    def check(self, bar: Mapping[str, float], index: int | None = None) -> ExitDecision | None:
        """Check this bar against every configured exit; None → stay open.

        ``bar`` is a mapping with ``open``/``high``/``low``/``close``;
        ``index`` is this bar's integer position and is only needed for the
        ``max_holding_bars`` time exit (omit it to check price exits only).

        Order: stop loss → take profit → trailing stop (stop-first tie-break,
        §4.5) → time exit. When NOTHING fires, the trailing stop ratchets
        with this bar's high AFTER the check (§4.5) — the ratchet is skipped
        on a decision, which is irrelevant because the position is closing.
        """
        open_price = float(bar["open"])
        high = float(bar["high"])
        low = float(bar["low"])

        # Stop loss first: conservative tie-break when both levels are hit (R5).
        if self._stop_level is not None and min(open_price, low) <= self._stop_level:
            return ExitDecision(
                reason="stop_loss",
                price=resolve_exit_fill(open_price, self._stop_level, "stop"),
            )

        if self._take_profit_level is not None and max(open_price, high) >= self._take_profit_level:
            return ExitDecision(
                reason="take_profit",
                price=resolve_exit_fill(open_price, self._take_profit_level, "take_profit"),
            )

        # Trailing stop uses the level from PRIOR bars (R10); the ratchet
        # below only runs when this check comes back empty.
        if self._trail_level is not None and min(open_price, low) <= self._trail_level:
            return ExitDecision(
                reason="trailing_stop",
                price=resolve_exit_fill(open_price, self._trail_level, "stop"),
            )

        if index is not None and self.time_exit_due(index):
            return ExitDecision(reason="time_exit", price=None)

        # Ratchet AFTER the check (§4.5): this bar's own high can never
        # raise the stop that this bar's own low then hits (R10).
        self.update_trailing(high)
        return None

    def __repr__(self) -> str:
        """Debug view of the configured levels."""
        return (
            f"RiskManager(entry_price={self._entry_price!r}, "
            f"stop={self._stop_level!r}, take_profit={self._take_profit_level!r}, "
            f"trail={self._trail_level!r}, max_holding={self._max_holding_bars!r}, "
            f"entry_bar={self._entry_bar!r})"
        )
