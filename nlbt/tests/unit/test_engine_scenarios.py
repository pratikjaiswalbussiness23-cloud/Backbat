"""P4-T8 hand-computed scenario suite (SC1-SC13) + §8.3 invariant stubs (I1-I14).

Stage note (R14): written from the acceptance criteria ONLY; no engine code was
read (there is none yet). Every test lazily imports ``nlbt.engine.backtest``
through a fixture — they collect today and ERROR at fixture setup until the
builder lands the module. The property invariants are STUBS with the correct
structure, deliberately skipped per the task text. Never mocked.

PINNED API under test (docs/OPEN_QUESTIONS.md OQ-0049):

    from nlbt.engine.backtest import run
    run(spec, bars) -> result
    result.trades       -> list of Trade-like objects (§4.6 fields used here:
                           signal_time, entry_time, entry_price, exit_signal_time,
                           exit_time, exit_price, shares, net_pnl, exit_reason,
                           bars_held)
    result.warnings     -> list[str]
    result.equity_curve -> DataFrame with columns
                           t/equity/cash/position_value/drawdown (§4.6)
    result.metrics      -> mapping of metric name -> float | None
                           (undefined metrics are None, never NaN/inf — §4.7)

Hand-computed conventions shared by SC3-SC10/SC12 ("the standard setup"):
    capital 10000, fee 5 bps, slippage 0 (isolates the risk/sizing arithmetic
    under test), integer shares, entry rule close > 100, entry fills at bar 1
    open = 100:
      shares   = floor(10000 / (100 * 1.0005)) = floor(99.9500249...) = 99
      cost     = 99 * 100 = 9900
      fee_buy  = 9900 * 0.0005 = 4.95
      cash     = 10000 - 9900 - 4.95 = 95.05
    (slippage 0 makes every fill price a raw open/close — no end-of-data
    slippage ambiguity; see OPEN_QUESTIONS OQ-0053 for the slippage reading.)

Expected-value provenance (R4): every number is hand-computed with the
arithmetic shown in the test docstring and independently re-checked with a
one-off Python calculation (never copied from an implementation — there is
none). Two criteria-text arithmetic errors were found this way and are
documented IN the affected docstrings plus OPEN_QUESTIONS OQ-0050 (SC2) and
OQ-0051 (SC3); the tests assert the arithmetically correct values derived
from §4.5's own formulas. Exact vs approx is stated per assertion: tolerance
is 1e-9 on prices (binary roundoff), 1e-6 on small cash balances, 1e-4 on
equities/P&L (IEEE accumulation only — a formula or convention error would
differ by dollars, far beyond these tolerances).
"""

from __future__ import annotations

import importlib
import itertools
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.spec.models import StrategySpec

# Shared tolerance constants (documented above).
PRICE_TOL = 1e-9
CASH_TOL = 1e-6
MONEY_TOL = 1e-4


@pytest.fixture()
def backtest_mod() -> ModuleType:
    """Lazily import the (not yet existing) backtest module.

    Fixture setup runs before the test body, so while ``nlbt.engine`` is
    missing every scenario test ERRORs while collection still succeeds.
    """
    return importlib.import_module("nlbt.engine.backtest")


# --------------------------------------------------------------------------- #
# Construction helpers (inputs only — no engine logic)
# --------------------------------------------------------------------------- #


def _flat_bars(closes: list[float]) -> Bars:
    """Bars with open == close, high = close+1, low = close-1 (valid OHLC)."""
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [float(c) for c in closes],
            "high": [float(c) + 1.0 for c in closes],
            "low": [float(c) - 1.0 for c in closes],
            "close": [float(c) for c in closes],
            "volume": [1000.0] * len(closes),
        },
        index=idx,
    )
    return Bars(frame)


