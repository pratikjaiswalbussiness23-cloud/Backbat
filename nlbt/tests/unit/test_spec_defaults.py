"""P3-T6 tests: defaults registry + phrase table (nlbt.spec.defaults).

Sections mirror the task's numbered tests 1-47:

1. DEFAULTS VALUES (1-11): exact literal values + frozen-ness.
2. SINGLE SOURCE OF TRUTH (12): AST scan over every src/nlbt/*.py EXCEPT
   defaults.py itself -- no simple assignment may hardcode fee_bps = 5(.0)
   or initial_capital = 100000(.0). Canary test 47 proves the scanner
   actually fires.
3. PHRASE TABLE (13-27): one test per entry, 15 entries.
4. LOOKUP (28-32): case-insensitive first-match semantics.
5. BOUNDARY WORDING (33-37): strict vs inclusive vs crossover ops, with
   the WHY in each docstring (F-category eval cases, §4.4).
6. DATE RESOLUTION (38-42): hand-computed windows incl. the Feb-29 edge.
7. MUST-ASK (43-46).
CANARY (47): the test-12 scanner run against a planted violation.

All expected values are literals from the task text or hand-computed
arithmetic shown in the docstrings (AGENTS.md: never invent values).
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import date
from pathlib import Path
from types import ModuleType

from nlbt.spec.defaults import (
    DEFAULTS,
    MUST_ASK,
    PHRASE_TABLE,
    NlbtDefaults,
    PhraseEntry,
    get_phrase,
    resolve_date_range,
)

#: tests/unit/test_spec_defaults.py -> parents[2] = nlbt/ (project root).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src" / "nlbt"


def _find_hardcoded(
    source: str,
    name: str,
    value: float,
) -> bool:
    """True if `source` contains `name = <numeric literal value>`.

    Matches only SIMPLE assignments (ast.Assign with ast.Name targets)
    whose value is a numeric Constant equal to `value` (int or float:
    the task says "a numeric literal 5", so 5 and 5.0 both violate).
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        literal = node.value.value
        if not isinstance(literal, (int, float)) or isinstance(literal, bool):
            continue
        if literal != value:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return True
    return False


# ---------------------------------------------------------------------------
# SECTION 1: defaults are correct values (tests 1-11)
# ---------------------------------------------------------------------------


def test_01_default_initial_capital() -> None:
    assert DEFAULTS.initial_capital == 100_000.0


def test_02_default_fee_bps() -> None:
    assert DEFAULTS.fee_bps == 5.0


def test_03_default_slippage_bps() -> None:
    assert DEFAULTS.slippage_bps == 5.0


def test_04_default_sizing_method() -> None:
    assert DEFAULTS.sizing_method == "percent_of_equity"


def test_05_default_sizing_value() -> None:
    assert DEFAULTS.sizing_value == 100.0


def test_06_default_rsi_period() -> None:
    assert DEFAULTS.rsi_period == 14


def test_07_default_rsi_oversold() -> None:
    assert DEFAULTS.rsi_oversold == 30.0


def test_08_default_rsi_overbought() -> None:
    assert DEFAULTS.rsi_overbought == 70.0


def test_09_default_lookback_years() -> None:
    assert DEFAULTS.lookback_years == 5.0


def test_10_default_fill() -> None:
    assert DEFAULTS.fill == "next_open"


def test_11_defaults_frozen() -> None:
    """NlbtDefaults is dataclass(frozen=True): mutation must raise."""
    assert NlbtDefaults.__dataclass_params__.frozen is True
    try:
        DEFAULTS.fee_bps = 9.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("DEFAULTS is mutable; must be frozen")
    # And the attempted write left the value untouched.
    assert DEFAULTS.fee_bps == 5.0


# ---------------------------------------------------------------------------
# SECTION 2: single source of truth (test 12)
# ---------------------------------------------------------------------------


