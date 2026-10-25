"""nlbt command-line interface (ROADMAP P5-T5, hackathon Phase 5 subset).

A THIN layer: every behavior lives in the existing functions (spec
validation, English rendering, the CSV/yfinance providers, ``execute_run``,
the result-payload builder in ``nlbt.results.store``); this module only
parses argv, formats output and maps errors to exit codes.

Exit codes (ROADMAP 4.8; P7-T1 polish is out of scope for v0):

* ``0`` - success.
* ``1`` - domain error: any :class:`nlbt.errors.NlbtError` printed verbatim
  via ``str(exc)`` (``[CODE] message (hint: ...)``), or an unexpected
  exception printed as ``unexpected error: <Type>: <message>`` (full
  traceback only when ``NLBT_DEBUG=1``).
* ``2`` - usage error (typer) or a missing/unreadable spec file (plain
  message, no invented error code - owner ruling Q1).

Output rules: ``typer.echo`` only, no rich markup, no color, ASCII-only;
metric values render through ``_fmt`` so ``None``/non-finite become ``n/a``
-- the strings "nan"/"inf" are never printed.

The public entry point is :func:`main` (``argv -> int``, never raises,
never calls ``sys.exit`` itself); the console script (``nlbt``) and
``python -m nlbt`` wrap it. The Streamlit UI and the LLM layer must call
``execute_run`` directly instead of shelling out to this CLI.
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

# typer 0.27.2 vendors click as typer._click (probed 2026-10-25; the lock
# pins the version, and docs/DEPENDENCIES.md records the dependency).
from typer._click.exceptions import UsageError

from nlbt.config import Config
from nlbt.data.csv_provider import CSVProvider
from nlbt.data.models import Bars, BarsMeta
from nlbt.errors import NlbtError, SpecSchemaError
from nlbt.results import execute_run
from nlbt.results.store import build_result_payload, render_result_json
from nlbt.spec import StrategySpec, render_spec, validate_spec

__all__ = ["main"]

#: Required verbatim on --help (P5-T5 design point).
_DISCLAIMER = "Historical simulation only; not investment advice."

#: Plain help (rich_markup_mode=None): ASCII-only, no color, no boxes.
_APP = typer.Typer(
    name="nlbt",
    rich_markup_mode=None,
    add_completion=False,
    epilog=_DISCLAIMER,
)


def _fmt(value: float | None) -> str:
    """Human metric text: ``None``/non-finite -> ``"n/a"`` (never nan/inf)."""
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:.6g}"


def _load_spec(spec_file: str) -> StrategySpec:
    """Read + parse a spec JSON file into a schema-valid ``StrategySpec``.

    ``spec_file`` stays a STRING so messages echo the path exactly as the
    user typed it (Windows ``Path`` would rewrite the separators). Missing
    or unreadable file -> plain message + exit 2 (Q1); malformed JSON or
    schema violation -> ``E_SPEC_SCHEMA`` (exit 1 via ``main``).
    """
    try:
        text = Path(spec_file).read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        typer.echo(f"error: cannot read spec file: {spec_file}", err=True)
        raise typer.Exit(2) from None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecSchemaError(
            f"spec file is not valid JSON: {spec_file}",
            details={"reason": str(exc)},
            hint="fix the JSON syntax; docs/spec_schema.json has the schema",
        ) from exc
    try:
        return StrategySpec.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors()
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first["loc"])
            problem = f"{location}: {first['msg']}"
        else:  # pragma: no cover -- pydantic always reports >= 1 error
            problem = "unknown schema violation"
        raise SpecSchemaError(
            f"spec schema violation in {spec_file}: {problem}",
            details={"path": spec_file, "error_count": len(errors)},
            hint="docs/spec_schema.json describes the required StrategySpec schema",
        ) from exc


def _validate_or_exit(spec: StrategySpec) -> None:
    """Run the semantic validator; print errors (stderr) and exit 1 if any."""
    result = validate_spec(spec)
    for error in result.errors:
        hint = f" (hint: {error.hint})" if error.hint else ""
        typer.echo(f"[{error.code}] {error.path}: {error.message}{hint}", err=True)
    if result.errors:
        raise typer.Exit(1)


def _load_bars(spec: StrategySpec, data_csv: str | None) -> tuple[Bars, BarsMeta, dict[str, str]]:
    """Fetch bars for the spec's universe/period from the chosen provider."""
    if data_csv is not None:
        # --data-csv string is kept VERBATIM (Windows pathlib would turn a
        # Path into backslashes; the manifest/golden need the literal text).
        bars, meta = CSVProvider().get_bars(
            data_csv,
            spec.period.start,
            spec.period.end,
            interval=spec.universe.interval,
        )
        return bars, meta, {"kind": "csv", "path": data_csv}
    # Lazy: yfinance is only imported when actually fetching (keeps
    # --data-csv runs and their startup cost independent of it).
    from nlbt.data.yf_provider import YFinanceProvider

    symbol = spec.universe.symbols[0]
    bars, meta = YFinanceProvider().get_bars(
        symbol,
        spec.period.start,
        spec.period.end,
        interval=spec.universe.interval,
    )
    return bars, meta, {"kind": "yfinance", "symbol": symbol}


