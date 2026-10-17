"""OQ-0060b: sizing's cash cap must agree with the ledger's buy budget.

The ledger (commit 052e7fb) budgets ``cash - 2.0 * fixed_fee`` on the buy
side (entry fee + exit-fee reserve, OQ-0060). After OQ-0060b,
``compute_shares`` caps with the IDENTICAL expression, so whenever the cash
cap binds, the request handed to ``Ledger.buy`` is exactly the ledger's own
``max_affordable`` — never larger — and "Buy size reduced" can no longer
fire for that reason.

Core property (verbatim OQ-0060b): for fixed_fee > 0, whenever sizing's
cash cap binds, ``Ledger.buy(compute_shares(...))`` accepts the size
UNCHANGED (``ledger.shares == requested`` — exact ==, that is the property
under test) with NO "Buy size reduced" warning.

Expected values are HAND-COMPUTED (R4): every derivation is written out in
its test docstring; nothing is copied from an engine output. Where IEEE-754
rounding makes an exact result impossible (e.g. ``19.6 * 50 =
980.0000000000001``), the docstring shows the float arithmetic and cash is
asserted with ``pytest.approx(abs=1e-9)`` — a tolerance far below any
convention-level difference, and ~4 orders of magnitude above the observed
~1e-13 rounding noise. Values whose arithmetic stays in dyadic rationals
(integer-mode cash of 40.0) keep exact ``==``.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest


@pytest.fixture()
def sizing_mod() -> ModuleType:
    """Lazily import the sizing module."""
    return importlib.import_module("nlbt.engine.sizing")


@pytest.fixture()
def ledger_mod() -> ModuleType:
    """Lazily import the ledger module."""
    return importlib.import_module("nlbt.engine.ledger")


@pytest.fixture()
def execution_mod() -> ModuleType:
    """Lazily import execution for ``apply_slippage`` — the SAME function
    backtest.py:261 uses to derive the fill price it hands to sizing, so the
    grid's fill cannot drift from the engine's by even one float step."""
    return importlib.import_module("nlbt.engine.execution")


def test_fractional_cash_cap_accepted_verbatim(
    sizing_mod: ModuleType, ledger_mod: ModuleType
) -> None:
    """OQ-0060b anchor (fractional). Hand arithmetic (R4):

    cash=1000, fixed_fee=10, fee_bps=0, price=50, no slippage.
      divisor       = 50 * (1 + 0/10000) = 50
      method        = 990 / 50 = 19.8  (OLD cap: (1000-10)/50 = 19.8 — would
                      leave cash 1000 - 990 - 10 = 0 < exit fee: the OQ-0060b bug)
      NEW cap       = (1000 - 2*10) / 50 = 980/50 = 19.6 -> requested 19.6
      ledger budget = 1000 - 2*10 = 980 ; max_affordable = 980 / 50 = 19.6 —
                      the SAME IEEE-754 division (both sides evaluate
                      ``budget / (fill * (1 + fee/10000))`` in the same
                      order), so `requested > max_affordable` compares two
                      bit-identical doubles -> FALSE -> accepted verbatim.
      cost   = 19.6 * 50 = 980.0000000000001 (verified: 19.6 is not
               binary-exact; the product is ONE ulp above 980 —
               ulp(980) = 2^-43 ≈ 1.14e-13)
      fee    = cost * 0/10000 + 10 = 10.0 EXACTLY (any finite * 0.0 == 0.0,
               + 10.0 == 10.0) — one fixed_fee charged at entry, never two.
      cash'  = 1000 - 980.0000000000001 - 10 = 9.999999999999886
               (≈ 10 - 1.1e-13: rounding noise from the product above)
               -> asserted with pytest.approx(abs=1e-9), NOT exact ==.
               `ledger.shares == requested` stays EXACT (0.0 + r == r).
      sell 19.6 @ 50: proceeds = 19.6 * 50 = 980.0000000000001, fee = 10,
               cash'' ≈ 980 ± 1e-13 -> approx; the position closes itself
               (no EngineInvariantError — the OQ-0060 guarantee).
    """
    requested = sizing_mod.compute_shares(
        "fixed_cash",
        990.0,
        equity=1000.0,
        cash=1000.0,
        price=50.0,
        fee_bps=0.0,
        fixed_fee=10.0,
        allow_fractional=True,
    )
    assert requested == 980.0 / 50.0  # = 19.6: (1000 - 2*10) / 50

    ledger = ledger_mod.Ledger(1000.0, fee_bps=0.0, slippage_bps=0.0, fixed_fee=10.0)
    entry_fee = ledger.buy(requested, 50.0)
    assert ledger.shares == requested  # accepted VERBATIM (exact — the property)
    assert not any("Buy size reduced" in w for w in ledger.warnings)
    assert entry_fee == 10.0  # exactly 1 * fixed_fee (finite*0.0 + 10.0)
    # Float noise on cash is ~1.1e-13 (see docstring); exact == would fail.
    assert ledger.cash == pytest.approx(10.0, abs=1e-9)

    exit_fee = ledger.sell(ledger.shares, 50.0)
    assert exit_fee == 10.0  # exactly 1 * fixed_fee at exit
    assert ledger.cash == pytest.approx(980.0, abs=1e-9)  # 10 + 980.0000000000001 - 10
    assert not any("Buy size reduced" in w for w in ledger.warnings)


def test_integer_cash_cap_accepted_verbatim(sizing_mod: ModuleType, ledger_mod: ModuleType) -> None:
    """Integer mode. Hand: raw method = 2000/50 = 40; floor -> 40.
    cap = 980/50 = 19.6; floor(19.6) = 19 -> requested 19.
    ledger: requested floor(19) = 19 <= max_affordable 19.6 -> accepted.
    cash' = 1000 - 19*50 - 10 = 1000 - 950 - 10 = 40.0 — all dyadic
    (950 and 40 are exact in binary), so exact == is safe here.
    """
    requested = sizing_mod.compute_shares(
        "fixed_cash",
        2000.0,
        equity=1000.0,
        cash=1000.0,
        price=50.0,
        fee_bps=0.0,
        fixed_fee=10.0,
        allow_fractional=False,
    )
    assert requested == 19.0
    ledger = ledger_mod.Ledger(
        1000.0, fee_bps=0.0, slippage_bps=0.0, allow_fractional=False, fixed_fee=10.0
    )
    ledger.buy(requested, 50.0)
    assert ledger.shares == 19.0
    assert not any("Buy size reduced" in w for w in ledger.warnings)
    assert ledger.cash == 40.0  # exact: 1000 - 950 - 10, all dyadic


def test_all_four_methods_cap_to_the_same_budget(sizing_mod: ModuleType) -> None:
    """Every method overdraws the same budget, so all four cap to one number.
    cash=1000, fixed_fee=10, price=50, fee 0 -> cap = (1000-20)/50 = 980/50 = 19.6.
      percent_of_equity 100 % : 1000 * 1.00 / 50        = 20.0 > 19.6 -> 19.6
      fixed_cash 990          : 990 / 50                = 19.8 > 19.6 -> 19.6
      fixed_shares 21         : 21.0                    = 21.0 > 19.6 -> 19.6
      risk_per_trade 5 %      : risk/share = 50*0.05 = 2.5; (1000*0.05)/2.5
                                = 50/2.5 = 20.0         > 19.6 -> 19.6
    Each expected result is the SAME expression the sizing docstring
    specifies (``(cash - 2*fixed_fee) / divisor``), hand-derived here.
    """
    cap = 980.0 / 50.0
    cases = [
        ("percent_of_equity", 100.0, None),
        ("fixed_cash", 990.0, None),
        ("fixed_shares", 21.0, None),
        ("risk_per_trade", 5.0, 5.0),  # needs stop_loss_pct = 5
    ]
    for method, value, stop in cases:
        got = sizing_mod.compute_shares(
            method,
            value,
            equity=1000.0,
            cash=1000.0,
            price=50.0,
            fee_bps=0.0,
            fixed_fee=10.0,
            allow_fractional=True,
            stop_loss_pct=stop,
        )
        assert got == cap, f"{method}: {got!r} != shared cap {cap!r}"


def test_negative_cap_clamps_to_zero(sizing_mod: ModuleType, ledger_mod: ModuleType) -> None:
    """OQ-0060b cell: NEGATIVE budget — cash=15, fixed_fee=10 (cap = -0.1).

    The clamp lives in compute_shares: sizing.py:106 computes
    ``max_cash_shares = (cash - 2.0 * fixed_fee) / divisor = (15-20)/50 =
    -0.1``, and ``if shares < 0.0: shares = 0.0`` (sizing.py:112-113) clamps
    the capped value; integer mode reaches the same clamp after
    ``math.floor(-0.1) = -1.0`` (sizing.py:109). Hand arithmetic:
      method = fixed_cash 50 / 50 = 1.0 share
      cap    = (15 - 2*10) / 50 = -5/50 = -0.1
      1.0 > -0.1 -> shares = -0.1 -> clamp -> 0.0 EXACTLY, never negative.
    ``Ledger.buy(0.0, ...)`` early-returns (ledger.py:162-163): no trade,
    cash untouched. NOTE: no warning is recorded on this path — that gap is
    logged as OQ-0061 (owner decision 2026-10-17: fix in its own task before
    Gate 4); this test deliberately does not pin that warning behaviour.
    """
    requested = sizing_mod.compute_shares(
        "fixed_cash",
        50.0,
        equity=15.0,
        cash=15.0,
        price=50.0,
        fee_bps=0.0,
        fixed_fee=10.0,
        allow_fractional=True,
    )
    assert requested == 0.0  # exactly, not approx
    assert requested >= 0.0  # never a negative share count

    requested_int = sizing_mod.compute_shares(
        "fixed_cash",
        50.0,
        equity=15.0,
        cash=15.0,
        price=50.0,
        fee_bps=0.0,
        fixed_fee=10.0,
        allow_fractional=False,
    )
    assert requested_int == 0.0  # floor(-0.1) = -1 lands on the same clamp
    assert requested_int >= 0.0

    ledger = ledger_mod.Ledger(15.0, fee_bps=0.0, slippage_bps=0.0, fixed_fee=10.0)
    ledger.buy(requested, 50.0)
    assert ledger.shares == 0.0
    assert ledger.cash == 15.0  # untouched (dyadic exact)
    assert not any("Buy size reduced" in w for w in ledger.warnings)


def test_zero_budget_sizes_to_zero_without_shrink(
    sizing_mod: ModuleType, ledger_mod: ModuleType
) -> None:
    """Budget exactly 0. Hand: 20 - 2*10 = 0 -> cap 0/50 = 0 -> fixed_cash 50
    (1.0 share raw) capped to 0.0; ``Ledger.buy(0, ...)`` is a no-op (early
    return), so cash stays 20.0 and no "Buy size reduced" is recorded.
    NOTE (OQ-0061): under the OLD cap this cell sized to (20-10)/50 = 0.2
    and the ledger REJECTED with a warning — that warning no longer fires
    once sizing itself returns 0.
    """
    requested = sizing_mod.compute_shares(
        "fixed_cash",
        50.0,
        equity=20.0,
        cash=20.0,
        price=50.0,
        fee_bps=0.0,
        fixed_fee=10.0,
        allow_fractional=True,
    )
    assert requested == 0.0
    ledger = ledger_mod.Ledger(20.0, fee_bps=0.0, slippage_bps=0.0, fixed_fee=10.0)
    ledger.buy(requested, 50.0)
    assert ledger.shares == 0.0
    assert ledger.cash == 20.0
    assert not any("Buy size reduced" in w for w in ledger.warnings)


def test_binding_grid_accepted_verbatim_by_ledger(
    sizing_mod: ModuleType, ledger_mod: ModuleType, execution_mod: ModuleType
) -> None:
    """Every cell: cash cap BINDS (independent precondition) and the ledger
    must accept the sized result VERBATIM. Hand derivations (R4): cap =
    (cash - 2f) / (fill * (1 + fee_bps/10000)); fill comes from the
    SAME ``apply_slippage`` backtest.py uses (not a hand formula):

    c1 frac    : cash1000 f10 fee0 slip0 p50 fixed_cash 990
                 -> 980/50 = 19.6 (method 990/50 = 19.8 > cap)
    c2 integer : cash1000 f10 fee0 slip0 p50 fixed_cash 2000
                 -> floor(19.6) = 19 (method 40 > cap)
    c3 percent : cash1000 f10 fee0 slip0 p50 pct100 e1000
                 -> 19.6 (method 1000/50 = 20 > cap)
    c4 shares  : cash1000 f10 fee0 slip0 p50 fixed_shares 21
                 -> 19.6 (21 > cap)
    c5 risk    : cash1000 f10 fee0 slip0 p50 risk5% stop5
                 -> 19.6 (method 50/2.5 = 20 > cap)
    c6 fee>0   : cash10000 f7.5 fee5 slip0 p100 fixed_cash 9995
                 -> 9985/100.05 (9995/100.05 > cap;
                    divisor = 100*(1+0.0005) = 100.05)
    c7 slip>0  : cash5000 f5 fee10 slip25 p80 fixed_cash 4995
                 -> 4990/(80.2*1.001) (4995/div > cap;
                    fill = apply_slippage(80,"buy",25) = 80.2)
    c8 zero    : cash20 f10 fee0 slip0 p50 fixed_cash 50
                 -> 0 (method 1.0 > 0 = cap)
    c9 tiny    : cash100.01 f10 fee0 slip0 p50 fixed_cash 99
                 -> 80.01/50 = 1.6002 (method 99/50 = 1.98 > cap)
    c10 neg    : cash15 f10 fee0 slip0 p50 fixed_cash 50
                 -> clamp: -5/50 = -0.1 -> 0.0 (method 1.0 > -0.1)


    For integer cells the binding precondition is checked pre-floor
    (floor is monotone, so method > cap implies floor(method) >= floor(cap),
    and sizing takes the min -> the cap still decides the result).
    """
    cells = [
        # name, cash, f, fee_bps, slip_bps, raw_price, method, value, equity, frac, stop
        ("c1", 1000.0, 10.0, 0.0, 0.0, 50.0, "fixed_cash", 990.0, 1000.0, True, None),
        ("c2", 1000.0, 10.0, 0.0, 0.0, 50.0, "fixed_cash", 2000.0, 1000.0, False, None),
        ("c3", 1000.0, 10.0, 0.0, 0.0, 50.0, "percent_of_equity", 100.0, 1000.0, True, None),
        ("c4", 1000.0, 10.0, 0.0, 0.0, 50.0, "fixed_shares", 21.0, 1000.0, True, None),
        ("c5", 1000.0, 10.0, 0.0, 0.0, 50.0, "risk_per_trade", 5.0, 1000.0, True, 5.0),
        ("c6", 10000.0, 7.5, 5.0, 0.0, 100.0, "fixed_cash", 9995.0, 10000.0, True, None),
        ("c7", 5000.0, 5.0, 10.0, 25.0, 80.0, "fixed_cash", 4995.0, 5000.0, True, None),
        ("c8", 20.0, 10.0, 0.0, 0.0, 50.0, "fixed_cash", 50.0, 20.0, True, None),
        ("c9", 100.01, 10.0, 0.0, 0.0, 50.0, "fixed_cash", 99.0, 100.01, True, None),
        ("c10", 15.0, 10.0, 0.0, 0.0, 50.0, "fixed_cash", 50.0, 15.0, True, None),
    ]
    for name, cash, fixed_fee, fee_bps, slip, raw_price, method, value, equity, frac, stop in cells:
        # Fill exactly as backtest.py:261 derives it: apply_slippage(raw, "buy", slip).
        fill = execution_mod.apply_slippage(raw_price, "buy", slip)
        divisor = fill * (1.0 + fee_bps / 10_000.0)
        cap = (cash - 2.0 * fixed_fee) / divisor
        # Binding precondition from the §4.5 formulas, independent of the engine call:
        if method == "fixed_cash":
            raw_method = value / divisor
        elif method == "percent_of_equity":
            raw_method = equity * (value / 100.0) / divisor
        elif method == "fixed_shares":
            raw_method = value
        else:  # risk_per_trade: risk_per_share = price * stop/100 (sizing receives the FILL)
            raw_method = equity * (value / 100.0) / (fill * (stop / 100.0))
        assert raw_method > cap, f"{name}: cell does not bind — fix the test"

        requested = sizing_mod.compute_shares(
            method,
            value,
            equity=equity,
            cash=cash,
            price=fill,  # same fill backtest.py passes
            fee_bps=fee_bps,
            fixed_fee=fixed_fee,
            allow_fractional=frac,
            stop_loss_pct=stop,
        )
        assert requested >= 0.0, name  # sizing never returns a negative share count

        ledger = ledger_mod.Ledger(
            cash,
            fee_bps=fee_bps,
            slippage_bps=slip,
            allow_fractional=frac,
            fixed_fee=fixed_fee,
        )
        ledger.buy(requested, raw_price)  # ledger re-derives fill internally (same function)
        assert ledger.shares == requested, (
            f"{name}: ledger shrank/rejected sizing's {requested!r} to {ledger.shares!r}"
        )
        assert not any("Buy size reduced" in w for w in ledger.warnings), name
        assert ledger.cash >= 0.0, name  # I2
