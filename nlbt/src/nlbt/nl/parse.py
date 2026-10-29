"""P6-T3: text -> forced structured output -> pydantic -> semantic, bounded repair.

Contract (ROADMAP.md:620-623):

* validation chain: Envelope pydantic -> StrategySpec pydantic -> semantic
  ``validate_spec`` -> deterministic L4 gates (must-ask, unsupported blocking,
  stop/target detection);
* on failure the EXACT validation errors are fed back verbatim, at most
  ``MAX_REPAIR_ROUNDS = 2`` rounds; after that ``E_NL_LLM`` is raised and NO
  partial result is ever returned (S4/C4);
* temperature is always 0.0 and the input length is capped before any LLM
  call (``E_LIMIT_EXCEEDED``);
* defaults come only from ``spec/defaults.py`` (S6) and every applied default
  is disclosed in ``assumptions[]``;
* an unknown indicator can never surface as ``ok``: it fails semantic
  validation with ``E_SPEC_REF`` and lands in the repair loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from pydantic import ValidationError

from nlbt.errors import LimitExceededError, NLLlmError, SpecRangeError
from nlbt.nl.client import LLMResponse
from nlbt.nl.dates import PeriodExpression, resolve_period
from nlbt.nl.envelope import Envelope
from nlbt.nl.prompt import ASSUMPTION_FIELDS, PROMPT_VERSION, build_system_prompt
from nlbt.spec.defaults import DEFAULTS, MUST_ASK, resolve_date_range
from nlbt.spec.models import Assumption, StrategySpec
from nlbt.spec.validate import validate_spec

__all__ = [
    "MAX_INPUT_CHARS",
    "MAX_REPAIR_ROUNDS",
    "STOP_QUESTION",
    "ParseResult",
    "build_user_message",
    "parse_text",
    "pydantic_error_dicts",
    "semantic_error_dicts",
]

#: Hard input cap, checked BEFORE any LLM call (E_LIMIT_EXCEEDED, §4.8).
MAX_INPUT_CHARS = 4_000

#: Hard repair cap: initial response + at most 2 repairs (S4). Never tunable.
MAX_REPAIR_ROUNDS = 2

#: Deterministic must-ask question for a stop/target mentioned without a number.
STOP_QUESTION = "What stop-loss percentage should exit the position?"

#: Markers delimiting the user's text INSIDE the user message (data, S12).
USER_TEXT_BEGIN = "<<<NLBT_USER_TEXT>>>"
USER_TEXT_END = "<<<END_NLBT_USER_TEXT>>>"

#: Markers delimiting the exact validation errors fed back in a repair round.
ERRORS_BEGIN = "<<<NLBT_VALIDATION_ERRORS>>>"
ERRORS_END = "<<<END_NLBT_VALIDATION_ERRORS>>>"

#: Envelope statuses that never carry a spec.
_NO_SPEC_STATUSES = frozenset({"needs_clarification", "unsupported"})

_REASON = "nlbt default (spec/defaults.py)"

#: Reason recorded for dates code-resolved from a period_expression (P6-T6).
_PERIOD_RESOLVED_REASON = "resolved from period_expression (injected clock)"

#: spec dotted-path -> the DEFAULTS value (S6: the ONLY source of defaults).
_MANAGED_DEFAULTS: dict[str, Any] = {
    "universe.interval": DEFAULTS.interval,
    "capital.initial": DEFAULTS.initial_capital,
    "execution.fee_bps": DEFAULTS.fee_bps,
    "execution.slippage_bps": DEFAULTS.slippage_bps,
    "execution.fixed_fee": DEFAULTS.fixed_fee,
    "execution.fill": DEFAULTS.fill,
    "sizing.method": DEFAULTS.sizing_method,
    "sizing.value": DEFAULTS.sizing_value,
    "sizing.allow_fractional": DEFAULTS.allow_fractional,
}


@dataclass(frozen=True)
class ParseResult:
    """Everything P6-T3 produces (P6-T4/P6-T10 consume it)."""

    status: str  # ok | needs_clarification | unsupported
    spec: StrategySpec | None = None
    questions: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    period_expression: PeriodExpression | None = None
    llm_model: str = ""
    prompt_version: str = PROMPT_VERSION
    llm_source: str = "recorded"


class _ParserClient(Protocol):
    """Structural type of the P6-T1 client the parser needs (test-friendly)."""

    def complete_structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> LLMResponse: ...


def pydantic_error_dicts(exc: ValidationError) -> list[dict[str, Any]]:
    """Exact pydantic errors as plain dicts (fed back VERBATIM on repair)."""
    return [
        {"path": ".".join(str(part) for part in err["loc"]), "message": err["msg"]}
        for err in exc.errors()
    ]


def semantic_error_dicts(errors: list[Any]) -> list[dict[str, Any]]:
    return [
        {"code": err.code, "path": err.path, "message": err.message, "hint": err.hint}
        for err in errors
    ]


def build_user_message(text: str, *, repair_errors: list[dict[str, Any]] | None = None) -> str:
    """Delimit the user text as DATA; append exact errors verbatim if repairing."""
    parts = [
        f"{USER_TEXT_BEGIN}\n{text}\n{USER_TEXT_END}",
        "Translate the text between the markers into the nlbt envelope JSON.",
    ]
    if repair_errors is not None:
        rendered = json.dumps(repair_errors, indent=1, ensure_ascii=False)
        parts.append(
            "Your previous response was rejected. Fix EXACTLY these validation errors "
            "(verbatim):"
            f"\n{ERRORS_BEGIN}\n{rendered}\n{ERRORS_END}"
        )
    parts.append("Respond with the envelope JSON object only.")
    return "\n\n".join(parts)


def _check_input(text: str) -> None:
    if len(text) > MAX_INPUT_CHARS:
        raise LimitExceededError(
            "Input too long to translate",
            details={"reason": "input_too_long", "limit": MAX_INPUT_CHARS, "length": len(text)},
            hint=f"Shorten the request to at most {MAX_INPUT_CHARS} characters.",
        )
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise LimitExceededError(
            "Input contains characters that are not valid UTF-8",
            details={"reason": "non_utf8_input", "position": exc.start},
            hint="Resend the request as plain UTF-8 text.",
        ) from exc


def _apply_defaults(spec_dict: dict[str, Any], today: date) -> list[Assumption]:
    """Fill managed fields ONLY from DEFAULTS; record each applied default (S6).

    Omitted managed fields are filled by code; a value equal to the registry
    default (whether echoed by the model or filled here) is disclosed in
    ``assumptions``. ``period`` is filled from the injected clock via
    ``resolve_date_range`` (S10: dates resolved by code, never by the model).
    """
    assumptions: list[Assumption] = []

    universe = spec_dict.setdefault("universe", {})
    if universe.get("interval") is None:
        universe["interval"] = DEFAULTS.interval
    if universe["interval"] == DEFAULTS.interval:
        assumptions.append(
            Assumption(field="universe.interval", value=DEFAULTS.interval, reason=_REASON)
        )

    capital = spec_dict.setdefault("capital", {})
    if "initial" not in capital:
        capital["initial"] = DEFAULTS.initial_capital
    if capital["initial"] == DEFAULTS.initial_capital:
        assumptions.append(
            Assumption(field="capital.initial", value=DEFAULTS.initial_capital, reason=_REASON)
        )

    execution = spec_dict.setdefault("execution", {})
    for key, default in (
        ("fill", DEFAULTS.fill),
        ("fee_bps", DEFAULTS.fee_bps),
        ("slippage_bps", DEFAULTS.slippage_bps),
        ("fixed_fee", DEFAULTS.fixed_fee),
    ):
        if execution.get(key) is None:
            execution[key] = default
        if execution[key] == default:
            assumptions.append(Assumption(field=f"execution.{key}", value=default, reason=_REASON))

    sizing = spec_dict.setdefault("sizing", {})
    if "method" not in sizing:
        sizing["method"] = DEFAULTS.sizing_method
    if sizing["method"] == DEFAULTS.sizing_method:
        assumptions.append(
            Assumption(field="sizing.method", value=DEFAULTS.sizing_method, reason=_REASON)
        )
    if "value" not in sizing:
        sizing["value"] = DEFAULTS.sizing_value
    if sizing["value"] == DEFAULTS.sizing_value:
        assumptions.append(
            Assumption(field="sizing.value", value=DEFAULTS.sizing_value, reason=_REASON)
        )
    if "allow_fractional" not in sizing:
        sizing["allow_fractional"] = DEFAULTS.allow_fractional
    if sizing["allow_fractional"] == DEFAULTS.allow_fractional:
        assumptions.append(
            Assumption(
                field="sizing.allow_fractional", value=DEFAULTS.allow_fractional, reason=_REASON
            )
        )

    if spec_dict.get("period") is None:
        start, end = resolve_date_range(today)
        spec_dict["period"] = {"start": start.isoformat(), "end": end.isoformat()}
        assumptions.append(
            Assumption(field="period.start", value=start.isoformat(), reason=_REASON)
        )
        assumptions.append(Assumption(field="period.end", value=end.isoformat(), reason=_REASON))

    return assumptions


def _merge_assumptions(
    payload: dict[str, Any], code_assumptions: list[Assumption]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Enforce S6: model assumptions must be allowed fields equal to code's."""
    errors: list[dict[str, Any]] = []
    merged: list[dict[str, Any]] = [
        {"field": a.field, "value": a.value, "reason": a.reason} for a in code_assumptions
    ]
    known = {a["field"]: a["value"] for a in merged}
    for index, raw in enumerate(payload.get("assumptions", [])):
        path = raw.get("field")
        if path not in ASSUMPTION_FIELDS:
            errors.append(
                {
                    "code": "E_NL_ASSUMPTION",
                    "path": f"assumptions[{index}].field",
                    "message": f"assumption field {path!r} is not an allowed managed field",
                    "hint": f"Allowed fields: {', '.join(ASSUMPTION_FIELDS)}.",
                }
            )
            continue
        if path in known and raw.get("value") != known[path]:
            errors.append(
                {
                    "code": "E_NL_ASSUMPTION",
                    "path": f"assumptions[{index}].value",
                    "message": (
                        f"assumption {path} claims {raw.get('value')!r} "
                        f"but the spec says {known[path]!r}"
                    ),
                    "hint": (
                        "Make the assumption value equal the spec value, or drop the assumption."
                    ),
                }
            )
        elif path not in known:
            merged.append(dict(raw))
    return merged, errors


