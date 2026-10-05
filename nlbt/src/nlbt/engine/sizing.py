"""Position sizing (ROADMAP P4-T6, §4.5 sizing formulas).

One function, four methods (SizingMethod, §4.1), computed at FILL time
from cash and the (slippage-adjusted) fill price — §4.5 "sizing is computed
at fill time from cash and the fill price".

Pinned API (tests/unit/test_engine_sizing.py, OQ-0049):

    compute_shares(method, value, *, equity, cash, price, fee_bps=0.0,
                   fixed_fee=0.0, allow_fractional=True, stop_loss_pct=None)
        -> float

Formulas, verbatim §4.5 / P4-T6 (``fee_rate = fee_bps/10000``,
``divisor = price * (1 + fee_rate)``):

    percent_of_equity: notional = equity * value/100
                       shares   = notional / divisor   (floor if integer)
    fixed_cash:        shares   = value / divisor      (floor if integer)
    fixed_shares:      shares   = value                (floor if integer)
    risk_per_trade:    risk_amount   = equity * value/100
                       risk_per_share = price * stop_loss_pct/100
                       shares   = risk_amount / risk_per_share
                                        (floor if integer)

Every method is then CAPPED to what the cash allows with the same
fee-inclusive divisor (``min(shares, cash / divisor)``, floored for integer
shares) so a fill can never push cash negative (I2/L10): a raw-notional cap
would overshoot by exactly the fee — SZ6's arithmetic shows
``floor(10000 / 50.025) = 199``, while a raw ``10000/50 = 200`` would cost
``10005 > cash``.

``fixed_fee`` (§4.1 ``execution.fixed_fee``) is NOT part of the §4.5
divisor — it only reduces the cash budget behind the cap, exactly as the
ledger's affordability check does (``(cash - fixed_fee) / divisor``), so
sizing and ledger agree bit-for-bit. Every pinned criterion passes 0, for
which ``cash - 0.0 == cash`` holds exactly.

``risk_per_trade`` without ``stop_loss_pct`` is a spec-validation error
(P4-T6: "risk_per_trade without a stop is a spec-validation error") →
``E_SPEC_RANGE`` (§4.8).
"""

from __future__ import annotations

import math

from nlbt.errors import SpecRangeError

__all__ = ["compute_shares"]


def compute_shares(
    method: str,
    value: float,
    *,
    equity: float,
    cash: float,
    price: float,
    fee_bps: float = 0.0,
    fixed_fee: float = 0.0,
    allow_fractional: bool = True,
    stop_loss_pct: float | None = None,
) -> float:
    """Shares to buy for ``method``/``value`` at ``price`` — §4.5 exact chain.

    ``equity``/``cash`` are read at fill time; ``price`` is the ALREADY
    slippage-adjusted fill price. Integer mode floors the result and the
    cash cap; fractional mode keeps the exact quotient (SZ7: 1999.5, not
    1999). The return value is always a ``float``.
    """
    fee_rate = fee_bps / 10_000.0
    divisor = price * (1.0 + fee_rate)

    if method == "percent_of_equity":
        shares = equity * (value / 100.0) / divisor
    elif method == "fixed_cash":
        shares = value / divisor
    elif method == "fixed_shares":
        shares = float(value)
    elif method == "risk_per_trade":
        if stop_loss_pct is None:
            raise SpecRangeError(
                "risk_per_trade sizing requires risk.stop_loss_pct",
                details={"method": method, "value": value},
                hint="Set risk.stop_loss_pct (> 0) or choose another sizing method.",
            )
        risk_per_share = price * (stop_loss_pct / 100.0)
        if risk_per_share <= 0.0:
            raise SpecRangeError(
                "risk_per_trade requires a positive stop distance",
                details={"stop_loss_pct": stop_loss_pct, "price": price},
                hint="risk.stop_loss_pct must be > 0 (§4.1 bounds).",
            )
        shares = equity * (value / 100.0) / risk_per_share
    else:
        raise ValueError(f"Unknown sizing method {method!r}")

    # Cash cap, fee-inclusive so fees cannot overshoot (I2/L10; SZ6).
    # Budget subtracts the flat fee first — the ledger's affordability uses
    # the identical expression, so sizing never requests an unfillable size.
    max_cash_shares = (cash - fixed_fee) / divisor
    if not allow_fractional:
        shares = float(math.floor(shares))
        max_cash_shares = float(math.floor(max_cash_shares))
    if shares > max_cash_shares:
        shares = max_cash_shares
    if shares < 0.0:
        shares = 0.0
    return float(shares)
