"""P6-T6: structured period expressions resolved to ISO dates in code (S10).

The LLM emits a :class:`PeriodExpression` discriminated union — a closed set
of five structured forms — and NEVER emits dates for a relative expression
(ROADMAP S10, P6-T6). :func:`resolve_period` is a pure function of
``(expr, today)``: it never reads a clock, so tests pin every rule with a
fixed ``today``.

Resolution rules (all outputs satisfy ``start < end <= today``, the
``spec/models.Period`` invariant):

* ``last_n_years`` — ``end = today``; ``start`` keeps today's month/day and
  subtracts ``n`` years, falling back to Feb 28 when a Feb 29 start lands in
  a non-leap year (identical to ``spec/defaults.resolve_date_range``:
  2024-02-29 - 1y = 2023-02-28, - 4y = 2020-02-29).
* ``last_n_months`` — ``end = today``; ``start`` subtracts ``n`` whole
  months and clamps the day to the last day of the target month
  (2026-01-31 - 1m = 2025-12-31; 2026-03-31 - 1m = 2026-02-28).
* ``since_year`` — ``start = Jan 1 of year``, ``end = today``.
* ``during_year`` — the full calendar year, but ``end`` is clipped to
  ``today`` when ``year`` is the current year (so ``start < end`` still
  holds; Jan 1 of the current year with ``today = Jan 1`` degenerates and
  raises ``E_SPEC_RANGE``).
* ``between`` — ``start = Jan 1 of start_year``, ``end = Dec 31 of
  end_year``, clipped to ``today`` when ``end_year`` is the current year.

Future years, ``start_year > end_year``, ``n < 1`` and any degenerate window
raise :class:`nlbt.errors.SpecRangeError` (§4.8 "bad dates" row, code
``E_SPEC_RANGE``) — the typed date error, which the parser feeds into the
bounded repair loop.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from nlbt.errors import SpecRangeError

__all__ = [
    "Between",
    "DuringYear",
    "LastNMonths",
    "LastNYears",
    "PeriodExpression",
    "SinceYear",
    "resolve_period",
]


class _PeriodExpressionBase(BaseModel):
    """Closed shape: an unknown field from the model is a validation failure."""

    model_config = ConfigDict(extra="forbid")


class LastNYears(_PeriodExpressionBase):
    """``"last n years"`` — a window of ``n`` whole years ending at ``today``."""

    kind: Literal["last_n_years"]
    n: int = Field(description="Whole years to look back; must be >= 1")


class LastNMonths(_PeriodExpressionBase):
    """``"last n months"`` — a window of ``n`` whole months ending at ``today``."""

    kind: Literal["last_n_months"]
    n: int = Field(description="Whole months to look back; must be >= 1")


class SinceYear(_PeriodExpressionBase):
    """``"since <year>"`` — Jan 1 of ``year`` through ``today``."""

    kind: Literal["since_year"]
    year: int


class DuringYear(_PeriodExpressionBase):
    """``"during <year>"`` — one calendar year, clipped to ``today`` if current."""

    kind: Literal["during_year"]
    year: int


class Between(_PeriodExpressionBase):
    """``"from <start_year> to <end_year>"`` — inclusive calendar years."""

    kind: Literal["between"]
    start_year: int
    end_year: int


#: The wire form: a discriminated union on ``kind`` (JSON Schema anyOf of
#: exactly these five objects; pydantic enforces the closed vocabulary).
PeriodExpression = Annotated[
    LastNYears | LastNMonths | SinceYear | DuringYear | Between,
    Field(discriminator="kind"),
]


def _range_error(message: str, *, hint: str, **details: object) -> SpecRangeError:
    """The typed §4.8 date error, always with an actionable hint."""
    return SpecRangeError(message, details=details, hint=hint)


def _resolve_years(n: int, today: date) -> tuple[date, date]:
    if n < 1:
        raise _range_error(
            f"last_n_years n must be >= 1, got {n}",
            hint='Use {"kind": "last_n_years", "n": 1} or larger.',
            kind="last_n_years",
            n=n,
        )
    try:
        start = date(today.year - n, today.month, today.day)
    except ValueError:
        # (month, day) invalid in the target year: Feb 29 in a non-leap year.
        if today.month == 2 and today.day == 29 and not calendar.isleap(today.year - n):
            start = date(today.year - n, 2, 28)
        else:
            raise
    return start, today


def _resolve_months(n: int, today: date) -> tuple[date, date]:
    if n < 1:
        raise _range_error(
            f"last_n_months n must be >= 1, got {n}",
            hint='Use {"kind": "last_n_months", "n": 1} or larger.',
            kind="last_n_months",
            n=n,
        )
    total = today.year * 12 + (today.month - 1) - n
    year, zero_based_month = divmod(total, 12)
    month = zero_based_month + 1
    # Clamp to the target month's last day (2026-01-31 - 1m = 2025-12-31;
    # 2026-03-31 - 1m = 2026-02-28).
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day), today


def _check_future(year: int, today: date, *, kind: str) -> None:
    if year > today.year:
        raise _range_error(
            f"{kind} year {year} is in the future (today is {today.isoformat()})",
            hint=f"Use a year <= {today.year}, or omit the period to take nlbt's default.",
            kind=kind,
            year=year,
            today=today.isoformat(),
        )


def resolve_period(expr: PeriodExpression, today: date) -> tuple[date, date]:
    """Resolve ``expr`` against the INJECTED ``today`` to ``(start, end)``.

    Pure (S10): no clock access, no I/O — every rule is a function of
    ``expr`` and ``today`` only. Raises ``SpecRangeError`` (``E_SPEC_RANGE``)
    for future years, reversed ranges, ``n < 1`` and degenerate windows.
    """
    if isinstance(expr, LastNYears):
        start, end = _resolve_years(expr.n, today)
    elif isinstance(expr, LastNMonths):
        start, end = _resolve_months(expr.n, today)
    elif isinstance(expr, SinceYear):
        _check_future(expr.year, today, kind=expr.kind)
        start, end = date(expr.year, 1, 1), today
    elif isinstance(expr, DuringYear):
        _check_future(expr.year, today, kind=expr.kind)
        start = date(expr.year, 1, 1)
        end = today if expr.year == today.year else date(expr.year, 12, 31)
    elif isinstance(expr, Between):
        if expr.start_year > expr.end_year:
            raise _range_error(
                f"between start_year {expr.start_year} is after end_year {expr.end_year}",
                hint="Give start_year <= end_year.",
                start_year=expr.start_year,
                end_year=expr.end_year,
            )
        _check_future(expr.end_year, today, kind=expr.kind)
        start = date(expr.start_year, 1, 1)
        end = today if expr.end_year == today.year else date(expr.end_year, 12, 31)
    else:  # pragma: no cover - the discriminated union makes this unreachable
        raise _range_error(
            f"unknown period_expression kind {expr.kind!r}",
            hint="Use one of: last_n_years, last_n_months, since_year, during_year, between.",
            kind=str(expr.kind),
        )

    if start >= end:
        raise _range_error(
            f"resolved period is empty: start {start.isoformat()} is not before "
            f"end {end.isoformat()}",
            hint=(
                "Pick a period that spans more than one day (e.g. a full year "
                "for a current-year expression)."
            ),
            start=start.isoformat(),
            end=end.isoformat(),
            today=today.isoformat(),
        )
    if end > today:
        raise _range_error(
            f"resolved period end {end.isoformat()} is in the future "
            f"(today is {today.isoformat()})",
            hint=f"Use an end date <= {today.isoformat()}.",
            end=end.isoformat(),
            today=today.isoformat(),
        )
    return start, end
