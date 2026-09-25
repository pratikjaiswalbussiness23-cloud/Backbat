"""P3-T3 tests: JSON Schema export (nlbt.spec.schema, docs/spec_schema.json).

Sections:

1. STALENESS: the committed docs/spec_schema.json must equal a fresh
   in-memory generation MODULO the volatile ``x-nlbt-generated-at``
   timestamp (P2-T8 precedent). Hand-edits or model/registry changes
   without ``uv run python -m nlbt.spec.schema`` fail here -- CI freshness
   without a CI-only step.
2. STRUCTURE: top-level keys, the registry enum injected into
   ``#/$defs/IndicatorDef/properties/type`` (closed vocabulary, S1/C7),
   and the ``spec_version = "1.0"`` constraint.
3. INDEPENDENT VALIDATION: the ROADMAP acceptance demands validation
   "using an independent JSON-Schema validator (not pydantic)" -- every
   check here runs through jsonschema's Draft202012Validator (probed in
   verified_apis.md, including that FormatChecker ENFORCES ``format:
   "date"`` on this install). The fixtures are the Appendix C specs
   converted to the fully TAGGED wire format (task choice A): the LLM
   emits tagged documents, the generated schema pins exactly that form,
   and the shorthand -> tagged lifting (OQ-0033) stays an INPUT
   convenience that the schema deliberately does not bless.
4. ROUND-TRIP: pydantic-valid implies jsonschema-valid for all three
   fixtures; the committed file is real JSON; generation is idempotent.
5. CANARY: a hallucinated indicator type ("sentiment_analysis") is
   REJECTED by the JSON Schema validator -- the registry enum makes the
   vocabulary closed.

Registry note (OQ-0032): an unrelated test pollutes the GLOBAL registry
mid-suite (adds ``dummy_global_path`` with no cleanup). All generations
in this file therefore use a SNAPSHOT registry, built at IMPORT time
(collection, before any test runs) from the then-clean global REGISTRY.
Snapshot != mock: it registers the real built-in IndicatorSpec objects
in a fresh Registry() (probed: Registry instances are isolated dicts).

This test enforces ROADMAP S1 (closed vocabulary) and C7: the schema is
GENERATED from the models + registry, so validator, docs and prompt can
never drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nlbt.indicators.registry import REGISTRY, Registry
from nlbt.spec.models import StrategySpec
from nlbt.spec.schema import (
    GENERATED_AT_KEY,
    generate_spec_schema,
    validate_with_jsonschema,
)

#: Import-time snapshot of the global registry (OQ-0032 defence, see
#: module docstring). Collection imports every test module BEFORE any
#: test executes, so this captures the clean built-in 12.
_SNAPSHOT_REGISTRY = Registry()
for _name in REGISTRY.list_indicators():
    _SNAPSHOT_REGISTRY.register(REGISTRY.get(_name))

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_SCHEMA_PATH = _PROJECT_ROOT / "docs" / "spec_schema.json"
_STALENESS_MESSAGE = "docs/spec_schema.json is stale. Run: uv run python -m nlbt.spec.schema"


def _load_committed_schema() -> dict[str, Any]:
    raw = COMMITTED_SCHEMA_PATH.read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


def _strip_timestamp(schema: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in schema.items() if k != GENERATED_AT_KEY}


# ---------------------------------------------------------------------------
# Appendix C fixtures in the fully TAGGED wire format (task choice A).
# c1_spec_tagged's docstring carries the full dict, per the task text.
# ---------------------------------------------------------------------------


def c1_spec_tagged() -> dict[str, Any]:
    """Appendix C1 (SMA 50/200 golden cross) in the fully TAGGED wire
    format that the generated schema validates (and that P6 will emit)::

        {
          "spec_version": "1.0",
          "name": "SMA 50/200 golden cross",
          "universe": {"symbols": ["SPY"], "interval": "1d"},
          "period": {"start": "2010-01-01", "end": "2024-12-31"},
          "indicators": {
            "fast": {"type": "sma", "params": {"period": 50}, "source": "close"},
            "slow": {"type": "sma", "params": {"period": 200}, "source": "close"}
          },
          "rules": {
            "entry_long": {
              "kind": "all",
              "conditions": [{
                "kind": "condition",
                "left":  {"kind": "indicator", "name": "fast", "output": "value", "lag": 0},
                "op": "crosses_above",
                "right": {"kind": "indicator", "name": "slow", "output": "value", "lag": 0}
              }]
            },
            "exit_long": {
              "kind": "all",
              "conditions": [{
                "kind": "condition",
                "left":  {"kind": "indicator", "name": "fast", "output": "value", "lag": 0},
                "op": "crosses_below",
                "right": {"kind": "indicator", "name": "slow", "output": "value", "lag": 0}
              }]
            }
          },
          "risk": {},
          "sizing": {"method": "percent_of_equity", "value": 100, "allow_fractional": true},
          "execution": {"fill": "next_open", "fee_bps": 5, "slippage_bps": 5, "fixed_fee": 0},
          "capital": {"initial": 100000, "currency": "USD"}
        }
    """
    fast = {"kind": "indicator", "name": "fast", "output": "value", "lag": 0}
    slow = {"kind": "indicator", "name": "slow", "output": "value", "lag": 0}
    return {
        "spec_version": "1.0",
        "name": "SMA 50/200 golden cross",
        "universe": {"symbols": ["SPY"], "interval": "1d"},
        "period": {"start": "2010-01-01", "end": "2024-12-31"},
        "indicators": {
            "fast": {"type": "sma", "params": {"period": 50}, "source": "close"},
            "slow": {"type": "sma", "params": {"period": 200}, "source": "close"},
        },
        "rules": {
            "entry_long": {
                "kind": "all",
                "conditions": [
                    {"kind": "condition", "left": fast, "op": "crosses_above", "right": slow}
                ],
            },
            "exit_long": {
                "kind": "all",
                "conditions": [
                    {"kind": "condition", "left": fast, "op": "crosses_below", "right": slow}
                ],
            },
        },
        "risk": {},
        "sizing": {"method": "percent_of_equity", "value": 100, "allow_fractional": True},
        "execution": {"fill": "next_open", "fee_bps": 5, "slippage_bps": 5, "fixed_fee": 0},
        "capital": {"initial": 100000, "currency": "USD"},
    }


def c2_spec_tagged() -> dict[str, Any]:
    """Appendix C2 (RSI 2 dip buy above 200 SMA), tagged wire format."""
    return {
        "spec_version": "1.0",
        "name": "RSI 2 dip buy above 200 SMA",
        "universe": {"symbols": ["QQQ"], "interval": "1d"},
        "period": {"start": "2015-01-01", "end": "2024-12-31"},
        "indicators": {
            "rsi2": {"type": "rsi", "params": {"period": 2}, "source": "close"},
            "trend": {"type": "sma", "params": {"period": 200}, "source": "close"},
        },
        "rules": {
            "entry_long": {
                "kind": "all",
                "conditions": [
                    {
                        "kind": "condition",
                        "left": {"kind": "raw_column", "name": "close"},
                        "op": ">",
                        "right": {
                            "kind": "indicator",
                            "name": "trend",
                            "output": "value",
                            "lag": 0,
                        },
                    },
                    {
                        "kind": "condition",
                        "left": {"kind": "indicator", "name": "rsi2", "output": "value", "lag": 0},
                        "op": "<",
                        "right": {"kind": "number", "value": 10},
                    },
                ],
            },
            "exit_long": {
                "kind": "any",
                "conditions": [
                    {
                        "kind": "condition",
                        "left": {"kind": "indicator", "name": "rsi2", "output": "value", "lag": 0},
                        "op": ">",
                        "right": {"kind": "number", "value": 70},
                    }
                ],
            },
        },
        "risk": {"stop_loss_pct": 6, "max_holding_bars": 10},
        "sizing": {"method": "percent_of_equity", "value": 50, "allow_fractional": True},
        "execution": {"fill": "next_open", "fee_bps": 5, "slippage_bps": 5, "fixed_fee": 0},
        "capital": {"initial": 100000, "currency": "USD"},
    }


def c3_spec_tagged() -> dict[str, Any]:
    """Appendix C3 (20-day breakout, 8% trailing stop), tagged wire format."""
    return {
        "spec_version": "1.0",
        "name": "20-day breakout, 8% trailing stop",
        "universe": {"symbols": ["BTC-USD"], "interval": "1d"},
        "period": {"start": "2018-01-01", "end": "2024-12-31"},
        "indicators": {"hh20": {"type": "highest", "params": {"period": 20}, "source": "high"}},
        "rules": {
            "entry_long": {
                "kind": "all",
                "conditions": [
                    {
                        "kind": "condition",
                        "left": {"kind": "raw_column", "name": "close"},
                        "op": ">",
                        "right": {"kind": "indicator", "name": "hh20", "output": "value", "lag": 0},
                    }
                ],
            }
        },
        "risk": {"trailing_stop_pct": 8, "stop_loss_pct": 8},
        "sizing": {"method": "risk_per_trade", "value": 1, "allow_fractional": True},
        "execution": {"fill": "next_open", "fee_bps": 10, "slippage_bps": 10, "fixed_fee": 0},
        "capital": {"initial": 50000, "currency": "USD"},
    }


# ===========================================================================
# SECTION 1 -- staleness
# ===========================================================================


class TestStaleness:
    def test_01_spec_schema_is_not_stale(self) -> None:
        fresh = generate_spec_schema(registry=_SNAPSHOT_REGISTRY)
        committed = _load_committed_schema()
        assert _strip_timestamp(fresh) == _strip_timestamp(committed), _STALENESS_MESSAGE


# ===========================================================================
# SECTION 2 -- schema structure
# ===========================================================================


class TestSchemaStructure:
    def test_02_schema_has_required_top_level_fields(self) -> None:
        schema = _load_committed_schema()
        for key in ("type", "properties", "required", "x-nlbt-version"):
            assert key in schema, f"missing top-level key {key!r}"
        assert schema["x-nlbt-version"] == "1.0"

    def test_03_schema_indicator_type_is_enumerated(self) -> None:
        schema = _load_committed_schema()
        type_node = schema["$defs"]["IndicatorDef"]["properties"]["type"]
        assert "enum" in type_node
        enum = type_node["enum"]
        assert "sma" in enum
        assert "ema" in enum
        builtin = _SNAPSHOT_REGISTRY.list_indicators()
        assert len(builtin) == 12
        assert set(builtin) <= set(enum)
        # The enum is EXACTLY the registry's closed vocabulary, sorted --
        # no extra names an LLM could lean on.
        assert enum == sorted(builtin)
        assert "fake_indicator" not in enum

    def test_04_schema_spec_version_is_constrained(self) -> None:
        schema = _load_committed_schema()
        node = schema["properties"]["spec_version"]
        assert "const" in node or "enum" in node
        constrained = node.get("const") or node.get("enum")
        assert constrained == "1.0"


# ===========================================================================
# SECTION 3 -- independent jsonschema validation (NOT pydantic)
# ===========================================================================


class TestIndependentJsonschemaValidation:
    @pytest.fixture(autouse=True)
    def _schema(self) -> None:
        self.schema = _load_committed_schema()

    def test_05_valid_c1_spec_passes_jsonschema(self) -> None:
        errors = validate_with_jsonschema(c1_spec_tagged(), self.schema)
        assert errors == []

    def test_06_valid_c2_spec_passes_jsonschema(self) -> None:
        errors = validate_with_jsonschema(c2_spec_tagged(), self.schema)
        assert errors == []

    def test_07_valid_c3_spec_passes_jsonschema(self) -> None:
        errors = validate_with_jsonschema(c3_spec_tagged(), self.schema)
        assert errors == []

    def test_08_unknown_indicator_type_fails_jsonschema(self) -> None:
        spec = c1_spec_tagged()
        spec["indicators"]["fast"]["type"] = "fake_indicator"
        errors = validate_with_jsonschema(spec, self.schema)
        assert len(errors) >= 1
        assert any("fake_indicator" in message for message in errors)

    def test_09_missing_required_field_fails_jsonschema(self) -> None:
        spec = c1_spec_tagged()
        del spec["name"]
        errors = validate_with_jsonschema(spec, self.schema)
        assert len(errors) >= 1
        assert any("name" in message for message in errors)

    def test_10_unknown_top_level_field_fails_jsonschema(self) -> None:
        spec = c1_spec_tagged()
        spec["hacker_field"] = "evil"
        errors = validate_with_jsonschema(spec, self.schema)
        assert len(errors) >= 1
        assert any("hacker_field" in message for message in errors)

    def test_10b_shorthand_wire_format_is_not_schema_valid(self) -> None:
        # Choice A pinned: the schema validates the TAGGED wire format
        # only. The Appendix C shorthand (bare operands, untagged
        # rules/conditions) must NOT pass the independent validator --
        # the schema forces the LLM into the explicit form.
        shorthand = {
            "spec_version": "1.0",
            "name": "SMA 50/200 golden cross",
            "universe": {"symbols": ["SPY"], "interval": "1d"},
            "period": {"start": "2010-01-01", "end": "2024-12-31"},
            "indicators": {
                "fast": {"type": "sma", "params": {"period": 50}, "source": "close"},
                "slow": {"type": "sma", "params": {"period": 200}, "source": "close"},
            },
            "rules": {
                "entry_long": {"all": [{"left": "fast", "op": "crosses_above", "right": "slow"}]}
            },
            "risk": {},
            "sizing": {"method": "percent_of_equity", "value": 100, "allow_fractional": True},
            "capital": {"initial": 100000, "currency": "USD"},
        }
        errors = validate_with_jsonschema(shorthand, self.schema)
        assert len(errors) >= 1


# ===========================================================================
# SECTION 4 -- round-trip consistency
# ===========================================================================


class TestRoundTrip:
    @pytest.mark.parametrize(
        ("tagged_fixture", "label"),
        [
            (c1_spec_tagged, "C1"),
            (c2_spec_tagged, "C2"),
            (c3_spec_tagged, "C3"),
        ],
        ids=["C1", "C2", "C3"],
    )
    def test_11_pydantic_valid_implies_jsonschema_valid(
        self, tagged_fixture: Any, label: str
    ) -> None:
        spec_dict = tagged_fixture()
        # Layer 1 accepts (schema-valid tagged documents parse under
        # pydantic too -- tagged is the pass-through form).
        StrategySpec.model_validate(spec_dict)
        # Layer 2 must agree: no jsonschema errors.
        schema = _load_committed_schema()
        errors = validate_with_jsonschema(spec_dict, schema)
        assert errors == [], f"{label}: pydantic valid but jsonschema rejected: {errors}"

    def test_12_schema_is_valid_json(self) -> None:
        raw = COMMITTED_SCHEMA_PATH.read_text(encoding="utf-8")
        loaded = json.loads(raw)  # must not raise
        assert isinstance(loaded, dict)

    def test_13_generate_schema_is_idempotent(self) -> None:
        first = generate_spec_schema(registry=_SNAPSHOT_REGISTRY)
        second = generate_spec_schema(registry=_SNAPSHOT_REGISTRY)
        assert _strip_timestamp(first) == _strip_timestamp(second)


# ===========================================================================
# CANARY -- the anti-hallucination gate
# ===========================================================================


class TestHallucinationCanary:
    def test_14_canary_schema_rejects_hallucinated_indicator(self) -> None:
        """This test enforces ROADMAP S1 (closed vocabulary). The LLM may
        only reference indicators that exist in the registry. The schema
        is generated FROM the registry so they can never drift apart (C7).
        """
        spec = c1_spec_tagged()
        spec["indicators"]["sentiment"] = {
            "type": "sentiment_analysis",
            "params": {"model": "gpt-x"},
            "source": "close",
        }
        errors = validate_with_jsonschema(spec, _load_committed_schema())
        assert len(errors) >= 1, "hallucinated indicator type must be rejected"
        assert any("sentiment_analysis" in message for message in errors)