def _echo_summary(
    result: Any,
    *,
    result_path: Path | None,
) -> None:
    """Compact human summary: run_id, result path, spec line, metric table
    (strategy vs benchmark, ``n/a`` for undefined), surfaced warnings."""
    manifest: dict[str, Any] = result.manifest
    canonical: dict[str, Any] = manifest["spec"]
    data: dict[str, Any] = manifest["data"]
    typer.echo(f"run_id:  {result.run_id}")
    if result_path is not None:
        typer.echo(f"result:  {result_path}")
    else:
        typer.echo("result:  (not persisted)")
    typer.echo(
        f"spec:    {canonical['name']} | {canonical['universe']['symbols'][0]} | "
        f"{canonical['period']['start']}..{canonical['period']['end']} | {data['bars']} bars"
    )
    keys = sorted(set(result.metrics) | set(result.benchmark_metrics))
    typer.echo(f"{'metric':<26}{'strategy':>12}{'benchmark':>13}")
    for key in keys:
        strategy = _fmt(result.metrics.get(key))
        benchmark = _fmt(result.benchmark_metrics.get(key))
        typer.echo(f"{key:<26}{strategy:>12}{benchmark:>13}")
    if result.warnings:
        typer.echo("warnings:")
        for warning in result.warnings:
            typer.echo(f"- {warning}")
    else:
        typer.echo("warnings: none")


#: Module-level option singletons: typer's Option-in-default idiom is the
#: one thing ruff's B008 dislikes, and its own suggested remedy is to read
#: the default from a module-level variable (no noqa needed).
_DATA_CSV_OPTION = typer.Option(
    None, "--data-csv", help="OHLCV CSV file to use instead of the default provider."
)
_RF_OPTION = typer.Option(0.0, "--rf", help="Annual risk-free rate for Sharpe (default 0.0).")
_RUNS_DIR_OPTION = typer.Option(
    None, "--runs-dir", help="Directory for run outputs (default: NLBT_RUNS_DIR)."
)
_NO_PERSIST_OPTION = typer.Option(False, "--no-persist", help="Do not write result.json to disk.")
_JSON_OPTION = typer.Option(False, "--json", help="Print only the result payload as JSON.")


@_APP.command("run")
def _run(
    spec_file: str = typer.Argument(..., help="Path to a StrategySpec JSON file."),
    data_csv: str | None = _DATA_CSV_OPTION,
    rf: float = _RF_OPTION,
    runs_dir: Path | None = _RUNS_DIR_OPTION,
    no_persist: bool = _NO_PERSIST_OPTION,
    json_out: bool = _JSON_OPTION,
) -> None:
    """Backtest a spec and print a compact metrics summary."""
    spec = _load_spec(spec_file)
    _validate_or_exit(spec)
    bars, meta, data_source = _load_bars(spec, data_csv)
    result = execute_run(
        spec,
        bars,
        meta=meta,
        rf=rf,
        data_source=data_source,
        runs_dir=runs_dir,
        persist=not no_persist,
    )
    if json_out:
        # Same builder + same serialiser as the stored result.json, so
        # stdout and the file are byte-identical (P5-T5 ruling).
        payload = build_result_payload(
            run_id=result.run_id,
            manifest=result.manifest,
            metrics=result.metrics,
            benchmark_metrics=result.benchmark_metrics,
            warnings=result.warnings,
            data_quality_report=result.data_quality_report,
        )
        typer.echo(render_result_json(payload))
        return
    result_path: Path | None = None
    if not no_persist:
        base = runs_dir if runs_dir is not None else Path(Config().runs_dir)
        result_path = base / result.run_id / "result.json"
    _echo_summary(result, result_path=result_path)


@_APP.command("validate-spec")
def _validate_spec_cmd(
    spec_file: str = typer.Argument(..., help="Path to a StrategySpec JSON file."),
) -> None:
    """Validate a spec file (schema + semantics) and report findings."""
    spec = _load_spec(spec_file)
    _validate_or_exit(spec)
    result = validate_spec(spec)
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")
    typer.echo(f"valid: {spec_file}")


@_APP.command("render-spec")
def _render_spec_cmd(
    spec_file: str = typer.Argument(..., help="Path to a StrategySpec JSON file."),
) -> None:
    """Render a spec file as deterministic English."""
    spec = _load_spec(spec_file)
    typer.echo(render_spec(spec))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI on ``argv`` (default ``sys.argv[1:]``) and return 0/1/2.

    Never raises and never calls ``sys.exit`` itself: the console script
    ``nlbt = nlbt.cli:main`` and ``python -m nlbt`` both wrap this return
    value, and tests/UI code can call it directly.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        outcome = _APP(args=args, prog_name="nlbt", standalone_mode=False)
    except UsageError as exc:
        typer.echo(f"error: {exc.format_message()}", err=True)
        return 2
    except NlbtError as exc:
        typer.echo(str(exc), err=True)
        return 1
    except KeyboardInterrupt:
        typer.echo("error: interrupted", err=True)
        return 130
    except SystemExit as exc:  # defensive: non-standalone mode should not raise
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    except Exception as exc:
        typer.echo(f"unexpected error: {type(exc).__name__}: {exc}", err=True)
        if os.environ.get("NLBT_DEBUG") == "1":
            traceback.print_exc()
        return 1
    return outcome if isinstance(outcome, int) else 0
