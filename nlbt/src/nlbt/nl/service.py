"""P6-T4/T5/T10 (minimal): the NL service the CLI and the UI both call.

One entry point -- :func:`interpret` -- chains ``parse_text`` (P6-T3/T6:
validation chain, bounded repair, period resolution, registry-only
defaults) -> ``validate_spec`` (warnings) -> a provider fetch that VERIFIES
the symbol (P6-T5/S9) -> ``render_spec`` (deterministic English, S8). One
gate -- :func:`run_confirmed` -- refuses anything that is not
``status="ok"`` with a valid :class:`Confirmation` before ``execute_run``
is ever reached (Gate 7: "UI cannot run an unconfirmed spec").

Owner rulings implemented verbatim (Phase B task):

* **Q1** -- ``E_DATA_EMPTY`` becomes ``status="needs_clarification"`` with
  ``{"id": "symbol_not_identifiable", "question": "I couldn't find data for
  {symbol}. Which symbol did you mean?"}``, ``resolved_symbol=symbol``,
  ``spec=None``, ``bars=None``. An alternative ticker is NEVER invented:
  none of the providers (CSV/yfinance/cache) supports symbol search, so no
  suggestion tail is ever appended.
* **Q2** -- :class:`UnconfirmedSpecError` (``code = "E_NL_UNCONFIRMED"``)
  lives HERE, deliberately NOT registered in ``nlbt.errors`` (ROADMAP 4.8
  pins exactly 11 codes; ``tests/unit/test_errors.py`` asserts that set).
  See ``docs/OPEN_QUESTIONS.md`` OQ-0092.

Statuses follow the envelope (P6-T3): ``ok | needs_clarification |
unsupported | error``. ``interpret`` never raises an ``NlbtError``: typed
failures (``E_LIMIT_EXCEEDED``, ``E_NL_LLM``, data errors) come back as
``status="error"`` with the exact error object on ``Interpretation.error``;
:func:`run_confirmed` re-raises them unchanged.

Single-fetch design: the verification fetch keeps ``(bars, meta)`` on the
returned :class:`Interpretation` and :func:`run_confirmed` hands the SAME
frame to ``execute_run`` -- ``nlbt ask`` / the UI never fetch twice, so
``manifest.data.fetched_at`` and ``data_hash`` describe the frame the user
actually confirmed. Confirming freezes BOTH spec hashes
(``spec_hash_logic`` + ``spec_hash_full``); re-hashing at run time means ANY
edit after confirmation invalidates it -- including provenance-only edits
(``source_text``) that the logic hash alone cannot see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from nlbt.data.models import Bars, BarsMeta, DataProvider
from nlbt.errors import (
    DataEmptyError,
    EngineInvariantError,
    NLAmbiguousError,
    NlbtError,
    NLUnsupportedError,
)
from nlbt.nl.client import LLMClient
from nlbt.nl.parse import parse_text
from nlbt.results import RunResult, execute_run
from nlbt.spec.canonical import spec_hash_full, spec_hash_logic
from nlbt.spec.models import StrategySpec
from nlbt.spec.render import render_spec
from nlbt.spec.validate import validate_spec

__all__ = [
    "DATA_EMPTY_QUESTION_ID",
    "Confirmation",
    "Interpretation",
    "Status",
    "UnconfirmedSpecError",
    "confirm_spec",
    "interpret",
    "require_confirmation",
    "run_confirmed",
]

#: Envelope statuses (P6-T3) + the service's own failure status.
Status = Literal["ok", "needs_clarification", "unsupported", "error"]

#: How a confirmation was obtained (P6-T10; ``flag`` == ``nlbt ask --yes``).
ConfirmedVia = Literal["flag", "interactive", "ui"]

#: Q1: must-ask id used for the E_DATA_EMPTY clarification (an existing
#: ``MUST_ASK`` id -- the envelope rejects any other one).
DATA_EMPTY_QUESTION_ID = "symbol_not_identifiable"


class UnconfirmedSpecError(NlbtError):
    """Running without a valid confirmation (Gate 7).

    Lives in the service, NOT in ``nlbt.errors``: ROADMAP 4.8 defines
    exactly 11 codes and ``test_errors.py`` pins them (owner ruling Q2,
    OQ-0092). Still a real ``NlbtError``, so ``nlbt.cli.main`` prints
    ``[E_NL_UNCONFIRMED] message (hint: ...)`` and exits 1 like every other
    §4.8 error.
    """

    code = "E_NL_UNCONFIRMED"


@dataclass(frozen=True)
class Confirmation:
    """What the user confirmed, frozen at confirmation time (P6-T10).

    Both hashes are carried on purpose: ``spec_hash_logic`` covers trading
    logic, ``spec_hash_full`` additionally covers provenance fields
    (``source_text``) that ``_LOGIC_EXCLUDED_FIELDS`` deliberately excludes
    from the logic hash.
    """

    spec_hash_logic: str
    spec_hash_full: str
    user_confirmed_at: str
    confirmed_via: ConfirmedVia


@dataclass(frozen=True)
class Interpretation:
    """Everything one ``interpret()`` call produces for the CLI/UI."""

    status: Status
    spec: StrategySpec | None = None
    rendering: str = ""
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    resolved_symbol: str | None = None
    data_summary: dict[str, Any] | None = None
    bars: Bars | None = None
    bars_meta: BarsMeta | None = None
    #: The five Appendix-E ``manifest["nl"]`` keys with
    #: ``user_confirmed_at=None``; ``run_confirmed`` stamps the timestamp.
    nl_meta: dict[str, Any] | None = None
    #: Set if and only if ``status == "error"`` (the exact typed error).
    error: NlbtError | None = None


def interpret(
    text: str,
    *,
    client: LLMClient,
    provider: DataProvider,
    today: date | None = None,
    strict: bool = True,
    data_symbol_override: str | None = None,
) -> Interpretation:
    """Translate ``text`` and verify the symbol against real data (S9).

    Never raises ``NlbtError`` (only programming errors may escape); never
    fetches more than once; never invents a fallback ticker (Q1).

    ``data_symbol_override`` is the raw ``provider.get_bars`` first argument
    (``nlbt ask --data-csv`` passes the file path there -- for ``CSVProvider``
    the ``symbol`` argument IS the path), while ``resolved_symbol`` always
    stays ``spec.universe.symbols[0]``, the ticker the user sees (Q5).
    """
    try:
        parsed = parse_text(text, client=client, today=today, strict=strict)
    except NlbtError as exc:
        return Interpretation(status="error", error=exc)

    if parsed.status == "needs_clarification":
        return Interpretation(
            status="needs_clarification",
            questions=list(parsed.questions),
            unsupported=list(parsed.unsupported),
        )
    if parsed.status == "unsupported":
        return Interpretation(
            status="unsupported",
            unsupported=list(parsed.unsupported),
        )
    if parsed.status != "ok":
        return Interpretation(
            status="error",
            error=EngineInvariantError(
                f"parser returned an unknown status {parsed.status!r}",
                details={"status": parsed.status},
                hint="This is an nlbt bug; please report it.",
            ),
        )
    if parsed.spec is None:
        return Interpretation(
            status="error",
            error=EngineInvariantError(
                "parser returned status ok without a spec",
                hint="This is an nlbt bug; please report it.",
            ),
        )

    spec = parsed.spec
    validation = validate_spec(spec, today=today)
    if validation.errors:  # unreachable: parse_text validated the same spec
        return Interpretation(
            status="error",
            error=EngineInvariantError(
                "semantic validation failed after a successful parse",
                details={
                    "errors": [
                        {"code": err.code, "path": err.path, "message": err.message}
                        for err in validation.errors
                    ]
                },
                hint="This is an nlbt bug; please report it.",
            ),
        )

    resolved_symbol = spec.universe.symbols[0]
    fetch_symbol = data_symbol_override if data_symbol_override is not None else resolved_symbol
    try:
        bars, meta = provider.get_bars(
            fetch_symbol,
            spec.period.start,
            spec.period.end,
            interval=spec.universe.interval,
            adjusted=False,
        )
    except DataEmptyError:
        # Q1/P6-T5: clarify; never an invented alternative symbol.
        return Interpretation(
            status="needs_clarification",
            questions=[
                {
                    "id": DATA_EMPTY_QUESTION_ID,
                    "question": (
                        f"I couldn't find data for {resolved_symbol}. Which symbol did you mean?"
                    ),
                }
            ],
            resolved_symbol=resolved_symbol,
        )
    except NlbtError as exc:
        # A bad CSV / dead network is an error, not an ambiguous request.
        return Interpretation(status="error", error=exc, resolved_symbol=resolved_symbol)

    assumptions = [assumption.model_dump(mode="json") for assumption in parsed.assumptions]
    return Interpretation(
        status="ok",
        spec=spec,
        rendering=render_spec(spec),
        assumptions=assumptions,
        warnings=list(validation.warnings),
        unsupported=list(parsed.unsupported),
        resolved_symbol=resolved_symbol,
        data_summary={
            "provider": meta.provider,
            "symbol": resolved_symbol,
            "interval": spec.universe.interval,
            "adjusted": meta.adjusted,
            "bars": len(bars),
            "start": bars.index.min().date().isoformat(),
            "end": bars.index.max().date().isoformat(),
        },
        bars=bars,
        bars_meta=meta,
        nl_meta={
            "llm_model": parsed.llm_model,
            "prompt_version": parsed.prompt_version,
            "llm_source": parsed.llm_source,
            "assumptions": assumptions,
            "user_confirmed_at": None,
        },
    )


def confirm_spec(
    spec: StrategySpec,
    *,
    confirmed_via: ConfirmedVia,
    now: datetime | None = None,
) -> Confirmation:
    """Freeze what the user confirmed: both hashes + timestamp + channel.

    ``now`` is injectable so tests can assert the recorded timestamp
    exactly (same pattern as ``execute_run(now=...)``).
    """
    confirmed_at = now if now is not None else datetime.now(UTC)
    return Confirmation(
        spec_hash_logic=spec_hash_logic(spec),
        spec_hash_full=spec_hash_full(spec),
        user_confirmed_at=confirmed_at.isoformat(),
        confirmed_via=confirmed_via,
    )


def require_confirmation(spec: StrategySpec, confirmation: Confirmation | None) -> Confirmation:
    """Validate a confirmation against the CURRENT spec; raise if invalid.

    * ``confirmation is None`` -> :class:`UnconfirmedSpecError` (never run
      unconfirmed -- Gate 7).
    * either hash differs -> the spec was EDITED after confirmation, so the
      confirmation is invalid and must be obtained again (P6-T10).
    """
    if confirmation is None:
        raise UnconfirmedSpecError(
            "The spec has not been confirmed",
            details={"spec_hash_logic": spec_hash_logic(spec)},
            hint="Confirm the rendered spec first (interactive prompt, --yes, or the UI button).",
        )
    logic_now = spec_hash_logic(spec)
    full_now = spec_hash_full(spec)
    if confirmation.spec_hash_logic != logic_now or confirmation.spec_hash_full != full_now:
        raise UnconfirmedSpecError(
            "The spec changed after it was confirmed",
            details={
                "confirmed_spec_hash_logic": confirmation.spec_hash_logic,
                "spec_hash_logic": logic_now,
                "confirmed_spec_hash_full": confirmation.spec_hash_full,
                "spec_hash_full": full_now,
            },
            hint="Review the edited spec and confirm it again.",
        )
    return confirmation


def run_confirmed(
    interp: Interpretation,
    confirmation: Confirmation | None,
    *,
    data_source: dict[str, Any] | None = None,
    runs_dir: Path | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> RunResult:
    """The ONLY path from an Interpretation to ``execute_run`` (Gate 7).

    Order: status gate first (``error``/``needs_clarification``/``unsupported``
    can never run, confirmation or not), then :func:`require_confirmation`,
    then ``execute_run`` on the SAME bars ``interpret()`` already fetched --
    exactly one provider call per confirmed run.
    """
    if interp.status == "error":
        if interp.error is None:
            raise EngineInvariantError(
                "interpretation has status=error but carries no error object",
                hint="This is an nlbt bug; please report it.",
            )
        raise interp.error
    if interp.status == "needs_clarification":
        raise NLAmbiguousError(
            "The request needs clarification before it can run",
            hint="Answer the question and interpret the request again.",
        ).with_questions(interp.questions)
    if interp.status == "unsupported" or interp.unsupported:
        raise NLUnsupportedError(
            "The request contains features nlbt cannot express; strict mode refuses to run",
            details={"unsupported": interp.unsupported},
            hint="Rephrase without the unsupported features (see the unsupported list).",
        )
    if interp.status != "ok":
        raise EngineInvariantError(
            f"unexpected interpretation status {interp.status!r}",
            details={"status": interp.status},
            hint="This is an nlbt bug; please report it.",
        )
    if interp.spec is None or interp.bars is None or interp.nl_meta is None:
        raise EngineInvariantError(
            "status ok interpretation is missing spec, bars or nl_meta",
            hint="This is an nlbt bug; please report it.",
        )
    confirmed = require_confirmation(interp.spec, confirmation)
    nl_meta = {**interp.nl_meta, "user_confirmed_at": confirmed.user_confirmed_at}
    return execute_run(
        interp.spec,
        interp.bars,
        meta=interp.bars_meta,
        data_source=data_source,
        runs_dir=runs_dir,
        persist=persist,
        now=now,
        nl_meta=nl_meta,
    )
