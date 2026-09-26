"""P4-T1 tests: the ledger (cash, position, fees, equity) — acceptance criteria L1-L10.

Stage note (R14 — independent test authorship): these tests were written from
the acceptance criteria ONLY. ``nlbt.engine`` does not exist yet, so every test
requests a fixture that lazily imports ``nlbt.engine.ledger``; until the builder
lands the module each test ERRORs with ModuleNotFoundError at fixture setup.
That is the EXPECTED state at the test-author stage. The tests are never mocked
and never skip (AGENTS.md: do not mock the code under test).

PINNED API under test (the contract these tests define for the builder — see
docs/OPEN_QUESTIONS.md OQ-0049):

    from nlbt.engine.ledger import Ledger
    Ledger(cash, *, fee_bps=0.0, slippage_bps=0.0, allow_fractional=True)
        .cash: float            current cash (never negative — L10)
        .shares: float          current position size (0 when flat)
        .fees_paid: float       cumulative fees charged
        .warnings: list[str]    non-fatal notices (e.g. size rejection)
        .buy(shares, price, *, fee_bps=None, slippage_bps=None) -> float
        .sell(shares, price, *, fee_bps=None, slippage_bps=None) -> float
        .equity(price) -> float cash + shares * price
    buy/sell apply adverse slippage (buy: price*(1+bps/1e4),
    sell: price*(1-bps/1e4)) and charge fee = notional * fee_bps/1e4 at fill
    time; per-call keyword overrides the constructor config. buy() returns the
    fee charged. Insufficient cash: reduce the integer size or reject with a
    warning — acceptance criterion L7 explicitly permits EITHER; tests accept
    either branch but pin exact numbers inside each branch.

Expected-value provenance (R4): EVERY number below is hand-computed with the
arithmetic shown in the test's docstring (independently re-checked with a
one-off Python calculation, not copied from any implementation — there is
none). Exact vs approx is documented per assertion: values whose arithmetic
stays inside IEEE-754 dyadic rationals (e.g. 0.25, 99499.75) are still
compared with pytest.approx as belt-and-braces; everything else uses
pytest.approx with an absolute tolerance far below any convention-level
difference (<= 1e-6 unless stated).
"""

from __future__ import annotations

import importlib
import math
from types import ModuleType

import pytest


@pytest.fixture()
def ledger_mod() -> ModuleType:
    """Lazily import the (not yet existing) ledger module.

    Fixture setup runs BEFORE the test body, so while ``nlbt.engine`` is
    missing every test using this fixture reports ERROR (collection still
    succeeds — the point of doing the import here instead of at module
    level).
    """
    return importlib.import_module("nlbt.engine.ledger")


# --------------------------------------------------------------------------- #
# L1 — initial state
# --------------------------------------------------------------------------- #


def test_l1_initial_state(ledger_mod: ModuleType) -> None:
    """L1: cash=100000, position=0, equity=100000.

    equity = cash + position_value = 100000 + 0 * price = 100000.
    EXACT: 100000.0 + 0.0 is dyadic — no rounding possible at any price.
    """
    ledger = ledger_mod.Ledger(cash=100000.0, fee_bps=0.0, slippage_bps=0.0)
    assert ledger.cash == 100000.0
    assert ledger.shares == 0.0
    # position_value = 0 shares * 50 = 0; equity = 100000 + 0 = 100000 (exact).
    assert ledger.equity(price=50.0) == 100000.0


# --------------------------------------------------------------------------- #
# L2 — buy with percentage fee
# --------------------------------------------------------------------------- #


