"""Application configuration — ROADMAP §3.5 environment variables.

Reads the eight §3.5 variables via pydantic-settings (verified API:
``pydantic_settings.BaseSettings``, pydantic-settings 2.15.0 — see
docs/verified_apis.md).

Rules honoured here:
- ``extra="forbid"``: unexpected constructor kwargs are rejected loudly. NOTE
  (verified against pydantic-settings 2.15.0, see OQ-0002): extra="forbid" does
  NOT extend to unknown *environment variables* — the env source collects values
  only for known fields, so ``NLBT_NOT_A_REAL_VAR=1`` is silently ignored. If
  loud detection of unknown NLBT_* env vars is wanted, it must be added
  explicitly (owner decision pending: OPEN_QUESTIONS.md OQ-0002).
- ``ANTHROPIC_API_KEY`` is NOT required at startup (P0-T4 accept criterion:
  "config fails fast on missing required vars *only when the LLM is actually
  used*"). The gate is :meth:`Config.validate_llm_ready`, which raises
  ``E_NL_LLM`` the moment an LLM call is attempted without a key.
- Singleton loaded once: :func:`get_config` builds ``Config()`` on first use and
  returns the same instance afterwards. Tests use :func:`reset_config` (a
  deliberate escape hatch, exported for the test-suite only).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nlbt.errors import NLLlmError

__all__ = ["Config", "get_config", "reset_config"]


class Config(BaseSettings):
    """The eight §3.5 environment variables with their roadmap defaults.

    Every field carries ``validation_alias=\"<ENV_VAR_NAME>\"`` so the env-var
    mapping is explicit rather than prefix-derived, and ``populate_by_name=True``
    so the same model can also be constructed with plain field-name kwargs
    (both paths verified empirically on pydantic-settings 2.15.0 — see
    docs/verified_apis.md).
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="forbid",  # unexpected kwargs: fail loudly (see OQ-0002 for env vars)
        env_ignore_empty=True,  # an empty shell var behaves like "unset"
        populate_by_name=True,  # allow field-name kwargs alongside validation aliases
        # No .env file on purpose: .env is a developer convenience for the shell,
        # not a config source the app may silently pick up (§3.5: "never commit .env").
    )

    # --- LLM -------------------------------------------------------------
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )  # optional until the LLM is used
    llm_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        validation_alias="NLBT_LLM_MODEL",
    )  # real ID but retired; see OQ-0001

    # --- Paths / behaviour ------------------------------------------------
    data_cache_dir: str = Field(
        default=".cache/nlbt",
        validation_alias="NLBT_DATA_CACHE_DIR",
    )
    db_path: str = Field(default="nlbt.db", validation_alias="NLBT_DB_PATH")
    log_level: str = Field(default="INFO", validation_alias="NLBT_LOG_LEVEL")

    # --- Guard rails (§3.5: E_LIMIT_EXCEEDED budget) ------------------------
    max_bars: int = Field(default=50_000, validation_alias="NLBT_MAX_BARS")
    max_sweep_combos: int = Field(
        default=10_000,
        validation_alias="NLBT_MAX_SWEEP_COMBOS",
    )

    # --- Mode ---------------------------------------------------------------
    # offline=True forces cache/CSV-only operation (§3.5).
    offline: bool = Field(default=False, validation_alias="NLBT_OFFLINE")

    def validate_llm_ready(self) -> None:
        """Raise ``E_NL_LLM`` if the LLM cannot be used (no API key).

        Call this immediately before the first LLM call — never at startup
        (P0-T4: config must not fail fast on a missing key).
        """
        if self.anthropic_api_key is None:
            raise NLLlmError(
                "ANTHROPIC_API_KEY is not set; the LLM layer cannot run",
                details={"env_var": "ANTHROPIC_API_KEY"},
                hint="Set ANTHROPIC_API_KEY in your environment (see .env.example)",
            )


_config: Config | None = None


def get_config() -> Config:
    """Return the process-wide Config, creating it once on first call."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """Drop the singleton so the next ``get_config()`` reloads the environment.

    Test-suite escape hatch (pydantic-settings caches os.environ at
    instantiation). Not part of the public engine API.
    """
    global _config
    _config = None
