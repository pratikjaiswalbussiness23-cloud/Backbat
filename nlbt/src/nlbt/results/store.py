"""result.json writer (ROADMAP P5-T4a).

Parquet files, ``load_run`` and replay are P5-T4b — this module ONLY
serialises the §4.6 result payload (no equity curve / trades: those go to
parquet later) under ``<runs_dir>/<run_id>/result.json``.

Serialisation rules: ``allow_nan=False`` (any NaN/Infinity raises — I13
gate, never emitted), ``sort_keys=True`` (stable bytes for the same
content), ``None`` -> JSON ``null``.

P5-T5 (CLI): the payload shape and the serialiser both live here so the
CLI's ``--json`` stdout and the stored ``result.json`` can never drift —
``build_result_payload`` + ``render_result_json`` are the shared builders.
(``execute_run`` still assembles its own equivalent dict literal; keeping
the two in one place is logged in docs/OPEN_QUESTIONS.md.)
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

__all__ = ["build_result_payload", "render_result_json", "write_result_json"]

_FILE = "result.json"


def _json_default(value: Any) -> str:
    """ISO-format datetimes/dates; anything else is a programming error."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"object of type {type(value).__name__} is not JSON serialisable")


def build_result_payload(
    run_id: str,
    manifest: dict[str, Any],
    metrics: dict[str, float | None],
    benchmark_metrics: dict[str, float | None],
    warnings: list[str],
    data_quality_report: dict[str, Any] | None,
) -> dict[str, Any]:
    """The §4.6 result payload (P5-T4a key set) — the single payload
    builder the CLI ``--json`` path reuses (P5-T5 ruling)."""
    return {
        "run_id": run_id,
        "manifest": manifest,
        "metrics": metrics,
        "benchmark_metrics": benchmark_metrics,
        "warnings": warnings,
        "data_quality_report": data_quality_report,
    }


def render_result_json(payload: dict[str, Any]) -> str:
    """Serialise a result payload to the exact JSON text written into
    ``result.json`` (no trailing newline): ``allow_nan=False`` raises rather
    than ever emitting NaN/Infinity, keys sorted for stable bytes. The CLI
    ``--json`` path reuses this so stdout and the stored file cannot drift.
    """
    return json.dumps(
        payload,
        allow_nan=False,
        sort_keys=True,
        indent=2,
        default=_json_default,
    )


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
        handle.write(render_result_json(payload))
        handle.write("\n")
    return final_run_id