def test_l2_buy_fee_arithmetic(ledger_mod: ModuleType) -> None:
    """L2: buy 10 shares at $50, fee 5 bps.

    fee        = shares * price * fee_bps/10000
               = 10 * 50 * 0.0005 = 500 * 0.0005 = 0.25
    cash_after = 100000 - (10 * 50 + 0.25) = 100000 - 500.25 = 99499.75
    position   = 10 shares
    position_value @ 50 = 10 * 50 = 500.00
    equity     = 99499.75 + 500.00 = 99999.75

    All four results are dyadic decimals (exact in IEEE-754); approx() is used
    as belt-and-braces per the task's float policy.
    """
    ledger = ledger_mod.Ledger(cash=100000.0, fee_bps=5.0, slippage_bps=0.0, allow_fractional=False)
    fee = ledger.buy(shares=10, price=50.0)

    assert fee == pytest.approx(0.25)  # 10 * 50 * 0.0005
    assert ledger.cash == pytest.approx(99499.75)  # 100000 - 500.25
    assert ledger.shares == pytest.approx(10.0)
    assert ledger.equity(price=50.0) == pytest.approx(99999.75)  # 99499.75 + 500


# --------------------------------------------------------------------------- #
# L3 — sell with percentage fee (continues from the L2 state)
# --------------------------------------------------------------------------- #


def test_l3_sell_fee_arithmetic(ledger_mod: ModuleType) -> None:
    """L3: sell 10 shares at $55, fee 5 bps, starting from the L2 state.

    fee         = shares * price * fee_bps/10000
                = 10 * 55 * 0.0005 = 550 * 0.0005 = 0.275
    net proceeds = 10 * 55 - 0.275 = 550 - 0.275 = 549.725
    cash_after  = 99499.75 + 549.725 = 100049.475
    position    = 0
    equity      = 100049.475 + 0 * price = 100049.475

    Cumulative fees_paid = 0.25 (L2) + 0.275 (L3) = 0.525.
    99499.75 and 549.725 are dyadic-exact; 100049.475 is a repeating decimal
    in binary, hence approx().
    """
    ledger = ledger_mod.Ledger(cash=100000.0, fee_bps=5.0, slippage_bps=0.0, allow_fractional=False)
    ledger.buy(shares=10, price=50.0)  # L2 state: cash 99499.75, shares 10

    fee = ledger.sell(shares=10, price=55.0)

    assert fee == pytest.approx(0.275)  # 10 * 55 * 0.0005
    assert ledger.cash == pytest.approx(100049.475)  # 99499.75 + 549.725
    assert ledger.shares == pytest.approx(0.0)
    assert ledger.fees_paid == pytest.approx(0.525)  # 0.25 + 0.275
    assert ledger.equity(price=55.0) == pytest.approx(100049.475)  # flat: cash only


# --------------------------------------------------------------------------- #
# L4 — fee is non-negative for any price and any non-negative fee_bps
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fee_bps", [0.0, 5.0, 500.0])
@pytest.mark.parametrize("price", [0.01, 50.0, 1000.0])
def test_l4_fee_always_non_negative(ledger_mod: ModuleType, fee_bps: float, price: float) -> None:
    """L4: fee = shares * price * fee_bps/10000 >= 0 for any price and fee_bps >= 0.

    Hand arithmetic for the worst case of this matrix:
      shares=10, price=1000, fee_bps=500 -> fee = 10*1000*0.05 = 500.0
      cost+fee = 10000 + 500 = 10500 <= cash 100000 (affordable, so a real fee
      is charged — the assertion is not vacuously true on a rejected buy).
    Every cheaper case is <= 500. Non-negative inputs can only produce a
    non-negative product; the test pins that no sign bug (e.g. fee_bps/100
    instead of /10000 with a stray minus, or slippage leaking into the fee)
    exists.
    """
    ledger = ledger_mod.Ledger(cash=100000.0, fee_bps=fee_bps, slippage_bps=0.0)
    fee = ledger.buy(shares=10, price=price)

    assert fee >= 0
    assert ledger.fees_paid >= 0
    assert ledger.cash >= 0  # L10 holds even here


# --------------------------------------------------------------------------- #
# L5 — adverse slippage on a buy
# --------------------------------------------------------------------------- #