def test_12_no_hardcoded_defaults_elsewhere() -> None:
    """No file under src/nlbt/ (EXCEPT defaults.py) hardcodes the defaults.

    Task wording: assert no other file contains an assignment where the
    target name is "fee_bps" with numeric literal 5, likewise
    "initial_capital" with 100000. Implemented with ast (not a raw string
    grep) so that unrelated text (docstrings, attribute READS like
    ``spec.execution.fee_bps``, comparisons) never false-positives.
    """
    checked = 0
    for path in sorted(SRC_DIR.rglob("*.py")):
        if path.name == "defaults.py":
            continue
        found_fee = _find_hardcoded(path.read_text(encoding="utf-8"), "fee_bps", 5.0)
        found_cap = _find_hardcoded(path.read_text(encoding="utf-8"), "initial_capital", 100000.0)
        assert not found_fee, f"hardcoded fee_bps default in {path}"
        assert not found_cap, f"hardcoded initial_capital default in {path}"
        checked += 1
    assert checked > 0, "scanner scanned no files; test would pass vacuously"


# ---------------------------------------------------------------------------
# SECTION 3: phrase table, one test per entry (tests 13-27)
# ---------------------------------------------------------------------------


def test_13_rsi_oversold() -> None:
    entry = get_phrase("RSI oversold")
    assert entry is not None
    assert entry.op == "<"
    assert entry.threshold == 30.0
    assert entry.indicator_type == "rsi"
    assert entry.indicator_params == {"period": 14}


def test_14_rsi_overbought() -> None:
    entry = get_phrase("RSI overbought")
    assert entry is not None
    assert entry.op == ">"
    assert entry.threshold == 70.0
    assert entry.indicator_type == "rsi"
    assert entry.indicator_params == {"period": 14}


def test_15_golden_cross() -> None:
    entry = get_phrase("golden cross")
    assert entry is not None
    assert entry.op == "crosses_above"
    assert entry.indicator_type == "sma"
    assert entry.indicator_params == {"period": 50}


def test_16_death_cross() -> None:
    entry = get_phrase("death cross")
    assert entry is not None
    assert entry.op == "crosses_below"
    assert entry.indicator_type == "sma"
    assert entry.indicator_params == {"period": 50}


def test_17_macd_crossover() -> None:
    entry = get_phrase("MACD crossover")
    assert entry is not None
    assert entry.op == "crosses_above"
    assert entry.indicator_type == "macd"
    assert entry.indicator_params == {"fast": 12, "slow": 26, "signal": 9}


def test_18_macd_bullish() -> None:
    entry = get_phrase("MACD bullish")
    assert entry is not None
    assert entry.op == "crosses_above"
    assert entry.indicator_type == "macd"
    assert entry.indicator_params == {"fast": 12, "slow": 26, "signal": 9}


def test_19_price_above_200_day_average() -> None:
    entry = get_phrase("price above the 200 day average")
    assert entry is not None
    assert entry.op == ">"
    assert entry.indicator_type == "sma"
    assert entry.indicator_params == {"period": 200}


def test_20_n_day_high_breakout() -> None:
    entry = get_phrase("N-day high breakout")
    assert entry is not None
    assert entry.op == ">"
    assert entry.indicator_type == "highest"
    assert entry.indicator_params is None


def test_21_under_x() -> None:
    entry = get_phrase("under X")
    assert entry is not None
    assert entry.op == "<"


def test_22_below_x() -> None:
    entry = get_phrase("below X")
    assert entry is not None
    assert entry.op == "<"


def test_23_at_least_x() -> None:
    entry = get_phrase("at least X")
    assert entry is not None
    assert entry.op == ">="


def test_24_x_or_more() -> None:
    entry = get_phrase("X or more")
    assert entry is not None
    assert entry.op == ">="


def test_25_above_x() -> None:
    entry = get_phrase("above X")
    assert entry is not None
    assert entry.op == ">"


def test_26_crosses_above() -> None:
    entry = get_phrase("crosses above")
    assert entry is not None
    assert entry.op == "crosses_above"


def test_27_crosses_below() -> None:
    entry = get_phrase("crosses below")
    assert entry is not None
    assert entry.op == "crosses_below"


def test_phrase_table_has_exactly_15_entries() -> None:
    """Guard for the one-test-per-entry contract: 15 rows, each a PhraseEntry."""
    assert len(PHRASE_TABLE) == 15
    for entry in PHRASE_TABLE:
        assert isinstance(entry, PhraseEntry)
    # And every row is reachable through get_phrase (no orphan rows).
    for entry in PHRASE_TABLE:
        assert get_phrase(entry.phrase) is entry


# ---------------------------------------------------------------------------
# SECTION 4: phrase lookup (tests 28-32)
# ---------------------------------------------------------------------------


