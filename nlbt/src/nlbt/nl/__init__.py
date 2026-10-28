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
from nlbt.nl.service import (
    Confirmation,
    Interpretation,
    Status,
    UnconfirmedSpecError,
    confirm_spec,
    interpret,
    require_confirmation,
    run_confirmed,
)

__all__ = [
    "STRUCTURED_MODES",
    "Confirmation",
    "Envelope",
    "Interpretation",
    "LLMClient",
    "LLMResponse",
    "OpenAICompatibleClient",
    "RecordedClient",
    "Source",
    "Status",
    "UnconfirmedSpecError",
    "confirm_spec",
    "envelope_schema",
    "flatten_schema",
    "interpret",
    "request_fingerprint",
    "require_confirmation",
    "run_confirmed",
    "schema_sha256",
]
