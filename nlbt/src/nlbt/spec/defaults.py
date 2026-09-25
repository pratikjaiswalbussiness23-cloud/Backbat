"""Single source of truth for nlbt's default values (ROADMAP §4.4, P3-T6).

This module is DATA, not logic: constants and lookup tables only. The LLM
prompt, the parser, the renderer and the validator all read from
``DEFAULTS``; no other module may hardcode a default value (enforced by
the AST scanner in tests/unit/test_spec_defaults.py, canary test 47).

``resolve_date_range`` is the module's single permitted function: it
RESOLVES a date range FROM a stored default (``lookback_years``); it does
not compute or store any default itself.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class NlbtDefaults:
    """Every defaultable value in nlbt, stored as data (§4.4)."""

    initial_capital: float = 100_000.0
    initial_currency: str = "USD"
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    fixed_fee: float = 0.0
    sizing_method: str = "percent_of_equity"
    sizing_value: float = 100.0
    allow_fractional: bool = True
    fill: str = "next_open"
    lookback_years: float = 5.0
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    interval: str = "1d"


#: The one instance every consumer reads.
DEFAULTS = NlbtDefaults()


#: Conditions under which the parser MUST ask for clarification instead of
#: applying a default (§4.4).
MUST_ASK: tuple[str, ...] = (
    "symbol_not_identifiable",
    "entry_logic_missing",
    "entry_logic_purely_qualitative",
    "indicator_period_missing",
    "stop_target_mentioned_without_number",
    "contradictory_instructions",
    "direction_unclear",
)


@dataclass(frozen=True)
class PhraseEntry:
    """One row of the canonical English-phrase table (§4.4).

    Attributes:
        phrase: The English phrase.
        description: What it maps to, in words.
        indicator_type: e.g. ``"rsi"``, ``"sma"``; None where not applicable.
        indicator_params: e.g. ``{"period": 14}``; None where not
        applicable. Typed ``dict[str, int]`` (every v1 row stores integer
        indicator params; widen deliberately if a future row needs more).
        op: e.g. ``"<"``, ``"crosses_above"``; None where not applicable.
        threshold: e.g. ``30.0``, ``70.0``; None where not applicable.
        notes: Disambiguation notes.
    """

    phrase: str
    description: str
    indicator_type: str | None
    indicator_params: dict[str, int] | None
    op: str | None
    threshold: float | None
    notes: str = ""


#: Canonical phrase table, verbatim from the task text (§4.4).
PHRASE_TABLE: tuple[PhraseEntry, ...] = (
    PhraseEntry(
        phrase="RSI oversold",
        description="RSI(14) is strictly below 30",
        indicator_type="rsi",
        indicator_params={"period": 14},
        op="<",
        threshold=30.0,
    ),
    PhraseEntry(
        phrase="RSI overbought",
        description="RSI(14) is strictly above 70",
        indicator_type="rsi",
        indicator_params={"period": 14},
        op=">",
        threshold=70.0,
    ),
    PhraseEntry(
        phrase="golden cross",
        description="SMA(50) crosses above SMA(200)",
        indicator_type="sma",
        indicator_params={"period": 50},
        op="crosses_above",
        threshold=None,
        notes="slow SMA period=200",
    ),
    PhraseEntry(
        phrase="death cross",
        description="SMA(50) crosses below SMA(200)",
        indicator_type="sma",
        indicator_params={"period": 50},
        op="crosses_below",
        threshold=None,
        notes="slow SMA period=200",
    ),
    PhraseEntry(
        phrase="MACD crossover",
        description="MACD line crosses above signal line",
        indicator_type="macd",
        indicator_params={"fast": 12, "slow": 26, "signal": 9},
        op="crosses_above",
        threshold=None,
        notes="macd.line crosses_above macd.signal",
    ),
    PhraseEntry(
        phrase="MACD bullish",
        description="MACD line crosses above signal line",
        indicator_type="macd",
        indicator_params={"fast": 12, "slow": 26, "signal": 9},
        op="crosses_above",
        threshold=None,
        notes="macd.line crosses_above macd.signal",
    ),
    PhraseEntry(
        phrase="price above the 200 day average",
        description="close is strictly above SMA(200)",
        indicator_type="sma",
        indicator_params={"period": 200},
        op=">",
        threshold=None,
        notes="raw_column close vs sma(200)",
    ),
    PhraseEntry(
        phrase="N-day high breakout",
        description="close is strictly above highest(N)",
        indicator_type="highest",
        indicator_params=None,
        op=">",
        threshold=None,
        notes="N is user-supplied; highest excludes current bar",
    ),
    PhraseEntry(
        phrase="under X",
        description="strictly below X",
        indicator_type=None,
        indicator_params=None,
        op="<",
        threshold=None,
        notes="strict inequality; X is user-supplied",
    ),
    PhraseEntry(
        phrase="below X",
        description="strictly below X",
        indicator_type=None,
        indicator_params=None,
        op="<",
        threshold=None,
        notes="strict inequality; X is user-supplied",
    ),
    PhraseEntry(
        phrase="at least X",
        description="at or above X",
        indicator_type=None,
        indicator_params=None,
        op=">=",
        threshold=None,
        notes="inclusive; X is user-supplied",
    ),
    PhraseEntry(
        phrase="X or more",
        description="at or above X",
        indicator_type=None,
        indicator_params=None,
        op=">=",
        threshold=None,
        notes="inclusive; X is user-supplied",
    ),
    PhraseEntry(
        phrase="above X",
        description="strictly above X",
        indicator_type=None,
        indicator_params=None,
        op=">",
        threshold=None,
        notes="strict inequality; X is user-supplied",
    ),
    PhraseEntry(
        phrase="crosses above",
        description="crosses above (crossover event)",
        indicator_type=None,
        indicator_params=None,
        op="crosses_above",
        threshold=None,
        notes="distinct from 'above' which is a comparison",
    ),
    PhraseEntry(
        phrase="crosses below",
        description="crosses below (crossover event)",
        indicator_type=None,
        indicator_params=None,
        op="crosses_below",
        threshold=None,
        notes="distinct from 'below' which is a comparison",
    ),
)


def get_phrase(phrase: str) -> PhraseEntry | None:
    """Return the FIRST table entry whose phrase matches, case-insensitively.

    The table order is significant: the first row wins (§4.4).
    """
    wanted = phrase.casefold()
    for entry in PHRASE_TABLE:
        if entry.phrase.casefold() == wanted:
            return entry
    return None


def resolve_date_range(
    today: date,
    lookback_years: float | None = None,
) -> tuple[date, date]:
    """Resolve a ``(start, end)`` backtest window ending at ``today``.

    ``lookback_years`` None means DEFAULTS.lookback_years (§4.4: defaults
    are read from here, never hardcoded at call sites). The start is
    ``today.year - int(lookback_years)`` with month/day unchanged; a Feb 29
    start in a non-leap target year falls back to Feb 28 (2023-02-29 does
    not exist, so 1 year back from 2024-02-29 is 2023-02-28).
    """
    years = DEFAULTS.lookback_years if lookback_years is None else lookback_years
    try:
        start = date(today.year - int(years), today.month, today.day)
    except ValueError:
        # Only reachable when (month, day) is invalid in the target year:
        # Feb 29 in a non-leap year.
        if today.month == 2 and today.day == 29 and not calendar.isleap(today.year - int(years)):
            start = date(today.year - int(years), 2, 28)
        else:
            raise
    return (start, today)
