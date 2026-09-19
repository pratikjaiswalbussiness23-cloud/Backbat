"""Error taxonomy — ROADMAP.md §4.8, implemented verbatim.

Every error carries exactly four pieces of information (§4.8):
- ``code``:    the stable ``E_*`` string from the §4.8 table (machine-readable ID)
- ``message``: human-readable description of what went wrong
- ``details``: machine-readable dict (e.g. field paths, offending values, questions)
- ``hint``:    what the user should change

Design notes:
- One base class :class:`NlbtError`; one subclass per §4.8 row; each subclass pins
  its ``code`` as a class-level constant so the code survives pickling/logging and
  cannot drift from the taxonomy.
- No silent defaults that hide information: ``details`` defaults to an *empty dict*
  (not a fabricated payload) and ``hint`` to an *empty string* (not advice we did
  not actually compute). Callers must supply what they know.
- Exceptions are plain classes; the ``extra="forbid"`` rule applies to the pydantic
  spec models (§3), not here.
- Instances are intentionally immutable-ish (``__slots__``): errors carry evidence;
  mutating them after the fact would corrupt reports.

HTTP mapping (for the later HTTP API phase, P8): §4.8 assigns a status code to
each ``E_*``; it lives in ``HTTP_STATUS`` so the mapping cannot drift either.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ERROR_CODES",
    "HTTP_STATUS",
    "DataEmptyError",
    "DataProviderError",
    "DataQualityError",
    "EngineInvariantError",
    "LimitExceededError",
    "NLAmbiguousError",
    "NLLlmError",
    "NLUnsupportedError",
    "NlbtError",
    "SpecRangeError",
    "SpecRefError",
    "SpecSchemaError",
]


class NlbtError(Exception):
    """Base class for every nlbt error (ROADMAP §4.8).

    Raises subclasses only; catching ``NlbtError`` catches the whole taxonomy.
    """

    #: The §4.8 code string; every subclass MUST override this.
    code: str = "E_UNKNOWN"

    __slots__ = ("details", "hint", "message")

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        hint: str = "",
    ) -> None:
        """``details=None`` normalises to ``{}`` so callers never get None back."""
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = {} if details is None else details
        self.hint = hint

    def __str__(self) -> str:
        """``[CODE] message (hint: ...)`` — the CLI prints this verbatim (P7-T1)."""
        base = f"[{self.code}] {self.message}"
        return f"{base} (hint: {self.hint})" if self.hint else base

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, message={self.message!r}, "
            f"details={self.details!r}, hint={self.hint!r})"
        )


# --------------------------------------------------------------------------
# Spec errors (§4.8 rows 1-3, HTTP 422)
# --------------------------------------------------------------------------


class SpecSchemaError(NlbtError):
    """Strategy Spec violates the JSON schema (§4.1)."""

    code = "E_SPEC_SCHEMA"


class SpecRefError(NlbtError):
    """Unknown indicator/operand/output reference in the spec."""

    code = "E_SPEC_REF"


class SpecRangeError(NlbtError):
    """Parameter out of bounds, bad dates."""

    code = "E_SPEC_RANGE"


# --------------------------------------------------------------------------
# Data errors (§4.8 rows 4-6)
# --------------------------------------------------------------------------


class DataEmptyError(NlbtError):
    """Provider returned nothing (bad ticker/range)."""

    code = "E_DATA_EMPTY"


class DataQualityError(NlbtError):
    """Data failed blocking validation (§4.2)."""

    code = "E_DATA_QUALITY"


class DataProviderError(NlbtError):
    """Provider/network failure."""

    code = "E_DATA_PROVIDER"


# --------------------------------------------------------------------------
# NL layer errors (§4.8 rows 7-9) — note rows 7-8 are *status* errors:
# §4.8 maps them to HTTP 200 with status=needs_clarification / unsupported,
# so they are normal control flow for the NL endpoint, not crashes.
# --------------------------------------------------------------------------


class NLAmbiguousError(NlbtError):
    """Needs clarification; ``details["questions"]`` carries the questions.

    §4.8: "Needs clarification (carries questions)". By convention the questions
    live in ``details["questions"]`` (list of dicts with ``id``/``question``);
    see :meth:`with_questions` for the canonical constructor.
    """

    code = "E_NL_AMBIGUOUS"

    def with_questions(self, questions: list[dict[str, Any]]) -> NLAmbiguousError:
        """Return a copy carrying ``questions`` in ``details["questions"]``.

        Returns a new instance (exceptions are effectively immutable here) so a
        partially-built error can be enriched without mutating a shared one.
        """
        merged = dict(self.details)
        merged["questions"] = questions
        return NLAmbiguousError(self.message, details=merged, hint=self.hint)


class NLUnsupportedError(NlbtError):
    """Requested feature not expressible in the DSL (§5, S5 ``unsupported`` list)."""

    code = "E_NL_UNSUPPORTED"


class NLLlmError(NlbtError):
    """LLM call or repair loop failed (repair cap = 2 rounds, S4)."""

    code = "E_NL_LLM"


# --------------------------------------------------------------------------
# Engine / limits (§4.8 rows 10-11)
# --------------------------------------------------------------------------


class EngineInvariantError(NlbtError):
    """Internal invariant broken (a bug) — §8.3. Never caught and papered over."""

    code = "E_ENGINE_INVARIANT"


class LimitExceededError(NlbtError):
    """Bars/combos/size limits exceeded (§3.5 NLBT_MAX_* guards)."""

    code = "E_LIMIT_EXCEEDED"


#: §4.8 HTTP status per code, kept beside the classes so the two cannot drift.
#: Rows 7-8 intentionally map to 200 (the endpoint *succeeds* with a status body).
HTTP_STATUS: dict[str, int] = {
    SpecSchemaError.code: 422,
    SpecRefError.code: 422,
    SpecRangeError.code: 422,
    DataEmptyError.code: 404,
    DataQualityError.code: 422,
    DataProviderError.code: 502,
    NLAmbiguousError.code: 200,
    NLUnsupportedError.code: 200,
    NLLlmError.code: 502,
    EngineInvariantError.code: 500,
    LimitExceededError.code: 413,
}

#: Every concrete §4.8 code, in table order — the taxonomy is closed under this set.
ERROR_CODES: tuple[str, ...] = tuple(HTTP_STATUS)
