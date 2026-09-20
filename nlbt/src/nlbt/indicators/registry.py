"""Indicator registry and base API (ROADMAP P2-T1, §4.3).

This module is the *catalog* layer for the indicator library: it defines what
an indicator IS (name, outputs, bounded params, allowed sources, warmup,
compute), keeps them in a registry, and exposes the registry to later layers:

* the spec schema (P3) validates references and param bounds against it,
* the LLM prompt (P6) embeds ``Registry.json_schema()`` so the model can only
  name indicators/params that actually exist (ROADMAP §2 anti-hallucination),
* generated docs (P2-T8) are rendered from ``describe()`` — never hand-written.

Contracts fixed here (§4.3 "Rules for all indicators"):

* ``compute_fn(bars, params, source) -> DataFrame`` — columns exactly
  ``spec.outputs``, index identical to ``bars.index``, leading NaN only during
  warmup, no NaN after warmup unless the input is NaN, never ``inf``.
  (Enforced per-indicator by tests in P2-T2+; the registry cannot check it
  without executing ``compute_fn``.)
* ``warmup_fn(params) -> int`` — number of bars before the first valid output.
* Params: every param has a type (``int``/``float``), INCLUSIVE bounds and a
  default; ``validate_indicator_params`` is the single gate that fills
  defaults and rejects out-of-bounds/unknown/non-numeric values with
  ``E_SPEC_RANGE``.

Singleton note: ``REGISTRY`` is a plain module-level object. Importing it from
``nlbt.indicators`` and from ``nlbt.indicators.registry`` yields the SAME
object (Python module caching); verified by test — no mypy issue arises from
this pattern (mypy strict green).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

from nlbt.errors import SpecRangeError, SpecRefError

__all__ = [
    "REGISTRY",
    "IndicatorSpec",
    "ParamSpec",
    "Registry",
    "register_indicator",
    "validate_indicator_params",
]


class ParamSpec(BaseModel):
    """Definition of ONE indicator parameter: type, inclusive bounds, default.

    ``extra="forbid"`` so a typo'd field in a param definition fails loudly at
    registration time instead of silently ignoring it (ROADMAP §2 R1 spirit).
    Uses the ``model_config = ConfigDict(...)`` form — the codebase convention
    (``data/models.py``) — rather than the task text's class-kwargs form
    ``class ParamSpec(BaseModel, extra="forbid")``. Both were probed
    runtime-equivalent on pydantic 2.13.5 (docs/verified_apis.md); the dict
    form is the one mypy strict accepts without the pydantic mypy plugin.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["int", "float"]
    minimum: float | None = None
    maximum: float | None = None
    default: float | int
    description: str


@dataclass(frozen=True)
class IndicatorSpec:
    """Internal metadata describing one indicator (NOT user input → dataclass).

    ``outputs`` — output column names, in order. Single-output indicators use
    ``("value",)``; multi-output e.g. ``("line", "signal", "hist")``.

    ``allowed_sources`` — which OHLCV columns are valid ``source`` inputs
    (usually all five; price-only indicators exclude ``"volume"``).

    ``warmup_fn(params) -> int`` — bars needed before the first valid output
    (a function of params: e.g. SMA(period=20) warms up 19 bars).

    ``compute_fn(bars, params, source) -> DataFrame`` — see module docstring
    for the output contract.
    """

    name: str
    outputs: tuple[str, ...]
    params: dict[str, ParamSpec]
    allowed_sources: tuple[str, ...]
    warmup_fn: Callable[[dict[str, Any]], int]
    compute_fn: Callable[..., pd.DataFrame]
    description: str