def test_28_get_phrase_exact_case() -> None:
    assert get_phrase("RSI oversold") is PHRASE_TABLE[0]


def test_29_get_phrase_case_insensitive_lower() -> None:
    assert get_phrase("rsi oversold") is PHRASE_TABLE[0]


def test_30_get_phrase_case_insensitive_upper() -> None:
    assert get_phrase("RSI OVERSOLD") is PHRASE_TABLE[0]


def test_31_get_phrase_unknown_returns_none() -> None:
    assert get_phrase("unknown phrase") is None


def test_32_get_phrase_golden_not_death() -> None:
    entry = get_phrase("golden cross")
    assert entry is not None
    assert entry.op == "crosses_above"
    assert entry is not get_phrase("death cross")
    assert entry.description == "SMA(50) crosses above SMA(200)"


# ---------------------------------------------------------------------------
# SECTION 5: boundary wording tests (tests 33-37)
# ---------------------------------------------------------------------------


def test_33_under_x_is_strict_not_inclusive() -> None:
    """WHY the boundary matters: "under 30" means RSI < 30, not RSI <= 30.

    A difference that matters at exactly RSI=30: a strategy reading "RSI
    under 30" must NOT fire when RSI is exactly 30. Mapping "under" to
    "<=" would silently widen the entry condition by one whole price
    regime (the classic oversold threshold).
    """
    entry = get_phrase("under X")
    assert entry is not None
    assert entry.op == "<"
    assert entry.op != "<="


def test_34_at_least_x_is_inclusive_not_strict() -> None:
    """WHY the boundary matters: "at least 5" means X >= 5, not X > 5.

    At exactly the threshold the condition MUST hold: "buy when RSI is at
    least 70" includes RSI == 70. Mapping "at least" to ">" would drop
    the boundary bar and change every signal that fires exactly at the
    threshold.
    """
    entry = get_phrase("at least X")
    assert entry is not None
    assert entry.op == ">="
    assert entry.op != ">"


def test_35_above_x_is_strict_not_inclusive() -> None:
    """WHY the boundary matters: "above 200" means X > 200, not X >= 200.

    The mirror of test 34: "close above the 200 day average" must NOT
    fire on an exact touch (close == SMA). Mapping "above" to ">=" would
    turn boundary touches into signals.
    """
    entry = get_phrase("above X")
    assert entry is not None
    assert entry.op == ">"
    assert entry.op != ">="


def test_36_crosses_above_is_event_not_comparison() -> None:
    """WHY the boundary matters: "crosses above" is a crossover EVENT.

    Mapping "crosses above" to ">" would compare a single bar instead of
    two: a value that was ALWAYS above the line (never crossed) would
    falsely fire on every bar. The event semantics require prev <= line
    AND now > line; the op string encodes which engine branch runs.
    """
    entry = get_phrase("crosses above")
    assert entry is not None
    assert entry.op == "crosses_above"
    assert entry.op != ">"


def test_37_boundary_docstrings_present() -> None:
    """Each of tests 33-36 carries a WHY docstring (task section 5.37)."""
    for name in (
        "test_33_under_x_is_strict_not_inclusive",
        "test_34_at_least_x_is_inclusive_not_strict",
        "test_35_above_x_is_strict_not_inclusive",
        "test_36_crosses_above_is_event_not_comparison",
    ):
        doc = getattr(import_current_module(), name).__doc__ or ""
        assert "WHY" in doc, f"{name} lacks a WHY docstring"


def import_current_module() -> ModuleType:
    """Import this test module by name (helper for test 37's introspection)."""
    import sys

    return sys.modules[__name__]


# ---------------------------------------------------------------------------
# SECTION 6: date resolution (tests 38-42)
# ---------------------------------------------------------------------------


def test_38_default_lookback_five_years() -> None:
    """Hand computation: 5 years back from 2024-01-15 is 2019-01-15.

    2024 - 5 = 2019; month (1) and day (15) unchanged; 2019-01-15 exists.
    """
    assert resolve_date_range(date(2024, 1, 15)) == (date(2019, 1, 15), date(2024, 1, 15))


