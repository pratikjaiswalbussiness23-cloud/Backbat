"""P6-T1 safe env-file parsing and OQ-0083 runtime key loading tests."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

from nlbt.config import load_nvidia_api_key

_HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "envfile.py"


def _load_helper() -> object:
    spec = importlib.util.spec_from_file_location("nlbt_envfile_helper", _HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bom_crlf_comments_blanks_and_double_quotes(tmp_path: Path) -> None:
    content = (
        '﻿# leading comment\r\n\r\nNVIDIA_API_KEY="nvapi-FAKE-VALUE-0001"\r\nOTHER_VAR=plain\r\n'
    )
    path = tmp_path / ".env"
    path.write_bytes(content.encode("utf-8"))
    helper = _load_helper()
    parsed = helper.read_env_file(path)  # type: ignore[attr-defined]
    assert parsed["NVIDIA_API_KEY"] == "nvapi-FAKE-VALUE-0001"
    assert parsed["OTHER_VAR"] == "plain"


def test_single_quotes_and_inner_equals(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "NVIDIA_API_KEY='nvapi-QUOTED'\nURL=https://example.test/v1?a=b=c\n",
        encoding="utf-8",
    )
    helper = _load_helper()
    parsed = helper.read_env_file(path)  # type: ignore[attr-defined]
    assert parsed["NVIDIA_API_KEY"] == "nvapi-QUOTED"
    assert parsed["URL"] == "https://example.test/v1?a=b=c"


def test_missing_key_returns_none(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("OTHER_VAR=1\n", encoding="utf-8")
    helper = _load_helper()
    assert helper.find_key(path) is None  # type: ignore[attr-defined]


def test_empty_value_returns_none(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text('NVIDIA_API_KEY=""\n', encoding="utf-8")
    helper = _load_helper()
    assert helper.find_key(path) is None  # type: ignore[attr-defined]


def test_lines_without_equals_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("just some text\nNVIDIA_API_KEY=nvapi-OK\n", encoding="utf-8")
    helper = _load_helper()
    assert helper.find_key(path) == "nvapi-OK"  # type: ignore[attr-defined]


def test_helper_never_imported_by_library_code() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    offenders = [
        str(p) for p in src.rglob("*.py") if "scripts.envfile" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_load_nvidia_key_from_envfile_without_exporting_or_logging(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    key_value = "not-a-real-secret-test-value"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\ufeff# comment\r\nOTHER=value=with=equals\r\n"
        'NVIDIA_API_KEY="not-a-real-secret-test-value"  \r\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    caplog.set_level(logging.DEBUG)

    loaded = load_nvidia_api_key(env_file)

    assert loaded == key_value
    assert "NVIDIA_API_KEY" not in os.environ
    assert key_value not in caplog.text


def test_load_nvidia_key_prefers_environment_and_empty_file_value_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "environment-test-value")
    assert load_nvidia_api_key(tmp_path / ".env") == "environment-test-value"
    monkeypatch.delenv("NVIDIA_API_KEY")

    empty = tmp_path / "empty.env"
    empty.write_text('# none\nNVIDIA_API_KEY=""\n', encoding="utf-8")
    assert load_nvidia_api_key(empty) is None
