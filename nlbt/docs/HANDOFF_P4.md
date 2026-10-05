# nlbt — Handoff Brief (start here)

**Written 2026-10-05. Every number below was produced by running the commands shown, not
inherited from notes.** Re-run them before trusting this file.

---

## 0. What this project is

A **natural-language trading strategy backtester**. You describe a strategy in plain
English; nlbt converts it to a validated JSON spec, shows you in plain English exactly
what will run, backtests it deterministically, and reports metrics with data-quality
and robustness diagnostics.

It produces **historical simulations, not predictions**. Not financial advice.

## 1. Read these first, in this order

1. `AGENTS.md` (repo root) — the non-negotiable rules. **R5 especially.**
2. `ROADMAP.md` §0.3 (principles), §2 (anti-hallucination), §4 (contracts).
3. `docs/OPEN_QUESTIONS.md` — **56 open rows.** See §6.
4. `docs/adr/` — decisions already made. Do not relitigate.
5. `docs/verified_apis.md` — probed behaviour of every third-party API used.

## 2. Verified current state

Run the gate before and after any change:

```bash
cd nlbt
mingw32-make all      # NOTE: plain `make` is NOT installed on this Windows box
```

| Check | Result | Exit |
|---|---|---|
| `ruff check src tests` | All checks passed | 0 |
| `ruff format --check src tests` | clean | 0 |
| `mypy` (strict, `files = ["src"]`) | Success, 35 source files | 0 |
| `pytest` | **702 passed, 15 skipped, 3 deselected** | 0 |
| **`mingw32-make all`** | **`== make all: PASSED ==`** | **0** |

- Coverage (with engine tests enabled): **92.5%** — 2142 statements, 115 missed.
- Scale: ~6,740 lines `src/`, ~11,785 lines `tests/`, 33 commits.

## 3. What is built

| Phase | Status |
|---|---|
| **P0** scaffold, config, logging, errors, import boundaries | done |
| **P1** data: providers (yfinance/CSV), parquet cache + hash verify, quality checks, frequency inference | done |
| **P2** indicators: registry + **12 indicators** (sma, ema, rsi, roc, macd, bbands, atr, stoch, adx, highest, lowest, obv) + truncation property tests | done |
| **P3** spec: pydantic models, semantic validator, JSON-schema export w/ staleness gate, canonical JSON + hashing, English renderer, defaults registry | done |
| **P4** engine: `ledger`, `signals`, `execution`, `sizing`, `risk`, `backtest` | **T1–T6 done; T7–T12 outstanding** |
| **P5–P10** metrics, CLI, LLM layer, API/UI, robustness, production | **not started** |

The engine shipped in `97dd1de`. The two test defects that kept the suite red were
owner-ratified fixes in `eff2b45`, after which the six `--ignore`d engine test files were
re-enabled in the Makefile.

## 4. The rules that will get you fired if you break them

From `AGENTS.md` / `ROADMAP.md` §0.3:

- **C1** The LLM never computes numbers, never simulates trades, never emits executed code. It only translates English → JSON.
- **C2** Determinism: same spec + same data + same code version ⇒ byte-identical result.
- **C3** Every number the user sees is produced by tested code, traceable to a run manifest.
- **C4** Fail loudly. Unknown/unsupported/ambiguous ⇒ error or clarifying question. Never a silent guess.
- **C5** Assume the backtest is lying until tests and diagnostics show otherwise.
- **C7** Single source of truth — the indicator registry generates the schema, the prompt, the docs and the validator, so they cannot drift.

Hard operational rules:

- **R5 — never edit a test to make it pass.** Two exceptions were explicitly authorized by the owner (OQ-0056, OQ-0057). That is *not* a general licence.
- **No lookahead.** Decisions at bar `t` use data ≤ `t`; fills happen at the **next bar's open**.
- Never invent expected values. Hand-compute (show the arithmetic in the docstring) or use an independent oracle.
- No `eval`/`exec`/`pickle` on user-controlled data. No secrets in code or logs.
- If something is ambiguous or a test looks wrong: **STOP**, write it in `docs/OPEN_QUESTIONS.md`, ask. Do not resolve an OQ's Status yourself — the owner does.
- State plainly what you could not verify. Never fill gaps with plausible text.

## 5. Immediate next actions, in priority order

### 5.1 Un-skip the 14 stale invariant tests — **highest value, lowest risk**

