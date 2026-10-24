"""result.json writer (ROADMAP P5-T4a).

Parquet files, ``load_run`` and replay are P5-T4b — this module ONLY
serialises the §4.6 result payload (no equity curve / trades: those go to
parquet later) under ``<runs_dir>/<run_id>/result.json``.

Serialisation rules: ``allow_nan=False`` (any NaN/Infinity raises — I13
gate, never emitted), ``sort_keys=True`` (stable bytes for the same
content), ``None`` -> JSON ``null``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

__all__ = ["write_result_json"]

_FILE = "result.json"


def _json_default(value: Any) -> str:
    """ISO-format datetimes/dates; anything else is a programming error."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"object of type {type(value).__name__} is not JSON serialisable")


def write_result_json(runs_dir: Path, run_id: str, payload: dict[str, Any]) -> str:
    """Write ``<runs_dir>/<run_id>/result.json``; NEVER overwrite an existing
    run directory — on collision a numeric suffix (``_2``, ``_3``, …) is
    appended. Returns the final run_id (also written into the payload)."""
    directory = runs_dir / run_id
    attempt = 2
    while directory.exists():
        directory = runs_dir / f"{run_id}_{attempt}"
        attempt += 1
    final_run_id = directory.name
    if final_run_id != run_id:
        payload = {**payload, "run_id": final_run_id}
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / _FILE).open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            allow_nan=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        )
        handle.write("\n")
    return final_run_id
