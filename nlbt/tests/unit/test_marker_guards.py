"""P0-T2 guard: network/llm_live markers are real and deselected by default.

ROADMAP P0-T2: "`network` and `llm_live` tests excluded by default."

This module proves the mechanism, not just the config text:
- A plain `pytest` (default addopts, no -m override): network/llm_live-marked
  tests are DESELECTED, so a developer's default run never touches the
  network or an LLM.
- `pytest -m network`: the very same tests ARE collected — proving exclusion
  is marker-driven, not an accident of collection.
"""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = PROJECT_ROOT / "tests" / "unit" / "test_marker_guards.py"


@pytest.mark.network
def test_network_marked_marker() -> None:
    """Body never runs in the default suite; see the selection test below."""
    assert True


@pytest.mark.network
@pytest.mark.llm_live
def test_llm_live_marked_marker() -> None:
    """Body never runs in the default suite; see the selection test below."""
    assert True


def _collect(marker: str | None) -> tuple[int, str]:
    """Collect THIS file with the given marker override (None = default).

    No -q: quiet collect output shows only per-file counts, not test names.
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(THIS_FILE),
        "--collect-only",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]
    if marker is not None:
        cmd += ["-m", marker]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def test_default_run_deselects_network_and_llm() -> None:
    """Plain pytest (no -m) must deselect both marked tests."""
    code, out = _collect(None)
    assert code == 0, out
    assert "test_network_marked_marker" not in out
    assert "test_llm_live_marked_marker" not in out
    assert "2 deselected" in out


def test_explicit_selection_finds_marked_tests() -> None:
    """pytest -m network still finds the marked tests: the marker exists."""
    code, out = _collect("network")
    assert code == 0, out
    assert "test_network_marked_marker" in out
    assert "test_llm_live_marked_marker" in out
