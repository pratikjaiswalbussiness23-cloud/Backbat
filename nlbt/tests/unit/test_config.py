"""Tests for §3.5 configuration (nlbt.config).

Independent acceptance checks (P0-T4):
- Config loads with NO env vars set → roadmap defaults
- ``NLBT_OFFLINE=true`` loads as bool ``True``
- ``validate_llm_ready()`` raises ``E_NL_LLM`` when the key is missing
- ``validate_llm_ready()`` passes when the key is set
- ``NLBT_MAX_BARS`` loads as ``int``, not ``str``

All tests isolate the environment via ``monkeypatch.delenv/setenv`` and reset
the singleton through the public ``reset_config()`` hook.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nlbt.config import Config, get_config, reset_config
from nlbt.errors import NLLlmError

ALL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "NLBT_LLM_MODEL",
    "NLBT_DATA_CACHE_DIR",
    "NLBT_DB_PATH",
    "NLBT_LOG_LEVEL",
    "NLBT_MAX_BARS",
    "NLBT_MAX_SWEEP_COMBOS",
    "NLBT_OFFLINE",
)


@pytest.fixture(autouse=True)
def _clean_env_and_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with none of the §3.5 vars set and no cached config."""
    for var in ALL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    reset_config()
    yield
    reset_config()


def test_defaults_with_no_env_vars_set() -> None:
    """No §3.5 var set → every field equals the ROADMAP §3.5/task default."""
    cfg = Config()
    assert cfg.anthropic_api_key is None
    assert cfg.llm_model == "claude-3-5-sonnet-20241022"
    assert cfg.data_cache_dir == ".cache/nlbt"
    assert cfg.db_path == "nlbt.db"
    assert cfg.log_level == "INFO"
    assert cfg.max_bars == 50_000
    assert cfg.max_sweep_combos == 10_000
    assert cfg.offline is False


def test_offline_string_true_loads_as_bool() -> None:
    """``NLBT_OFFLINE=true`` must become Python ``True`` (pydantic bool coercion)."""
    cfg = Config(_env_file=None, offline="true")  # pydantic-settings accepts kwargs too
    assert cfg.offline is True
    assert isinstance(cfg.offline, bool)


def test_offline_false_string_loads_as_bool_false() -> None:
    cfg = Config(_env_file=None, offline="false")
    assert cfg.offline is False


def test_offline_via_actual_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same bool check through the real NLBT_OFFLINE env-var path."""
    monkeypatch.setenv("NLBT_OFFLINE", "true")
    cfg = Config(_env_file=None)
    assert cfg.offline is True
    assert isinstance(cfg.offline, bool)


def test_max_bars_loads_as_int_not_str() -> None:
    """``NLBT_MAX_BARS=50000`` must arrive as ``int`` (task requirement)."""
    cfg = Config(_env_file=None, max_bars="12345")
    assert cfg.max_bars == 12345
    assert isinstance(cfg.max_bars, int)
    assert not isinstance(cfg.max_bars, bool)


def test_max_bars_via_actual_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same check through the real env-var path (not just kwargs)."""
    monkeypatch.setenv("NLBT_MAX_BARS", "777")
    cfg = Config(_env_file=None)
    assert cfg.max_bars == 777
    assert isinstance(cfg.max_bars, int)


def test_validate_llm_ready_raises_when_key_missing() -> None:
    """No ANTHROPIC_API_KEY → E_NL_LLM from validate_llm_ready()."""
    cfg = Config(_env_file=None)
    with pytest.raises(NLLlmError) as excinfo:
        cfg.validate_llm_ready()
    assert excinfo.value.code == "E_NL_LLM"
    assert excinfo.value.details["env_var"] == "ANTHROPIC_API_KEY"


def test_validate_llm_ready_passes_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A present (fake) key passes the gate — startup itself never demands it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real")
    cfg = Config(_env_file=None)
    cfg.validate_llm_ready()  # must not raise


def test_api_key_optional_at_startup() -> None:
    """P0-T4: config must load fine with no key — no exception at all."""
    Config(_env_file=None)  # must not raise


def test_extra_forbid_rejects_unknown_init_kwarg() -> None:
    """extra=forbid: unexpected constructor kwargs are a config mistake → loud error."""
    with pytest.raises(ValidationError) as excinfo:
        Config(_env_file=None, not_a_real_var="1")
    assert "not_a_real_var" in str(excinfo.value).lower()


def test_unknown_env_var_is_ignored_library_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Documents VERIFIED pydantic-settings 2.15.0 semantics (OQ-0003).

    Empirically probed (2026-09-19, pydantic-settings 2.15.0): with
    extra="forbid", an unknown NLBT_* env var does NOT raise — the env source
    gathers values only for known fields, so it is silently ignored. This test
    pins that observed behavior; if the owner decides unknown env vars must
    fail loudly (OPEN_QUESTIONS OQ-0002), this test is meant to FAIL and force
    the explicit scanning feature.
    """
    monkeypatch.setenv("NLBT_NOT_A_REAL_VAR", "1")
    cfg = Config(_env_file=None)  # must NOT raise on 2.15.0
    assert cfg.log_level == "INFO"


def test_empty_env_var_behaves_like_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``NLBT_MAX_BARS=""`` must not crash int parsing (env_ignore_empty=True)."""
    monkeypatch.setenv("NLBT_MAX_BARS", "")
    cfg = Config(_env_file=None)
    assert cfg.max_bars == 50_000


def test_singleton_returns_same_instance() -> None:
    """get_config() is load-once: two calls, one instance (task requirement)."""
    first = get_config()
    second = get_config()
    assert first is second


def test_reset_config_forces_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    """After reset + env change, get_config() reflects the new environment."""
    monkeypatch.setenv("NLBT_LOG_LEVEL", "DEBUG")
    debug_cfg = get_config()
    assert debug_cfg.log_level == "DEBUG"
    monkeypatch.setenv("NLBT_LOG_LEVEL", "WARNING")
    reset_config()
    assert get_config().log_level == "WARNING"
