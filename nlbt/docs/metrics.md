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

**Warning surfacing is deferred (OQ-0072, owner ruling (a)):**
`compute_return_metrics` returns its warnings, and `run()` also gets the
`infer_frequency` warning, but neither is appended to
`BacktestResult.warnings` in P5-T1. Both **must** be surfaced in P5-T4,
whose Phase A proposes the channel — do not drop them.

## Risk-free rate

`rf` is a keyword on `run()` (default `0.0`) and is **always** present in
`result.metrics` as `risk_free_rate`, next to Sharpe (§4.7: "always
displayed with its rf").
