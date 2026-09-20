# DEPENDENCIES.md

Per ROADMAP.md §2A (R12): no new dependency without an entry here (purpose, license, maintenance status, alternatives considered). The provisional register in docs/adr/ADR-0001 moves here as packages are added.

| Package | Version | Purpose | License | Alternatives considered |
|---------|---------|---------|---------|-------------------------|
| pydantic-settings | 2.15.0 (locked in uv.lock) | P0-T4: read §3.5 env vars via `BaseSettings` (task-mandated) | MIT (pydantic-settings is MIT, same stack as pydantic; license classifier absent from installed dist metadata — flagged in verification report) | python-dotenv + os.environ by hand (rejected: re-implements validation); dynaconf (rejected: heavier, new config paradigm); stdlib `getenv` + manual coercion (rejected: loses typed validation, bool/int parsing, extra=forbid) |
| pydantic | 2.13.5 (locked) | Validation models (later phases); dependency of pydantic-settings | MIT | attrs+cattrs (rejected: no JSON-schema generation needed for S2); msgspec (rejected: less ecosystem fit for spec models) |
| pandas-stubs | 2.3.3.260113 (locked, dev-only) | P1-T1/T2: mypy strict mode cannot check pandas without stubs (`import-untyped`; subclassing `DataFrame` errors under strict). Added by the P1 agent — see OQ-0004 | BSD-3-Clause (mirrors pandas) | `# type: ignore` per import (rejected: blanket suppression, hides real type errors); `mypy --ignore-missing-imports` (rejected: disables checking of the whole data layer) |
| yfinance | 1.7.0 (locked) | P1-T3: Yahoo Finance bars provider behind the DataProvider protocol. **Unofficial API** — may break without notice; unit tests never touch the network (recorded responses), the single network-marked test is excluded by default | Apache-2.0 (verified from installed dist metadata) | direct `requests` calls to Yahoo endpoints (rejected: re-implements scraping/rate-limit/cookie handling that yfinance maintains); Alpha Vantage / Polygon SDKs (not applicable: task mandates Yahoo data; both need API keys) |
| pyarrow | 25.0.1 (locked) | P1-T4: parquet engine for the bar cache (`DataFrame.to_parquet`/`read_parquet`). Already a `[project]` dependency since ADR-0001 — no new dependency added | Apache-2.0 (verified from installed dist metadata) | fastparquet (rejected: less maintained, pandas `engine='auto'` already prefers pyarrow); pickle files (FORBIDDEN: AGENTS.md bans pickle; not portable/schema-safe); plain CSV cache (rejected: lossy dtypes, slower) |

P1-T6 (frequency.py): **no new dependency** — uses pandas 3.0.6 and pydantic 2.13.5, both registered above (APIs probed in verified_apis.md).

P2-T1 (indicators/registry.py): **no new dependency** — pandas 3.0.6, numpy 2.5.3 and pydantic 2.13.5, all registered above; versions probed 2026-09-20 and recorded in verified_apis.md. The `indicators` package intentionally imports no network/LLM modules (import-boundary test P0-T3 applies).
