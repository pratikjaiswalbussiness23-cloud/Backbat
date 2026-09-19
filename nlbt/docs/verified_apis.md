# verified_apis.md

Per ROADMAP.md §2A (R1): never assume a third-party API exists. Before using any function/class from a library, verify it against the INSTALLED version (inspect.signature, help(), installed source, or official docs) and record it here with the package version.

| Package | Version | Function/Class | Verified via | Notes |
|---------|---------|----------------|--------------|-------|
| pydantic-settings | 2.15.0 | `pydantic_settings.BaseSettings` | `uv run python -c "from pydantic_settings import BaseSettings; print(BaseSettings.__module__)"` → `pydantic_settings.main` | P0-T4 mandated pre-check. Correct import path for v2; NOT `pydantic.BaseSettings` (removed in pydantic v2) |
| pydantic-settings | 2.15.0 | `pydantic_settings.SettingsConfigDict` | import + `SettingsConfigDict.__annotations__` | Supports `env_prefix`, `extra`, `env_ignore_empty`; keys confirmed on installed version |
| pydantic-settings | 2.15.0 | `BaseSettings` + `Field(validation_alias="ENV_NAME")` | behavior probe: env set → value picked up; unset → default; empty string → default kept with `env_ignore_empty=True` | `pydantic_settings.EnvNameAlias` does NOT exist in 2.15.0 (ImportError); plain str `validation_alias` is the correct mechanism. Field names stay snake_case (`anthropic_api_key` ← `ANTHROPIC_API_KEY`). Without an explicit alias + `env_prefix=""`, env vars are matched by FIELD name only — bare `offline`/`max_bars`, never `NLBT_OFFLINE`/`NLBT_MAX_BARS` (caught by the env-path tests) |
| pydantic-settings | 2.15.0 | `extra="forbid"` semantics | empirical probe + installed source `sources/providers/env.py` | Rejects unknown *constructor kwargs*. Does NOT flag unknown *env vars* (env source is field-driven) — recorded as OQ-0002 |
| pydantic | 2.13.5 | `pydantic.__version__` | `uv run python -c "import pydantic; print(pydantic.__version__)"` | P0-T4 mandated pre-check |
| pydantic | 2.13.5 | `BaseModel.model_config` dict style (`extra="forbid"`) | probe: class with dict `model_config` instantiates | Not used in P0-T4 (errors are plain exceptions); verified for later spec models (P3) |
| stdlib logging | CPython 3.14.4 | `logging.Filter` / `logging.StreamHandler.setStream` | `inspect.signature(logging.Filter.__init__)` → `(self, name='')`; `hasattr(StreamHandler, 'setStream')` → True | Filter signature stable; setStream used to capture output in tests |
| pydantic-settings | 2.15.0 | `SettingsConfigDict(populate_by_name=True)` | behavior probe: `M(_env_file=None, offline="false", max_bars="5")` constructs via field-name kwargs while `validation_alias` still drives env lookup | Required so tests/CLI can construct `Config` with snake_case kwargs; without it, alias-only models reject field-name kwargs |