`tests/unit/test_engine_scenarios.py` still carries **14 tests** marked
`@pytest.mark.skip(reason="Awaiting engine implementation")`. The engine now ships, so
the reason is stale and those §8.3 invariants are **unverified in the gate**.

**I probed this (2026-10-05, temporary copy, since removed — no repo file was edited):**

- **12 of 14 passed** against the real engine, first try.
- **2 failed** (`test_i4_no_entry_before_warmup`, `test_i12_price_scaling_leaves_timing_unchanged`)
  — and both failed on a **test-helper bug, not an engine bug**: the `_sma_spec()` helper
  calls `_spec(..., with_exit=False, ...)` but `_spec()` (line 113) has no `with_exit`
  parameter — it is `exit_long`. `TypeError: _spec() got an unexpected keyword argument 'with_exit'`.
- After stripping that one bogus kwarg in the probe, **14 passed**.

So the engine satisfies the §8.3 invariants; the gate just isn't proving it. Fixing this
needs owner authorization (R5) because it edits tests. Proposed change: drop the 14 stale
skip markers and correct the `with_exit` → `exit_long` kwarg in `_sma_spec`.

### 5.2 Finish P4 — Gate 4 checklist (all currently unticked)

- **P4-T7 short selling** — gated behind **Gate 4a: owner confirms long-only results are trusted.** Ask before starting; this is an owner sign-off, not a coding decision.
- **P4-T9** property tests for engine invariants (hypothesis, marker `property`; ≥1,000 examples nightly, 100 in PR CI). *Currently no engine property tests exist* — only the P2-T7 indicator ones. **Trap:** the `property` marker is **not yet registered** in `pyproject.toml`, and `addopts` sets `--strict-markers`, so using `@pytest.mark.property` before registering it is a hard error. This is exactly the OQ-0007 trap; register it in `[tool.pytest.ini_options] markers` as part of the same task.
- **P4-T10** lookahead defences (marker `lookahead`): truncation + future-poison on the **engine**, not just indicators. **Canary must go red.**
- **P4-T11** differential testing against an independent implementation.
- **P4-T12** determinism and performance.

### 5.3 Then P5 (metrics, CLI, charts) — this completes milestone **M1 Deterministic core**

Per `ROADMAP.md`, do **not** start P6 (the LLM layer) until M1 is signed off. "An LLM on
top of a wrong engine just produces confident wrong answers faster."

### 5.4 Also worth doing

`docs/OPEN_QUESTIONS.md` has **56 Open** rows (2 now Resolved). Many already carry an
implemented resolution marked *"needs owner confirmation"* — batching those for owner
sign-off would unblock a lot of settled work. Notable:
- **OQ-0001** — the mandated default `NLBT_LLM_MODEL` is a **retired** Anthropic model ID; P6-T6 would fail at runtime. Must be resolved before P6.
- **OQ-0059** — the builder's insufficient-cash strategy choice (reduce-when-affordable) needs owner ratification.
- **OQ-0058** — `return_pct` / `mae_pct` / `mfe_pct` implemented as **ratios**, not 0–100. One multiplication each if the owner prefers the other convention.

## 6. Known gaps and traps

- **`make` does not exist on this machine.** Use `mingw32-make`. If your environment has GNU make, `make all` is equivalent.
- `pyproject.toml` `addopts` already includes `-q`, so `pytest -q` runs as `-qq` and **suppresses the final `N passed` line**. Use a single `-q` or none when you need counts.
- `pandas-ta` is **uninstallable** here (pins `numba==0.61.2` → `numpy<2.3`, while the project needs `numpy>=2.5`). The oracle library in use is `ta==0.11.0` (OQ-0015). Don't "fix" this by downgrading numpy.
- `mypy` strict runs **without** the pydantic mypy plugin, which is why the codebase uses `model_config = ConfigDict(...)` rather than class-kwargs `extra="forbid"` (OQ-0013).
- Test-order fragility: `tests/unit/test_indicator_registry.py` leaks a `dummy_global_path` into the **global** registry with no cleanup (OQ-0032), which can make doc-generation tests fail only in a full-suite run.

## 7. Definition of done (per `AGENTS.md`)

Acceptance criteria each marked PASS **with evidence**, `mingw32-make all` green,
verification report written, **no unrelated changes**. One task per change; touch only the
files the task lists; search the repo before creating anything.