class Registry:
    """Catalog of :class:`IndicatorSpec` objects, keyed by unique name."""

    def __init__(self) -> None:
        self._indicators: dict[str, IndicatorSpec] = {}

    def register(self, spec: IndicatorSpec) -> None:
        """Add ``spec``; raise ``ValueError`` on duplicate name or outputs.

        Also rejects an empty name / empty outputs — a spec that could never
        be referenced or read must not enter the catalog.
        """
        if not spec.name:
            raise ValueError("Indicator name must be a non-empty string")
        if not spec.outputs:
            raise ValueError(f"Indicator {spec.name!r} must declare at least one output")
        if len(set(spec.outputs)) != len(spec.outputs):
            raise ValueError(
                f"Indicator {spec.name!r} has duplicate output names: {spec.outputs!r}"
            )
        if spec.name in self._indicators:
            raise ValueError(f"Indicator {spec.name!r} is already registered")
        self._indicators[spec.name] = spec

    def get(self, name: str) -> IndicatorSpec:
        """Return the spec for ``name``; raise ``KeyError`` if not registered."""
        try:
            return self._indicators[name]
        except KeyError:
            raise KeyError(
                f"Unknown indicator {name!r}; registered: {sorted(self._indicators)}"
            ) from None

    def list_indicators(self) -> list[str]:
        """Sorted names of all registered indicators (stable order for prompts)."""
        return sorted(self._indicators)

    def json_schema(self) -> dict[str, Any]:
        """Machine-readable catalog for the LLM prompt and spec schema (§2/§4.3).

        ``warmup`` is evaluated at each indicator's DEFAULT params — the number
        the spec layer can rely on before the user overrides anything.
        """
        indicators: dict[str, dict[str, Any]] = {}
        for name in self.list_indicators():
            spec = self._indicators[name]
            defaults: dict[str, Any] = {p: ps.default for p, ps in spec.params.items()}
            indicators[name] = {
                "outputs": list(spec.outputs),
                "params": {p: ps.model_dump() for p, ps in spec.params.items()},
                "allowed_sources": list(spec.allowed_sources),
                "warmup": spec.warmup_fn(defaults),
                "description": spec.description,
            }
        return {"indicators": indicators}

    def describe(self, name: str) -> str:
        """Human-readable description of one indicator (generated docs, P2-T8)."""
        spec = self.get(name)
        defaults: dict[str, Any] = {p: ps.default for p, ps in spec.params.items()}
        lines = [
            f"{spec.name} — {spec.description}",
            f"  outputs: {', '.join(spec.outputs)}",
            f"  allowed sources: {', '.join(spec.allowed_sources)}",
            f"  warmup: {spec.warmup_fn(defaults)} bars (at default params)",
        ]
        for p_name, p in spec.params.items():
            bounds: list[str] = []
            if p.minimum is not None:
                bounds.append(f">= {p.minimum}")
            if p.maximum is not None:
                bounds.append(f"<= {p.maximum}")
            bound_txt = f" ({' and '.join(bounds)})" if bounds else ""
            lines.append(f"  {p_name}: {p.type}, default {p.default}{bound_txt} — {p.description}")
        return "\n".join(lines)


#: Module-level singleton — indicator modules (P2-T2+) call
#: :func:`register_indicator` at import time; every consumer imports THIS
#: object, so there is exactly one catalog per process.
REGISTRY = Registry()


def register_indicator(spec: IndicatorSpec) -> None:
    """Register ``spec`` in the global :data:`REGISTRY` (P2-T2+ entry point)."""
    REGISTRY.register(spec)


def validate_indicator_params(
    name: str,
    params: dict[str, Any],
    registry: Registry | None = None,
) -> dict[str, Any]:
    """Fill defaults, then validate against the spec; return complete params.

    Checks (all violations reported in ONE error, details["violations"]):

    * unknown param names → violation (typo'd params must not be dropped
      silently — that would change strategy semantics),
    * non-numeric / non-finite values, ``bool`` (a Python ``int`` subclass but
      never a meaningful parameter), and ``float`` values for ``type="int"``
      params → violation (strict types, §4.1 "no silent coercion"),
    * inclusive bounds ``minimum <= value <= maximum`` → violation.

    Errors: unknown indicator name → ``SpecRefError`` (E_SPEC_REF, §4.8 row 2);
    any param violation → ``SpecRangeError`` (E_SPEC_RANGE, §4.8 row 3) —
    see OQ-0014 for the owner-confirmation note.
    """
    reg = REGISTRY if registry is None else registry
    try:
        spec = reg.get(name)
    except KeyError as exc:
        raise SpecRefError(
            f"Unknown indicator {name!r}",
            details={"indicator": name, "known_indicators": reg.list_indicators()},
            hint="Use a registered indicator name (see Registry.json_schema()).",
        ) from exc

    unknown = sorted(set(params) - set(spec.params))
    if unknown:
        raise SpecRangeError(
            f"Unknown parameter(s) for indicator {name!r}: {unknown}",
            details={
                "indicator": name,
                "unknown_params": unknown,
                "known_params": sorted(spec.params),
            },
            hint=f"Allowed parameters for {name!r}: {sorted(spec.params)}",
        )

    resolved: dict[str, Any] = {}
    violations: list[dict[str, Any]] = []
    for p_name, p_spec in spec.params.items():
        value: Any = params.get(p_name, p_spec.default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            violations.append({"param": p_name, "problem": "not_numeric", "value": repr(value)})
            continue
        if not math.isfinite(value):  # NaN and ±inf: §4.3 "never inf", no NaN params
            violations.append({"param": p_name, "problem": "not_finite", "value": repr(value)})
            continue
        if p_spec.type == "int" and not isinstance(value, int):
            violations.append({"param": p_name, "problem": "expected_int", "value": repr(value)})
            continue
        if p_spec.minimum is not None and value < p_spec.minimum:
            violations.append(
                {
                    "param": p_name,
                    "problem": "below_minimum",
                    "value": value,
                    "minimum": p_spec.minimum,
                }
            )
            continue
        if p_spec.maximum is not None and value > p_spec.maximum:
            violations.append(
                {
                    "param": p_name,
                    "problem": "above_maximum",
                    "value": value,
                    "maximum": p_spec.maximum,
                }
            )
            continue
        resolved[p_name] = value

    if violations:
        summary = "; ".join(f"{v['param']}: {v['problem']} ({v['value']})" for v in violations)
        raise SpecRangeError(
            f"Invalid parameter(s) for indicator {name!r}: {summary}",
            details={"indicator": name, "violations": violations},
            hint="Fix the parameters listed in details['violations']; bounds are inclusive.",
        )
    return resolved
