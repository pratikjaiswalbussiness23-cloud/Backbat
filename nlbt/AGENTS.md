# AGENTS.md — rules for every coding agent working on nlbt

## Project in one line
Natural-language trading strategy → validated JSON spec → deterministic backtest engine → metrics. The LLM only translates; it never computes numbers or runs code.

## Read first
1. ROADMAP.md §2 (anti-hallucination), §4 (contracts), and the task text you were given.
2. docs/OPEN_QUESTIONS.md and docs/ADR/ for decisions already made.

## Non-negotiable rules
- Never assume a library API. Verify against the INSTALLED version (inspect/help/source) and record it in docs/verified_apis.md.
- Never invent expected values in tests. Hand-compute (show arithmetic in the docstring) or use an independent oracle.
- Never weaken, skip, delete or loosen a test to make it pass. Never regenerate golden files.
- Do not mock the code under test. Mock only network and LLM boundaries.
- No lookahead: decisions at bar t use data up to t only; fills happen at the next bar's open.
- No eval/exec/pickle on user-controlled data. No secrets in code or logs.
- No new dependency without an entry in docs/DEPENDENCIES.md.
- One task per change. Touch only the files the task lists. Search the repo before creating anything.
- If anything is ambiguous or a test seems wrong: STOP, write it in docs/OPEN_QUESTIONS.md, and ask.
- State plainly what you could not verify. Never fill gaps with plausible text.

## Commands
- `make all` runs lint, type-check and tests. Paste its real output in your report.
- `pytest -m lookahead` runs the no-lookahead defences.
- `nlbt eval-nl --replay` runs the NL eval on recorded LLM responses.

## Definition of done for a task
Acceptance criteria each marked PASS with evidence, `make all` green, verification report written (ROADMAP Appendix F), no unrelated changes.