def _validate_once(
    payload: dict[str, Any],
    *,
    text: str,
    today: date,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """One full pass of the validation chain (no repair, no gates).

    Returns ``(sanitized_payload, errors)``; non-empty ``errors`` means the
    response must be repaired. ``sanitized_payload`` is only meaningful when
    there are no errors.
    """
    errors: list[dict[str, Any]] = []

    try:
        envelope = Envelope.model_validate(payload)
    except ValidationError as exc:
        return None, pydantic_error_dicts(exc)

    if envelope.status in _NO_SPEC_STATUSES:
        if envelope.status == "needs_clarification" and not envelope.questions:
            errors.append(
                {
                    "code": "E_NL_ENVELOPE",
                    "path": "questions",
                    "message": "status needs_clarification requires at least one question",
                    "hint": "Ask what is missing, with a must-ask id.",
                }
            )
        for index, question in enumerate(envelope.questions):
            if question.id not in MUST_ASK:
                errors.append(
                    {
                        "code": "E_NL_ENVELOPE",
                        "path": f"questions[{index}].id",
                        "message": f"{question.id!r} is not a must-ask id",
                        "hint": f"Use one of: {', '.join(MUST_ASK)}.",
                    }
                )
        if envelope.status == "unsupported" and not envelope.unsupported:
            errors.append(
                {
                    "code": "E_NL_ENVELOPE",
                    "path": "unsupported",
                    "message": "status unsupported requires a non-empty unsupported list",
                    "hint": "List each inexpressible feature.",
                }
            )
        if envelope.spec is not None:
            errors.append(
                {
                    "code": "E_NL_ENVELOPE",
                    "path": "spec",
                    "message": f"spec must be null when status is {envelope.status}",
                    "hint": "Set spec to null for this status.",
                }
            )
        sanitized: dict[str, Any] | None = (
            None
            if errors
            else {
                "status": envelope.status,
                "questions": [{"id": q.id, "question": q.question} for q in envelope.questions],
                "unsupported": list(envelope.unsupported),
                "period_expression": envelope.period_expression,
            }
        )
        return sanitized, errors

    # ---------------------------------------------------------------- status ok
    if envelope.spec is None:
        return None, [
            {
                "code": "E_NL_ENVELOPE",
                "path": "spec",
                "message": "status ok requires a spec",
                "hint": "Emit the complete StrategySpec, or use needs_clarification.",
            }
        ]
    if envelope.questions:
        errors.append(
            {
                "code": "E_NL_ENVELOPE",
                "path": "questions",
                "message": "status ok must not carry questions",
                "hint": "Use needs_clarification when you must ask.",
            }
        )

    model_provided_period = envelope.spec.get("period") is not None
    spec_dict = dict(envelope.spec)
    resolved_period: tuple[date, date] | None = None
    if envelope.period_expression is not None and model_provided_period:
        # OQ-D (P6-T6): the prompt says "Never output both" — enforced here
        # as a repairable E_NL_ENVELOPE error, never a silent pick.
        errors.append(
            {
                "code": "E_NL_ENVELOPE",
                "path": "period_expression",
                "message": "spec.period and period_expression are mutually exclusive",
                "hint": (
                    "Omit spec.period for a relative expression, or omit "
                    "period_expression for explicit calendar dates."
                ),
            }
        )
    elif envelope.period_expression is not None:
        # P6-T6/S10: code resolves the structured expression against the
        # INJECTED clock; the model never produces dates for it.
        try:
            resolved_period = resolve_period(envelope.period_expression, today)
        except SpecRangeError as exc:
            errors.append(
                {
                    "code": exc.code,
                    "path": "period_expression",
                    "message": exc.message,
                    "hint": exc.hint,
                }
            )
        else:
            start, end = resolved_period
            spec_dict["period"] = {"start": start.isoformat(), "end": end.isoformat()}
    code_assumptions = _apply_defaults(spec_dict, today)
    if resolved_period is not None:
        start, end = resolved_period
        code_assumptions.append(
            Assumption(
                field="period.start", value=start.isoformat(), reason=_PERIOD_RESOLVED_REASON
            )
        )
        code_assumptions.append(
            Assumption(field="period.end", value=end.isoformat(), reason=_PERIOD_RESOLVED_REASON)
        )
    try:
        spec_dict["source_text"] = text
        spec = StrategySpec.model_validate(spec_dict)
    except ValidationError as exc:
        return None, [*errors, *pydantic_error_dicts(exc)]

    semantic = validate_spec(spec, today=today)
    if semantic.errors:
        return None, [*errors, *semantic_error_dicts(semantic.errors)]

    merged, assumption_errors = _merge_assumptions(payload, code_assumptions)
    if assumption_errors:
        return None, [*errors, *assumption_errors]

    sanitized = {
        "status": "ok",
        "questions": [],
        "period_expression": envelope.period_expression,
        "unsupported": list(envelope.unsupported),
        "assumptions": merged,
        "model_provided_period": model_provided_period,
        "spec": json.loads(spec.model_dump_json()),
    }
    return sanitized, errors


def _gate_checks(
    sanitized: dict[str, Any],
    *,
    text: str,
    strict: bool,
) -> tuple[str, list[dict[str, Any]] | None, list[str]]:
    """Deterministic L4 gates over a chain-clean payload.

    Returns ``(status, questions_or_None, unsupported)``. The model's own
    needs_clarification/unsupported outcome is preserved; only a model ``ok``
    is subject to the deterministic gates.
    """
    unsupported = [str(item) for item in sanitized.get("unsupported", [])]
    spec_dict = sanitized.get("spec") or {}

    if sanitized["status"] == "needs_clarification":
        return "needs_clarification", list(sanitized.get("questions", [])), unsupported
    if sanitized["status"] == "unsupported":
        # The model refused; there is no spec to run whatever `strict` says.
        return "unsupported", None, unsupported

    if strict and unsupported:
        return "unsupported", None, unsupported
    risk = spec_dict.get("risk") or {}
    if "stop" in text.casefold() and not any(
        risk.get(field) for field in ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct")
    ):
        return (
            "needs_clarification",
            [{"id": "stop_target_mentioned_without_number", "question": STOP_QUESTION}],
            unsupported,
        )
    return "ok", None, unsupported


def get_model_id() -> str:
    """Model id from config (never hard-coded here)."""
    from nlbt.config import get_config

    return get_config().llm_model


def parse_text(
    text: str,
    *,
    client: _ParserClient,
    today: date | None = None,
    strict: bool = True,
    model: str | None = None,
) -> ParseResult:
    """Translate ``text`` into a validated spec (or a typed outcome).

    Raises ``E_LIMIT_EXCEEDED`` on input problems (before any LLM call),
    ``E_NL_LLM`` immediately when the model reports ``status="error"``, and
    ``E_NL_LLM`` when the bounded repair loop is exhausted. Never returns a
    partial or unvalidated spec (S4/C4).
    """
    _check_input(text)
    resolved_today = today if today is not None else date.today()
    system = build_system_prompt()
    user = build_user_message(text)
    schema = Envelope.model_json_schema()
    model_id = model if model is not None else get_model_id()

    last_errors: list[dict[str, Any]] = []
    for attempt in range(1 + MAX_REPAIR_ROUNDS):
        response = client.complete_structured(system, user, schema, temperature=0.0, model=model_id)
        payload = response.payload
        if payload.get("status") == "error":
            raise NLLlmError(
                "The model reported that it could not translate the text",
                details={"reason": "envelope_status_error", "rounds": attempt},
                hint="Rephrase the request with a concrete indicator and condition.",
            )
        sanitized, errors = _validate_once(payload, text=text, today=resolved_today)
        if errors:
            last_errors = errors
            if attempt < MAX_REPAIR_ROUNDS:
                user = build_user_message(text, repair_errors=errors)
            continue
        assert sanitized is not None  # no errors implies a sanitized payload
        status, questions, unsupported = _gate_checks(sanitized, text=text, strict=strict)
        common: dict[str, Any] = {
            "unsupported": unsupported,
            "period_expression": sanitized.get("period_expression"),
            "llm_model": model_id,
            "llm_source": response.source,
        }
        if status == "ok":
            spec = StrategySpec.model_validate(sanitized["spec"])
            return ParseResult(
                status="ok",
                spec=spec,
                assumptions=[Assumption(**a) for a in sanitized["assumptions"]],
                **common,
            )
        if status == "needs_clarification":
            return ParseResult(status="needs_clarification", questions=questions or [], **common)
        return ParseResult(status="unsupported", **common)

    raise NLLlmError(
        "NL parse failed after the bounded repair loop",
        details={"rounds": MAX_REPAIR_ROUNDS, "errors": last_errors},
        hint="Rephrase the request; the exact validation errors are in details.errors.",
    )
