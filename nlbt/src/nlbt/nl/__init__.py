"""Natural-language → spec layer (P6). P6-T1: the LLM client abstraction.

ROADMAP §3.2: ``nl`` is the only package allowed to import an LLM SDK —
P6-T1 deliberately uses plain ``requests`` against an OpenAI-compatible
endpoint instead of any SDK (owner ruling: no ``openai`` package).
"""

from __future__ import annotations

from nlbt.nl.client import (
    STRUCTURED_MODES,
    LLMClient,
    LLMResponse,
    Source,
    request_fingerprint,
    schema_sha256,
)
from nlbt.nl.envelope import Envelope, envelope_schema, flatten_schema
from nlbt.nl.openai_client import OpenAICompatibleClient
from nlbt.nl.recorded import RecordedClient

__all__ = [
    "STRUCTURED_MODES",
    "Envelope",
    "LLMClient",
    "LLMResponse",
    "OpenAICompatibleClient",
    "RecordedClient",
    "Source",
    "envelope_schema",
    "flatten_schema",
    "request_fingerprint",
    "schema_sha256",
]