def test_l5_slippage_on_buy(ledger_mod: ModuleType) -> None:
    """L5: buy at open=50 with slippage 5 bps — the fill price is adverse.

    adverse_price = open * (1 + slippage_bps/10000) = 50 * 1.0005 = 50.025
    shares        = floor(cash / adverse_price)            [criterion's formula]
                  = floor(100000 / 50.025)
      50.025 * 1999 = 99999.975 <= 100000
      50.025 * 2000 = 100050.00  > 100000  -> 1999 shares
    cost = 1999 * 50.025 = 99999.975
    cash_after = 100000 - 99999.975 = 0.025 >= 0

    fee_bps = 0.0 deliberately: criterion L5 states only slippage in its
    arithmetic, and floor(cash/adverse_price) IGNORES fees — charging a fee on
    top of that size would drive cash to -49.97 and violate criterion L10
    (logged as OPEN_QUESTIONS OQ-0054).
    cash == 0.025 (to 1e-6) is the observable proof the fill happened at
    50.025: filling at the raw 50.0 would leave cash = 50.0 instead.
    """
    ledger = ledger_mod.Ledger(cash=100000.0, fee_bps=0.0, slippage_bps=5.0, allow_fractional=False)
    adverse_price = 50.0 * (1 + 0.0005)  # = 50.025
    shares = math.floor(100000.0 / adverse_price)  # = 1999

    ledger.buy(shares=shares, price=50.0)

    assert adverse_price == pytest.approx(50.025)
    assert shares == 1999
    assert ledger.shares == pytest.approx(1999.0)
    assert ledger.cash == pytest.approx(0.025, abs=1e-6)  # 100000 - 1999*50.025
    assert ledger.cash >= 0  # L10


# --------------------------------------------------------------------------- #
# L6 — adverse slippage on a sell
# --------------------------------------------------------------------------- #


def test_l6_slippage_on_sell(ledger_mod: ModuleType) -> None:
    """L6: sell at open=55 with slippage 5 bps — the fill price is adverse (lower).

    adverse_price = open * (1 - slippage_bps/10000) = 55 * 0.9995 = 54.9725
    Starting from the L2 state (cash 99499.75, shares 10), selling 10 with
    fee 5 bps:
    proceeds   = 10 * 54.9725 = 549.725
    fee        = 549.725 * 0.0005 = 0.2748625
    cash_after = 99499.75 + 549.725 - 0.2748625 = 100049.2001375

    Cross-check against L3 (same sell WITHOUT slippage): L3 cash is
    100049.475, so adverse slippage costs exactly
      100049.475 - 100049.2001375 = 0.2748625
        = gross slippage 10*(55 - 54.9725) = 0.275
          MINUS fee saved on the smaller proceeds (0.275 * 0.0005 = 0.0001375).
    The sell side must end up with LESS cash than the no-slippage case, which
    is also asserted.
    """
    ledger = ledger_mod.Ledger(cash=100000.0, fee_bps=5.0, slippage_bps=0.0, allow_fractional=False)
    ledger.buy(shares=10, price=50.0)  # L2 state: cash 99499.75, shares 10

    ledger.sell(shares=10, price=55.0, slippage_bps=5.0)

    adverse_price = 55.0 * (1 - 0.0005)  # = 54.9725
    assert adverse_price == pytest.approx(54.9725)
    assert ledger.shares == pytest.approx(0.0)
    # cash = 99499.75 + 549.725 - 0.2748625 (full arithmetic above):
    assert ledger.cash == pytest.approx(100049.2001375, abs=1e-6)
    # adverse sell < no-slippage sell (L3's 100049.475):
    assert ledger.cash < pytest.approx(100049.475)


# --------------------------------------------------------------------------- #
# L7 — insufficient cash: reduce or reject, never negative
# --------------------------------------------------------------------------- #


