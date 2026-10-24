"""OQ-0064: reported metrics vs the forced end-of-data close (§4.5 edge rule).

The equity curve's LAST ROW stays pre-settlement (differential S1 depends on
it); the REPORTED ``final_equity``/``total_return`` must include the forced
close's exit costs, because §4.7 measures ``E_end`` and the owner ruled that
E_end is measured AFTER the forced close.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.spec.models import StrategySpec

FEE_BPS = 5.0
SLIPPAGE_BPS = 5.0
CAPITAL = 10_000.0

CLOSES = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]


def _bars() -> Bars:
    idx = pd.date_range("2024-01-01", periods=len(CLOSES), freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": CLOSES,  # open == close keeps fills simple to follow
            "high": [c + 1.0 for c in CLOSES],
            "low": [c - 1.0 for c in CLOSES],
            "close": CLOSES,
            "volume": [1000.0] * len(CLOSES),
        },
        index=idx,
    )
    return Bars(frame)


def _spec(entry: dict[str, Any], exit_long: dict[str, Any] | None = None) -> StrategySpec:
    rules: dict[str, Any] = {"entry_long": entry}
    if exit_long is not None:
        rules["exit_long"] = exit_long
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "oq0064-metrics",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {},
            "rules": rules,
            "risk": {},
            "sizing": {
                "method": "percent_of_equity",
                "value": 50.0,
                "allow_fractional": True,
            },
            "execution": {
                "fill": "next_open",
                "fee_bps": FEE_BPS,
                "slippage_bps": SLIPPAGE_BPS,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": CAPITAL},
        }
    )


# always-true entry, no exit rule -> still in position on the last bar
_ENDS_IN_POSITION = ({"all": [{"left": "close", "op": ">", "right": 0}]}, None)

# entry only while close < 102 (fires bar 0, fills bar 1); exit on close > 103
# (fires bar 4, fills bar 5); after that close >= 104 so the entry can never
# fire again -> the run ENDS FLAT.
_ENDS_FLAT = (
    {
        "all": [
            {"left": "close", "op": ">", "right": 0},
            {"left": "close", "op": "<", "right": 102},
        ]
    },
    {"all": [{"left": "close", "op": ">", "right": 103}]},
)


def test_final_equity_identity_for_run_ending_in_position() -> None:
    """(a) sum(net_pnl) == final_equity - initial, even when the forced
    end_of_data close settles AFTER the curve's last row (§4.5 edge rule)."""
    result = run(_spec(*_ENDS_IN_POSITION), _bars())
    curve = result.equity_curve
    assert float(curve["position_value"].iloc[-1]) > 0.0  # ends in a position
    assert result.trades[-1].exit_reason == "end_of_data"

    total = sum(t.net_pnl for t in result.trades)
    final = result.metrics["final_equity"]
    assert total == pytest.approx(final - CAPITAL, rel=1e-9, abs=1e-6)
    assert result.metrics["total_return"] == pytest.approx(
        final / CAPITAL - 1.0, rel=1e-9, abs=1e-12
    )


def test_curve_last_row_unchanged_gap_is_exit_costs() -> None:
    """(b) Curve-unchanged guard, hand-computed: the curve's last row stays
    pre-settlement, and the gap to the reported final_equity is exactly the
    forced close's exit slippage + exit fee — no pinned output values.

    curve_last_equity = cash_before_close + shares * last_close
    final_equity      = cash_before_close + shares * exit_price - exit_fee
    gap                = shares * (last_close - exit_price)   (exit slippage)
                       + exit_fee
    with exit_price = last_close * (1 - SLIPPAGE_BPS/1e4) and
    exit_fee = shares * exit_price * FEE_BPS/1e4 + 0 (fixed_fee = 0),
    per Ledger.sell / compute_fee (fees are charged on the fill).
    """
    bars = _bars()
    result = run(_spec(*_ENDS_IN_POSITION), bars)
    curve_last_equity = float(result.equity_curve["equity"].iloc[-1])
    final_equity = result.metrics["final_equity"]

    trade = result.trades[-1]
    assert trade.exit_reason == "end_of_data"
    last_close = float(bars["close"].iloc[-1])
    assert trade.exit_price == pytest.approx(last_close * (1.0 - SLIPPAGE_BPS / 10_000.0))

    exit_slippage_cost = trade.shares * (last_close - trade.exit_price)
    exit_fee = trade.shares * trade.exit_price * FEE_BPS / 10_000.0 + 0.0
    hand_gap = exit_slippage_cost + exit_fee

    assert hand_gap > 0.0  # the forced close is not free
    assert curve_last_equity - final_equity == pytest.approx(hand_gap, rel=1e-9, abs=1e-6)


def test_final_equity_unchanged_for_run_ending_flat() -> None:
    """(c) Ends flat: reported final_equity equals the curve's last equity
    (unchanged behaviour — the fix only touches the forced-close path)."""
    result = run(_spec(*_ENDS_FLAT), _bars())
    curve = result.equity_curve
    assert float(curve["position_value"].iloc[-1]) == pytest.approx(0.0)
    assert result.trades  # actually traded
    assert result.trades[-1].exit_reason != "end_of_data"
    assert result.metrics["final_equity"] == float(curve["equity"].iloc[-1])
