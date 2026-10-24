"""Section-4.6 result building (ROADMAP P5-T4a): run + benchmark + manifest.

``execute_run`` is the top-level wrapper around the pure engine: it calls
:func:`nlbt.engine.backtest.run`, :func:`nlbt.engine.benchmark.compute_benchmark`
and (when ``meta`` is supplied) :func:`nlbt.data.quality.run_quality_checks`,
builds the §4.6 ``RunResult`` with the Appendix-E manifest, and **surfaces
the warnings** per OQ-0072: final ``warnings`` = engine warnings + the
engine's ``metric_warnings`` (return-metric, trade-metric and
``infer_frequency`` warnings) + benchmark warnings prefixed ``benchmark: ``,
exact duplicates dropped, order preserved, engine warnings first.

``run()`` itself is unchanged: its ``warnings`` field stays engine-only and
the deferred warnings live in its new defaulted ``metric_warnings`` field.

Persistence: only ``result.json`` in this task (P5-T4a). ``equity.parquet``
and ``trades.parquet``, ``load_run`` and ``nlbt replay`` are P5-T4b.
"""

from __future__ import annotations

import platform
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

import pandas as pd

from nlbt.data.models import Bars, BarsMeta
from nlbt.data.quality import run_quality_checks
from nlbt.engine.backtest import Trade, run
from nlbt.engine.benchmark import compute_benchmark
from nlbt.results.store import write_result_json
from nlbt.spec.canonical import canonicalise, spec_hash_full, spec_hash_logic
from nlbt.spec.models import StrategySpec

__all__ = ["RunResult", "execute_run"]

_PACKAGES = ("pandas", "numpy", "pydantic", "pyarrow")


@dataclass
class RunResult:
    """§4.6 BacktestResult as built by ``execute_run`` (P5-T4a)."""

    run_id: str
    manifest: dict[str, Any]
    metrics: dict[str, float | None]
    benchmark_metrics: dict[str, float | None]
    equity_curve: pd.DataFrame
    trades: list[Trade]
    warnings: list[str]
    data_quality_report: dict[str, Any] | None


def _code_version() -> str:
    """git sha of HEAD (§4.6 code_version), or "unknown" outside a checkout."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            cwd=Path(__file__).resolve().parents[3],
        )
    except OSError, subprocess.SubprocessError:
        return "unknown"
    sha = completed.stdout.strip()
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else "unknown"


def _data_hash(bars: Bars) -> str:
    """sha256 of the validated bars' parquet bytes (cache.py precedent).

    Known limitation (OQ-0075): a pyarrow upgrade could change the bytes
    for the same data.
    """
    import hashlib

    return "sha256:" + hashlib.sha256(bars.to_parquet()).hexdigest()


def _merge_warnings(
    engine_warnings: Sequence[str],
    metric_warnings: Sequence[str],
    benchmark_warnings: Sequence[str],
) -> list[str]:
    """Engine first, then metric/frequency, then ``benchmark: ``-prefixed;
    exact duplicates dropped, order preserved (OQ-0072 owner ruling)."""
    merged = [
        *engine_warnings,
        *metric_warnings,
        *(f"benchmark: {warning}" for warning in benchmark_warnings),
    ]
    seen: set[str] = set()
    deduplicated: list[str] = []
    for warning in merged:
        if warning not in seen:
            seen.add(warning)
            deduplicated.append(warning)
    return deduplicated


def _manifest(
    spec: StrategySpec,
    bars: Bars,
    *,
    now: datetime,
    data_hash: str,
    data_source: dict[str, Any] | None,
    meta: BarsMeta | None,
) -> dict[str, Any]:
    """Appendix-E manifest with §4.6 fields (owner-ruled table, P5-T4a)."""
    return {
        "spec": canonicalise(spec),
        "spec_hash_logic": spec_hash_logic(spec),
        "spec_hash_full": spec_hash_full(spec),
        "data_hash": data_hash,
        "data": {
            "provider": meta.provider if meta else (data_source or {}).get("kind"),
            "symbol": meta.symbol if meta else spec.universe.symbols[0],
            "interval": spec.universe.interval,
            "adjusted": meta.adjusted if meta else None,
            "fetched_at": meta.fetched_at.isoformat() if meta else None,
            "bars": len(bars),
            # documented §4.6 extension: source needed for P5-T4b replay
            "source": data_source,
        },
        "code": {
            "code_version": _code_version(),
            "python": platform.python_version(),
            "packages": {name: importlib_metadata.version(name) for name in _PACKAGES},
        },
        # null until Phase 6 (llm) and the UI confirm gate (user_confirmed_at)
        "llm": {"llm_model": None, "prompt_version": None, "user_confirmed_at": None},
        "run_started_at": now.isoformat(),
    }


def execute_run(
    spec: StrategySpec,
    bars: Bars,
    *,
    meta: BarsMeta | None = None,
    rf: float = 0.0,
    data_source: dict[str, Any] | None = None,
    runs_dir: Path | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> RunResult:
    """Build the §4.6 result for one run; persist ``result.json`` unless
    ``persist=False``. ``now`` is injectable for deterministic tests."""
    started = now if now is not None else datetime.now(UTC)

    engine = run(spec, bars, rf=rf)
    benchmark_metrics, benchmark_warnings = compute_benchmark(spec, bars, rf=rf)
    warnings = _merge_warnings(engine.warnings, engine.metric_warnings, benchmark_warnings)

    data_hash = _data_hash(bars)
    manifest = _manifest(
        spec,
        bars,
        now=started,
        data_hash=data_hash,
        data_source=data_source,
        meta=meta,
    )
    run_id = f"{started:%Y-%m-%dT%H-%M-%SZ}_{spec_hash_logic(spec)[7:13]}"

    report: dict[str, Any] | None = None
    if meta is not None:
        report = run_quality_checks(bars, meta).model_dump(mode="json")

    payload: dict[str, Any] = {
        "run_id": run_id,
        "manifest": manifest,
        "metrics": engine.metrics,
        "benchmark_metrics": benchmark_metrics,
        "warnings": warnings,
        "data_quality_report": report,
    }
    if persist:
        directory = Path(runs_dir) if runs_dir is not None else Path(_runs_dir())
        run_id = write_result_json(directory, run_id, payload)

    return RunResult(
        run_id=run_id,
        manifest=manifest,
        metrics=engine.metrics,
        benchmark_metrics=benchmark_metrics,
        equity_curve=engine.equity_curve,
        trades=engine.trades,
        warnings=warnings,
        data_quality_report=report,
    )


def _runs_dir() -> str:
    """Default output dir from Config (NLBT_RUNS_DIR); only when persisting."""
    from nlbt.config import Config

    return Config().runs_dir
