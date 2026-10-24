# nlbt metric definitions (ROADMAP §4.7)

Implemented by `nlbt.metrics` (return-based, P5-T1); trade-based metrics
follow in P5-T2. Every value is tested against hand-computed arithmetic and
an independent numpy oracle (`tests/unit/test_metrics_returns.py`).

## Return-based metrics

| Metric | Definition |
|--------|------------|
| Bar return | `r[t] = E[t]/E[t−1] − 1` |
| Years | `(last_date − first_date).days / 365.25` |
| Total return | `E_end / E_start − 1` |
| CAGR | `(E_end / E_start)^(1/years) − 1` |
| Annualised volatility | `std(r, ddof=1) × sqrt(bars_per_year)` |
| Sharpe | `(mean(r) − rf/bars_per_year) / std(r, ddof=1) × sqrt(bars_per_year)`; `rf` configurable, default 0, **always displayed with its rf** (`risk_free_rate` key) |
| Max drawdown | `min(E / cummax(E) − 1)`; also longest drawdown duration in bars (`longest_drawdown_bars`) |
| Calmar | `CAGR / abs(max drawdown)`; null if drawdown is 0 |
| `bars_per_year` | derived from data frequency via `nlbt.data.frequency.infer_frequency`, or explicitly supplied — never hardcoded silently |

Sortino is **not implemented** (OQ-0071): §4.7 gives only the
downside-deviation formula, with no ratio form or target definition.

## Trade-based metrics (P5-T2, rulings OQ-0073/OQ-0074)

| Metric | Definition |
|--------|------------|
| Num trades | count of completed trades (0 when none — a defined count) |
| Win rate | trades with `net_pnl > 0` / total trades |
| Profit factor | **NET basis**: `sum(net_pnl > 0) / abs(sum(net_pnl < 0))`; null + warning when there are no losses — the warning IS the §4.7 flag |
| Expectancy | mean `return_pct` over ALL trades |
| Avg win / avg loss | means of `return_pct` split by `net_pnl > 0` / `net_pnl < 0`; a breakeven trade (`net_pnl == 0`) belongs to neither |
| Longest losing streak | consecutive trades with `net_pnl < 0`; a breakeven trade resets the streak |
| Exposure | fraction of bars with an open position (equity curve `position_value > 0`) |

MAE/MFE stay per trade (`Trade.mae_pct` / `Trade.mfe_pct`); no aggregates
(OQ-0073 deferred).

## Benchmark (P5-T3)

`nlbt.engine.benchmark.compute_benchmark(spec, bars, rf=0.0)` runs a private
buy-and-hold spec through the **same engine** — same universe, period,
execution costs (fee/slippage/fixed_fee) and capital; `entry_long = close>0`,
no exit, no risk, 100% equity, fractional shares — and returns the same §4.7
return-metrics dict plus warnings. Caveats:

- the benchmark buys at the **first fill (bar 1 open, as in SC2)**, not at
  the strategy's own start after warm-up;
- it uses **fractional shares** (fully invested);
- at end of data it is closed by the same forced `end_of_data` close
  (exit costs included), so its metrics are settled like the strategy's;
- warnings are returned, not attached: `run()`/`BacktestResult` are
  unchanged for the benchmark; `execute_run()` (P5-T4a) attaches
  `benchmark_metrics` to the final result and surfaces these warnings
  prefixed `"benchmark: "`.

## The settled series (owner decision, OQ-0064 / P5-T1)

All metrics above are computed on the **settled equity series**: the
engine's stored equity curve with its **last value replaced by the
realized `final_equity`** when a forced `end_of_data` close happened
(the close settles fees/slippage after the final row is recorded, §4.5).
The replacement happens on a local copy inside `run()` — **the stored
equity curve is never modified** (the differential S1 test pins its
pre-settlement last row).

Consequence — **stored `drawdown` column vs `max_drawdown` metric:** the
curve's `drawdown` column is computed per bar from the *unsettled* mark,
while `metrics["max_drawdown"]` is computed from the *settled* series.
After a forced close the two can differ slightly (the settled last value
realises the exit's fee+slippage). This is intended; the curve is not
"fixed" because S1 depends on it.

## null + warning policy (§4.7, I13)

An undefined metric is reported as `null` (`None` in Python) with a
warning reason — never `0`, `NaN` or `inf` when the value is undefined:
zero variance → Sharpe null; zero drawdown → Calmar null; fewer than 2
bars → all return metrics null (including total return); sample std with
fewer than 3 bars → volatility/Sharpe null; `years == 0` → CAGR null;
non-positive start/end equity or non-finite input → all null;
`bars_per_year <= 0` raises `ValueError`.

**Warning surfacing (OQ-0072, resolved in P5-T4a):** `run()` stays the
pure engine — its `BacktestResult.warnings` is byte-for-byte unchanged
(the S1–S6 and zero-size exact-list assertions still pass). `run()`
collects the return-metric warnings, the trade-metric warnings and the
`infer_frequency` warning into a new defaulted field
`BacktestResult.metric_warnings: list[str]`. The final §4.6 result is
built by `nlbt.results.execute_run()`, whose `RunResult.warnings` is
`engine.warnings + engine.metric_warnings + benchmark warnings`, where
benchmark warnings are prefixed `"benchmark: "`; exact duplicates are
dropped, order preserved, engine warnings first. Persisting the result
(`result.json` under `runs/<run_id>/`) is `results/store.py`.

## Risk-free rate

`rf` is a keyword on `run()` (default `0.0`) and is **always** present in
`result.metrics` as `risk_free_rate`, next to Sharpe (§4.7: "always
displayed with its rf").
