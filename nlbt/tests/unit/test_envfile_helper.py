"""P6-T1: the tiny .env reader used by the step-2 probe and the recorder.

Owner authorization (2026-10-25, "source .env for the probe"): the probe and
``scripts/record_llm_fixture.py`` may load ``NVIDIA_API_KEY`` from the
gitignored ``nlbt/.env`` through ONE small helper -- this file covers it with
FAKE temp files only. The helper must never be imported by library code
(``src/nlbt``) and never by a test that hits the network (the network tests
use a stubbed transport or the env var directly). The helper is loaded from
its file path because ``scripts/`` is not a package.

Parsing contract under test (verbatim from the authorization):
utf-8-sig (BOM tolerated), strip ``\\r`` and surrounding whitespace per line,
ignore blank lines and ``#`` comments, split on the FIRST ``=``, strip
surrounding quotes from the value, and treat a missing or empty key as absent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "envfile.py"


def _load_helper() -> object:
    spec = importlib.util.spec_from_file_location("nlbt_envfile_helper", _HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bom_crlf_comments_blanks_and_double_quotes(tmp_path: Path) -> None:
    """BOM + CRLF + comments + blanks are tolerated; double quotes stripped."""
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
    """Single quotes stripped; only the FIRST ``=`` splits name from value."""
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
    """A file without the entry yields None (probe prints KEY MISSING)."""
    path = tmp_path / ".env"
    path.write_text("OTHER_VAR=1\n", encoding="utf-8")

    helper = _load_helper()

    assert helper.find_key(path) is None  # type: ignore[attr-defined]


def test_empty_value_returns_none(tmp_path: Path) -> None:
    """An empty value behaves exactly like a missing one (env_ignore_empty)."""
    path = tmp_path / ".env"
    path.write_text('NVIDIA_API_KEY=""\n', encoding="utf-8")

    helper = _load_helper()

    assert helper.find_key(path) is None  # type: ignore[attr-defined]


def test_lines_without_equals_are_ignored(tmp_path: Path) -> None:
    """Garbage lines (no ``=``) are skipped instead of raising."""
    path = tmp_path / ".env"
    path.write_text("just some text\nNVIDIA_API_KEY=nvapi-OK\n", encoding="utf-8")

    helper = _load_helper()

    assert helper.find_key(path) == "nvapi-OK"  # type: ignore[attr-defined]


def test_helper_never_imported_by_library_code() -> None:
    """Guard: the loader is dev tooling -- nothing under src/ references it."""
    src = Path(__file__).resolve().parents[2] / "src"
    offenders = [str(p) for p in src.rglob("*.py") if "envfile" in p.read_text(encoding="utf-8")]
    assert offenders == []