def test_l7_insufficient_cash_never_negative(ledger_mod: ModuleType) -> None:
    """L7: cash=100, try to buy 10 shares at $50 (slippage 5 bps, fee 5 bps).

    adverse_price = 50 * 1.0005 = 50.025
    affordable    = floor(100 / 50.025): 50.025*1 = 50.025 <= 100,
                                     50.025*2 = 100.05  > 100  -> 1 share
    Criterion L7 permits EITHER behaviour (OPEN_QUESTIONS OQ-0054) — accept
    both, with exact numbers:

    reduce branch: shares = 1
      cost = 50.025, fee = 50.025 * 0.0005 = 0.0250125
      cash = 100 - 50.025 - 0.0250125 = 49.9499875
    reject branch: shares = 0, cash unchanged at 100.0, a warning recorded.

    In BOTH branches cash >= 0 — the non-negotiable part of L7.
    """
    ledger = ledger_mod.Ledger(cash=100.0, fee_bps=5.0, slippage_bps=5.0, allow_fractional=False)
    ledger.buy(shares=10, price=50.0)

    assert ledger.cash >= 0, f"cash went negative: {ledger.cash}"
    if ledger.shares == 0.0:
        # Rejection branch: nothing charged, warning must be recorded.
        assert ledger.cash == pytest.approx(100.0)
        assert ledger.warnings, "a rejected order must carry a warning"
    else:
        # Reduction branch: exactly the affordable share count.
        assert ledger.shares == pytest.approx(1.0)
        assert ledger.cash == pytest.approx(49.9499875, abs=1e-6)


# --------------------------------------------------------------------------- #
# L8 — integer share rounding
# --------------------------------------------------------------------------- #


def test_l8_integer_share_rounding(ledger_mod: ModuleType) -> None:
    """L8: cash=1000, price=30, fee 5 bps, integer shares.

    max_shares = floor(1000 / (30 * (1 + 0.0005)))     [fee-inclusive, §4.5]
               = floor(1000 / 30.015)
      30.015 * 33 = 990.495 <= 1000
      30.015 * 34 = 1020.51  > 1000  -> 33 shares
    cost (notional) = 33 * 30 = 990
    fee             = 990 * 0.0005 = 0.495
    total           = 990 + 0.495 = 990.495        [= 33 * 30.015, criterion]
    cash_after      = 1000 - 990.495 = 9.505
    """
    ledger = ledger_mod.Ledger(cash=1000.0, fee_bps=5.0, slippage_bps=0.0, allow_fractional=False)
    max_shares = math.floor(1000.0 / (30.0 * (1 + 0.0005)))  # hand value: 33

    fee = ledger.buy(shares=max_shares, price=30.0)

    assert max_shares == 33
    assert ledger.shares == pytest.approx(33.0)
    assert fee == pytest.approx(0.495)  # 990 * 0.0005
    assert ledger.cash == pytest.approx(9.505, abs=1e-6)  # 1000 - 990.495
    assert ledger.cash >= 0


def test_l8b_one_share_beyond_affordable(ledger_mod: ModuleType) -> None:
    """L8 boundary: asking for 34 shares when only 33 fit.

    34 * 30.015 = 1020.51 > cash 1000 -> reduce to 33 (cash 9.505) or
    reject (cash 1000). Either branch keeps cash >= 0; both outcomes are
    hand-computed above in test_l8_integer_share_rounding.
    """
    ledger = ledger_mod.Ledger(cash=1000.0, fee_bps=5.0, slippage_bps=0.0, allow_fractional=False)
    ledger.buy(shares=34, price=30.0)

    assert ledger.cash >= 0, f"cash went negative: {ledger.cash}"
    if ledger.shares == 0.0:
        assert ledger.cash == pytest.approx(1000.0)
        assert ledger.warnings, "a rejected order must carry a warning"
    else:
        assert ledger.shares == pytest.approx(33.0)
        assert ledger.cash == pytest.approx(9.505, abs=1e-6)


