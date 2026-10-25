"""LLMClient abstraction — P6-T1 (ROADMAP §3.4 ``nl/``, S2 schema-forced output).

One provider-neutral Protocol, one response wrapper, one fingerprint:

* :class:`LLMClient` — the single method every implementation satisfies.
* :class:`LLMResponse` — payload + provenance ``source`` (``"live"`` |
  ``"recorded"`` | ``"recorded-demo"``). Owner ruling: P6-T1 exposes the
  provenance on the wrapper ONLY; wiring ``llm_source``/``llm_model``/
  ``prompt_version`` into the manifest happens in P6-T3 (OQ-logged).
* :func:`request_fingerprint` — sha256 over the CANONICAL JSON of exactly
  five fields: ``model``, ``messages``, ``schema_sha256``, ``temperature``,
  ``structured_mode``. The API key and all headers are excluded BY
  CONSTRUCTION: they are simply not part of the hashed material, so a
  recording can be matched without ever touching a secret.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = [
    "STRUCTURED_MODES",
    "LLMClient",
    "LLMResponse",
    "Source",
    "request_fingerprint",
    "schema_sha256",
]

#: Provenance of a response (owner ruling: exposed on the wrapper only).
Source = Literal["live", "recorded", "recorded-demo"]

#: The two schema-forcing transports the client speaks. JSON mode is
#: deliberately ABSENT: it does not force *our* schema (S2 forbids it).
STRUCTURED_MODES: tuple[str, ...] = ("json_schema", "nvext_guided_json")


@dataclass(frozen=True)
class LLMResponse:
    """A validated envelope payload plus where it came from."""

    payload: dict[str, Any]
    source: Source


@runtime_checkable
class LLMClient(Protocol):
    """The one method every LLM implementation provides (P6-T1)."""

    def complete_structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> LLMResponse:
        """Translate ``user`` under ``system`` into ``schema``-forced JSON."""
        ...


def _canonical(obj: Any) -> str:
    """Deterministic JSON: sorted keys, tight separators, ASCII-safe."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def schema_sha256(schema: dict[str, Any]) -> str:
    """sha256 of the canonical envelope schema JSON."""
    return hashlib.sha256(_canonical(schema).encode("utf-8")).hexdigest()


def request_fingerprint(
    *,
    model: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    temperature: float,
    structured_mode: str,
) -> str:
    """sha256 over the canonical JSON of the five hashed fields.

    Only ``role``/``content`` are taken from each message, so session-irrelevant
    metadata can never change the hash — and no secret can ever enter it.
    """
    material = {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "schema_sha256": schema_sha256(schema),
        "temperature": temperature,
        "structured_mode": structured_mode,
    }
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()