def test_39_explicit_three_year_lookback() -> None:
    """Hand computation: 3 years back from 2024-01-15 is 2021-01-15.

    2024 - 3 = 2021; month/day unchanged.
    """
    result = resolve_date_range(date(2024, 1, 15), lookback_years=3.0)
    assert result == (date(2021, 1, 15), date(2024, 1, 15))


def test_40_one_year_lookback_across_leap_boundary() -> None:
    """Hand computation: 1 year back from 2024-03-01 is 2023-03-01.

    2024 is a leap year but the WINDOW START lands in 2023 (not a leap
    year); (month, day) = (3, 1) exists in any year, so no fallback.
    """
    result = resolve_date_range(date(2024, 3, 1), lookback_years=1.0)
    assert result == (date(2023, 3, 1), date(2024, 3, 1))


def test_41_feb29_falls_back_to_feb28() -> None:
    """Hand computation: 1 year back from 2024-02-29 is 2023-02-28.

    date(2024 - 1, 2, 29) = date(2023, 2, 29) does not exist (2023 is not
    a leap year: 2023 % 4 != 0). The fallback clamps day 29 -> 28, giving
    (2023-02-28, 2024-02-29). The end date stays 2024-02-29 (2024 IS a
    leap year: 2024 % 4 == 0 and 2024 % 100 != 0).
    """
    result = resolve_date_range(date(2024, 2, 29), lookback_years=1.0)
    assert result == (date(2023, 2, 28), date(2024, 2, 29))


def test_42_none_uses_defaults_lookback() -> None:
    """lookback_years=None reads DEFAULTS.lookback_years (5.0).

    Hand computation: 2024 - int(5.0) = 2019; from 2024-06-01 the window
    is (2019-06-01, 2024-06-01). Also: passing DEFAULTS.lookback_years
    explicitly must give the SAME window.
    """
    today = date(2024, 6, 1)
    result = resolve_date_range(today)
    assert result[0] == date(2019, 6, 1)
    assert result[1] == today
    assert resolve_date_range(today, lookback_years=DEFAULTS.lookback_years) == result


# ---------------------------------------------------------------------------
# SECTION 7: must-ask list (tests 43-46)
# ---------------------------------------------------------------------------


def test_43_must_ask_symbol_not_identifiable() -> None:
    assert "symbol_not_identifiable" in MUST_ASK


def test_44_must_ask_entry_logic_missing() -> None:
    assert "entry_logic_missing" in MUST_ASK


def test_45_must_ask_direction_unclear() -> None:
    assert "direction_unclear" in MUST_ASK


def test_46_must_ask_has_exactly_seven() -> None:
    assert len(MUST_ASK) == 7
    assert isinstance(MUST_ASK, tuple)
    # The full task-mandated vocabulary, no more, no less.
    assert set(MUST_ASK) == {
        "symbol_not_identifiable",
        "entry_logic_missing",
        "entry_logic_purely_qualitative",
        "indicator_period_missing",
        "stop_target_mentioned_without_number",
        "contradictory_instructions",
        "direction_unclear",
    }


# ---------------------------------------------------------------------------
# CANARY (test 47)
# ---------------------------------------------------------------------------


def test_47_ast_scanner_catches_planted_violation() -> None:
    """Prove the test-12 scanner WORKS: it must catch a planted violation.

    If fee_bps were hardcoded in TWO places, changing one would not change
    the other -- the AST search in test 12 is the canary guarding that.
    A canary that can never fire proves nothing, so this test runs the
    same matching logic against a temp code string containing a hardcoded
    ``fee_bps = 5.0`` and asserts it IS found. Test 12 passing therefore
    means there genuinely are no violations.
    """
    fake_code = "fee_bps = 5.0\nx = 1"
    tree = ast.parse(fake_code)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (
                    isinstance(t, ast.Name)
                    and t.id == "fee_bps"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value == 5.0
                ):
                    found = True
    assert found, "AST scanner did not find hardcoded value"
    # The shared helper agrees with the inline canary logic...
    assert _find_hardcoded(fake_code, "fee_bps", 5.0) is True
    # ...and does NOT fire on a different value (5 != 5.0 edge would be a
    # false-negative factory) nor on a read of the attribute.
    assert _find_hardcoded("fee_bps = 9.0", "fee_bps", 5.0) is False
    assert _find_hardcoded("x.fee_bps = 5.0\ny = 1", "fee_bps", 5.0) is False
