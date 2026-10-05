"""Ledger — cash, position, fees, equity (ROADMAP P4-T1, criteria L1-L10).

The ledger is the ONLY place money moves. Every operation preserves the
invariants of §8.3 (I2/L10: cash never negative) by reducing or rejecting a
buy that the available cash cannot cover, and raises
:class:`~nlbt.errors.EngineInvariantError` (E_ENGINE_INVARIANT, §4.8) if a
violation would nevertheless occur — a bug, never a silent clamp of a real
overshoot.

Pinned API (tests/unit/test_engine_ledger.py, OQ-0049):

    Ledger(cash, *, fee_bps=0.0, slippage_bps=0.0, allow_fractional=True,
           fixed_fee=0.0)
        .cash / .shares / .fees_paid / .warnings
        .buy(shares, price, *, fee_bps=None, slippage_bps=None) -> fee
        .sell(shares, price, *, fee_bps=None, slippage_bps=None) -> fee
        .equity(price) -> cash + shares * price

``buy``/``sell`` apply adverse slippage to ``price`` (buy: up, sell: down —
:func:`nlbt.engine.execution.apply_slippage`) and charge
:func:`nlbt.engine.execution.compute_fee` on the slipped fill; per-call
keyword overrides the constructor config.

Insufficient cash on a buy (L7/OQ-0054): REDUCE the size to what the cash
covers when at least one share (or a fractional share, when allowed) fits —
recording a warning — and REJECT outright (warning, no state change) when
nothing affordable fits. Either branch keeps ``cash >= 0`` (the
non-negotiable part of L7); the tests accept both branches with exact
numbers pinned inside each.

Affordability uses the fee-inclusive divisor ``fill * (1 + fee_rate)`` so a
fill can never overshoot cash by its own fee (§4.5 sizing rule, I2/L10);
``fixed_fee`` is subtracted from the budget first (buy side).

``fixed_fee`` (``execution.fixed_fee``, §4.1) defaults to 0.0 — every pinned
criterion constructs the ledger without it, so the percentage fee alone
drives the tested arithmetic.
"""

from __future__ import annotations

import math

from nlbt.engine.execution import apply_slippage, compute_fee
from nlbt.errors import EngineInvariantError

__all__ = ["Ledger"]

#: Slack for IEEE-754 dust produced by the affordability division
#: (``cash / (fill * (1 + rate)) * fill * (1 + rate)`` can differ from
#: ``cash`` by ~1 ulp). Anything below this magnitude is rounding noise, not
#: an invariant violation; anything at or above it is a real overshoot and
#: raises E_ENGINE_INVARIANT.
_CASH_EPSILON = 1e-9


