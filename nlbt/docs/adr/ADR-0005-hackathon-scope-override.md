# ADR-0005: Hackathon Scope Override — LLM Layer Before Milestone 1

## Status: Accepted (hackathon only, 2026-10-24)

## Context

ROADMAP.md (repo root) mandates strict phase ordering:

- ROADMAP.md:23 — "**Do not reorder phases.** Engine correctness (Phases 0–5) is built and proven *before* any LLM work (Phase 6). An LLM on top of a wrong engine just produces confident wrong answers faster."
- ROADMAP.md:410 — "## 5. Phase plan — Milestone 1: Deterministic core (Phases 0–5)"
- ROADMAP.md:609 (Phase 6 entry condition) — "> Start only after **Gate 5**. The LLM's job is narrow: **translate**. It has no tools other than the schema-forced output, no network, no code execution."

The hackathon deadline (submission Sat 31 Oct 2026) requires a demoable
plain-English → spec → backtest flow before Milestone 1 (Phases 0–5) is
formally complete. The demo needs the LLM translation layer visible end to end.

## Decision

Override the roadmap rule above **for this hackathon only**: a thin LLM layer
(Phase 6 subset) is built before Milestone 1 is finished. Completing
Milestone 1 properly remains the target afterwards; this override does not
change the roadmap for any later work.

- **Build order:** (a) OQ-0064 fix, (b) a MINIMAL Phase 5 (metrics, result
  object, CLI), (c) a thin LLM layer (Phase 6 subset), (d) UI. The LLM layer
  is not built before the result object exists.
- **Rationale:** the demo needs plain-English → spec translation; the LLM
  translates and never computes numbers (roadmap constraint C1, ROADMAP.md:28);
  all numbers stay in the deterministic engine.
- **Gate 4 still covers scenarios 1–12** (P4-T8 list, ROADMAP.md:556–567);
  **scenario 13 (short selling) stays gated and unbuilt** — the product is
  long-only and P4-T7 (ROADMAP.md:553) is not built. Gate 4/Gate 4a wording:
  ROADMAP.md:586–587.
- **Process:** the full Phase A/B process (failing test first,
  deliberate-break check, `mingw32-make all`, docs/OPEN_QUESTIONS.md, stop
  before commit) remains mandatory for **all engine and metrics changes**;
  only this ADR and later UI/README work use the lighter process.

## Consequences

- The demo can ship the full translate→validate→backtest story by Sat 31 Oct
  2026 while engine/metrics rigor is preserved by keeping the full process on
  those layers.
- Gate 4 is claimed only for scenarios 1–12 (long-only); the formal Gate 4
  report is deferred (see below).

## Deferred items (known limitations)

- OQ-0063 (trailing stop should be checked before take-profit)
- OQ-0067 (null metric without the §4.7 warning → Phase 5)
- OQ-0068 (`compare()`/`crosses_above()` on a scalar; not reachable via `run()`)
- OQ-0069 (lagged raw column error message)
- OQ-0070 (`volume=inf` accepted by the validator)
- P4-T7 shorts (gated; do not build)
- Formal Gate 4 report
- Per-file coverage targets (several files are 85–88% individually)
- Nightly property runs
