"""Zero-size entry fills must warn — OQ-0061 (C4, §4.5 "reject with a warning").

Every expectation here is HAND-DERIVED (R4): arithmetic and dates are
computed in each docstring from the fixture, never copied from engine
output. Interval is Literal["1d"] only (spec/models.py:478), so bar dates
are plain calendar dates and the warning uses ``.date()``.

Fixture shape (all cases): flat bars, entry rule ``close > 0`` (always
true) => an entry order is pending at EVERY bar, so a fill is attempted
at every bar t >= 1. ``bdate_range("2024-01-02", periods=n)`` has no
holiday handling, so the first n business days of 2024 are used literally.
"""

from __future__ import annotations

import pandas as pd

from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.engine.ledger import Ledger
from nlbt.spec.models import StrategySpec


def _flat_bars(price: float, n: int) -> Bars:
    """n flat business-day bars starting 2024-01-02 (valid OHLC)."""
    idx = pd.bdate_range("2024-01-02", periods=n)
    return Bars(
        pd.DataFrame(
            {
                "open": [price] * n,
                "high": [price * 1.01] * n,
                "low": [price * 0.99] * n,
                "close": [price] * n,
                "volume": [1_000_000.0] * n,
            },
            index=idx,
        )
    )


def _spec(
    *,
    capital: float,
    method: str = "percent_of_equity",
    value: float = 100.0,
    allow_fractional: bool = True,
    fixed_fee: float = 0.0,
) -> StrategySpec:
    """Valid §4.1 StrategySpec: entry close > 0 (always true), no exit rule."""
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "oq0061-test",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {},
            "rules": {"entry_long": {"all": [{"left": "close", "op": ">", "right": 0}]}},
            "risk": {},
            "sizing": {"method": method, "value": value, "allow_fractional": allow_fractional},
            "execution": {
                "fill": "next_open",
                "fee_bps": 0.0,
                "slippage_bps": 0.0,
                "fixed_fee": fixed_fee,
            },
            "capital": {"initial": capital},
        }
    )


def _skip(fill_date: str, signal_date: str, cash: str, fixed_fee: str) -> str:
    """The exact OQ-0061 warning text template (fill price is 150 in all cases)."""
    return (
        f"Entry skipped on {fill_date}: computed size 0 "
        f"(cash {cash}, fill price 150, fixed_fee {fixed_fee}); "
        f"entry signal from {signal_date}."
    )


def test_zero_size_entry_warns_integer_cash_cap_floor() -> None:
    """T1: integer mode, cash cap floors to 0 — the fill must warn (was silent).

    5 flat bars @150 (2024-01-02..01-08), capital 149, fixed_shares=100,
    integer shares, zero fees. Hand-derived sizing:
        target  = 100 shares (fixed_shares)
        cap     = floor((149 - 2*0) / (150 * 1.0)) = floor(0.99333) = 0
        shares  = min(100, 0) = 0          -> Ledger.buy(0) no-ops silently
    Fill attempts: signal at bar 0 => pending => fill at bars 1..4 (4 events).
    Hand-derived warning order (chronological, §4.5 bar loop):
        bars 1-4 zero-size skips, THEN the pre-existing last-bar warning
        (bar 4 is the last bar: fill attempt in STEP 1, last-bar notice in
        STEP 4). No ledger warnings (buy(0) never reaches the ledger).
    """
    res = run(
        _spec(capital=149.0, method="fixed_shares", value=100.0, allow_fractional=False),
        _flat_bars(150.0, 5),
    )

    assert res.warnings == [
        _skip("2024-01-03", "2024-01-02", "149", "0"),
        _skip("2024-01-04", "2024-01-03", "149", "0"),
        _skip("2024-01-05", "2024-01-04", "149", "0"),
        _skip("2024-01-08", "2024-01-05", "149", "0"),
        "Entry signal on the last bar (bar 4) ignored: no next bar "
        "to fill the order at (\u00a74.5 edge rule).",
    ]
    assert res.trades == []
    assert list(res.equity_curve["cash"]) == [149.0] * 5
    assert list(res.equity_curve["equity"]) == [149.0] * 5


def test_zero_size_entry_warns_fixed_fee_band() -> None:
    """T2: the OQ-0060b band fixed_fee < cash <= 2*fixed_fee — must warn.

    3 flat bars @150, capital 15, fixed_fee 10, fractional. Hand-derived:
        cap = (15 - 2*10) / 150 = -0.03333 -> clamped to 0.0 (sizing.py:112)
        shares = 0 -> Ledger.buy(0) no-ops silently
    Pre-OQ-0060b the ledger's budget<=0 reject warned here; the alignment
    removed that warning, so this is the regression pin for the gap.
    Fill attempts at bars 1-2; bar 2 is also the last bar.
    """
    res = run(_spec(capital=15.0, fixed_fee=10.0), _flat_bars(150.0, 3))

    assert res.warnings == [
        _skip("2024-01-03", "2024-01-02", "15", "10"),
        _skip("2024-01-04", "2024-01-03", "15", "10"),
        "Entry signal on the last bar (bar 2) ignored: no next bar "
        "to fill the order at (\u00a74.5 edge rule).",
    ]
    assert res.trades == []


