"""Minimal .env reader -- P6-T1 dev tooling (probe + recorder ONLY).

Owner authorization ("source .env for the probe", 2026-10-25): the step-2 live
probe and ``scripts/record_llm_fixture.py`` may read the gitignored
``nlbt/.env`` for ``NVIDIA_API_KEY`` under these conditions, honoured here:

* Python-side parsing, no shell sourcing; the value goes to a LOCAL variable
  in the caller -- never exported, printed, written to disk, or embedded in an
  exception message.
* Parsing contract: open with ``encoding="utf-8-sig"`` (BOM tolerated), strip
  ``\\r`` and surrounding whitespace per line, ignore blank lines and lines
  starting with ``#``, split on the FIRST ``=``, strip surrounding quotes from
  the value.
* Missing or empty entry -> ``None`` (the probe prints "KEY MISSING IN .env"
  and stops; never a partial value).

Not library code: nothing under ``src/nlbt`` may import this module (guarded
by ``tests/unit/test_envfile_helper.py``), and tests that hit the network
never call it.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["find_key", "read_env_file"]


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a simple ``.env`` file into a dict. Missing file -> empty dict."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}

    entries: dict[str, str] = {}
    for raw_line in text.split("\n"):
        line = raw_line.strip()  # strips \r and surrounding whitespace
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        entries[name.strip()] = value
    return entries


def find_key(path: Path, name: str = "NVIDIA_API_KEY") -> str | None:
    """Return the value of ``name`` or ``None`` if it is missing/empty.

    The caller decides what to do; this function never raises on absence and
    never includes any value in an exception (it raises none at all).
    """
    value = read_env_file(path).get(name, "")
    return value or None