class Ledger:
    """Cash-and-position account with fees, slippage and invariant checks.

    State invariants (asserted after every operation, §8.3):

    * ``cash >= 0`` (I2/L10) — unlevered long-only, so no operation may
      create negative cash;
    * ``shares >= 0`` — v1 is long-only (P4-T7 gates shorting);
    * ``fees_paid`` is the running total of every fee charged.
    """

    def __init__(
        self,
        cash: float,
        *,
        fee_bps: float = 0.0,
        slippage_bps: float = 0.0,
        allow_fractional: bool = True,
        fixed_fee: float = 0.0,
    ) -> None:
        """Create a flat ledger with ``cash`` available (L1: shares = 0)."""
        if cash < 0.0:
            raise EngineInvariantError(
                "Ledger cannot start with negative cash",
                details={"cash": cash},
                hint="capital.initial must be > 0 (validated by the spec).",
            )
        self._cash = float(cash)
        self._shares = 0.0
        self._fees_paid = 0.0
        self._fee_bps = fee_bps
        self._slippage_bps = slippage_bps
        self._allow_fractional = allow_fractional
        self._fixed_fee = fixed_fee
        self._warnings: list[str] = []

    # ------------------------------------------------------------------ state

    @property
    def cash(self) -> float:
        """Current cash; never negative (L10)."""
        return self._cash

    @property
    def shares(self) -> float:
        """Current position size (0 when flat)."""
        return self._shares

    @property
    def fees_paid(self) -> float:
        """Cumulative fees charged across every buy and sell."""
        return self._fees_paid

    @property
    def warnings(self) -> list[str]:
        """Non-fatal notices (size reduction / order rejection)."""
        return self._warnings

    def equity(self, price: float) -> float:
        """``cash + shares * price`` (L9: the identity after every operation)."""
        return self._cash + self._shares * price

    # ------------------------------------------------------------------- buy

    def buy(
        self,
        shares: float,
        price: float,
        *,
        fee_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> float:
        """Buy ``shares`` at quoted ``price``; return the fee charged.

        Fill price is adverse: ``price * (1 + slip_bps/1e4)``. Cash pays
        ``shares * fill + fee``. If that exceeds available cash, the size is
        REDUCED to the affordable count (integer floor when
        ``allow_fractional=False``) with a warning, or REJECTED (nothing
        charged, warning recorded) when zero shares are affordable — both
        branches keep ``cash >= 0`` (L7, OQ-0054: reduce-or-reject).
        """
        rate_bps = self._fee_bps if fee_bps is None else fee_bps
        slip_bps = self._slippage_bps if slippage_bps is None else slippage_bps
        if shares <= 0.0:
            return 0.0

        fill = apply_slippage(price, "buy", slip_bps)
        requested = float(math.floor(shares)) if not self._allow_fractional else float(shares)

        # Fee-inclusive affordability: actual * fill * (1 + rate) + fixed <= cash.
        budget = self._cash - self._fixed_fee
        if budget <= 0.0:
            self._warnings.append(
                f"Buy rejected: fixed fee {self._fixed_fee:g} exceeds cash {self._cash:g}."
            )
            return 0.0
        max_affordable = budget / (fill * (1.0 + rate_bps / 10_000.0))

        actual = requested
        if requested > max_affordable:
            actual = max_affordable if self._allow_fractional else float(math.floor(max_affordable))
            if actual <= 0.0:
                self._warnings.append(
                    f"Buy rejected: cannot afford {requested:g} shares at fill {fill:g} "
                    f"with cash {self._cash:g}."
                )
                return 0.0
            self._warnings.append(
                f"Buy size reduced from {requested:g} to {actual:g} shares: "
                f"insufficient cash ({self._cash:g})."
            )

        cost = actual * fill
        fee = compute_fee(actual, fill, rate_bps, self._fixed_fee)
        new_cash = self._cash - cost - fee
        if new_cash < 0.0:
            if new_cash >= -_CASH_EPSILON:
                new_cash = 0.0  # IEEE-754 dust from the affordability division
            else:
                raise EngineInvariantError(
                    "buy would drive cash negative (L10/I2 violation)",
                    details={
                        "cash": self._cash,
                        "cost": cost,
                        "fee": fee,
                        "shares": actual,
                        "fill": fill,
                    },
                    hint="This is an engine bug: the affordability cap must include fees.",
                )
        self._cash = new_cash
        self._shares += actual
        self._fees_paid += fee
        return fee

    # ------------------------------------------------------------------ sell

    def sell(
        self,
        shares: float,
        price: float,
        *,
        fee_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> float:
        """Sell ``shares`` (clamped to what is held) at ``price``; return the fee.

        Fill price is adverse: ``price * (1 - slip_bps/1e4)``. Cash receives
        ``shares * fill - fee``. Selling more than held clamps to the held
        size (long-only, one position — §4.5); a non-positive request or an
        empty position is a no-op returning 0.0.
        """
        rate_bps = self._fee_bps if fee_bps is None else fee_bps
        slip_bps = self._slippage_bps if slippage_bps is None else slippage_bps
        if shares <= 0.0 or self._shares <= 0.0:
            return 0.0

        fill = apply_slippage(price, "sell", slip_bps)
        actual = min(float(shares), self._shares)
        proceeds = actual * fill
        fee = compute_fee(actual, fill, rate_bps, self._fixed_fee)
        new_cash = self._cash + proceeds - fee
        if new_cash < 0.0:
            if new_cash >= -_CASH_EPSILON:
                new_cash = 0.0
            else:
                raise EngineInvariantError(
                    "sell would drive cash negative (L10/I2 violation)",
                    details={
                        "cash": self._cash,
                        "proceeds": proceeds,
                        "fee": fee,
                        "shares": actual,
                        "fill": fill,
                    },
                    hint="A fixed fee larger than proceeds + cash is a configuration bug.",
                )
        self._cash = new_cash
        self._shares -= actual
        self._fees_paid += fee
        return fee

    # ------------------------------------------------------- internal helpers

    def __repr__(self) -> str:
        """Debug view of the three money state variables."""
        return (
            f"Ledger(cash={self._cash!r}, shares={self._shares!r}, fees_paid={self._fees_paid!r})"
        )
