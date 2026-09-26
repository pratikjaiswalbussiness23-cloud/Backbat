"""P4-T3 tests: the order and fill model (nlbt.engine.execution) — criteria E1-E8.

Stage note (R14): written from the acceptance criteria ONLY; no engine code was
read (there is none yet). Pure-function tests (E2-E7) request a fixture that
lazily imports ``nlbt.engine.execution``; end-to-end tests (E1, E8) lazily
import ``nlbt.engine.backtest``. They collect today and ERROR at fixture
setup until the builder lands the modules — the expected state at the
test-author stage. Never mocked, never skipped.

PINNED API under test (docs/OPEN_QUESTIONS.md OQ-0049):

    from nlbt.engine.execution import (
        apply_slippage,   # apply_slippage(price, side, slippage_bps) -> float
                          # side "buy":  price * (1 + bps/10000)  (adverse, up)
                          # side "sell": price * (1 - bps/10000)  (adverse, down)
        compute_fee,      # compute_fee(shares, price, fee_bps, fixed_fee=0.0)
                          # -> shares*price*fee_bps/10000 + fixed_fee
        resolve_exit_fill,  # resolve_exit_fill(open_price, level, kind) -> float
                          # kind "stop": long stop -> open if open < level
                          #             (gap through the stop) else level
                          # kind "take_profit": open if open > level else level
    )

    from nlbt.engine.backtest import run
    run(spec, bars) -> result with .trades (list of Trade-like objects with
    signal_time/entry_time/entry_price/exit_* fields per §4.6), .warnings
    (list[str]) and .equity_curve (DataFrame with columns
    t/equity/cash/position_value/drawdown per §4.6).

Expected-value provenance (R4): every number is hand-computed with the
arithmetic in the docstring. E1/E8 additionally pin timing (next-open fill,
last-bar rule) end-to-end through run(). Exact vs approx is documented per
assertion.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.spec.models import StrategySpec


@pytest.fixture()
def execution_mod() -> ModuleType:
    """Lazily import the (not yet existing) execution module."""
    return importlib.import_module("nlbt.engine.execution")


@pytest.fixture()
def backtest_mod() -> ModuleType:
    """Lazily import the (not yet existing) backtest module (E1, E8)."""
    return importlib.import_module("nlbt.engine.backtest")


def _make_bars(rows: list[tuple[float, float, float, float]]) -> Bars:
    """Build valid Bars from (open, high, low, close) tuples; volume constant."""
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


def _entry_spec(*, fee_bps: float, slippage_bps: float, capital: float) -> StrategySpec:
    """Spec: entry when close > 100, no exit rule, no risk exits, integer shares."""
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "p4-execution",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {},
            "rules": {"entry_long": {"all": [{"left": "close", "op": ">", "right": 100}]}},
            "risk": {},
            "sizing": {
                "method": "percent_of_equity",
                "value": 100,
                "allow_fractional": False,
            },
            "execution": {
                "fill": "next_open",
                "fee_bps": fee_bps,
                "slippage_bps": slippage_bps,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": capital},
        }
    )


# --------------------------------------------------------------------------- #
# E1 — next-open fill
# --------------------------------------------------------------------------- #


def test_e1_fill_happens_at_next_bar_open_with_slippage(
    backtest_mod: ModuleType,
) -> None:
    """E1: signal at bar t (close), fill at bar t+1 open, slippage 5 bps.

    bars (open, high, low, close):
      bar0: (100, 102, 99, 101)  -> close 101 > 100: signal at bar 0
      bar1: (52, 54, 51, 53)     -> pending order fills at open[1] = 52.0

    buy_price = open[t+1] * (1 + slippage_bps/10000)
              = 52.0 * 1.0005 = 52 + 52*0.0005 = 52 + 0.026 = 52.026

    Assertions: signal_time == bar0, entry_time == bar1 (NEXT bar — never
    same-bar), entry_price == 52.026. Entry price compared with
    approx(abs=1e-9) because 52*1.0005 = 52.0259999... in binary floating
    point (52.026 itself is not dyadic); timing compared EXACTLY (index
    equality on DatetimeIndex).
    """
    spec = _entry_spec(fee_bps=0.0, slippage_bps=5.0, capital=10000.0)
    bars = _make_bars([(100.0, 102.0, 99.0, 101.0), (52.0, 54.0, 51.0, 53.0)])

    result = backtest_mod.run(spec, bars)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.signal_time == bars.index[0]
    assert trade.entry_time == bars.index[1]  # fills at t+1, not t
    assert trade.entry_price == pytest.approx(52.026, abs=1e-9)  # 52 * 1.0005


# --------------------------------------------------------------------------- #
# E2/E3 — sign of adverse slippage
# --------------------------------------------------------------------------- #


def test_e2_adverse_slippage_on_buy_increases_price(execution_mod: ModuleType) -> None:
    """E2: buy-side slippage must push the fill ABOVE the raw price.

    fill = 50 * (1 + 5/10000) = 50 * 1.0005 = 50 + 0.025 = 50.025 > 50.0
    """
    raw = 50.0
    fill = execution_mod.apply_slippage(raw, "buy", 5.0)
    assert fill == pytest.approx(50.025, abs=1e-9)
    assert fill > raw


def test_e3_adverse_slippage_on_sell_decreases_price(execution_mod: ModuleType) -> None:
    """E3: sell-side slippage must push the fill BELOW the raw price.

    fill = 55 * (1 - 5/10000) = 55 * 0.9995 = 55 - 0.0275 = 54.9725 < 55.0
    """
    raw = 55.0
    fill = execution_mod.apply_slippage(raw, "sell", 5.0)
    assert fill == pytest.approx(54.9725, abs=1e-9)
    assert fill < raw


# --------------------------------------------------------------------------- #
# E4/E5 — fee arithmetic
# --------------------------------------------------------------------------- #


def test_e4_percentage_fee(execution_mod: ModuleType) -> None:
    """E4: fee = shares * fill_price * fee_bps/10000.

    shares=100, fill_price=52.026, fee_bps=5:
    fee = 100 * 52.026 * 0.0005 = 5202.6 * 0.0005 = 2.6013

    approx(abs=1e-9): 52.026 is not dyadic, the product carries binary
    roundoff; 1e-9 is far below any convention-level difference.
    """
    fee = execution_mod.compute_fee(shares=100.0, price=52.026, fee_bps=5.0)
    assert fee == pytest.approx(2.6013, abs=1e-9)


def test_e5_fixed_fee_is_added(execution_mod: ModuleType) -> None:
    """E5: total_fee = shares*price*fee_bps/10000 + fixed_fee.

    shares=100, price=52.026, fee_bps=5, fixed_fee=1.0:
      percentage part = 2.6013          (from E4's arithmetic)
      total           = 2.6013 + 1.0 = 3.6013
    """
    fee = execution_mod.compute_fee(shares=100.0, price=52.026, fee_bps=5.0, fixed_fee=1.0)
    assert fee == pytest.approx(3.6013, abs=1e-9)


# --------------------------------------------------------------------------- #
# E6/E7 — gap fills at the open, not at the level
# --------------------------------------------------------------------------- #


def test_e6_gap_through_stop_fills_at_open(execution_mod: ModuleType) -> None:
    """E6: stop level = entry*(1 - 0.05) = 100*0.95 = 95.0.

    If open[t] = 90.0 the bar GAPPS below the stop: fill at open = 90.0,
    NOT at 95.0 (§4.5: "If open[t] is already beyond a level (gap), fill at
    open[t]").
    """
    stop_level = 100.0 * (1 - 0.05)  # hand value: 95.0
    fill = execution_mod.resolve_exit_fill(open_price=90.0, level=stop_level, kind="stop")
    assert stop_level == pytest.approx(95.0)
    assert fill == pytest.approx(90.0)
    assert fill != stop_level, "a gap through the stop must NOT fill at the level"


def test_e7_gap_through_take_profit_fills_at_open(execution_mod: ModuleType) -> None:
    """E7: take-profit level = entry * 1.10 = 100 * 1.10 = 110.0.

    If open[t] = 115.0 the bar GAPPS above the target: fill at open = 115.0,
    NOT at 110.0 (§4.5 gap rule, profit-taking side).
    """
    tp_level = 100.0 * 1.10  # hand value: 110.0
    fill = execution_mod.resolve_exit_fill(open_price=115.0, level=tp_level, kind="take_profit")
    assert tp_level == pytest.approx(110.0)
    assert fill == pytest.approx(115.0)
    assert fill != tp_level, "a gap above the target must NOT fill at the level"


# --------------------------------------------------------------------------- #
# E8 — signal on the last bar is ignored
# --------------------------------------------------------------------------- #


def test_e8_signal_on_last_bar_creates_no_order(backtest_mod: ModuleType) -> None:
    """E8: a signal on the FINAL bar has no t+1 to fill at -> ignored + warning.

    closes = [90, 90, 90, 90, 105], entry rule close > 100:
    only bar 4 (the last bar) signals.

    Assertions:
      * no trade exists (no order was created),
      * position_value is exactly 0 on every bar (nothing was ever held),
      * result.warnings contains a message naming the last/final bar
        (§4.5 edge rule: "a signal on the last bar is ignored (logged)").

    position_value 0.0 * close is dyadic -> EXACT zero.
    """
    spec = _entry_spec(fee_bps=5.0, slippage_bps=5.0, capital=100000.0)
    bars = _make_bars(
        [
            (90.0, 91.0, 89.0, 90.0),
            (90.0, 91.0, 89.0, 90.0),
            (90.0, 91.0, 89.0, 90.0),
            (90.0, 91.0, 89.0, 90.0),
            (105.0, 106.0, 104.0, 105.0),
        ]
    )

    result = backtest_mod.run(spec, bars)

    assert result.trades == [], "a last-bar signal must not create an order"
    assert list(result.equity_curve["position_value"]) == [0.0] * 5
    assert any(
        "last bar" in str(w).lower() or "final bar" in str(w).lower() for w in result.warnings
    ), f"expected a last-bar warning, got {result.warnings!r}"