def _make_bars(rows: list[tuple[float, float, float, float]]) -> Bars:
    """Bars from explicit (open, high, low, close) rows; volume constant."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [float(r[0]) for r in rows],
            "high": [float(r[1]) for r in rows],
            "low": [float(r[2]) for r in rows],
            "close": [float(r[3]) for r in rows],
            "volume": [1000.0] * len(rows),
        },
        index=idx,
    )
    return Bars(frame)


def _spec(
    *,
    entry: dict[str, Any],
    exit_long: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    risk: dict[str, Any] | None = None,
    sizing_value: float = 100.0,
    allow_fractional: bool = False,
    fee_bps: float = 5.0,
    slippage_bps: float = 0.0,
    capital: float = 10000.0,
) -> StrategySpec:
    """Valid StrategySpec (§4.1) for scenario runs; §4.2 shorthand rules."""
    rules: dict[str, Any] = {"entry_long": entry}
    if exit_long is not None:
        rules["exit_long"] = exit_long
    payload: dict[str, Any] = {
        "spec_version": "1.0",
        "name": "p4-scenario",
        "universe": {"symbols": ["TEST"], "interval": "1d"},
        "period": {"start": "2024-01-01", "end": "2024-12-31"},
        "indicators": indicators or {},
        "rules": rules,
        "risk": risk or {},
        "sizing": {
            "method": "percent_of_equity",
            "value": sizing_value,
            "allow_fractional": allow_fractional,
        },
        "execution": {
            "fill": "next_open",
            "fee_bps": fee_bps,
            "slippage_bps": slippage_bps,
            "fixed_fee": 0.0,
        },
        "capital": {"initial": capital},
    }
    return StrategySpec.model_validate(payload)


_GT_100 = {"all": [{"left": "close", "op": ">", "right": 100}]}
_GT_102 = {"all": [{"left": "close", "op": ">", "right": 102}]}


# --------------------------------------------------------------------------- #
# SC1 — no signals: equity flat
# --------------------------------------------------------------------------- #


def test_sc1_no_signals_equity_flat(backtest_mod: ModuleType) -> None:
    """SC1: 10 bars, entry rule never fires -> equity flat at 100000.

    closes = [100, 101, 99, 102, 98, 103, 97, 104, 96, 105], entry rule
    close > 10000 (never true for any bar).

    equity[t] = cash[t] + shares[t] * close[t]
              = 100000 + 0 * close = 100000 for every t.
    EXACT: 100000.0 and 0.0 are dyadic; the assertion is a literal list
    equality (no tolerance) — any drift (a phantom fee, a phantom fill)
    breaks it.
    """
    spec = _spec(entry={"all": [{"left": "close", "op": ">", "right": 10000}]}, capital=100000.0)
    bars = _flat_bars([100, 101, 99, 102, 98, 103, 97, 104, 96, 105])

    result = backtest_mod.run(spec, bars)

    assert result.trades == []
    assert list(result.equity_curve["equity"]) == [100000.0] * 10
    assert list(result.equity_curve["cash"]) == [100000.0] * 10


# --------------------------------------------------------------------------- #
# SC2 — always-long from bar 0, never exit
# --------------------------------------------------------------------------- #


def test_sc2_always_long_equals_buy_and_hold_minus_costs(
    backtest_mod: ModuleType,
) -> None:
    """SC2: always-long from bar 0, never exit -> buy-and-hold minus costs.

    Setup: closes = opens = [100, 101, 102, 103, 104, 105]; capital 10000,
    fee 5 bps, slippage 5 bps, sizing 100 % of equity, fractional shares,
    entry rule close > 0 (fires at bar 0; while long further entry signals
    are ignored — one position, §4.5), no exit rule -> end-of-data close.

    ENTRY (signal bar 0, fill bar 1 open, §4.5 step 1):
      buy_price = 101 * (1 + 0.0005) = 101.0505
      shares    = notional / (fill * (1 + fee_rate))       [§4.5 exact formula]
                = 10000 / (101.0505 * 1.0005) = 10000 / 101.10102525
                = 98.910965297... shares
      cost      = shares * 101.0505 = 9995.0024987...
      fee_buy   = cost * 0.0005     = 4.9975012...
      cash      = 10000 - cost - fee_buy = 0.0000000  (exactly 0 in exact
                 arithmetic; IEEE-754 leaves ~1e-12, asserted approx 0)

    MARK TO MARKET (§4.5 step 3), position_value = shares * close:
      equity[0] = 10000.0                      (flat; fill is bar 1) EXACT
      equity[1] = 0 + 98.910965297*101 =  9990.0075
      equity[2] = 0 + 98.910965297*102 = 10088.9185
      equity[3] = 0 + 98.910965297*103 = 10187.8294
      equity[4] = 0 + 98.910965297*104 = 10286.7404
      equity[5] = 0 + 98.910965297*105 = 10385.6514  (last bar, still long;
                 the forced close runs after the last bar's mark, §4.5)

    END OF DATA (§4.5: position closed at the last close, exit_reason
    end_of_data; slippage/fees applied as at any fill — OQ-0053):
      sell_price = 105 * (1 - 0.0005) = 104.9475
      proceeds   = 98.910965297 * 104.9475 = 10380.4585...
      fee_sell   = proceeds * 0.0005       = 5.1902...
      final cash = 0 + proceeds - fee_sell = 10375.2683
      net_pnl    = 10375.2683 - 10000      = 375.2683
                 = shares*(104.9475 - 101.0505) - (4.9975012 + 5.1902293)
                 = 385.4560... - 10.1877... = 375.2683  (cross-check)

    CRITERIA-TEXT DISCREPANCY (OPEN_QUESTIONS OQ-0050 — verified by
    arithmetic, not copied): the printed chain in the task text is
    internally inconsistent:
      10000 / 101.0505          = 98.9604207... (text prints 98.9607...)
      98.9607 * 101.0505        = 10000.0282... (text prints 9999.975)
      10000 - 9999.975 - 4.999  = -4.974        (text prints "approx 0")
    The criterion's own intent ("cash_after approx 0", "equals buy-and-hold
    minus costs EXACT") requires §4.5's fee-inclusive divisor — the values
    above — which is what is asserted.
    """
    spec = _spec(
        entry={"all": [{"left": "close", "op": ">", "right": 0}]},
        allow_fractional=True,
        fee_bps=5.0,
        slippage_bps=5.0,
        capital=10000.0,
    )
    bars = _flat_bars([100, 101, 102, 103, 104, 105])

    result = backtest_mod.run(spec, bars)
    curve = result.equity_curve

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.signal_time == bars.index[0]
    assert trade.entry_time == bars.index[1]
    assert trade.entry_price == pytest.approx(101.0505, abs=PRICE_TOL)
    assert trade.shares == pytest.approx(98.910965297, abs=1e-6)
    assert trade.exit_reason == "end_of_data"
    assert trade.exit_time == bars.index[5]
    assert trade.exit_price == pytest.approx(104.9475, abs=PRICE_TOL)
    assert trade.net_pnl == pytest.approx(375.2683, abs=MONEY_TOL)

    assert len(curve) == 6  # one row per bar (§4.6)
    assert float(curve["equity"].iloc[0]) == 10000.0  # EXACT: flat at bar 0
    assert float(curve["cash"].iloc[1]) == pytest.approx(0.0, abs=CASH_TOL)
    for i, expected in [
        (1, 9990.0075),
        (2, 10088.9185),
        (3, 10187.8294),
        (4, 10286.7404),
        (5, 10385.6514),
    ]:
        assert float(curve["equity"].iloc[i]) == pytest.approx(expected, abs=MONEY_TOL)


# --------------------------------------------------------------------------- #
# SC3 — one winning round trip (exact cents)
# --------------------------------------------------------------------------- #


def test_sc3_one_winning_round_trip_exact_cents(backtest_mod: ModuleType) -> None:
    """SC3: one winning round trip with fees + slippage, every cent shown.

    Standard setup (capital 10000, fee 5 bps, slippage 5 bps, integer
    shares) with an exit rule close > 102:
      bar0 (100,102,99,101): close 101 > 100 -> entry signal
      bar1 (100,101,99,100): entry FILLS at open 100
      bar2 (105,106,104,105): close 105 > 102 -> exit signal
      bar3 (110,111,99,100): exit FILLS at open 110; flat afterwards
        (close 100: entry rule false, exit rule false -> one trade total)

    ENTRY:
      buy_price  = 100 * (1 + 0.0005) = 100.05
      shares     = floor(10000 / 100.05) = 99          [criterion formula]
                   (fee-inclusive floor(10000/100.100025) = 99 — same value,
                   so the rounding is identical under both readings)
      cost       = 99 * 100.05 = 9904.95
      fee_buy    = 9904.95 * 0.0005 = 4.952475
      cash after = 10000 - 9904.95 - 4.952475 = 90.097525

    EXIT:
      sell_price  = 110 * (1 - 0.0005) = 109.945
      proceeds    = 99 * 109.945 = 10884.555
      fee_sell    = 10884.555 * 0.0005 = 5.4422775
      cash final  = 90.097525 + 10884.555 - 5.4422775 = 10969.2102475
      net_pnl     = 10969.2102475 - 10000 = 969.2102475
                  cross-check: (109.945 - 100.05)*99 - (4.952475 + 5.4422775)
                  = 979.605 - 10.3947525 = 969.2102475  (identical)

    CRITERIA-TEXT DISCREPANCY (OPEN_QUESTIONS OQ-0051 — verified): the task
    text prints fee_buy = 4.95225, but 9904.95 * 0.0005 = 4.952475 (the
    printed value equals 9904.5 * 0.0005 — a digit dropped). Every downstream
    number in the text (cash 90.09775, final 10969.2105, pnl 969.2105)
    inherits that slip; the arithmetically correct chain above is asserted.
    """
    spec = _spec(
        entry=_GT_100,
        exit_long=_GT_102,
        fee_bps=5.0,
        slippage_bps=5.0,
        capital=10000.0,
    )
    bars = _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),
            (100.0, 101.0, 99.0, 100.0),
            (105.0, 106.0, 104.0, 105.0),
            (110.0, 111.0, 99.0, 100.0),
        ]
    )

    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.signal_time == bars.index[0]
    assert trade.entry_time == bars.index[1]
    assert trade.entry_price == pytest.approx(100.05, abs=PRICE_TOL)  # 100*1.0005
    assert trade.shares == pytest.approx(99.0)
    assert trade.exit_signal_time == bars.index[2]
    assert trade.exit_time == bars.index[3]
    assert trade.exit_price == pytest.approx(109.945, abs=PRICE_TOL)  # 110*0.9995
    assert trade.exit_reason == "signal"
    assert trade.net_pnl == pytest.approx(969.2102475, abs=MONEY_TOL)
    # cash row 3 (flat after the exit fill at bar 3's open):
    assert float(result.equity_curve["cash"].iloc[3]) == pytest.approx(10969.2102475, abs=MONEY_TOL)


# --------------------------------------------------------------------------- #
# SC4 — stop hit intrabar (no gap)
# --------------------------------------------------------------------------- #


def test_sc4_stop_hit_intrabar_no_gap(backtest_mod: ModuleType) -> None:
    """SC4: stop hit intrabar, not a gap -> exit at the stop level 95.0.

    Standard setup: entry fills bar1 open 100 -> 99 shares, cash 95.05
    (arithmetic in the module docstring). risk stop_loss_pct = 5:
      stop_level = 100 * (1 - 0.05) = 95.0
      bar2 (98, 99, 93, 96): open 98 >= 95 (no gap), low 93 < 95
      -> fill at 95.0, exit_reason stop_loss, exit at bar 2 (same bar).

    EXIT ARITHMETIC (slippage 0):
      proceeds = 99 * 95 = 9405
      fee_sell = 9405 * 0.0005 = 4.7025
      cash     = 95.05 + 9405 - 4.7025 = 9495.3475
      net_pnl  = 9495.3475 - 10000 = -504.6525
               cross-check: (95 - 100)*99 - (4.95 + 4.7025)
                          = -495 - 9.6525 = -504.6525
    """
    spec = _spec(entry=_GT_100, risk={"stop_loss_pct": 5})
    bars = _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),  # signal: close 101 > 100
            (100.0, 101.0, 99.0, 100.0),  # entry fill @100; low 99 > 95, safe
            (98.0, 99.0, 93.0, 96.0),  # low 93 < 95 -> STOP at 95.0
            (96.0, 97.0, 95.0, 96.0),  # flat afterwards
        ]
    )

    result = backtest_mod.run(spec, bars)
    curve = result.equity_curve

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(100.0, abs=PRICE_TOL)
    assert trade.exit_price == pytest.approx(95.0, abs=PRICE_TOL)  # level, not 93
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_time == bars.index[2]
    assert trade.net_pnl == pytest.approx(-504.6525, abs=MONEY_TOL)
    assert float(curve["cash"].iloc[2]) == pytest.approx(9495.3475, abs=MONEY_TOL)
    assert float(curve["cash"].iloc[3]) == pytest.approx(9495.3475, abs=MONEY_TOL)


# --------------------------------------------------------------------------- #
# SC5 — gap down through the stop
# --------------------------------------------------------------------------- #


def test_sc5_gap_down_through_stop_fills_at_open(backtest_mod: ModuleType) -> None:
    """SC5: stop_level 95.0 but open gaps below it -> fill at the open 90.0.

    Standard setup: entry fills bar1 open 100 -> 99 shares, cash 95.05.
    risk stop_loss_pct = 5 -> stop_level = 100 * 0.95 = 95.0.
    bar2 (90, 91, 88, 90): open 90 < 95 -> §4.5 gap rule: fill at open
    = 90.0, NOT 95.0 (worse than the stop — realistic pessimism).

    EXIT ARITHMETIC (slippage 0):
      proceeds = 99 * 90 = 8910
      fee_sell = 8910 * 0.0005 = 4.455
      cash     = 95.05 + 8910 - 4.455 = 9000.595
      net_pnl  = 9000.595 - 10000 = -999.405
               cross-check: (90 - 100)*99 - (4.95 + 4.455)
                          = -990 - 9.405 = -999.405
    """
    spec = _spec(entry=_GT_100, risk={"stop_loss_pct": 5})
    bars = _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),  # signal
            (100.0, 101.0, 99.0, 100.0),  # entry fill @100
            (90.0, 91.0, 88.0, 90.0),  # open 90 gaps below stop 95
            (89.0, 90.0, 88.0, 89.0),  # flat afterwards
        ]
    )

    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_price == pytest.approx(90.0, abs=PRICE_TOL)  # the open
    assert trade.exit_price != pytest.approx(95.0), "gap must fill at open, not level"
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_time == bars.index[2]
    assert trade.net_pnl == pytest.approx(-999.405, abs=MONEY_TOL)
    assert float(result.equity_curve["cash"].iloc[3]) == pytest.approx(9000.595, abs=MONEY_TOL)


# --------------------------------------------------------------------------- #
# SC6 — stop and take-profit same bar -> stop first
# --------------------------------------------------------------------------- #


def test_sc6_stop_and_take_profit_same_bar_stop_first(
    backtest_mod: ModuleType,
) -> None:
    """SC6: both reachable in one bar -> stop assumed to hit first (§4.5).

    Standard setup: entry fills bar1 open 100 -> 99 shares, cash 95.05.
    risk: stop_loss_pct 5 (level 95), take_profit_pct 10 (level 110).
    bar2 (102, 115, 93, 98):
      stop reachable:        low 93  < 95   yes
      take-profit reachable: high 115 > 110 yes
      open 102 >= 95 -> not a stop gap; fill at the STOP LEVEL 95.0.
    close 98 keeps the entry rule false afterwards -> one trade total.

    LOSS ARITHMETIC (identical chain to SC4):
      proceeds = 99 * 95 = 9405; fee_sell = 4.7025
      cash     = 95.05 + 9405 - 4.7025 = 9495.3475
      net_pnl  = -504.6525  (=(95-100)*99 - (4.95 + 4.7025))
    """
    spec = _spec(entry=_GT_100, risk={"stop_loss_pct": 5, "take_profit_pct": 10})
    bars = _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),  # signal
            (100.0, 101.0, 99.0, 100.0),  # entry fill @100; high 101 < 110 safe
            (102.0, 115.0, 93.0, 98.0),  # BOTH reachable; close 98 -> no re-entry
            (98.0, 99.0, 97.0, 98.0),  # flat
        ]
    )

    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_price == pytest.approx(95.0, abs=PRICE_TOL)  # stop level
    assert trade.exit_price != pytest.approx(110.0), "stop wins over take-profit"
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_time == bars.index[2]
    assert trade.net_pnl == pytest.approx(-504.6525, abs=MONEY_TOL)
    assert float(result.equity_curve["cash"].iloc[3]) == pytest.approx(9495.3475, abs=MONEY_TOL)


# --------------------------------------------------------------------------- #
# SC7 — trailing stop ratchets up, then triggers
# --------------------------------------------------------------------------- #


def test_sc7_trailing_stop_ratchets_then_triggers(backtest_mod: ModuleType) -> None:
    """SC7: trailing stop 10 % — each bar's trail shown, exit at 108.0.

    Standard setup entry: 99 shares at 100 (cash 95.05). risk trailing 10 %.
    trail arithmetic (§4.5: highest high since entry, checked BEFORE the
    bar's own high ratchets it):

      before bar1: highest = entry 100 -> trail = 100 * 0.9 = 90.0
      bar1 (100, 110, 99, 108): low 99 > 90 -> no hit
                                ratchet: 110 * 0.9 = 99.0
      bar2 (109, 120, 105, 115): low 105 > 99 -> no hit
                                 ratchet: max(110,120) = 120 -> 120*0.9 = 108.0
      bar3 (110, 112, 109, 110): low 109 > 108 -> no hit
                                 ratchet: highest stays 120 -> 108.0 (NEVER down)
      bar4 (109, 111, 105, 107): open 109 >= 108 (no gap), low 105 < 108
                                 -> TRAILING STOP at 108.0 (pre-slippage),
                                 reason trailing_stop, exit at bar 4.
      (bar4 close 107 > 100 re-enters while flat but bar4 is the last bar:
       that last-bar signal is ignored with a warning — §4.5 edge rule —
       so exactly one trade results.)

    EXIT ARITHMETIC (slippage 0):
      proceeds = 99 * 108 = 10692; fee_sell = 10692 * 0.0005 = 5.346
      cash     = 95.05 + 10692 - 5.346 = 10781.704
      net_pnl  = 10781.704 - 10000 = 781.704
               cross-check: (108 - 100)*99 - (4.95 + 5.346)
                          = 792 - 10.296 = 781.704
    The exit at exactly 108.0 proves the ratchet: a down-moving trail
    (bar3's own 112*0.9 = 100.8) or a pre-check raise from bar4's high
    (111*0.9 = 99.9) would exit at a different price (see also R8-R10).
    """
    spec = _spec(entry=_GT_100, risk={"trailing_stop_pct": 10})
    bars = _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),  # signal
            (100.0, 110.0, 99.0, 108.0),  # entry @100; trail -> 99.0
            (109.0, 120.0, 105.0, 115.0),  # trail -> 108.0
            (110.0, 112.0, 109.0, 110.0),  # trail stays 108.0
            (109.0, 111.0, 105.0, 107.0),  # low 105 < 108 -> exit at 108.0
        ]
    )

    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(100.0, abs=PRICE_TOL)
    assert trade.exit_price == pytest.approx(108.0, abs=PRICE_TOL)
    assert trade.exit_reason == "trailing_stop"
    assert trade.exit_time == bars.index[4]
    assert trade.net_pnl == pytest.approx(781.704, abs=MONEY_TOL)
    assert float(result.equity_curve["cash"].iloc[4]) == pytest.approx(10781.704, abs=MONEY_TOL)


# --------------------------------------------------------------------------- #
# SC8 — signal on last bar ignored; open position closed end_of_data
# --------------------------------------------------------------------------- #


def test_sc8a_signal_on_last_bar_ignored(backtest_mod: ModuleType) -> None:
    """SC8a: entry signal fires on the final bar (bar N-1) -> no order.

    closes = [90, 90, 90, 90, 105], entry close > 100: only the last bar
    signals. There is no bar N to fill at (§4.5 edge rule), so:
      * no trade exists (nothing to "enter at bar N"),
      * result.warnings names the last/final bar,
      * position_value stays EXACTLY 0 on every bar (0.0 * close = 0.0).
    """
    spec = _spec(entry=_GT_100, capital=100000.0)
    bars = _flat_bars([90, 90, 90, 90, 105])

    result = backtest_mod.run(spec, bars)

    assert result.trades == [], "no trade entry exists after the last bar"
    assert list(result.equity_curve["position_value"]) == [0.0] * 5
    assert any(
        "last bar" in str(w).lower() or "final bar" in str(w).lower() for w in result.warnings
    ), f"expected a last-bar warning, got {result.warnings!r}"


def test_sc8b_open_position_closed_end_of_data(backtest_mod: ModuleType) -> None:
    """SC8b: a position still open after the last bar closes at the last
    close with exit_reason end_of_data (§4.5 edge rule).

    Standard setup: entry fills bar1 open 100 -> 99 shares, cash 95.05.
    No exit rule, no risk exits -> held through bar4 (close 105; bar4's
    close > 100 entry signal is moot — already long).

    END ARITHMETIC (slippage 0, so "closed AT the last close" literally —
    sidesteps the slippage-at-end ambiguity, OQ-0053):
      proceeds = 99 * 105 = 10395
      fee_sell = 10395 * 0.0005 = 5.1975
      final cash = 95.05 + 10395 - 5.1975 = 10484.8525
      net_pnl  = 10484.8525 - 10000 = 484.8525
               cross-check: (105 - 100)*99 - (4.95 + 5.1975)
                          = 495 - 10.1475 = 484.8525
    """
    spec = _spec(entry=_GT_100, fee_bps=5.0, slippage_bps=0.0)
    bars = _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),  # signal
            (100.0, 101.0, 99.0, 100.0),  # entry fill @100
            (100.0, 101.0, 99.0, 99.0),
            (99.0, 100.0, 98.0, 98.0),
            (104.0, 106.0, 103.0, 105.0),  # last close 105
        ]
    )

    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "end_of_data"
    assert trade.exit_time == bars.index[4]
    assert trade.exit_price == pytest.approx(105.0, abs=PRICE_TOL)  # last close
    assert trade.net_pnl == pytest.approx(484.8525, abs=MONEY_TOL)


# --------------------------------------------------------------------------- #
# SC9 — entry while in position ignored; exit/entry same-bar precedence
# --------------------------------------------------------------------------- #


def test_sc9a_entry_signal_while_in_position_ignored(backtest_mod: ModuleType) -> None:
    """SC9a: already long; the entry signal keeps firing -> nothing changes.

    entry rule close > 90 fires on EVERY bar (closes 95..99), but §4.5 step
    4 only evaluates entry_long while FLAT:
      bar0 (94,96,93,95): flat -> signal
      bar1 (100,101,95,96): FILLS 99 shares @100 (cash 10000-9900-4.95 = 95.05)
      bar2..bar4: in position -> entry signal ignored (no order, no cash move)

    Assertions: exactly ONE trade of 99 shares; cash frozen at 95.05 across
    bars 1-3 (a second buy would move it — hand value 95.05 from the module
    docstring); position held (position_value > 0) bars 1-3. Row 4 (last
    bar) is deliberately not asserted: the end-of-data forced close timing
    on the final row is OQ-0053.
    """
    spec = _spec(entry={"all": [{"left": "close", "op": ">", "right": 90}]})
    bars = _make_bars(
        [
            (94.0, 96.0, 93.0, 95.0),
            (100.0, 101.0, 95.0, 96.0),
            (96.0, 98.0, 95.0, 97.0),
            (97.0, 99.0, 96.0, 98.0),
            (98.0, 100.0, 97.0, 99.0),
        ]
    )

    result = backtest_mod.run(spec, bars)
    curve = result.equity_curve

    assert len(result.trades) == 1, "re-entering while long must be ignored"
    assert result.trades[0].shares == pytest.approx(99.0)
    assert result.trades[0].entry_time == bars.index[1]
    for i in (1, 2, 3):
        assert float(curve["cash"].iloc[i]) == pytest.approx(95.05, abs=CASH_TOL), (
            f"cash moved at bar {i} — a duplicate entry was executed"
        )
        assert float(curve["position_value"].iloc[i]) > 0.0


def test_sc9b_exit_has_priority_over_entry_on_same_bar(
    backtest_mod: ModuleType,
) -> None:
    """SC9b: exit and entry both true while long -> exit wins (§4.5 step 4).

    entry rule close > 90, exit rule close > 102, slippage 0:
      bar0 (94,96,93,95): flat -> entry signal
      bar1 (100,101,95,96): entry FILLS @100 -> 99 shares, cash 95.05
      bar2 (96,98,95,97): in position, exit false (97 <= 102)
      bar3 (97,104,96,103): close 103 -> exit TRUE and entry TRUE while
          long -> EXIT takes precedence -> pending exit (NO entry order)
      bar4 (104,105,95,96): exit FILLS @104 (open, slip 0); then flat ->
          close 96 > 90 -> entry signal -> pending entry
      bar5 (96,98,95,97): second entry FILLS @96 (held to end ->
          end_of_data; not asserted here)

    trade1 EXIT ARITHMETIC: proceeds = 99 * 104 = 10296;
      fee_sell = 10296 * 0.0005 = 5.148
      net_pnl  = (104 - 100)*99 - (4.95 + 5.148) = 396 - 10.098 = 385.902

    Assertions: two trades; trade1 exits at bar4 for reason "signal"; NO
    trade enters at bar4 (the entry half of the same-bar precedence was
    dropped); trade2 enters strictly after trade1 exited (no overlap, I5).
    """
    spec = _spec(
        entry={"all": [{"left": "close", "op": ">", "right": 90}]},
        exit_long=_GT_102,
    )
    bars = _make_bars(
        [
            (94.0, 96.0, 93.0, 95.0),
            (100.0, 101.0, 95.0, 96.0),
            (96.0, 98.0, 95.0, 97.0),
            (97.0, 104.0, 96.0, 103.0),
            (104.0, 105.0, 95.0, 96.0),
            (96.0, 98.0, 95.0, 97.0),
        ]
    )

    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 2
    trade1, trade2 = result.trades[0], result.trades[1]

    assert trade1.entry_time == bars.index[1]
    assert trade1.exit_signal_time == bars.index[3]
    assert trade1.exit_time == bars.index[4]  # next open after the exit signal
    assert trade1.exit_price == pytest.approx(104.0, abs=PRICE_TOL)
    assert trade1.exit_reason == "signal"
    assert trade1.net_pnl == pytest.approx(385.902, abs=MONEY_TOL)

    assert trade2.entry_time == bars.index[5]  # re-entry fills the bar AFTER bar4
    assert trade2.entry_time > trade1.exit_time  # never overlapping (I5)
    assert all(t.entry_time != bars.index[4] for t in result.trades), (
        "entry was not allowed on the same bar the exit filled"
    )


# --------------------------------------------------------------------------- #
# SC10 — insufficient cash + integer rounding
# --------------------------------------------------------------------------- #


def test_sc10_insufficient_cash_integer_rounding(backtest_mod: ModuleType) -> None:
    """SC10: cash=150, price=100 (fill 100.05 with 5 bps slippage), fee 5 bps.

      fill_price   = 100 * (1 + 0.0005) = 100.05
      max_shares   = floor(150 / 100.05) = floor(1.499250...) = 1
                     (fee-inclusive floor(150/100.100025) = 1 — same value)
      cost         = 1 * 100.05 = 100.05
      fee          = 100.05 * 0.0005 = 0.050025
      cash_after   = 150 - 100.05 - 0.050025 = 49.899975
    Criterion: cash_after approx 49.90 within 1 cent — asserted BOTH as the
    exact hand chain (abs 1e-6) and the literal within-a-cent check; cash
    never negative on any bar (L10).
    """
    spec = _spec(entry=_GT_100, fee_bps=5.0, slippage_bps=5.0, capital=150.0)
    bars = _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),  # signal
            (100.0, 101.0, 99.0, 100.0),  # entry fill @100 -> 100.05
            (100.0, 101.0, 99.0, 100.0),  # extra bar: row 1 is unambiguous
        ]
    )

    result = backtest_mod.run(spec, bars)
    curve = result.equity_curve

    assert len(result.trades) == 1
    assert result.trades[0].shares == pytest.approx(1.0)  # integer rounding
    cash_after = float(curve["cash"].iloc[1])
    assert cash_after == pytest.approx(49.899975, abs=CASH_TOL)  # hand chain
    assert cash_after == pytest.approx(49.90, abs=0.01)  # criterion's 1-cent bound
    assert all(float(c) >= 0.0 for c in curve["cash"])  # L10 on every bar


# --------------------------------------------------------------------------- #
# SC11 — warm-up: no trade before indicators are valid
# --------------------------------------------------------------------------- #


def test_sc11_no_trade_before_warmup(backtest_mod: ModuleType) -> None:
    """SC11: SMA(5) warm-up = 4 — no trade in the first 4 bars.

    closes = [10]*5 + [20]*5 (10 bars), entry rule close > sma5,
    sma5 = IndicatorDef(type="sma", period=5).

    Hand computation (SMA(5) first valid at index period-1 = 4; NaN at
    indices 0..3 makes every comparison False — §4.2):
      sma5 = [NaN, NaN, NaN, NaN, 10, 12, 14, 16, 18, 20]
      signal close > sma5 = [F, F, F, F, F, T, T, T, T, F]
      (bar 4: 10 > 10 false; bar 9: 20 > 20 false — strict inequality)
    First signal at bar 5 -> next-open fill at bar 6.

    Assertions: no trade SIGNAL before bar 4 and no trade ENTRY before bar
    4 (criterion wording), plus the exact pins signal at index 5 and entry
    at index 6 (the next bar's open — §4.5).
    """
    indicators = {"sma5": {"type": "sma", "params": {"period": 5}, "source": "close"}}
    spec = _spec(
        entry={"all": [{"left": "close", "op": ">", "right": "sma5"}]},
        indicators=indicators,
        fee_bps=5.0,
        slippage_bps=0.0,
    )
    bars = _flat_bars([10, 10, 10, 10, 10, 20, 20, 20, 20, 20])  # five 10s, five 20s
    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 1
    trade = result.trades[0]
    # no trade in the first 4 bars (warm-up), criterion wording:
    assert trade.signal_time >= bars.index[4]
    assert trade.entry_time >= bars.index[4]
    # exact pins from the hand table above:
    assert trade.signal_time == bars.index[5]  # first close > sma5
    assert trade.entry_time == bars.index[6]  # fill at next bar's open
    assert trade.entry_price == pytest.approx(20.0, abs=PRICE_TOL)  # open 20, slip 0


# --------------------------------------------------------------------------- #
# SC12 — max_holding_bars exit
# --------------------------------------------------------------------------- #


def test_sc12_max_holding_bars_exit(backtest_mod: ModuleType) -> None:
    """SC12: max=3, entry at bar 2 -> exit forced at bar 5 (bar 2 + 3 = 5).

    entry rule close > 90, risk max_holding_bars 3, slippage 0:
      bar0 (80,81,79,80): close 80 <= 90 -> no signal
      bar1 (94,96,93,95): close 95 > 90 -> signal
      bar2 (95,97,94,96): entry FILLS @95  (entry_time = bar 2)
      bar3, bar4: held
      bar5 (98,100,97,99): bars_held = 5 - 2 = 3 >= max 3 -> §4.5 step 4
          creates the pending time-exit order (exit_signal_time = bar 5)
      bar6 (96,97,87,88): order FILLS at open 96 (exit_time = bar 6),
          exit_reason time_exit

    Bar-counting arithmetic: entry_bar + max = 2 + 3 = 5 — the force fires
    at bar 5 exactly as the criterion states; §4.5's fill convention
    (pending orders fill at t+1 open) puts the actual exit at bar 6.
    Criterion text says "exit forced at bar 5", §4.5 says fills happen at
    t+1 — the test pins exit_signal_time = bar 5 AND exit_time = bar 6,
    which satisfies both readings of "at bar 5" (decision vs fill).
    Logged as OPEN_QUESTIONS OQ-0052.
    """
    spec = _spec(
        entry={"all": [{"left": "close", "op": ">", "right": 90}]}, risk={"max_holding_bars": 3}
    )
    bars = _make_bars(
        [
            (80.0, 81.0, 79.0, 80.0),
            (94.0, 96.0, 93.0, 95.0),
            (95.0, 97.0, 94.0, 96.0),
            (96.0, 98.0, 95.0, 97.0),
            (97.0, 99.0, 96.0, 98.0),
            (98.0, 100.0, 97.0, 99.0),
            (96.0, 97.0, 87.0, 88.0),
        ]
    )

    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_time == bars.index[2]
    assert trade.exit_signal_time == bars.index[5]  # bar 2 + 3 = bar 5
    assert trade.exit_time == bars.index[6]  # §4.5: fills at t+1 open
    assert trade.exit_price == pytest.approx(96.0, abs=PRICE_TOL)  # bar6 open
    assert trade.exit_reason == "time_exit"


# --------------------------------------------------------------------------- #
# SC13 — short selling (gated on P4-T7)
# --------------------------------------------------------------------------- #


@pytest.mark.skip(reason="P4-T7 short selling not yet implemented")
def test_sc13_short_round_trip(backtest_mod: ModuleType) -> None:
    """SC13: short round trip with borrow cost — gated behind P4-T7.

    Deliberately empty: the short-side scenario is skipped per the task
    text until the short-selling extension exists.
    """
    ...


# --------------------------------------------------------------------------- #
# §8.3 property invariant STUBS (I1-I14)
# --------------------------------------------------------------------------- #
# Each stub has the correct structure and a real assertion body, but is
# skipped with the task-mandated reason until the engine exists. They are
# NOT weakened placeholders: unskipped, each one runs a real backtest and
# checks the invariant exactly as §8.3 states it.


def _stub_spec(
    *,
    entry: dict[str, Any] | None = None,
    with_exit: bool = True,
    indicators: dict[str, Any] | None = None,
    risk: dict[str, Any] | None = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 0.0,
    capital: float = 10000.0,
    allow_fractional: bool = False,
) -> StrategySpec:
    """Standard stub spec: entry close > 100, optional exit close > 102."""
    return _spec(
        entry=entry or _GT_100,
        exit_long=_GT_102 if with_exit else None,
        indicators=indicators,
        risk=risk,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        capital=capital,
        allow_fractional=allow_fractional,
    )


def _stub_bars() -> Bars:
    """Stub bars: entry fills bar1, exit signal bar3, flat from bar4 on.

    closes: [101, 100, 102, 103, 100, 99]
      bar0 close 101 > 100 -> entry signal; bar1 fills @100;
      bar3 close 103 > 102 -> exit signal; bar4 fills @103 (open 103);
      bar4 close 100 not > 100, bar5 close 99 -> no re-entry -> FLAT at end.
    """
    return _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),
            (100.0, 101.0, 99.0, 100.0),
            (101.0, 103.0, 100.0, 102.0),
            (102.0, 104.0, 101.0, 103.0),
            (103.0, 105.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 99.0),
        ]
    )


def _sma_spec() -> StrategySpec:
    """Scale-invariant stub spec: entry close > sma5 (no absolute threshold)."""
    return _spec(
        entry={"all": [{"left": "close", "op": ">", "right": "sma5"}]},
        with_exit=False,
        indicators={"sma5": {"type": "sma", "params": {"period": 5}, "source": "close"}},
        slippage_bps=0.0,
    )


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i1_equity_identity_every_bar(backtest_mod: ModuleType) -> None:
    """I1 (§8.3): equity[t] = cash[t] + position_value[t] for every bar."""
    result = backtest_mod.run(_stub_spec(), _stub_bars())
    curve = result.equity_curve
    assert len(curve) > 0
    for i in range(len(curve)):
        equity = float(curve["equity"].iloc[i])
        parts = float(curve["cash"].iloc[i]) + float(curve["position_value"].iloc[i])
        assert equity == pytest.approx(parts), f"identity broken at bar {i}"


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i2_cash_never_negative(backtest_mod: ModuleType) -> None:
    """I2 (§8.3): cash never negative for unlevered long-only."""
    result = backtest_mod.run(_stub_spec(), _stub_bars())
    for i, cash in enumerate(result.equity_curve["cash"]):
        assert float(cash) >= 0.0, f"cash negative at bar {i}: {cash}"


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i3_entry_time_strictly_after_signal_time(backtest_mod: ModuleType) -> None:
    """I3 (§8.3): every entry_time is strictly after its signal_time."""
    result = backtest_mod.run(_stub_spec(), _stub_bars())
    assert result.trades, "fixture must produce at least one trade"
    for trade in result.trades:
        assert trade.entry_time > trade.signal_time  # next bar or later


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i4_no_entry_before_warmup(backtest_mod: ModuleType) -> None:
    """I4 (§8.3): no entry before all used indicators are valid.

    SMA(5) is valid from index 4 (period - 1), so no signal may fire before
    bars.index[4] (hand table in SC11's docstring).
    """
    bars = _flat_bars([10, 10, 10, 10, 10, 10, 20, 20, 20, 20])
    result = backtest_mod.run(_sma_spec(), bars)
    assert result.trades, "fixture must produce at least one trade"
    for trade in result.trades:
        assert trade.signal_time >= bars.index[4]


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i5_trades_never_overlap(backtest_mod: ModuleType) -> None:
    """I5 (§8.3): trades never overlap for the same symbol (single position)."""
    bars = _make_bars(
        [
            (94.0, 96.0, 93.0, 95.0),
            (100.0, 101.0, 95.0, 96.0),
            (96.0, 98.0, 95.0, 97.0),
            (97.0, 104.0, 96.0, 103.0),
            (104.0, 105.0, 95.0, 96.0),
            (96.0, 98.0, 95.0, 97.0),
        ]
    )
    spec = _spec(
        entry={"all": [{"left": "close", "op": ">", "right": 90}]},
        exit_long=_GT_102,
    )
    result = backtest_mod.run(spec, bars)
    ordered = sorted(result.trades, key=lambda t: t.entry_time)
    for prev, nxt in itertools.pairwise(ordered):
        assert prev.exit_time <= nxt.entry_time, "trades overlap"


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i6_exit_time_not_before_entry_time(backtest_mod: ModuleType) -> None:
    """I6 (§8.3): exit_time >= entry_time and bars_held >= 0."""
    result = backtest_mod.run(_stub_spec(), _stub_bars())
    assert result.trades
    for trade in result.trades:
        assert trade.exit_time is not None
        assert trade.exit_time >= trade.entry_time
        assert trade.bars_held >= 0


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i7_net_pnl_sums_to_equity_change(backtest_mod: ModuleType) -> None:
    """I7 (§8.3): sum(net_pnl) = final_equity - initial_capital when flat.

    The stub fixture exits by signal at bar 4 and never re-enters, so the
    position is flat at the end and equity[row -1] is pure cash (hand setup
    in _stub_bars).
    """
    initial = 10000.0
    result = backtest_mod.run(_stub_spec(), _stub_bars())
    curve = result.equity_curve
    assert float(curve["position_value"].iloc[-1]) == pytest.approx(0.0)
    final = float(curve["equity"].iloc[-1])
    total = sum(float(t.net_pnl) for t in result.trades)
    assert total == pytest.approx(final - initial, abs=CASH_TOL)


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i8_fill_price_within_bar_range(backtest_mod: ModuleType) -> None:
    """I8 (§8.3): pre-slippage fill price lies within [low, high] of its bar.

    The stub fixture runs with slippage_bps = 0, so the recorded
    entry/exit prices ARE the pre-slippage fills.
    """
    bars = _stub_bars()
    result = backtest_mod.run(_stub_spec(slippage_bps=0.0), bars)
    assert result.trades
    for trade in result.trades:
        entry_bar = bars.loc[trade.entry_time]
        assert float(entry_bar["low"]) <= trade.entry_price <= float(entry_bar["high"])
        exit_bar = bars.loc[trade.exit_time]
        assert float(exit_bar["low"]) <= trade.exit_price <= float(exit_bar["high"])


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i9_determinism_two_runs_identical(backtest_mod: ModuleType) -> None:
    """I9 (§8.3): two runs of the same spec+data give identical results."""
    spec1, spec2 = _stub_spec(), _stub_spec()
    bars1, bars2 = _stub_bars(), _stub_bars()
    first = backtest_mod.run(spec1, bars1)
    second = backtest_mod.run(spec2, bars2)

    pd.testing.assert_frame_equal(first.equity_curve, second.equity_curve)

    def key(t: Any) -> tuple[Any, ...]:
        return (
            t.signal_time,
            t.entry_time,
            t.entry_price,
            t.exit_time,
            t.exit_price,
            t.net_pnl,
        )

    assert [key(t) for t in first.trades] == [key(t) for t in second.trades]


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i10_higher_fees_never_higher_equity(backtest_mod: ModuleType) -> None:
    """I10 (§8.3): identical trade sequence, higher fees -> equity not higher."""
    bars = _stub_bars()
    low = backtest_mod.run(_stub_spec(fee_bps=0.0), bars)
    high = backtest_mod.run(_stub_spec(fee_bps=500.0), bars)  # §4.1 max
    assert len(low.trades) == len(high.trades)
    final_low = float(low.equity_curve["equity"].iloc[-1])
    final_high = float(high.equity_curve["equity"].iloc[-1])
    assert final_high <= final_low + 1e-9


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i11_double_capital_same_timing_same_pct_returns(
    backtest_mod: ModuleType,
) -> None:
    """I11 (§8.3): double capital (fractional, percent sizing, fixed_fee 0)
    -> identical trade timing and identical percentage returns."""
    bars = _stub_bars()
    base = backtest_mod.run(_stub_spec(capital=10000.0, allow_fractional=True), bars)
    double = backtest_mod.run(_stub_spec(capital=20000.0, allow_fractional=True), bars)

    def times(r: Any) -> list[Any]:
        return [(t.signal_time, t.entry_time, t.exit_time) for t in r.trades]

    assert times(base) == times(double)
    pct_base = float(base.equity_curve["equity"].iloc[-1]) / 10000.0 - 1.0
    pct_double = float(double.equity_curve["equity"].iloc[-1]) / 20000.0 - 1.0
    assert pct_base == pytest.approx(pct_double, abs=1e-9)


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i12_price_scaling_leaves_timing_unchanged(backtest_mod: ModuleType) -> None:
    """I12 (§8.3): scaling all prices by k > 0 leaves trade timing unchanged
    for specs WITHOUT absolute price thresholds.

    The stub spec enters on close > sma5 — a relative (scale-invariant)
    rule: sma5 scales with the prices, so the comparison result per bar is
    mathematically unchanged (k*close > k*sma5 <=> close > sma5 for k > 0).
    """
    bars = _flat_bars([10, 10, 10, 10, 10, 10, 20, 20, 20, 20])
    scaled = Bars(bars * 2.0)
    first = backtest_mod.run(_sma_spec(), bars)
    second = backtest_mod.run(_sma_spec(), scaled)

    def times(r: Any) -> list[Any]:
        return [(t.signal_time, t.entry_time, t.exit_time) for t in r.trades]

    assert times(first) == times(second)


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i13_no_nan_or_inf_in_equity_or_metrics(backtest_mod: ModuleType) -> None:
    """I13 (§8.3): no NaN/inf in equity curve or metrics.

    Undefined metrics are None (§4.7 null + warning), never NaN/inf.
    """
    result = backtest_mod.run(_stub_spec(), _stub_bars())
    numeric = result.equity_curve[["equity", "cash", "position_value"]].to_numpy()
    assert np.isfinite(numeric).all()
    for name, value in dict(result.metrics).items():
        if value is None:
            continue  # documented null + warning
        assert np.isfinite(float(value)), f"metric {name} is NaN/inf: {value}"


@pytest.mark.skip(reason="Awaiting engine implementation")
def test_i14_stop_fill_never_above_stop_level(backtest_mod: ModuleType) -> None:
    """I14 (§8.3): long stop fill never ABOVE the stop level (pre-slippage),
    and gap fills happen at the open.

    Stub fixture: entry fills bar1 open 100 (slippage 0), stop 5 % ->
    level 95.0; bar2 (96, 97, 90, 94): open 96 >= 95 (no gap), low 90 < 95
    -> expected fill exactly 95.0.
    """
    spec = _stub_spec(risk={"stop_loss_pct": 5}, slippage_bps=0.0)
    bars = _make_bars(
        [
            (100.0, 102.0, 99.0, 101.0),
            (100.0, 101.0, 99.0, 100.0),
            (96.0, 97.0, 90.0, 94.0),  # low 90 < stop 95
            (94.0, 95.0, 93.0, 94.0),
        ]
    )
    result = backtest_mod.run(spec, bars)
    stops = [t for t in result.trades if t.exit_reason == "stop_loss"]
    assert stops, "fixture must trigger the stop"
    for trade in stops:
        stop_level = trade.entry_price * (1 - 0.05)  # 100 * 0.95 = 95.0
        assert trade.exit_price <= stop_level + PRICE_TOL
        exit_bar = bars.loc[trade.exit_time]
        open_price = float(exit_bar["open"])
        if open_price < stop_level:  # gap -> must equal the open
            assert trade.exit_price == pytest.approx(open_price, abs=PRICE_TOL)
        else:  # no gap -> must equal the level
            assert trade.exit_price == pytest.approx(stop_level, abs=PRICE_TOL)
