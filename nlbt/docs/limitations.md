# Known limitations

Historical simulation only; not investment advice.

This page is an honest inventory of what nlbt **does not** do (or does
imperfectly today). Every item is tracked in
[`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md) or
[`adr/ADR-0005-hackathon-scope-override.md`](adr/ADR-0005-hackathon-scope-override.md);
nothing here is hidden, and the owner still has to sign this page (Gate 10).

## Engine behaviour

### OQ-0063 — take-profit is checked before the trailing stop on a shared bar

When a bar can trigger **both** a take-profit and a trailing stop,
`RiskManager` currently evaluates take-profit first. If the trailing stop was
the tighter (more likely) exit, the realized outcome is optimistic: the trade
is credited with the better fill. The decision recorded in OPEN_QUESTIONS.md
is to check the **trailing stop first** (pessimistic); that fix is scheduled,
and the current behaviour is deliberately flagged here rather than silently
kept. Long-only v1 with both exits active on one bar is the only affected
configuration.

### OQ-0068 — `compare()` / `crosses_above()` crash on a scalar operand

The operand helpers in the signal layer do not guard scalar-vs-array inputs.
This is **not reachable through `nlbt run` / `run_confirmed()`** (the spec
validator ensures indicator/column operands), but direct library use of the
helper API is brittle.

### OQ-0069 — misleading error for a lagged raw column

Referencing a raw column with a lag, e.g. `{"name": "close", "lag": 1}`,
produces an error message whose path/term wording can be confusing. The
rejection itself is correct; only the message needs work.

### OQ-0070 — `volume=inf` is accepted by the validator

`validate_bars_shape` rejects ±inf **OHLC** prices (OQ-0066 fix), but
`volume=inf` still passes. An infinite volume would propagate through volume
indicators (OBV and any future VWAP/MFI) and violate the "no inf in outputs"
invariant (I13) downstream. Use finite volumes.

### OQ-0071 — Sortino ratio is not implemented

ROADMAP §4.7 specifies only the downside-deviation formula, with no ratio form
or target definition, so Sortino was ruled OUT of P5-T1. Sharpe (with `rf`
always displayed) and Calmar are the risk-adjusted metrics available today.

## Determinism & artifacts

### OQ-0075 — data hash is byte-sensitive to future `pyarrow` upgrades

`manifest.data_hash` is the sha256 of the validated bars' **parquet bytes**.
Byte-stability is tied to the pinned `pyarrow>=25,<26` range: a future
`pyarrow` major upgrade could serialize identical data differently and change
the hash (the same caveat as the data cache content hash).

### P5-T4b — `nlbt replay` and parquet artifact persistence are deferred

`result.json` (manifest, metrics, warnings, data-quality report) is persisted
per run under `runs/<run_id>/`. `equity.parquet` / `trades.parquet` and the
`nlbt replay <run_id>` command are **not built** yet. The replay error codes
are pre-ruled: data-hash mismatch → `E_DATA_QUALITY`; metrics mismatch on
identical data → `E_ENGINE_INVARIANT`.

## Data & CLI

### OQ-0078 — partial `--data-csv` coverage is silent

`CSVProvider.get_bars` raises `E_DATA_QUALITY` only when **zero** rows fall
inside the spec period. If the CSV covers just **part** of `spec.period`, the
overlapping slice is returned silently and the backtest runs on fewer bars
than requested, with no warning. The owner ruled this as-is for CLI v0;
surfacing a "data covers only X of the requested period" warning is deferred.

### OQ-0079 — `nlbt validate-data SYMBOL` is deferred

The data-validation subcommand from ROADMAP.md is not built in v0 (only
`run`, `ask`, `validate-spec`, `render-spec` exist). The underlying
validation logic (`nlbt.data.validate`, `nlbt.data.quality`) already exists
and is exercised by the test suite.

### OQ-0080 — two definitions of the result payload must stay in sync

`nlbt run --json` serializes through `results/store.build_result_payload()`
+ `render_result_json()`, while `execute_run()` still assembles its own
equivalent dict inline (the Phase B ruling forbade touching `execute_run`).
The key sets are identical today and pinned by
`tests/unit/test_results_roundtrip.py`, but they must be kept in sync until
someone consolidates `execute_run` onto the builder.

## LLM layer

### OQ-0082 — free-tier NVIDIA NIM rate limits and model account-gating

A live probe (2026-10-25) found that most listed models are usable but some
are **account-gated** (HTTP 404 for 5 of 6 Nemotron candidates), and the real
rate limit is unverified (community reports suggest ~40 requests/minute; no
429 was observed in the probe). Consequences:

- the model id comes from `NLBT_LLM_MODEL` and is never hard-coded;
- when the endpoint is unreachable, `NLBT_LLM_DEMO=1` replays **recorded,
  fingerprint-matched** responses via `RecordedClient`, clearly labelled
  (`[nlbt][DEMO]` on stderr, `llm_source="recorded-demo"`);
- a recording miss is a loud `E_NL_LLM`, never a silent fallback.

See also [`demo_script.md`](demo_script.md) for the offline demo setup.

### Related smaller open items (see `OPEN_QUESTIONS.md` for the full list)

- **OQ-0001:** the `NLBT_LLM_MODEL` *default* is the retired
  `claude-3-5-sonnet-20241022` id (mandated by the original task text); a
  working NIM model id must be supplied via `NLBT_LLM_MODEL`.
- **OQ-0085:** the NL input cap is 4,000 characters (`E_LIMIT_EXCEEDED`).
- **OQ-0089:** the "stop mentioned without a number" must-ask gate is a
  deterministic keyword heuristic and can produce false positives.
- **OQ-0092:** `E_NL_UNCONFIRMED` is a service-local error code, not yet in
  the §4.8 taxonomy.

## Product scope cut for the hackathon (ADR-0005)

ADR-0005 overrode the roadmap ordering for the hackathon **only**: the LLM
translation layer and a minimal Phase 5 were built before Milestone 1 was
formally complete, while the full process (failing test first,
deliberate-break check, `mingw32-make all`, stop before commit) remains
mandatory for every engine/metrics change. The following are **out of scope
for v1** and gated/unbuilt:

- **Long-only v1.** Short selling (P4-T7: borrow cost, margin, symmetric
  stops, `entry_short`/`exit_short`) is gated behind **Gate 4a** ("owner
  confirms long-only results are trusted") and is **not built**.
- **Daily bars only** (`interval="1d"`); no intraday intervals.
- **One symbol per run** (`universe.symbols` has exactly one entry).
- **No FastAPI/SQLite server** (P7-T2/T3) — v1 ships the CLI and the local
  Streamlit UI only.
- **No Phase 8 robustness suite** (train/test split, walk-forward, parameter
  sensitivity, Monte Carlo, cost sensitivity, random-entry baseline) and **no
  Phase 9 narrative generator**.
- Also deferred from ADR-0005's list: the formal Gate 4 report, per-file
  coverage targets (a few files sit at 85–88 % individually; overall is
  88.3 %), and nightly property runs.
- Not in v1 by ROADMAP scope (§1.2, never to be built as part of this
  project): live trading / broker connections, investment advice, LLM
  trading decisions or generated executable strategy code, options, futures
  rolls, fundamentals, sentiment, ML price models, tick-level simulation.

## What "reproducible" does and does not mean

Same spec + same data + same code version ⇒ byte-identical `result.json`.
This covers the engine, metrics, benchmark and manifest. It does **not**
cover: live yfinance data (the remote API can change history — use
`--data-csv` or the parquet cache for reproducible runs), live LLM output
(use `RecordedClient` / `NLBT_LLM_DEMO=1`), or the parquet-byte caveat in
OQ-0075 across dependency upgrades.
