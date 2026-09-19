"""Tests for the §4.8 error taxonomy (nlbt.errors).

Independent acceptance checks (P0-T4):
- every §4.8 code can be raised and caught as the common base ``NlbtError``
- every error exposes the four §4.8 fields: ``code``, ``message``, ``details``, ``hint``
- every subclass pins the exact §4.8 code string as a class constant
- ``E_NL_AMBIGUOUS`` carries a questions list in ``details`` (§4.8 row 7)

Expected values are the literal strings from ROADMAP §4.8 (the contract table),
not outputs of the implementation.
"""

from __future__ import annotations

import pytest

from nlbt.errors import (
    ERROR_CODES,
    HTTP_STATUS,
    DataEmptyError,
    DataProviderError,
    DataQualityError,
    EngineInvariantError,
    LimitExceededError,
    NLAmbiguousError,
    NlbtError,
    NLLlmError,
    NLUnsupportedError,
    SpecRangeError,
    SpecRefError,
    SpecSchemaError,
)

# (class, exact §4.8 code string) — transcribed from the ROADMAP §4.8 table.
TAXONOMY: list[tuple[type[NlbtError], str]] = [
    (SpecSchemaError, "E_SPEC_SCHEMA"),
    (SpecRefError, "E_SPEC_REF"),
    (SpecRangeError, "E_SPEC_RANGE"),
    (DataEmptyError, "E_DATA_EMPTY"),
    (DataQualityError, "E_DATA_QUALITY"),
    (DataProviderError, "E_DATA_PROVIDER"),
    (NLAmbiguousError, "E_NL_AMBIGUOUS"),
    (NLUnsupportedError, "E_NL_UNSUPPORTED"),
    (NLLlmError, "E_NL_LLM"),
    (EngineInvariantError, "E_ENGINE_INVARIANT"),
    (LimitExceededError, "E_LIMIT_EXCEEDED"),
]


def test_taxonomy_matches_roadmap_4_8_exactly() -> None:
    """The implemented set must equal the 11 §4.8 codes, no more, no fewer."""
    expected = [
        "E_SPEC_SCHEMA",
        "E_SPEC_REF",
        "E_SPEC_RANGE",
        "E_DATA_EMPTY",
        "E_DATA_QUALITY",
        "E_DATA_PROVIDER",
        "E_NL_AMBIGUOUS",
        "E_NL_UNSUPPORTED",
        "E_NL_LLM",
        "E_ENGINE_INVARIANT",
        "E_LIMIT_EXCEEDED",
    ]
    assert list(ERROR_CODES) == expected
    assert len(TAXONOMY) == 11


@pytest.mark.parametrize(("exc_class", "code"), TAXONOMY)
def test_raises_and_catches_as_base(exc_class: type[NlbtError], code: str) -> None:
    """Every §4.8 error is raisable and catchable as ``NlbtError`` (P0-T4)."""
    with pytest.raises(NlbtError) as excinfo:
        raise exc_class(f"boom for {code}")
    assert excinfo.value.code == code
    assert type(excinfo.value) is exc_class


@pytest.mark.parametrize(("exc_class", "code"), TAXONOMY)
def test_four_fields_present(exc_class: type[NlbtError], code: str) -> None:
    """Every error carries code/message/details/hint (§4.8 closing sentence)."""
    err = exc_class("something failed", details={"k": "v"}, hint="try X")
    assert err.code == code
    assert err.message == "something failed"
    assert err.details == {"k": "v"}
    assert err.hint == "try X"


@pytest.mark.parametrize(("exc_class", "code"), TAXONOMY)
def test_no_silent_defaults(exc_class: type[NlbtError], code: str) -> None:
    """details defaults to empty dict, hint to empty string — never fabricated."""
    err = exc_class("bare")
    assert err.details == {}
    assert err.hint == ""
    assert err.message == "bare"


@pytest.mark.parametrize(("exc_class", "code"), TAXONOMY)
def test_code_is_class_level_constant(exc_class: type[NlbtError], code: str) -> None:
    """The code lives on the class and equals the §4.8 string."""
    assert exc_class.code == code
    assert isinstance(exc_class.code, str)


def test_ambiguous_error_carries_questions_list() -> None:
    """§4.8 row 7: E_NL_AMBIGUOUS 'carries questions' — via details['questions']."""
    questions = [
        {"id": "q1", "question": "Which moving average period did you mean?"},
        {"id": "q2", "question": "Should entry be on cross or on close confirmation?"},
    ]
    err = NLAmbiguousError("strategy description is ambiguous")
    enriched = err.with_questions(questions)
    assert enriched.code == "E_NL_AMBIGUOUS"
    assert enriched.details["questions"] == questions


def test_http_status_mapping_matches_roadmap() -> None:
    """The HTTP column of §4.8, transcribed: incl. 200 for rows 7-8."""
    assert HTTP_STATUS["E_SPEC_SCHEMA"] == 422
    assert HTTP_STATUS["E_SPEC_REF"] == 422
    assert HTTP_STATUS["E_SPEC_RANGE"] == 422
    assert HTTP_STATUS["E_DATA_EMPTY"] == 404
    assert HTTP_STATUS["E_DATA_QUALITY"] == 422
    assert HTTP_STATUS["E_DATA_PROVIDER"] == 502
    assert HTTP_STATUS["E_NL_AMBIGUOUS"] == 200
    assert HTTP_STATUS["E_NL_UNSUPPORTED"] == 200
    assert HTTP_STATUS["E_NL_LLM"] == 502
    assert HTTP_STATUS["E_ENGINE_INVARIANT"] == 500
    assert HTTP_STATUS["E_LIMIT_EXCEEDED"] == 413


def test_str_includes_hint_and_code() -> None:
    """Human rendering carries code and hint (CLI prints it verbatim, P7-T1)."""
    err = SpecRangeError("period must be >= 2", details={"field": "period"}, hint="use 2..500")
    assert "[E_SPEC_RANGE]" in str(err)
    assert "period must be >= 2" in str(err)
    assert "use 2..500" in str(err)