# --------------------------------------------------------------------------- #
# L9 — equity invariant after every operation
# --------------------------------------------------------------------------- #


def test_l9_equity_invariant_after_every_operation(ledger_mod: ModuleType) -> None:
    """L9: equity = cash + shares * current_price after buy, price change, sell.

    Sequence (fee 5 bps, no slippage) with hand arithmetic:

    1. buy 10 @ 50:
       cash = 100000 - 500.25 = 99499.75, shares = 10
       equity(50) = 99499.75 + 10*50 = 99499.75 + 500 = 99999.75
    2. price rises to 60 (no operation):
       equity(60) = 99499.75 + 10*60 = 99499.75 + 600 = 100099.75
    3. sell 10 @ 55:
       cash = 99499.75 + (550 - 0.275) = 100049.475, shares = 0
       equity(any price) = 100049.475 + 0 = 100049.475
    """
    ledger = ledger_mod.Ledger(cash=100000.0, fee_bps=5.0, slippage_bps=0.0, allow_fractional=False)

    ledger.buy(shares=10, price=50.0)
    assert ledger.equity(price=50.0) == pytest.approx(99999.75)
    assert ledger.equity(price=60.0) == pytest.approx(100099.75)
    # invariant explicitly, at a price with no trade:
    assert ledger.equity(price=47.0) == pytest.approx(99499.75 + 10 * 47.0)

    ledger.sell(shares=10, price=55.0)
    assert ledger.cash == pytest.approx(100049.475)
    assert ledger.equity(price=60.0) == pytest.approx(100049.475)
    for price in (40.0, 55.0, 60.0):
        assert ledger.equity(price=price) == pytest.approx(ledger.cash + ledger.shares * price)


# --------------------------------------------------------------------------- #
# L10 — cash never negative (property over a mixed sequence)
# --------------------------------------------------------------------------- #


def test_l10_cash_never_negative_property(ledger_mod: ModuleType) -> None:
    """L10: after ANY sequence of valid operations, cash >= 0 (property).

    Scripted sequence (integer shares, cash 1000, fee 5 bps, slippage 5 bps),
    chosen to include the adversarial cases where a naive ledger goes
    negative:

      buy  40 @ 25   -> adverse 25.0125, 40 * 25.0125 = 1000.5 > 1000
                        (must reduce/reject — the L7 path)
      sell 10 @ 30   -> partial exit (sized to what is held)
      buy   3 @ 300  -> adverse 300.15, 3 * 300.15 = 900.45 (+fee) vs remaining cash
      sell  3 @ 100  -> loss-making exit (cash must not drift negative)
      buy 100 @ 7    -> small-price round trip (fee dust rounding)
      sell 100 @ 7
      buy   1 @ 999.99 -> near-all-in boundary

    NO expected absolute values are asserted here (criterion L10 states only
    the bound): the invariant `cash >= 0` is itself the expected value.
    Rejected orders may leave cash unchanged; that also satisfies the bound.
    """
    ledger = ledger_mod.Ledger(cash=1000.0, fee_bps=5.0, slippage_bps=5.0, allow_fractional=False)
    ops: list[tuple[str, float, float]] = [
        ("buy", 40.0, 25.0),
        ("sell", 10.0, 30.0),
        ("buy", 3.0, 300.0),
        ("sell", 3.0, 100.0),
        ("buy", 100.0, 7.0),
        ("sell", 100.0, 7.0),
        ("buy", 1.0, 999.99),
    ]
    for side, shares, price in ops:
        if side == "buy":
            ledger.buy(shares=shares, price=price)
        else:
            held = ledger.shares
            if held > 0:
                ledger.sell(shares=min(shares, held), price=price)
        assert ledger.cash >= 0, f"cash negative after {side} {shares}@{price}"