def test_zero_size_warning_cap_and_summary_order() -> None:
    """T3: cap = 20 listed skips, then last-bar warning, then summary (order pinned).

    30 flat bars @150 (2024-01-02..2024-02-12), capital 149, fixed_shares=100,
    integer. Fill attempts at bars 1..29 = 29 zero-size events.
    Hand-derived bdate_range positions (no holidays in bdate_range):
        bar 1=Jan 3, 2=Jan 4, 3=Jan 5, 4=Jan 8, 5=Jan 9, 6=Jan 10, 7=Jan 11,
        8=Jan 12, 9=Jan 15, 10=Jan 16, 11=Jan 17, 12=Jan 18, 13=Jan 19,
        14=Jan 22, 15=Jan 23, 16=Jan 24, 17=Jan 25, 18=Jan 26, 19=Jan 29,
        20=Jan 30, ..., 29=Feb 12.
    Cap 20 => skips for bars 1-20 are listed (signal of bar 1 is bar 0 =
    Jan 2; each later signal date is the previous bar's date). Bars 21-29
    are counted but not listed. Chronological order inside the loop:
    zero-size skips (bars 1-20 listed), then the last-bar warning (bar 29),
    then the end-of-loop summary line. Total = 20 + 1 + 1 = 22 warnings.
    29 - 20 = 9 occurrences suppressed.
    """
    n_bars = 30
    res = run(
        _spec(capital=149.0, method="fixed_shares", value=100.0, allow_fractional=False),
        _flat_bars(150.0, n_bars),
    )

    listed_fills = [
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
        "2024-01-09",
        "2024-01-10",
        "2024-01-11",
        "2024-01-12",
        "2024-01-15",
        "2024-01-16",
        "2024-01-17",
        "2024-01-18",
        "2024-01-19",
        "2024-01-22",
        "2024-01-23",
        "2024-01-24",
        "2024-01-25",
        "2024-01-26",
        "2024-01-29",
        "2024-01-30",
    ]
    signal_dates = ["2024-01-02", *listed_fills[:-1]]
    expected_skips = [
        _skip(fill, signal, "149", "0")
        for fill, signal in zip(listed_fills, signal_dates, strict=True)
    ]

    assert len(res.warnings) == 22
    # positions 0-19: the first 20 skip lines (bars 1-20), in bar order
    assert res.warnings[:20] == expected_skips
    # position 20: the pre-existing last-bar warning (bar 29 = 2024-02-12)
    assert res.warnings[20] == (
        "Entry signal on the last bar (bar 29) ignored: no next bar "
        "to fill the order at (\u00a74.5 edge rule)."
    )
    # position 21: the end-of-run summary
    assert res.warnings[21] == (
        "Zero-size entry skips: 29 in total; 9 further occurrences not "
        "listed (first occurrences shown above)."
    )
    # no ledger warnings may appear anywhere (buy(0) never reaches the ledger)
    assert not any(w.startswith("Buy ") for w in res.warnings)
    assert res.trades == []


def test_normal_entry_produces_no_zero_size_warning() -> None:
    """T4 control: an affordable entry adds NO new warning (no false positives).

    5 flat bars @150, capital 10000, percent_of_equity 10, integer.
    Hand-derived: target = floor((10000 * 0.10) / 150) = floor(6.667) = 6;
    cap = floor(10000 / 150) = floor(66.67) = 66; shares = min(6, 66) = 6.
    Entry fills at bar 1; no exit rule => held to the end => closed
    end_of_data; at the last bar we are IN POSITION, so not even the
    last-bar entry warning applies. warnings must be EXACTLY empty.
    """
    res = run(_spec(capital=10000.0, value=10.0, allow_fractional=False), _flat_bars(150.0, 5))

    assert res.warnings == []
    assert len(res.trades) == 1
    assert res.trades[0].shares == 6.0


def test_ledger_reject_warning_unchanged_when_called_directly() -> None:
    """T5: ledger path (b) — budget <= 0 reject is still audible (unchanged).

    Ledger(15, fixed_fee=10).buy(1, 150): budget = 15 - 2*10 = -5 <= 0
    => "Buy rejected: fixed fees (entry + exit reserve = 20) reach cash 15."
    (2*fixed_fee = 20, cash = 15 — both :g-formatted literals).
    Unreachable via run() (sizing pre-clamps to 0 — OQ-0060b); pinned here
    so the fix can never have touched ledger.py.
    """
    ledger = Ledger(15.0, fixed_fee=10.0)
    ledger.buy(1.0, 150.0)
    assert ledger.warnings == [
        "Buy rejected: fixed fees (entry + exit reserve = 20) reach cash 15."
    ]


def test_ledger_reduce_warning_unchanged_when_called_directly() -> None:
    """T6: ledger path (c) — the reduce branch is still audible (unchanged).

    Ledger(1000).buy(100, 150), fractional: max_affordable = 1000/150 =
    6.66667 (%g: 6 significant digits) < 100 => reduce warning with the
    hand-derived numbers 100 -> 6.66667 and cash 1000.
    Unreachable via run() post-OQ-0060b; pinned so the fix can never have
    touched ledger.py.
    """
    ledger = Ledger(1000.0)
    ledger.buy(100.0, 150.0)
    assert ledger.warnings == [
        "Buy size reduced from 100 to 6.66667 shares: insufficient cash (1000)."
    ]
