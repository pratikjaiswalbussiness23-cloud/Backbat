"""P4-T5 tests: risk exits (nlbt.engine.risk) — criteria R1-R11.

Stage note (R14): written from the acceptance criteria ONLY; no engine code was
read (there is none yet). Tests request a fixture that lazily imports
``nlbt.engine.risk`` — they collect today and ERROR at fixture setup until
the builder lands the module. Never mocked, never skipped.

PINNED API under test (docs/OPEN_QUESTIONS.md OQ-0049):

    from nlbt.engine.risk import RiskManager, ExitDecision
    RiskManager(
        entry_price,                 # fill price of the long position
        *,
        stop_loss_pct=None,          # §4.1 risk.* percentages (0-100 scale)
        take_profit_pct=None,
        trailing_stop_pct=None,
        max_holding_bars=None,
        entry_bar=None,              # bar index of entry (for time exit)
    )
      .trail_level -> float | None   # trailing only: entry_price*(1-pct/100)
                                     # after construction; ratcheted UP only
      .check(bar, index=None) -> ExitDecision | None
          bar    = mapping with keys "open", "high", "low", "close"
          index  = this bar's index; required when max_holding_bars is set
    ExitDecision:
      .price  -> float | None   # pre-slippage fill: the LEVEL unless the
                                # bar's open gapped beyond it (then the
                                # open); None for "time_exit" (fills next
                                # open — §4.5 step 4)
      .reason -> str            # "stop_loss" | "take_profit" |
                                # "trailing_stop" | "time_exit" (§4.6 enum)

Level arithmetic (§4.5, long side):
    stop_level      = entry * (1 - stop_loss_pct/100)
    take_profit     = entry * (1 + take_profit_pct/100)
    trailing_level  = (highest high since entry, up to t-1) * (1 - pct/100),
                      ratcheted with bar t's high only AFTER bar t's check
                      (so a bar's own high can never raise the stop that its
                      own low then hits — R10)
    gap: if open is already beyond the level, fill at open (R6/R7)
    tie: stop wins when stop and take-profit are both reachable (R5)

Expected-value provenance (R4): every level/fill number is hand-computed in
the test docstring (e.g. 100 * 0.95 = 95.0, 105 * 0.9 = 94.5). Comparisons
use pytest.approx with abs=1e-9 (binary roundoff of dyadic-clean products
only); presence/absence of a decision and the reason string compare EXACTLY.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest


@pytest.fixture()
def risk_mod() -> ModuleType:
    """Lazily import the (not yet existing) risk module."""
    return importlib.import_module("nlbt.engine.risk")


def _bar(open_: float, high: float, low: float, close: float) -> dict[str, float]:
    """A single OHLC bar as the pinned mapping form."""
    return {"open": open_, "high": high, "low": low, "close": close}


# --------------------------------------------------------------------------- #
# R1/R2 — stop loss triggered / not triggered intrabar
# --------------------------------------------------------------------------- #


def test_r1_stop_loss_triggered_intrabar(risk_mod: ModuleType) -> None:
    """R1: entry=100, stop=5 % -> stop_level = 100 * (1 - 0.05) = 95.0.

    bar: open=98, high=99, low=93, close=96
    open 98 >= 95 (no gap) and low 93 < 95 -> stop hit intrabar
    fill at the LEVEL 95.0 (not at the low 93 — pessimistic assumption:
    the fill is at the stop price, the low merely proves reachability).
    """
    manager = risk_mod.RiskManager(entry_price=100.0, stop_loss_pct=5.0)
    decision = manager.check(_bar(98.0, 99.0, 93.0, 96.0))

    stop_level = 100.0 * (1 - 0.05)  # hand value: 95.0
    assert stop_level == pytest.approx(95.0)
    assert decision is not None
    assert decision.reason == "stop_loss"
    assert decision.price == pytest.approx(95.0, abs=1e-9)  # at the level
    assert decision.price != 93.0, "must not fill at the bar's low"


def test_r2_stop_loss_not_triggered(risk_mod: ModuleType) -> None:
    """R2: entry=100, stop=5 % -> stop_level = 95.0.

    bar: open=98, high=102, low=96, close=100
    low 96 > 95 -> the stop is never touched -> no exit decision.
    """
    manager = risk_mod.RiskManager(entry_price=100.0, stop_loss_pct=5.0)
    decision = manager.check(_bar(98.0, 102.0, 96.0, 100.0))

    assert decision is None  # low 96 > stop 95


# --------------------------------------------------------------------------- #
# R3/R4 — take profit triggered / not triggered intrabar
# --------------------------------------------------------------------------- #


def test_r3_take_profit_triggered_intrabar(risk_mod: ModuleType) -> None:
    """R3: entry=100, take_profit=10 % -> tp_level = 100 * 1.10 = 110.0.

    bar: open=108, high=112, low=107, close=109
    open 108 < 110 (no gap above) and high 112 > 110 -> target hit
    fill at the LEVEL 110.0 (not at the high 112 — the high only proves
    reachability; filling at the extreme high would be optimistic).
    """
    manager = risk_mod.RiskManager(entry_price=100.0, take_profit_pct=10.0)
    decision = manager.check(_bar(108.0, 112.0, 107.0, 109.0))

    tp_level = 100.0 * 1.10  # hand value: 110.0
    assert tp_level == pytest.approx(110.0)
    assert decision is not None
    assert decision.reason == "take_profit"
    assert decision.price == pytest.approx(110.0, abs=1e-9)
    assert decision.price != 112.0, "must not fill at the bar's high"


def test_r4_take_profit_not_triggered(risk_mod: ModuleType) -> None:
    """R4: entry=100, take_profit=10 % -> tp_level = 110.0.

    bar: open=105, high=109, low=104, close=108
    high 109 < 110 -> never reaches the target -> no exit decision.
    """
    manager = risk_mod.RiskManager(entry_price=100.0, take_profit_pct=10.0)
    decision = manager.check(_bar(105.0, 109.0, 104.0, 108.0))

    assert decision is None  # high 109 < tp 110


# --------------------------------------------------------------------------- #
# R5 — both hit same bar: stop wins (conservative)
# --------------------------------------------------------------------------- #


def test_r5_stop_wins_when_stop_and_take_profit_both_hit(risk_mod: ModuleType) -> None:
    """R5: entry=100, stop=5 % (level 95), tp=10 % (level 110).

    bar: open=102, high=115, low=93, close=105
      stop reachable:       low 93  < 95   yes
      take-profit reachable: high 115 > 110 yes
    BOTH reachable in the same bar -> ROADMAP §4.5: "If stop and take-profit
    are both reachable in the same bar, the stop is assumed to hit first
    (conservative)."

    Expected fill: 95.0 (the stop level), never 110.0.
    """
    manager = risk_mod.RiskManager(entry_price=100.0, stop_loss_pct=5.0, take_profit_pct=10.0)
    decision = manager.check(_bar(102.0, 115.0, 93.0, 105.0))

    assert decision is not None
    assert decision.reason == "stop_loss"
    assert decision.price == pytest.approx(95.0, abs=1e-9)
    assert decision.price != 110.0, "stop must be assumed to hit first (§4.5)"


# --------------------------------------------------------------------------- #
# R6/R7 — gap through stop / take profit
# --------------------------------------------------------------------------- #


def test_r6_gap_through_stop_fills_at_open(risk_mod: ModuleType) -> None:
    """R6: entry=100, stop=5 % -> stop_level = 95.0.

    bar: open=90 (gaps BELOW the stop), high=91, low=88, close=90
    open 90 < stop_level 95 -> §4.5 gap rule: fill at open = 90.0,
    NOT at the level 95.0 (the gap is worse than the stop — realistic
    pessimism).
    """
    manager = risk_mod.RiskManager(entry_price=100.0, stop_loss_pct=5.0)
    decision = manager.check(_bar(90.0, 91.0, 88.0, 90.0))

    stop_level = 100.0 * (1 - 0.05)  # 95.0
    assert decision is not None
    assert decision.reason == "stop_loss"
    assert decision.price == pytest.approx(90.0, abs=1e-9)  # == open, gap fill
    assert decision.price != stop_level, "open < stop_level -> fill at open"


def test_r7_gap_through_take_profit_fills_at_open(risk_mod: ModuleType) -> None:
    """R7: entry=100, tp=10 % -> tp_level = 110.0.

    bar: open=120 (gaps ABOVE the target), high=121, low=119, close=120
    open 120 > tp_level 110 -> §4.5 gap rule: fill at open = 120.0,
    NOT at the level 110.0 (you actually got the better price).
    """
    manager = risk_mod.RiskManager(entry_price=100.0, take_profit_pct=10.0)
    decision = manager.check(_bar(120.0, 121.0, 119.0, 120.0))

    tp_level = 100.0 * 1.10  # 110.0
    assert decision is not None
    assert decision.reason == "take_profit"
    assert decision.price == pytest.approx(120.0, abs=1e-9)  # == open, gap fill
    assert decision.price != tp_level, "open > tp_level -> fill at open"


# --------------------------------------------------------------------------- #
# R8/R9 — trailing stop ratchets up, then triggers
# --------------------------------------------------------------------------- #


def test_r8_trailing_stop_ratchets_up_and_never_down(risk_mod: ModuleType) -> None:
    """R8: entry=100, trailing=10 %. Hand arithmetic per bar:

    initial trail_level (highest since entry = entry 100):
        100 * (1 - 0.10) = 90.0
    bar1 {open 102, high 105, low 101, close 104}:
        check against 90.0 -> low 101 > 90.0: no exit
        ratchet with high 105: 105 * 0.9 = 94.5
    bar2 {open 106, high 110, low 104, close 108}:
        check against 94.5 -> low 104 > 94.5: no exit
        ratchet with high 110: 110 * 0.9 = 99.0
    bar3 {open 107, high 108, low 106, close 107}:
        check against 99.0 -> low 106 > 99.0: no exit
        ratchet: highest high since entry = max(105,110,108) = 110
        -> 110 * 0.9 = 99.0 (STAYS — bar3's own 108*0.9 = 97.2 must NOT
        move the stop DOWN)

    trail_level exposed by the manager after each check: 94.5, 99.0, 99.0.
    """
    manager = risk_mod.RiskManager(entry_price=100.0, trailing_stop_pct=10.0)
    assert manager.trail_level == pytest.approx(90.0, abs=1e-9)  # 100 * 0.9

    assert manager.check(_bar(102.0, 105.0, 101.0, 104.0)) is None
    assert manager.trail_level == pytest.approx(94.5, abs=1e-9)  # 105 * 0.9

    assert manager.check(_bar(106.0, 110.0, 104.0, 108.0)) is None
    assert manager.trail_level == pytest.approx(99.0, abs=1e-9)  # 110 * 0.9

    assert manager.check(_bar(107.0, 108.0, 106.0, 107.0)) is None
    assert manager.trail_level == pytest.approx(99.0, abs=1e-9)  # stays up-only


def test_r9_trailing_stop_triggers_after_ratchet(risk_mod: ModuleType) -> None:
    """R9: continues R8's manager (trail_level = 99.0 after bar3).

    bar4: open=101, high=102, low=97, close=100
    open 101 >= 99.0 (no gap below the trail) and low 97 < 99.0
    -> trailing stop hit, fill at the LEVEL 99.0 (not at the low 97).
    """
    manager = risk_mod.RiskManager(entry_price=100.0, trailing_stop_pct=10.0)
    manager.check(_bar(102.0, 105.0, 101.0, 104.0))  # trail -> 94.5 (R8)
    manager.check(_bar(106.0, 110.0, 104.0, 108.0))  # trail -> 99.0 (R8)
    manager.check(_bar(107.0, 108.0, 106.0, 107.0))  # trail stays 99.0 (R8)

    decision = manager.check(_bar(101.0, 102.0, 97.0, 100.0))

    assert decision is not None
    assert decision.reason == "trailing_stop"
    assert decision.price == pytest.approx(99.0, abs=1e-9)  # level, not low 97
    assert decision.price != 97.0


def test_r10_current_bar_high_cannot_raise_stop_before_its_own_low_check(
    risk_mod: ModuleType,
) -> None:
    """R10: a bar's own high must NOT raise the trailing stop before that
    same bar's low is checked against it.

    entry=100, trailing=10 % -> trail_level BEFORE this bar = 90.0.
    bar: open=100, high=120, low=85, close=95
    §4.5 order: check the low against the PREVIOUS trail first (low 85 <
    90.0 -> hit), THEN ratchet with high 120 (120*0.9 = 108.0 — too late).

    A buggy implementation that ratchets first would compute 108.0 and then
    "hit" 108.0 with low 85 — a nonsense fill ABOVE the bar's own open.
    Expected fill: 90.0 — NOT 108.0 (and not the low 85 either).
    """
    manager = risk_mod.RiskManager(entry_price=100.0, trailing_stop_pct=10.0)
    assert manager.trail_level == pytest.approx(90.0, abs=1e-9)  # 100 * 0.9

    decision = manager.check(_bar(100.0, 120.0, 85.0, 95.0))

    assert decision is not None
    assert decision.reason == "trailing_stop"
    assert decision.price == pytest.approx(90.0, abs=1e-9)  # pre-check trail
    assert decision.price != 108.0, "this bar's high 120 must not raise the stop"
    assert decision.price != 85.0, "fill is at the level, not the low"


# --------------------------------------------------------------------------- #
# R11 — max_holding_bars
# --------------------------------------------------------------------------- #


def test_r11_max_holding_bars_forced_exit(risk_mod: ModuleType) -> None:
    """R11: max=3 bars, entered at bar 5 -> forced exit from bar 8 on.

    Hand counting: bars_held(t) = t - entry_bar
      index 7: 7 - 5 = 2 < 3  -> no forced exit (None)
      index 8: 8 - 5 = 3 >= 3 -> forced exit, reason "time_exit"
    "Regardless of signals": no signal/condition is consulted here — the
    decision comes purely from the bar count. The FILL for a time exit is
    the next bar's open (§4.5 step 4 creates the pending order), so the
    decision itself carries no price — asserted as reason only; the fill
    timing is pinned end-to-end in SC12.
    """
    manager = risk_mod.RiskManager(entry_price=100.0, max_holding_bars=3, entry_bar=5)
    benign = _bar(100.0, 101.0, 99.0, 100.0)

    not_yet = manager.check(benign, index=7)
    forced = manager.check(benign, index=8)

    assert not_yet is None, "7 - 5 = 2 bars held < max 3"
    assert forced is not None
    assert forced.reason == "time_exit"
    assert forced.reason != "signal"  # forced, not signal-driven
