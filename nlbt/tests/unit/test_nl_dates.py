"""P6-T6: date resolution (``nlbt.nl.dates``) — table-driven, fixed ``today`` (S10).

Hand-computed expectations (AGENTS.md: never invent expected values):

``last_n_years`` keeps month/day and subtracts ``n`` years, reusing the
Feb-29 rule of ``spec/defaults.resolve_date_range`` (2023 is not a leap year,
2020 is):
  2024-02-29 - 1y = 2023-02-28,   2024-02-29 - 4y = 2020-02-29.

``last_n_months`` subtracts whole months and clamps the day to the last day
of the target month:
  2026-01-31 - 1m  = 2025-12-31 (December has 31 days)
  2026-03-31 - 1m  = 2026-02-28 (February 2026 has 28 days)
  2024-02-29 - 12m = 2023-02-28 (clamp again)

``since_year`` = Jan 1 of ``year`` .. ``today``. ``during_year`` = the full
calendar year, clipped to ``today`` when it is the current year. ``between``
= Jan 1 of ``start_year`` .. Dec 31 of ``end_year``, clipped to ``today``
when ``end_year`` is the current year.

Invalid expressions (future years, ``start_year > end_year``, ``n < 1``,
``start == end``) raise ``SpecRangeError`` (§4.8 ``E_SPEC_RANGE``, the "bad
dates" row). A source scan pins S10: ``dates.py`` never reads a clock.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from nlbt.errors import SpecRangeError
from nlbt.nl.dates import (
    Between,
    DuringYear,
    LastNMonths,
    LastNYears,
    SinceYear,
    resolve_period,
)
from nlbt.nl.envelope import Envelope, envelope_schema, flatten_schema
from nlbt.spec.models import Period

#: tests/unit/test_nl_dates.py -> parents[2] = nlbt/ (project root).
DATES_PY = Path(__file__).resolve().parents[2] / "src" / "nlbt" / "nl" / "dates.py"


# --------------------------------------------------------------------- valid
VALID_CASES = [
    pytest.param(
        LastNYears(kind="last_n_years", n=3),
        date(2026, 10, 26),
        date(2023, 10, 26),
        date(2026, 10, 26),
        id="last_n_years-3-20261026",
    ),
    pytest.param(
        LastNYears(kind="last_n_years", n=1),
        date(2024, 2, 29),
        date(2023, 2, 28),  # 2023 not a leap year: Feb 29 -> Feb 28
        date(2024, 2, 29),
        id="last_n_years-1-leap-fallback-20240229",
    ),
    pytest.param(
        LastNYears(kind="last_n_years", n=4),
        date(2024, 2, 29),
        date(2020, 2, 29),  # 2020 IS a leap year: Feb 29 kept
        date(2024, 2, 29),
        id="last_n_years-4-leap-kept-20240229",
    ),
    pytest.param(
        LastNMonths(kind="last_n_months", n=1),
        date(2026, 1, 31),
        date(2025, 12, 31),  # December has 31 days
        date(2026, 1, 31),
        id="last_n_months-1-20260131",
    ),
    pytest.param(
        LastNMonths(kind="last_n_months", n=1),
        date(2026, 3, 31),
        date(2026, 2, 28),  # February 2026 has 28 days: clamp
        date(2026, 3, 31),
        id="last_n_months-1-clamp-20260331",
    ),
    pytest.param(
        LastNMonths(kind="last_n_months", n=12),
        date(2024, 2, 29),
        date(2023, 2, 28),  # 2023-02-29 does not exist: clamp
        date(2024, 2, 29),
        id="last_n_months-12-leap-clamp-20240229",
    ),
    pytest.param(
        SinceYear(kind="since_year", year=2020),
        date(2026, 10, 26),
        date(2020, 1, 1),
        date(2026, 10, 26),
        id="since_year-2020-20261026",
    ),
    pytest.param(
        DuringYear(kind="during_year", year=2022),
        date(2026, 10, 26),
        date(2022, 1, 1),
        date(2022, 12, 31),  # past year: full calendar year
        id="during_year-2022-past-20261026",
    ),
    pytest.param(
        DuringYear(kind="during_year", year=2024),
        date(2024, 2, 29),
        date(2024, 1, 1),
        date(2024, 2, 29),  # current year: clipped to today (leap day)
        id="during_year-2024-clipped-20240229",
    ),
    pytest.param(
        DuringYear(kind="during_year", year=2026),
        date(2026, 1, 31),
        date(2026, 1, 1),
        date(2026, 1, 31),  # current year: clipped to today
        id="during_year-2026-clipped-20260131",
    ),
    pytest.param(
        Between(kind="between", start_year=2020, end_year=2022),
        date(2026, 10, 26),
        date(2020, 1, 1),
        date(2022, 12, 31),  # past end_year: Dec 31
        id="between-2020-2022-past-20261026",
    ),
    pytest.param(
        Between(kind="between", start_year=2024, end_year=2026),
        date(2026, 10, 26),
        date(2024, 1, 1),
        date(2026, 10, 26),  # current end_year: clipped to today
        id="between-2024-2026-clipped-20261026",
    ),
]


@pytest.mark.parametrize(("expr", "today", "expected_start", "expected_end"), VALID_CASES)
def test_resolve_period_valid_cases(
    expr: Any,
    today: date,
    expected_start: date,
    expected_end: date,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve, assert the spec window invariants, and validate as a Period."""
    start, end = resolve_period(expr, today)

    assert (start, end) == (expected_start, expected_end)
    # spec/models.py Period: start < end <= today (with today INJECTED).
    assert start < end <= today
    # The Period model's clock is frozen at the injected today (models.py:88).
    monkeypatch.setattr("nlbt.spec.models._get_today", lambda: today)
    validated = Period.model_validate({"start": start, "end": end})
    assert (validated.start, validated.end) == (expected_start, expected_end)


