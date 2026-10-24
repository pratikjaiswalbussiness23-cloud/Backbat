"""Bar loop and trade log (ROADMAP P4-T4, §4.5 steps 1-5 + edge rules).

``run(spec, bars)`` executes ONE deterministic backtest (long-only, one
position at a time — §4.5) and returns trades, the equity curve, warnings
and a metrics dict (§4.6/§4.7 primitives; the full metric suite is P5).

The bar loop, exactly as §4.5 prescribes:

1. **Fill pending orders** created at the close of t-1 at ``open[t]``,
   adverse slippage applied, fees charged (through the ledger). Position
   sizing is computed AT FILL TIME from cash and the slippage-adjusted fill
   price (§4.5).
2. **Intrabar risk exits** on the open position (including one opened at
   this bar's open): stop loss, take profit, trailing stop via
   :class:`~nlbt.engine.risk.RiskManager` — gap fills at the open, level
   fills at the level, stop-first tie-break; the trailing ratchet runs after
   each empty check (never raises the stop its own low then hits).
3. **Mark to market**: ``equity[t] = cash + shares * close[t]``.
4. **Evaluate signals using data ≤ t only** (precomputed vectorised arrays;
   indicator warm-up NaN ⇒ False ⇒ no early signals):
   flat + entry_long → pending entry for t+1; in position + exit_long (or
   ``max_holding_bars`` reached) → pending exit for t+1; exit has priority
   over entry; exit_long is ignored while flat.
5. **Record the bar**: equity, cash, position value, drawdown
   (``drawdown[t] = equity[t] / max(equity[0..t]) - 1``, ≤ 0).

Edge rules:

* a signal on the LAST bar is ignored and logged as a warning (no t+1 to
  fill at — E8/SC8a);
* a position still open after the last bar is closed at the last close
  with ``exit_reason = "end_of_data"`` AFTER the final row is recorded —
  the fill runs through the same slippage+fee path as any sell (OQ-0053
  resolution: SC2's ``104.9475 = 105 * (1 - 0.0005)`` pins slippage, its
  ``375.2683`` net pins the fee; SC8b's ``slippage_bps=0`` asserts the raw
  last close literally — both hold when the close is an ordinary sell);
* ``bars_held = exit_bar_index - entry_bar_index`` (integer positions,
  SC12: 6 - 2 = 4).

Trade P&L conventions (§4.6; every scenario docstring cross-checks these):

* ``entry_price`` / ``exit_price`` are the ACTUAL fills (slippage in);
* ``fees`` = entry fee + exit fee (percentage + fixed, §4.1);
* ``gross_pnl = (exit_price - entry_price) * shares``;
* ``net_pnl  = gross_pnl - fees``   (slippage already inside the prices);
* ``slippage_cost`` = currency value of the adverse price moves;
* ``mae_pct`` / ``mfe_pct`` = worst/best excursion of low/high over
  ``[entry..exit]`` relative to ``entry_price`` (a ratio, per the §4.5
  formula; ``None`` when the trade spans no bars between entry and exit).

No lookahead: fills use only ``open[t]`` of a later bar, signals use only
data ≤ t, and the trailing stop checks the prior trail before ratcheting on
the current high (§4.5/P4-T10 defences).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from nlbt.data.frequency import infer_frequency
from nlbt.data.models import Bars
from nlbt.engine.execution import apply_slippage
from nlbt.engine.ledger import Ledger
from nlbt.engine.risk import RiskManager
from nlbt.engine.signals import evaluate_rule
from nlbt.engine.sizing import compute_shares
from nlbt.indicators.registry import REGISTRY, Registry
from nlbt.metrics import compute_return_metrics, compute_trade_metrics
from nlbt.spec.models import StrategySpec

__all__ = ["BacktestResult", "Trade", "run"]

#: Cap on individually listed "Entry skipped … computed size 0" warnings
#: (OQ-0061): a persistent signal with insufficient cash fires this once
#: per bar, and a 100k-bar run must not emit 100k near-identical strings.
#: Beyond the cap, one total-count summary line is appended after the loop.
_ZERO_SIZE_SKIP_CAP = 20


@dataclass
class Trade:
    """One completed round trip (§4.6 Trade schema).

    ``exit_reason`` ∈ {"signal", "stop_loss", "take_profit", "trailing_stop",
    "time_exit", "end_of_data"} (§4.6 enum). ``exit_signal_time`` is None
    when the exit had no signal bar (intrabar risk exits and the
    end-of-data forced close). ``mae_pct``/``mfe_pct`` are ratios of
    ``entry_price`` (negative for adverse excursion), None when entry and
    exit share a bar.
    """

    id: int
    symbol: str
    side: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry_price: float
    exit_signal_time: pd.Timestamp | None
    exit_time: pd.Timestamp
    exit_price: float
    shares: float
    fees: float
    slippage_cost: float
    gross_pnl: float
    net_pnl: float
    return_pct: float
    bars_held: int
    exit_reason: str
    mae_pct: float | None
    mfe_pct: float | None


@dataclass
class BacktestResult:
    """Result of one ``run`` (§4.6 BacktestResult — engine subset).

    ``equity_curve`` carries columns ``t, equity, cash, position_value,
    drawdown`` indexed by the bars' DatetimeIndex; ``metrics`` maps metric
    name → float | None (None only where undefined — never NaN/inf, §4.7).
    """

    trades: list[Trade]
    equity_curve: pd.DataFrame
    warnings: list[str]
    metrics: dict[str, float | None]
    #: Return-metric, trade-metric and ``infer_frequency`` warnings,
    #: deferred for surfacing by ``nlbt.results.execute_run`` (OQ-0072
    #: owner-ruled channel). ``warnings`` above stays engine-only so every
    #: existing exact-assertion on it keeps passing.
    metric_warnings: list[str] = field(default_factory=list)


@dataclass
class _OpenTrade:
    """In-flight position bookkeeping until the exit fills (never exposed)."""

    id: int
    symbol: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry_price: float
    entry_idx: int
    shares: float
    fees: float  # entry-side fees so far
    slippage_cost: float  # entry-side slippage so far


@dataclass
class _PendingOrder:
    """Order created at step 4 of bar t, filled at step 1 of bar t+1."""

    kind: Literal["entry", "exit"]
    signal_time: pd.Timestamp
    reason: str  # exits: "signal" | "time_exit"; entries: "signal"


def run(
    spec: StrategySpec,
    bars: Bars,
    registry: Registry | None = None,
    *,
    rf: float = 0.0,
) -> BacktestResult:
    """Run the §4.5 bar loop over ``bars`` for ``spec``; return the result.

    ``registry`` defaults to the global indicator registry
    (:data:`~nlbt.indicators.registry.REGISTRY`); rules are evaluated once
    up front into boolean arrays (every element depends only on data ≤ its
    own bar), then consumed bar by bar inside the loop.
    """
    reg = REGISTRY if registry is None else registry
    n = len(bars)
    index = bars.index
    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)

    # ---- signal arrays (data ≤ t only; warm-up NaN ⇒ False, §4.2/S12) ----
    entry_signal = evaluate_rule(spec.rules.entry_long, bars, spec.indicators, registry=reg)
    if spec.rules.exit_long is not None:
        exit_signal = evaluate_rule(spec.rules.exit_long, bars, spec.indicators, registry=reg)
    else:
        exit_signal = np.zeros(n, dtype=bool)

    fee_bps = spec.execution.fee_bps
    slippage_bps = spec.execution.slippage_bps
    ledger = Ledger(
        spec.capital.initial,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        allow_fractional=spec.sizing.allow_fractional,
        fixed_fee=spec.execution.fixed_fee,
    )
    symbol = spec.universe.symbols[0]

    warnings: list[str] = []
    zero_size_skips = 0
    trades: list[Trade] = []
    open_pos: _OpenTrade | None = None
    risk: RiskManager | None = None
    pending: _PendingOrder | None = None
    next_trade_id = 0

    def close_position(
        position: _OpenTrade,
        *,
        exit_level: float,
        exit_time: pd.Timestamp,
        exit_idx: int,
        exit_reason: str,
        exit_signal_time: pd.Timestamp | None,
    ) -> Trade:
        """Sell the full position at ``exit_level`` (pre-slippage) and build
        the completed :class:`Trade` — the one exit path used by step-1 fills,
        intrabar risk exits and the end-of-data close alike."""
        shares_held = ledger.shares
        exit_fee = ledger.sell(shares_held, exit_level)
        exit_price = apply_slippage(exit_level, "sell", slippage_bps)
        gross = (exit_price - position.entry_price) * shares_held
        fees_total = position.fees + exit_fee
        net = gross - fees_total
        basis = position.entry_price * shares_held
        mae: float | None
        mfe: float | None
        if exit_idx > position.entry_idx:
            window_low = lows[position.entry_idx : exit_idx + 1]
            window_high = highs[position.entry_idx : exit_idx + 1]
            mae = (float(window_low.min()) - position.entry_price) / position.entry_price
            mfe = (float(window_high.max()) - position.entry_price) / position.entry_price
        else:
            mae = None  # no bars between entry and exit (§4.6)
            mfe = None
        return Trade(
            id=position.id,
            symbol=position.symbol,
            side="long",
            signal_time=position.signal_time,
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            exit_signal_time=exit_signal_time,
            exit_time=exit_time,
            exit_price=exit_price,
            shares=shares_held,
            fees=fees_total,
            slippage_cost=position.slippage_cost
            + shares_held * (exit_level - exit_price),  # adverse move, in currency
            gross_pnl=gross,
            net_pnl=net,
            return_pct=(net / basis) if basis > 0.0 else 0.0,
            bars_held=exit_idx - position.entry_idx,
            exit_reason=exit_reason,
            mae_pct=mae,
            mfe_pct=mfe,
        )

    peak: float | None = None
    times: list[Any] = []
    equity_values: list[float] = []
    cash_values: list[float] = []
    position_values: list[float] = []
    drawdown_values: list[float] = []

    for t in range(n):
        raw_open = float(opens[t])
        bar = {
            "open": raw_open,
            "high": float(highs[t]),
            "low": float(lows[t]),
            "close": float(closes[t]),
        }

        # ---- STEP 1: fill pending orders created at t-1 (§4.5) ----
        if pending is not None:
            order = pending
            pending = None
            if order.kind == "entry" and open_pos is None:
                fill_price = apply_slippage(raw_open, "buy", slippage_bps)
                shares = compute_shares(
                    spec.sizing.method,
                    spec.sizing.value,
                    equity=ledger.equity(fill_price),  # flat: == cash
                    cash=ledger.cash,
                    price=fill_price,  # slippage-adjusted (§4.5)
                    fee_bps=fee_bps,
                    fixed_fee=spec.execution.fixed_fee,
                    allow_fractional=spec.sizing.allow_fractional,
                    stop_loss_pct=spec.risk.stop_loss_pct,
                )
                entry_fee = ledger.buy(shares, raw_open)
                if ledger.shares > 0.0:
                    next_trade_id += 1
                    open_pos = _OpenTrade(
                        id=next_trade_id,
                        symbol=symbol,
                        signal_time=order.signal_time,
                        entry_time=index[t],
                        entry_price=fill_price,
                        entry_idx=t,
                        shares=ledger.shares,
                        fees=entry_fee,
                        slippage_cost=ledger.shares * (fill_price - raw_open),
                    )
                    risk = RiskManager(
                        entry_price=fill_price,
                        entry_bar=t,
                        stop_loss_pct=spec.risk.stop_loss_pct,
                        take_profit_pct=spec.risk.take_profit_pct,
                        trailing_stop_pct=spec.risk.trailing_stop_pct,
                        max_holding_bars=spec.risk.max_holding_bars,
                    )
                else:
                    # OQ-0061 (C4 / §4.5 "reject with a warning"): the entry
                    # order FILLED but sized to 0, so the entry is SKIPPED —
                    # record it loudly. (The ledger's own reject warnings are
                    # unreachable here: sizing pre-clamps to 0 with the
                    # identical budget — OQ-0060b — and ledger.buy(0)
                    # no-ops silently at ledger.py:162.)
                    zero_size_skips += 1
                    if zero_size_skips <= _ZERO_SIZE_SKIP_CAP:
                        warnings.append(
                            f"Entry skipped on {index[t].date()}: computed size 0 "
                            f"(cash {ledger.cash:g}, fill price {fill_price:g}, "
                            f"fixed_fee {spec.execution.fixed_fee:g}); "
                            f"entry signal from {order.signal_time.date()}."
                        )
            elif order.kind == "exit" and open_pos is not None:
                trades.append(
                    close_position(
                        open_pos,
                        exit_level=raw_open,
                        exit_time=index[t],
                        exit_idx=t,
                        exit_reason=order.reason,
                        exit_signal_time=order.signal_time,
                    )
                )
                open_pos = None
                risk = None

        # ---- STEP 2: intrabar risk exits (§4.5) ----
        if open_pos is not None and risk is not None:
            decision = risk.check(bar)
            if decision is not None and decision.price is not None:
                trades.append(
                    close_position(
                        open_pos,
                        exit_level=decision.price,  # level, or open on a gap
                        exit_time=index[t],
                        exit_idx=t,
                        exit_reason=decision.reason,
                        exit_signal_time=None,  # no signal bar: intrabar
                    )
                )
                open_pos = None
                risk = None

        # ---- STEP 3: mark to market at close[t] (§4.5) ----
        close_price = float(closes[t])
        equity = ledger.equity(close_price)
        cash = ledger.cash
        position_value = ledger.shares * close_price
        peak = equity if peak is None or equity > peak else peak
        drawdown = (equity / peak - 1.0) if peak > 0.0 else 0.0

        # ---- STEP 4: signals on data ≤ t only (§4.5) ----
        is_last = t == n - 1
        if open_pos is not None:
            # Exit priority over entry; entry is not even evaluated while
            # in position, and exit_long never re-enters (§4.5 step 4).
            if bool(exit_signal[t]):
                if is_last:
                    warnings.append(
                        f"Exit signal on the last bar (bar {t}) ignored: no next bar to "
                        "fill at; the position is closed at end_of_data instead."
                    )
                else:
                    pending = _PendingOrder(kind="exit", signal_time=index[t], reason="signal")
            elif risk is not None and risk.time_exit_due(t):
                if is_last:
                    warnings.append(
                        f"max_holding_bars exit on the last bar (bar {t}) ignored: "
                        "no next bar to fill at; closed at end_of_data instead."
                    )
                else:
                    pending = _PendingOrder(kind="exit", signal_time=index[t], reason="time_exit")
        elif bool(entry_signal[t]):
            if is_last:
                warnings.append(
                    f"Entry signal on the last bar (bar {t}) ignored: no next bar "
                    "to fill the order at (§4.5 edge rule)."
                )
            else:
                pending = _PendingOrder(kind="entry", signal_time=index[t], reason="signal")
        # while flat, exit_long is ignored (§4.5)

        # ---- STEP 5: record the bar (§4.5/§4.6) ----
        times.append(index[t])
        equity_values.append(equity)
        cash_values.append(cash)
        position_values.append(position_value)
        drawdown_values.append(drawdown)

    # ---- edge rule: close any position still open after the last bar ----
    closed_at_end = open_pos is not None
    if open_pos is not None:
        last_close = float(closes[n - 1])
        trades.append(
            close_position(
                open_pos,
                exit_level=last_close,
                exit_time=index[n - 1],
                exit_idx=n - 1,
                exit_reason="end_of_data",
                exit_signal_time=None,  # no signal bar: forced close (§4.5)
            )
        )

    if zero_size_skips > _ZERO_SIZE_SKIP_CAP:
        warnings.append(
            f"Zero-size entry skips: {zero_size_skips} in total; "
            f"{zero_size_skips - _ZERO_SIZE_SKIP_CAP} further occurrences not "
            "listed (first occurrences shown above)."
        )
    warnings.extend(ledger.warnings)

    equity_curve = pd.DataFrame(
        {
            "t": times,
            "equity": equity_values,
            "cash": cash_values,
            "position_value": position_values,
            "drawdown": drawdown_values,
        },
        index=index,
    )

    initial_capital = float(spec.capital.initial)
    # OQ-0064: when the forced end_of_data close ran, report the REALIZED
    # post-close cash (``ledger.cash`` — the close already flowed fee and
    # slippage through the ledger); otherwise keep the last curve row. The
    # equity curve itself, including its last row, stays pre-settlement
    # (differential S1 depends on it).
    if closed_at_end:
        final_equity = ledger.cash
    else:
        final_equity = equity_values[-1] if equity_values else initial_capital
    # P5-T1 (§4.7): settled series — a LOCAL copy whose last value is the
    # realized final_equity after a forced close; the stored curve above is
    # never modified. bars_per_year is inferred from the data, never
    # hardcoded (§4.7); its warning and the metric warnings are deliberately
    # NOT appended to ``warnings`` here (OQ-0072 owner ruling (a): surfaced
    # in P5-T4).
    settled = list(equity_values)
    if closed_at_end and settled:
        settled[-1] = final_equity
    freq = infer_frequency(bars, spec.universe.interval)
    return_metrics, return_warnings = compute_return_metrics(
        np.asarray(settled, dtype=float),
        pd.DatetimeIndex(times),
        freq.bars_per_year,
        rf=rf,
    )
    # P5-T2 (§4.7): trade metrics computed in ONE place (metrics/trades.py);
    # the mask comes from the curve's position_value > 0. Warnings returned
    # but NOT appended to result.warnings (OQ-0072 ruling (a): P5-T4).
    trade_metrics, trade_warnings = compute_trade_metrics(
        trades,
        equity_curve["position_value"].to_numpy() > 0.0,
    )
    metrics: dict[str, float | None] = {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        **return_metrics,  # total_return & max_drawdown computed in ONE place (P5-T1)
        **trade_metrics,  # num_trades/win_rate/... computed in ONE place (P5-T2)
    }
    # OQ-0072 (resolved by P5-T4a): surfaced by nlbt.results.execute_run
    # (final warnings = engine warnings + these + benchmark-prefixed ones);
    # run().warnings itself stays engine-only (existing exact assertions).
    metric_warnings = [*return_warnings, *trade_warnings]
    if freq.warning is not None:
        metric_warnings.append(freq.warning)

    return BacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        warnings=warnings,
        metrics=metrics,
        metric_warnings=metric_warnings,
    )
