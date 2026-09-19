# DEPENDENCIES.md

Per ROADMAP.md §2A (R12): no new dependency without an entry here (purpose, license, maintenance status, alternatives considered). The provisional register in docs/adr/ADR-0001 moves here as packages are added.

| Package | Version | Purpose | License | Alternatives considered |
|---------|---------|---------|---------|-------------------------|
| pydantic-settings | 2.15.0 (locked in uv.lock) | P0-T4: read §3.5 env vars via `BaseSettings` (task-mandated) | MIT (pydantic-settings is MIT, same stack as pydantic; license classifier absent from installed dist metadata — flagged in verification report) | python-dotenv + os.environ by hand (rejected: re-implements validation); dynaconf (rejected: heavier, new config paradigm); stdlib `getenv` + manual coercion (rejected: loses typed validation, bool/int parsing, extra=forbid) |
| pydantic | 2.13.5 (locked) | Validation models (later phases); dependency of pydantic-settings | MIT | attrs+cattrs (rejected: no JSON-schema generation needed for S2); msgspec (rejected: less ecosystem fit for spec models) |
| pandas-stubs | 2.3.3.260113 (locked, dev-only) | P1-T1/T2: mypy strict mode cannot check pandas without stubs (`import-untyped`; subclassing `DataFrame` errors under strict). Added by the P1 agent — see OQ-0004 | BSD-3-Clause (mirrors pandas) | `# type: ignore` per import (rejected: blanket suppression, hides real type errors); `mypy --ignore-missing-imports` (rejected: disables checking of the whole data layer) |
