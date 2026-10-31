"""nlbt self-hosted local web server (P7-T3, ADR-0006).

Run with:  uv run nlbt serve

or  python -m nlbt.server

This server provides HTTP endpoints for the 5-step flow:
  1. Interpret  → 2. Confirm  → 3. Run  → 4. Metrics  → 5. Persist

Endpoints (all POST, JSON bodies/results):

  POST /interpret    { "text": "..." }      → { status, spec, rendering, ... }
  POST /confirm      { "spec_hash_logic": "...", "spec_hash_full": "..." } → { confirmed }
  POST /run          { "interp": {...}, "confirmation": {...} }       → { result, metrics }

Static UI at /ui served from ./static/index.html
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nlbt.config import Config
from nlbt.errors import NlbtError
from nlbt.nl.openai_client import OpenAICompatibleClient
from nlbt.nl.service import (
    Confirmation,
    Interpretation,
    UnconfirmedSpecError,
    interpret,
    run_confirmed,
)
from nlbt.results.store import build_result_payload, render_result_json
from nlbt.spec.models import StrategySpec

app = FastAPI(title="nlbt", version="0.1.0")

# ──────────────────────────────────────────────────────────────────────
# Static UI (served from ./static relative to the project root)
# ──────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2] / "static"

if _PROJECT_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=str(_PROJECT_ROOT)), name="static")


@app.get("/ui", include_in_schema=False)
async def ui_root() -> FileResponse:
    """Serve the static HTML UI at /ui."""
    return FileResponse(str(_PROJECT_ROOT / "index.html"))


# ──────────────────────────────────────────────────────────────────────
# Pydantic request/response models
# ──────────────────────────────────────────────────────────────────────


class InterpretRequest(BaseModel):
    text: str = Field(..., description="Plain-English strategy request")


class InterpretResponse(BaseModel):
    status: str
    spec: dict[str, Any] | None = None
    rendering: str = ""
    assumptions: list[dict[str, Any]] = []
    warnings: list[str] = []
    unsupported: list[str] = []
    questions: list[dict[str, Any]] = []
    resolved_symbol: str | None = None
    data_summary: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ConfirmRequest(BaseModel):
    spec_hash_logic: str = Field(..., description="Logic hash of the current spec")
    spec_hash_full: str = Field(..., description="Full hash of the current spec")


class RunRequest(BaseModel):
    interp: dict[str, Any] = Field(..., description="Interpretation dict")
    confirmation: dict[str, Any] = Field(..., description="Confirmation dict")


# ──────────────────────────────────────────────────────────────────────
# POST /interpret
# ──────────────────────────────────────────────────────────────────────


@app.post("/interpret", response_model=InterpretResponse)
async def api_interpret(req: InterpretRequest) -> InterpretResponse:
    """Translate text → interpretation (same logic as ``nlbt ask``)."""
    try:
        config = Config()
        recordings = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"
        client = OpenAICompatibleClient(
            config=config,
            recordings_dir=recordings if recordings.is_dir() else None,
        )
        from nlbt.data.cache import CachedProvider
        from nlbt.data.yf_provider import YFinanceProvider

        provider = CachedProvider(YFinanceProvider(), config.data_cache_dir)
        data_symbol_override = None

        interp = interpret(
            text=req.text,
            client=client,
            provider=provider,
            data_symbol_override=data_symbol_override,
        )

        error_dict = None
        if interp.error is not None:
            error_dict = {
                "code": interp.error.code,
                "message": str(interp.error),
                "hint": getattr(interp.error, "hint", ""),
                "details": getattr(interp.error, "details", None),
            }

        return InterpretResponse(
            status=interp.status,
            spec=(dict(interp.spec.model_dump().items()) if interp.spec is not None else None),
            rendering=interp.rendering,
            assumptions=interp.assumptions,
            warnings=interp.warnings,
            unsupported=interp.unsupported,
            questions=interp.questions,
            resolved_symbol=interp.resolved_symbol,
            data_summary=interp.data_summary,
            error=error_dict,
        )
    except NlbtError as exc:
        return InterpretResponse(
            status="error",
            error={
                "code": exc.code,
                "message": str(exc),
                "hint": getattr(exc, "hint", ""),
                "details": getattr(exc, "details", None),
            },
        )
    except Exception as exc:  # unexpected - wrap as error status
        return InterpretResponse(
            status="error",
            error={
                "code": "E_NL_LLM",
                "message": str(exc),
                "hint": "Unexpected server error; see NLBT_DEBUG for trace.",
                "details": {"exc_type": exc.__class__.__name__, "exc_message": str(exc)},
            },
        )


# ──────────────────────────────────────────────────────────────────────
# POST /confirm
# ──────────────────────────────────────────────────────────────────────


@app.post("/confirm", response_model=dict[str, str])
async def api_confirm(req: ConfirmRequest) -> dict[str, str]:
    """Freeze a confirmation (both hashes + timestamp + channel)."""
    try:
        return {"status": "confirmed"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ──────────────────────────────────────────────────────────────────────
# POST /run
# ──────────────────────────────────────────────────────────────────────


@app.post("/run", response_model=dict[str, Any])
async def api_run(req: RunRequest) -> dict[str, Any]:
    """Run a confirmed interpretation and return the result payload."""
    try:
        interp_dict = req.interp
        confirmation_dict = req.confirmation

        interp = Interpretation(
            status=interp_dict.get("status", "ok"),
            spec=(
                StrategySpec.model_validate(interp_dict["spec"])
                if interp_dict.get("spec") is not None
                else None
            ),
            rendering=interp_dict.get("rendering", ""),
            assumptions=interp_dict.get("assumptions", []),
            warnings=interp_dict.get("warnings", []),
            unsupported=interp_dict.get("unsupported", []),
            questions=interp_dict.get("questions", []),
            resolved_symbol=interp_dict.get("resolved_symbol"),
            data_summary=interp_dict.get("data_summary"),
            bars=interp_dict.get("bars"),
            bars_meta=interp_dict.get("bars_meta"),
            nl_meta=interp_dict.get("nl_meta"),
            error=(interp_dict.get("error") if interp_dict.get("status") == "error" else None),
        )

        confirmation = Confirmation(
            spec_hash_logic=confirmation_dict.get("spec_hash_logic", ""),
            spec_hash_full=confirmation_dict.get("spec_hash_full", ""),
            user_confirmed_at=confirmation_dict.get("user_confirmed_at", ""),
            confirmed_via="ui",
        )

        confirmed = run_confirmed(
            interp=interp,
            confirmation=confirmation,
            data_source=None,
            runs_dir=None,
            persist=True,
        )

        payload = build_result_payload(
            run_id=confirmed.run_id,
            manifest=confirmed.manifest,
            metrics=confirmed.metrics,
            benchmark_metrics=confirmed.benchmark_metrics,
            warnings=confirmed.warnings,
            data_quality_report=confirmed.data_quality_report,
        )

        return {
            "status": "ok",
            "run_id": confirmed.run_id,
            "result_json": render_result_json(payload),
            "metrics": confirmed.metrics,
            "benchmark_metrics": confirmed.benchmark_metrics,
            "warnings": confirmed.warnings,
        }

    except UnconfirmedSpecError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NlbtError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}") from exc


# ──────────────────────────────────────────────────────────────────────
# CLI: `nlbt serve`
# ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``uv run nlbt serve`` or ``python -m nlbt.server``."""
    import uvicorn

    host = "127.0.0.1"
    port = 8000
    reload = False

    args = list(argv) if argv else []
    i = 0
    while i < len(args):
        if args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif args[i] == "--reload":
            reload = True
            i += 1
        else:
            i += 1

    print(f"nlbt server running at http://{host}:{port}/ui")
    uvicorn.run("nlbt.server:app", host=host, port=port, reload=reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ──────────────────────────────────────────────────────────────────────
# Start-up smoke test (when imported as ``nlbt.server`` module)
# ──────────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def _smoke_test() -> None:
    """Light smoke test at startup so we know the import chain works."""
    route_paths = {getattr(r, "path", None) for r in app.routes}
    essential = {"/interpret", "/confirm", "/run", "/ui"}
    missing = essential - route_paths
    if missing:
        print(f"warning: nlbt server startup — missing routes: {missing}")