# ------------------------------------------------------------------- invalid
INVALID_CASES = [
    pytest.param(DuringYear(kind="during_year", year=2030), date(2026, 10, 26), id="during-future"),
    pytest.param(SinceYear(kind="since_year", year=2027), date(2026, 10, 26), id="since-future"),
    pytest.param(
        Between(kind="between", start_year=2020, end_year=2030),
        date(2026, 10, 26),
        id="between-future-end",
    ),
    pytest.param(
        Between(kind="between", start_year=2027, end_year=2028),
        date(2026, 10, 26),
        id="between-future-start",
    ),
    pytest.param(
        Between(kind="between", start_year=2022, end_year=2020),
        date(2026, 10, 26),
        id="between-start-after-end",
    ),
    pytest.param(LastNYears(kind="last_n_years", n=0), date(2026, 10, 26), id="n-lt-1"),
    pytest.param(
        DuringYear(kind="during_year", year=2026),
        date(2026, 1, 1),
        id="start-eq-end-jan1",
    ),
]


@pytest.mark.parametrize(("expr", "today"), INVALID_CASES)
def test_resolve_period_invalid_cases(expr: Any, today: date) -> None:
    """Every invalid expression raises the typed §4.8 date error."""
    with pytest.raises(SpecRangeError) as excinfo:
        resolve_period(expr, today)

    assert excinfo.value.code == "E_SPEC_RANGE"
    assert excinfo.value.message  # never empty
    assert excinfo.value.hint  # actionable


# ------------------------------------------------------- envelope schema level
GOOD_EXPRESSIONS: list[dict[str, Any]] = [
    {"kind": "last_n_years", "n": 3},
    {"kind": "last_n_months", "n": 6},
    {"kind": "since_year", "year": 2020},
    {"kind": "during_year", "year": 2022},
    {"kind": "between", "start_year": 2020, "end_year": 2022},
]

BAD_EXPRESSIONS: list[Any] = [
    {"kind": "last_n_decades", "n": 3},  # unknown kind (discriminator tag)
    "last 3 years",  # string instead of object
    {"kind": "last_n_years"},  # missing n
    {"kind": "between", "start_year": 2020},  # missing end_year
    {},  # missing kind
    {"kind": "since_year", "year": 2020, "bogus": 1},  # unknown field (extra=forbid)
]
BAD_IDS = [
    "unknown-kind",
    "string-not-object",
    "missing-n",
    "missing-end-year",
    "missing-kind",
    "unknown-field",
]


@pytest.mark.parametrize(
    "value", GOOD_EXPRESSIONS, ids=[entry["kind"] for entry in GOOD_EXPRESSIONS]
)
def test_envelope_accepts_each_period_expression_form(value: dict[str, Any]) -> None:
    """The wire shape is a closed set of five structured forms."""
    envelope = Envelope.model_validate({"status": "ok", "period_expression": value})

    assert envelope.period_expression is not None
    assert envelope.period_expression.kind == value["kind"]


@pytest.mark.parametrize(
    ("value", "why"),
    list(zip(BAD_EXPRESSIONS, BAD_IDS, strict=True)),
    ids=BAD_IDS,
)
def test_envelope_rejects_bad_period_expression(value: Any, why: str) -> None:
    """Schema-level rejection: shape problems never reach resolve_period."""
    with pytest.raises(ValidationError):
        Envelope.model_validate({"status": "ok", "period_expression": value})


def test_flattened_and_raw_schemas_agree_on_the_union() -> None:
    """flatten_schema must change NOTHING about accept/reject verdicts (P6-T1)."""
    union_samples: list[tuple[dict[str, Any], bool]] = [
        *(({"status": "ok", "period_expression": entry}, True) for entry in GOOD_EXPRESSIONS),
        ({"status": "ok", "period_expression": None}, True),
        ({"status": "ok"}, True),
        *(({"status": "ok", "period_expression": entry}, False) for entry in BAD_EXPRESSIONS),
    ]

    raw_validator = jsonschema.Draft202012Validator(envelope_schema())
    flat_schema = flatten_schema(envelope_schema())
    assert "$defs" not in flat_schema
    flat_validator = jsonschema.Draft202012Validator(flat_schema)

    raw_verdicts = [not list(raw_validator.iter_errors(doc)) for doc, _ in union_samples]
    flat_verdicts = [not list(flat_validator.iter_errors(doc)) for doc, _ in union_samples]
    expected = [verdict for _, verdict in union_samples]
    assert raw_verdicts == expected, "raw envelope schema verdict diverged"
    assert flat_verdicts == expected, "flattened envelope schema verdict diverged"


# --------------------------------------------------------------- purity (S10)
def test_dates_module_never_reads_the_real_clock() -> None:
    """S10 source scan: dates.py never calls date.today()/datetime.now()."""
    tree = ast.parse(DATES_PY.read_text(encoding="utf-8"))
    clock_access = sorted(
        f"line {node.lineno}: .{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"today", "now", "utcnow"}
    )

    assert clock_access == [], f"resolve_period must take today as an argument: {clock_access}"
