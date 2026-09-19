"""P0-T3: import-boundary test (ROADMAP §3.2 module boundaries, Gate 0).

The architecture contract, enforced:

  1. If/when the ``nlbt.engine`` package exists, it must NOT import:
       - the ``nlbt.nl`` package (natural-language / LLM layer),
       - any LLM SDK (``anthropic``, ``openai``, ``google.generativeai``,
         ``litellm``, ``cohere``, ``mistralai``) or any network library
         (``requests``, ``httpx``, ``aiohttp``, ``urllib3``, ``socket``).

  2. ``nlbt.nl`` must be the ONLY package that imports an LLM SDK.

  3. No module may import a DANGEROUS module (``pickle``-style
     deserialization, raw ``socket``) — user data must never reach
     dynamic execution or deserialization (AGENTS.md).

How it guards: every ``.py`` under ``src/nlbt`` is parsed with :mod:`ast`
(no code is executed) and every ``import X`` / ``from X import ...`` is
checked against the rules above, using full dotted module names so
``import nlbt.nl`` is distinguished from ``import nlbt.spec``.

The self-canary tests assert the scanner FLAGS each forbidden import and
PASSES each legal one, so a silent regression in the scanner itself
cannot go unnoticed. The repo scan below passes today because
``nlbt.engine`` does not exist yet; it will fail the day someone adds a
forbidden import, which is exactly the point.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "nlbt"

#: Packages ``nlbt.engine`` is never allowed to import (§3.2).
FORBIDDEN_IN_ENGINE: frozenset[str] = frozenset(
    {
        "nlbt.nl",  # the natural-language / LLM layer
        "anthropic",
        "openai",
        "google.generativeai",
        "litellm",
        "cohere",
        "mistralai",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "socket",
    }
)

#: Only ``nlbt.nl`` may import an LLM SDK (§3.2).
LLM_SDKS: frozenset[str] = frozenset(
    {"anthropic", "openai", "google.generativeai", "litellm", "cohere", "mistralai"}
)

#: Modules banned everywhere in ``src/nlbt`` (AGENTS.md: no pickle on
#: user-controlled data; no raw sockets).
DANGEROUS: frozenset[str] = frozenset({"pickle", "dill", "shelve", "socket"})

#: The only package allowed to import an LLM SDK.
NL_PACKAGE = "nl"


def _imported_modules(source: str) -> set[str]:
    """All full dotted module names imported by *source* (ast-walk, no exec)."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)  # ignore relative imports
    return {name for name in names if name != "__future__"}


def _hits(imports: set[str], banned: frozenset[str]) -> set[str]:
    """Banned modules that are imported (exact or as a dotted prefix)."""
    return {
        b for imported in imports for b in banned if imported == b or imported.startswith(b + ".")
    }


def _boundaries_violated(source: str, package: str) -> list[str]:
    """Boundary rules broken by *source* when it lives in *package*."""
    imports = _imported_modules(source)
    bad: set[str] = set()
    if package == "engine":
        bad |= _hits(imports, FORBIDDEN_IN_ENGINE)
    if package != NL_PACKAGE:
        bad |= _hits(imports, LLM_SDKS)
    bad |= _hits(imports, DANGEROUS)
    return sorted(bad)


# --------------------------------------------------------------------------- #
# Self-canaries: prove the detector catches violations (scanner regression).  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("package", "source", "expected"),
    [
        ("engine", "import nlbt.nl\n", ["nlbt.nl"]),
        ("engine", "from nlbt.nl import parse\n", ["nlbt.nl"]),
        ("engine", "import anthropic\n", ["anthropic"]),
        ("engine", "import requests\n", ["requests"]),
        ("engine", "import anthropic\nimport pickle\n", ["anthropic", "pickle"]),
        ("spec", "import openai\n", ["openai"]),  # LLM SDKs: nl package ONLY
        ("metrics", "import pickle\n", ["pickle"]),  # dangerous: banned everywhere
    ],
)
def test_scanner_flags_violations(package: str, source: str, expected: list[str]) -> None:
    """Canary: each forbidden import MUST be flagged, wherever it appears."""
    assert _boundaries_violated(source, package) == expected


@pytest.mark.parametrize(
    ("package", "source"),
    [
        ("engine", "import pandas\nimport numpy\nfrom nlbt.spec import models\n"),
        ("nl", "import anthropic\n"),  # allowed: nl IS the LLM layer
        ("data", "import pyarrow.parquet\n"),
        ("spec", "import pydantic\n"),
        ("", "import typer\n"),  # top-level module (e.g. cli.py)
    ],
)
def test_scanner_allows_legal_imports(package: str, source: str) -> None:
    """Legal imports must NOT be flagged (no false positives)."""
    assert _boundaries_violated(source, package) == []


# --------------------------------------------------------------------------- #
# Repo scan: the actual gate. Passes today (no engine yet); fails the day a   #
# forbidden import appears, which is the intended behaviour.                  #
# --------------------------------------------------------------------------- #


def test_engine_does_not_exist_yet() -> None:
    """Documents the P0 state: the boundary gate is armed but has no target."""
    assert not (SRC / "engine").is_dir(), (
        "nlbt.engine now exists: review test_repo_imports_respect_boundaries "
        "and tighten it (e.g. per-module checks) before relying on it."
    )


def test_repo_imports_respect_boundaries() -> None:
    """Scan every real module under src/nlbt for boundary violations."""
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        package = rel.with_suffix("").parts[0] if rel.parts else ""
        bad = _boundaries_violated(path.read_text(encoding="utf-8"), package)
        if bad:
            violations.append(f"{rel}: {', '.join(bad)}")
    assert not violations, "Import boundary violations (ROADMAP §3.2):\n" + "\n".join(violations)
