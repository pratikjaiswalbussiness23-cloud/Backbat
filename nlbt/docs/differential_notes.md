# differential_notes.md — P4-T11 nlbt vs backtesting.py 0.6.6

Every discrepancy between the nlbt engine and the independent oracle
(backtesting.py 0.6.6, dev-only) is recorded here with its exact numbers and
verdict (ROADMAP P4-T11: "every discrepancy is explained … Unexplained
differences block the gate"). All entries dated 2026-10-18 (session date).

Suite: `tests/differential/test_differential.py` — scenarios S1–S5, each run
in two passes (Pass 1 zero costs; Pass 2 fee_bps=10, slippage_bps=5,
fixed_fee=0), constant 10 shares both sides.

---

## 1. Dependency audit — backtesting 0.6.6 added, nothing else moved (2026-10-18)

Pre-check: `uv lock --check` exit 0; lock resolved 72 packages, numpy 2.5.3.
After `uv add --dev backtesting`: 80 packages. `git diff uv.lock` =
**210 insertions, 0 deletions**; named before/after parse: REMOVED none,
VERSION CHANGED **NONE**, numpy **2.5.3 → 2.5.3**. Added (all transitive
deps of backtesting 0.6.6): bokeh 3.10.1, jinja2 3.1.6, markupsafe 3.0.4,
narwhals 2.27.1, pillow 13.0.0, tornado 6.5.10, xyzservices 2026.9.1.
Runtime: `numpy 2.5.3 | backtesting 0.6.6`.
(The probe-env numpy 2.3.5 seen earlier was a `uv --no-project` throwaway
env only — never this project's lock.)

## 2. `finalize_trades=True` is pinned in EVERY backtesting run (2026-10-18)

backtesting's default `finalize_trades=False` silently EXCLUDES a still-open
trade from stats (`# Trades 0`, `Win Rate NaN`) with only a stderr
UserWarning; on identical seeded data `Return [%]` was −12.3983 (finalize
off) vs −12.6943 (finalize on). The harness passes
`finalize_trades=True` unconditionally (`_run_bt`).

## 3. EXPLAINED DIFFERENCE — end_of_data settlement (S1, owner-approved) (2026-10-18)

**Convention difference, not a bug.** nlbt's §4.5 edge rule closes a position
open after the last bar at the **last close** (`exit_reason="end_of_data"`,
fill through the ordinary sell path: `close_last*(1-slip)`); backtesting's
finalize closes at the **last open** and also pays the exit commission there.

Probe numbers (99 shares, last bar Open 111.5 / Close 99.5, zero costs):
finalize-off last equity row **9950.5** (= pre-settlement close mark, nlbt's
convention) vs finalize-on **11138.5** (post-settlement at the open); the
pre-settlement mark reconstructs exactly:
`11138.5 − 99*(111.5−99.5) = 9950.5` (matched <1e-9); rows 0..n−2 are
identical between the two runs (only the last row is overwritten).

S1 handling (owner decision): S1 (buy-and-hold) cannot drain by definition,
so its settlement exit is EXCLUDED from the price comparison; the test
instead compares (a) the entry fill, (b) equity rows 0..n−2 natively, and
(c) the last row via the reconstruction
`nl_last == bt_last − shares*(open_last − close_last) + settle_fee`
with `settle_fee = shares*open_last*fee_rate` (backtesting charges the
settlement commission; Pass 1 fee_rate=0 so the term vanishes). S1 fixture
exact numbers: last bar Open **125** / Close **111**, 10 shares → bt settles
trade ExitPrice **125.0** (commission 1.25 in Pass 2), nlbt settles
**111*(1−0.0005) = 110.9445** (Pass 2) / 111.0 (Pass 1); final-row equity gap
between engines = `10*(125−111) − 1.25 = 138.75` (Pass 2) / 140.0 (Pass 1).
Both conventions asserted verbatim in `test_s1_buy_and_hold`. S2–S5 drain
before the final bar, so the convention never interacts there.

## 4. S5 entry-bar trailing gap — fixture-pinned, computed from actual fills (2026-10-18)

Trail is **3%** (owner correction). nlbt checks an initial trail
`entry_fill*(1−0.03)` on the entry bar; a plain backtesting `buy()` has no
stop that bar (ratchet stops are created in `strategy.next()`, which runs
after `broker.next()`). Owner-approved resolution: fixture option — the test
computes `low[entry] > actual_fill*(1−0.03)` (strict) **per pass and per
side from the real fills** (Pass 2 fills include slippage), never a
hard-coded price, and fails with the computed numbers in the message. The
level seeded for bar entry+1 is asserted EQUAL on both sides
(`strat.seeded_trail_raw` vs `RiskManager(...).check(entry_bar).trail_level`
after the engine's own post-check ratchet), plus each side's structural
formula (`max(fill, high[entry])*(1−pct)`).

## 5. Entry-bar stop-check order and tie-break — MATCH (2026-10-18)

backtesting 0.6.6 source (`_process_orders` + `_open_trade`): after a market
entry fills, `reprocess_orders=True` re-checks the new bracket against the
SAME bar (issue-#119 comment). Empirical: entry bar 2, low 50, `buy(sl=95)` →
`entry 2, exit 2, px 95.0` = nlbt's STEP1→STEP2 same-bar check. Tie-break:
SL 95 + TP 105 both reachable on the entry bar → SL wins (95.0) = nlbt's
conservative stop-first (R5). Gap: post-entry bar opening 80 below SL 95 →
exit at 80.0 (the open) = nlbt `resolve_exit_fill`. Caveat: CONTINGENT
(stop/limit) entry orders suppress the same-bar reprocess with a "dubious"
warning — excluded from differential scope (all harness entries are market
orders).

## 6. TrailingStrategy (lib) rejected; harness ratchet hand-written from §4.5 (2026-10-18)

`backtesting.lib.TrailingStrategy` trails `Close[t] − n_atr*ATR` (ATR
distance, `set_trailing_pct` documented INEXACT — converted to a fixed ATR
multiple) and, with plain `buy()`, holds no stop on the entry bar. It can
never match a `highest-high × (1−pct)` trail in value. The S5 harness
implements the ROADMAP §4.5 written rule by hand in `next()` (which runs
after the broker, giving §4.5's "ratchet AFTER the check" for free — probed:
level 72.5 derived from bar 2 (whose low was 50) did NOT fire on bar 2, fired
at bar 3): trail = highest high since entry up to t−1 times (1−pct),
up-only via `max`, stop pre-slipped (`×(1−slip)`) so fills equal nlbt's
slipped sell exactly. Never imported from nlbt.

## 7. Matched cost model — scheme validated bit-for-bit (2026-10-18)

nlbt: buy fill = `open*(1+slip)`, sell fill = `level/open*(1−slip)`, fee =
`shares*fill*fee_bps/1e4` on the slipped fill (ledger/execution source).
backtesting applies `spread` to ENTRY ONLY (source `_adjusted_price`) and
charges `|size|*price*rate` on the entry's adjusted price but the exit's RAW
fill. Matched scheme: `spread=0`; slippage enters through per-role Open
transforms (entry-fill bar `×(1+slip)`, signal-exit-fill bar `×(1−slip)`;
S5's stop level pre-slipped); float `commission=fee_bps/1e4` then lands on
the slipped fill on both sides = the same operands as nlbt's formula.
Probe (fee 10 bps, slip 5 bps, entry 100, exit 100, 10 shares): entry
**100.05**, exit **99.95**, all six equity rows
[10000, 10000, 9998.4995, 9998.4995, 9997.0, 9997.0] matched the §4.5 hand
formulas exactly. IEEE note: fee multiply/divide order differs by one
rounding between the engines (≤1e-13 relative) — inside the tolerance.

## 8. Known library offset — first `strategy.next()` runs at bar 1 (2026-10-18)

backtesting's run loop starts at bar 1 (`start = 1 + warmup`), so a bar-0
signal could fill one bar earlier in nlbt (which acts on any signal bar).
Every fixture's first signal is at bar ≥ 1 (S1: bar 1, S2/S3/S4: warmup
≥ 4, S5: bar 2), so this can never bite; recorded so future fixtures keep
the constraint.

## 9. Tolerance rule and deliberate-break canary (2026-10-18)

Owner rule (verbatim): exact equality on trade count, entry/exit timestamps,
exit reasons and share counts; prices and equity (every equity row) within
rel 1e-9 with an abs floor of 1e-6. Never widen a tolerance to make a test
pass: any exceedance must be explained with an exact cause or written to
docs/OPEN_QUESTIONS.md and reported to the owner.
`test_deliberate_break_is_detected` proves the comparator is not vacuously
green: a duplicated trade (count), a 1e-4 bumped exit price and a 5e-4
bumped equity row each raise, while the clean comparison passes. The
harness additionally caught three real bugs during development (exit-bar
sided rate, SL snapshot vs seed level, settlement commission missing from
the reconstruction — the last surfacing as an exact 1.25 = 10×125×0.001
mismatch), which is further evidence the comparison has teeth.

## 10. Scenario table and verdict (2026-10-18)

| # | Strategy | Rules (both sides) | Exit | Drain |
|---|----------|--------------------|------|-------|
| S1 | buy-and-hold | close > 100 | end_of_data (excluded, entry #3) | no (by definition) |
| S2 | SMA cross | fast(4) crosses_above/below slow(9) | signal | yes |
| S3 | RSI mean-reversion | rsi(14) < 30 / > 60 | signal | yes |
| S4 | Donchian breakout | close > prior-20 high / < prior-10 low | signal | yes |
| S5 | trailing stop 3% | close crosses_above 100; trail 3% | trailing_stop | yes |

Verdict: **all 10 scenario×pass comparisons pass** under the owner
tolerance (plus the canary = 11 tests green); trade lists, timestamps,
reasons, share counts and every equity row agree. Remaining known
divergences are exactly entries #3 (S1 settlement) and #8 (bar-1 start) —
both explained, both fixture-pinned out of the compared surface.

## 11. S6 fixed stop-loss added — intrabar touch AND gap-through (2026-10-18)

Owner gap: S3 had no stop and S5's trailing stop is a non-gap design, so the
FIXED `stop_loss_pct` path and the gap-through-stop rule were un-compared.
S6 (both passes): `stop_loss_pct = 5`, two trades — trade 1 exits via an
INTRABAR TOUCH (bar 7: open 98.0 above the stop ≈ 95.05 → fill at the slipped
LEVEL `entry_fill×0.95×(1−slip)`), trade 2 via a GAP down through the stop
(bar 12: open 90.0 below the stop ≈ 96.95 → fill at the slipped OPEN
`open×(1−slip)`). Same pre-slip method as S5: the harness sets
`trade.sl = entry_fill×0.95×(1−slip)`; the gap bar's Open is pre-slipped via
the per-role transform, so backtesting's `min(open', stop')` equals nlbt's
`resolve_exit_fill(open, level)×(1−slip)` exactly in BOTH branches. Owner
conditions honoured: entry-bar low clear of the stop asserted from the
ACTUAL fill of each pass and each side (no hard-coded prices); fixture
margins computed against the worst case (pass-2) thresholds — non-trigger
bars clear the RAW stop (the higher threshold), the touch bar pierces the
PRE-SLIPPED stop (the lower one), so the engines can never trigger on
different bars. Verdict: both passes agree within the owner tolerance; the
touch/gap fill formulas are additionally asserted with exact literals.

## 12. Engine deliberate-break — differential tests DO catch engine bugs (2026-10-18)

Owner condition: change one engine line, confirm a differential test fails,
revert. Change made: `src/nlbt/engine/execution.py`, `apply_slippage` sell
branch `(1.0 - bps / _BPS)` → `(1.0 + bps / _BPS)` (sign flip). Result:
`pytest tests/differential` → **6 FAILED, exit 1** — every pass-2 test
(S1–S6); pass-1 tests stayed green (slip = 0, so the bug is invisible
there) and the comparator canary stayed green (engine-independent).
Notably S1 failed through its EXCLUDED-settlement convention assertions
(`nlbt exit == close×(1−slip)`), so even the excluded trade's convention
pins carry detection power. Reverted; `git diff -- src/nlbt/engine/` = 0
diff lines; suite green again (13 passed). This complements entry #9's
canary: the canary proves the COMPARATOR detects corruption; this proves
the TESTS detect an ENGINE bug.

## 13. Fixtures are built in code, not loaded from a CSV (2026-10-18)

The approved plan mentioned a CSV fixture. These scenarios need ENGINEERED
events (exact single crossings, a designed trigger wick, a designed
gap-through bar, a wide last-bar settlement gap), so each scenario builds
its dated OHLC rows in code (`_s1_hold` … `_s6_stop_loss`; tz-aware UTC
daily index, deterministic, no I/O, reviewed line-by-line). A CSV would add
a file without adding information. Recorded here per the owner's request to
state the deviation.
