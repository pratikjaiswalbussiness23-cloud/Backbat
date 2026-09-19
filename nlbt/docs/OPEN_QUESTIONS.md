# OPEN_QUESTIONS.md

Per ROADMAP.md §2A (R7): if anything is ambiguous or a test seems wrong, STOP and log the question here instead of silently choosing an interpretation. An agent must never resolve a row's Status itself; the owner does.

| ID | Question | Raised by | Status |
|----|----------|-----------|--------|
| OQ-0001 | `NLBT_LLM_MODEL` default: the task mandates `claude-3-5-sonnet-20241022`. Verified via Anthropic's official model-deprecations page (platform.claude.com/docs/en/about-claude/model-deprecations, fetched 2026-09-19): the ID is real but **retired** from the first-party API. Keep as-is per task text, or switch default to a live model (e.g. a claude-sonnet-4.x ID)? Not decided silently because P6-T6 (live LLM calls) would fail at runtime with the retired default. | P0-T4 agent (Buffy) | Open |
| OQ-0002 | Should unknown `NLBT_*` env vars fail loudly? Empirically verified (2026-09-19, installed pydantic-settings 2.15.0, including installed source of `sources/providers/env.py`): `extra="forbid"` rejects unknown *constructor kwargs* only — unknown *environment variables* are silently ignored because the env source collects values for known fields. If loud detection is wanted, explicit env scanning must be added (small feature). Task says `extra="forbid"` without specifying env-var scope. | P0-T4 agent (Buffy) | Open |
