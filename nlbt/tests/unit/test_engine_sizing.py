"""P4-T6 tests: position sizing methods (nlbt.engine.sizing) — criteria SZ1-SZ8.

Stage note (R14): written from the acceptance criteria ONLY; no engine code was
read (there is none yet). Tests request a fixture that lazily imports
``nlbt.engine.sizing`` — they collect today and ERROR at fixture setup until
the builder lands the module. Never mocked, never skipped.

PINNED API under test (docs/OPEN_QUESTIONS.md OQ-0049):

    from nlbt.engine.sizing import compute_shares
    compute_shares(
        method,            # "percent_of_equity" | "fixed_cash" | "fixed_shares"
                           # | "risk_per_trade"
        value,             # spec.sizing.value (pct, cash, shares, risk %)
        *,
        equity,            # equity at fill time
        cash,              # cash at fill time
        price,             # fill price (already slippage-adjusted, §4.5)
        fee_bps=0.0,       # percentage fee rate used for affordability
        fixed_fee=0.0,     # accepted for spec parity; every criterion passes 0
        allow_fractional=True,
        stop_loss_pct=None,  # required for "risk_per_trade"
    ) -> float

    Formulas the tests pin (§4.5 / P4-T6):
      percent_of_equity: notional = equity * value/100
                         shares   = notional / (price * (1 + fee_rate))
                                    (floored when allow_fractional=False)
      fixed_cash:        shares = value / (price * (1 + fee_rate))
                                    (floored when allow_fractional=False)
      fixed_shares:      shares = value (integer required when
                                    allow_fractional=False), cash-capped
      risk_per_trade:    risk_amount   = equity * value/100
                         risk_per_share = price * stop_loss_pct/100
                         shares = risk_amount / risk_per_share
                         then capped by what cash allows:
                         min(shares, cash / (price * (1 + fee_rate)))
    The affordability divisor includes the fee so a fill can never push cash
    negative (invariant I2/L10 — a raw-notional cap would overshoot by the
    fee, shown in SZ6's arithmetic).

Expected-value provenance (R4): every number is hand-computed with the
arithmetic in the docstring. Results that are integer floors of exact
ratios compare EXACTLY where noted; the rest use pytest.approx (1e-9 —
binary roundoff only).
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest


@pytest.fixture()
def sizing_mod() -> ModuleType:
    """Lazily import the (not yet existing) sizing module."""
    return importlib.import_module("nlbt.engine.sizing")


# --------------------------------------------------------------------------- #
# SZ1 — percent_of_equity, 100 %
# --------------------------------------------------------------------------- #


def test_sz1_percent_of_equity_full(sizing_mod: ModuleType) -> None:
    """SZ1: equity=100000, pct=100 %, price=50, fee=5 bps, integer shares.

    notional = 100000 * 1.0 = 100000
    divisor  = price * (1 + fee_rate) = 50 * 1.0005 = 50.025
    shares   = floor(100000 / 50.025)
      50.025 * 1999 = 99999.975 <= 100000
      50.025 * 2000 = 100050.00  > 100000  -> 1999 shares
    cost = 1999 * 50.025 = 99999.975 <= cash 100000  (fits, criterion note)

    allow_fractional=False is deliberate: the criterion's expected value is
    the FLOOR 1999 (the unfloored quotient is 1999.00049975...).
    """
    shares = sizing_mod.compute_shares(
        "percent_of_equity",
        100.0,
        equity=100000.0,
        cash=100000.0,
        price=50.0,
        fee_bps=5.0,
        allow_fractional=False,
    )
    assert shares == 1999.0  # exact integer result of the floor
    cost = 1999.0 * 50.025  # 99999.975 fits in cash 100000
    assert cost == pytest.approx(99999.975)


# --------------------------------------------------------------------------- #
# SZ2 — percent_of_equity, 50 %
# --------------------------------------------------------------------------- #


def test_sz2_percent_of_equity_half(sizing_mod: ModuleType) -> None:
    """SZ2: equity=100000, pct=50 %, price=50, fee=5 bps, integer shares.

    notional = 100000 * 0.5 = 50000
    shares   = floor(50000 / 50.025)
      50000 / 50.025 = 999.500249...  (50.025 * 999 = 49974.975 <= 50000;
                                       50.025 * 1000 = 50025 > 50000)
      -> 999 shares
    """
    shares = sizing_mod.compute_shares(
        "percent_of_equity",
        50.0,
        equity=100000.0,
        cash=100000.0,
        price=50.0,
        fee_bps=5.0,
        allow_fractional=False,
    )
    assert shares == 999.0  # exact integer result of the floor


# --------------------------------------------------------------------------- #
# SZ3 — fixed_cash
# --------------------------------------------------------------------------- #


def test_sz3_fixed_cash(sizing_mod: ModuleType) -> None:
    """SZ3: fixed_cash value=10000, price=50, fee=5 bps, integer shares.

    shares = floor(10000 / (50 * 1.0005)) = floor(10000 / 50.025)
      10000 / 50.025 = 199.900049...  (50.025 * 199 = 9954.975 <= 10000;
                                       50.025 * 200 = 10005 > 10000)
      -> 199 shares
    """
    shares = sizing_mod.compute_shares(
        "fixed_cash",
        10000.0,
        equity=100000.0,
        cash=100000.0,
        price=50.0,
        fee_bps=5.0,
        allow_fractional=False,
    )
    assert shares == 199.0  # exact integer result of the floor


# --------------------------------------------------------------------------- #
# SZ4 — fixed_shares
# --------------------------------------------------------------------------- #


def test_sz4_fixed_shares(sizing_mod: ModuleType) -> None:
    """SZ4: fixed_shares value=100 -> exactly 100 shares, whatever the price,
    provided cash allows.

    Hand check that cash allows: 100 * 50 = 5000 notional, fee =
    5000 * 0.0005 = 2.5, total 5002.5 <= cash 10000.
    Value 100 is an integer, so it is valid with allow_fractional=False
    (P3-T2's fixed_shares integer constraint).
    """
    shares = sizing_mod.compute_shares(
        "fixed_shares",
        100.0,
        equity=100000.0,
        cash=10000.0,
        price=50.0,
        fee_bps=5.0,
        allow_fractional=False,
    )
    assert shares == 100.0  # EXACT: fixed count, price-independent
    total = 100.0 * 50.0 * (1 + 0.0005)  # 5002.5 <= cash 10000
    assert total == pytest.approx(5002.5)


# --------------------------------------------------------------------------- #
# SZ5 — risk_per_trade
# --------------------------------------------------------------------------- #


def test_sz5_risk_per_trade(sizing_mod: ModuleType) -> None:
    """SZ5: equity=100000, risk=1 %, entry=50, stop=5 %.

    risk_amount    = 100000 * 0.01 = 1000
    risk_per_share = entry * stop/100 = 50 * 0.05 = 2.5
    shares         = floor(1000 / 2.5) = floor(400.0) = 400

    Cash cap (fee-inclusive) = floor(100000 / 50.025) = 1999 > 400, so the
    risk formula governs (no cap applies). fee_bps=5 passed anyway to prove
    the fee does not leak into the risk-per-share denominator.
    """
    shares = sizing_mod.compute_shares(
        "risk_per_trade",
        1.0,
        equity=100000.0,
        cash=100000.0,
        price=50.0,
        fee_bps=5.0,
        allow_fractional=False,
        stop_loss_pct=5.0,
    )
    assert shares == 400.0  # EXACT: 1000 / 2.5 = 400


# --------------------------------------------------------------------------- #
# SZ6 — risk_per_trade capped by cash
# --------------------------------------------------------------------------- #


def test_sz6_risk_per_trade_capped_by_cash(sizing_mod: ModuleType) -> None:
    """SZ6: same as SZ5 but cash=10000 — the 400-share risk size does not fit.

    uncapped shares = 400 -> notional 400 * 50 = 20000 > cash 10000
    cash allows (fee-inclusive, so fees cannot push cash negative):
      floor(10000 / (50 * 1.0005)) = floor(10000 / 50.025)
        50.025 * 199 = 9954.975 <= 10000
        50.025 * 200 = 10005.00  > 10000  -> 199 shares
    (A raw-notional cap of 200 would cost 10000 + fee 5 = 10005 > cash —
    exactly the negative-cash bug invariants I2/L10 forbid.)

    Expected: 199 (= min(400, 199)).
    """
    shares = sizing_mod.compute_shares(
        "risk_per_trade",
        1.0,
        equity=100000.0,
        cash=10000.0,
        price=50.0,
        fee_bps=5.0,
        allow_fractional=False,
        stop_loss_pct=5.0,
    )
    assert shares == 199.0  # EXACT: fee-inclusive cash cap
    total = 199.0 * 50.0 * (1 + 0.0005)  # 9954.975 <= cash 10000
    assert total == pytest.approx(9954.975)


# --------------------------------------------------------------------------- #
# SZ7/SZ8 — fractional vs integer rounding
# --------------------------------------------------------------------------- #


def test_sz7_allow_fractional_returns_float(sizing_mod: ModuleType) -> None:
    """SZ7: allow_fractional=True keeps the fractional share count.

    equity=99975, pct=100 %, price=50, fee=0:
    shares = 99975 / (50 * 1.0) = 99975 / 50 = 1999.5   (exact decimal,
    dyadic in binary -> EXACT comparison)

    1999.5 shares is valid (criterion) and must be returned as a float,
    NOT floored to 1999.
    """
    shares = sizing_mod.compute_shares(
        "percent_of_equity",
        100.0,
        equity=99975.0,
        cash=99975.0,
        price=50.0,
        fee_bps=0.0,
        allow_fractional=True,
    )
    assert isinstance(shares, float)
    assert shares == 1999.5  # EXACT: 99975 / 50


def test_sz8_integer_shares_floored(sizing_mod: ModuleType) -> None:
    """SZ8: allow_fractional=False floors: 1999.9 -> 1999.

    equity=99995, pct=100 %, price=50, fee=0:
    quotient = 99995 / 50 = 1999.9 (exact decimal)
    floor(1999.9) = 1999
    """
    shares = sizing_mod.compute_shares(
        "percent_of_equity",
        100.0,
        equity=99995.0,
        cash=99995.0,
        price=50.0,
        fee_bps=0.0,
        allow_fractional=False,
    )
    assert shares == 1999.0  # EXACT floor of the exact quotient 1999.9
