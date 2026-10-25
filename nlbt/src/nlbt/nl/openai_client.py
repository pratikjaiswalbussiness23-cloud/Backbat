"""OpenAICompatibleClient — P6-T1: the one provider-neutral LLM transport.

Owner rulings implemented here (Phase A approved 2026-10-25):

* Plain ``requests`` over ``POST {base_url}/chat/completions`` — no SDK.
* ``structured_mode``: ``json_schema`` first (OpenAI-standard, provider
  neutral); ``nvext_guided_json`` is the NIM-documented alternative. JSON
  mode is NEVER a fallback — it does not force our schema (S2).
* Rate limits: 429 → backoff ``[1.0, 2.0, 4.0]`` (injectable ``sleep``),
  ``Retry-After`` honoured when numeric; exhausted → ``E_NL_LLM`` with
  ``details = {status, attempts, retry_after}``.
* Timeouts/connection errors ride the same retry loop; when the endpoint is
  UNREACHABLE after retries, ``NLBT_LLM_DEMO=1`` + a matching recording
  serves a clearly-labelled ``recorded-demo`` response (stderr warning);
  anything else raises ``E_NL_LLM``.
* 400/422 (and every other terminal status) → ``E_NL_LLM``, no retry.
* ``Config.offline`` refuses to touch the transport at all.
* The key lives ONLY in the ``Authorization`` header — never in the URL,
  body, logs, or exception details.

Provenance: the response wrapper carries ``source``; manifest wiring is P6-T3
(OQ-logged by this task).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
from pydantic import ValidationError

from nlbt.config import Config, get_config
from nlbt.errors import NLLlmError
from nlbt.nl.client import STRUCTURED_MODES, LLMResponse, request_fingerprint
from nlbt.nl.envelope import Envelope, flatten_schema
from nlbt.nl.recorded import RecordedClient

__all__ = ["DEMO_WARNING", "RETRY_DELAYS", "OpenAICompatibleClient"]

logger = logging.getLogger(__name__)

#: Hand-derived backoff schedule (owner test list: sleeps must be exact).
RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

#: Initial request + 3 retries = 4 attempts.
MAX_ATTEMPTS = 4

#: Printed to stderr whenever demo replay happens (owner: clearly labelled).
DEMO_WARNING = (
    "[nlbt][DEMO] serving RECORDED LLM response -- endpoint unreachable; "
    "output is NOT from the model"
)


def _parse_retry_after(value: str | None) -> float | None:
    """Numeric seconds only; anything else (HTTP-dates, junk) → None."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0.0 else None


class OpenAICompatibleClient:
    """Schema-forced chat completions against any OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        structured_mode: str = "json_schema",
        recordings_dir: Path | None = None,
        timeout: float = 180.0,
    ) -> None:
        if structured_mode not in STRUCTURED_MODES:
            raise NLLlmError(
                f"Unknown structured_mode {structured_mode!r}",
                details={"structured_mode": structured_mode, "allowed": list(STRUCTURED_MODES)},
                hint="Use 'json_schema' or 'nvext_guided_json'.",
            )
        self._config = config if config is not None else get_config()
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep
        self._structured_mode = structured_mode
        self._recordings_dir = recordings_dir
        self._timeout = timeout

    # ------------------------------------------------------------- public API

    def complete_structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> LLMResponse:
        cfg = self._config
        if cfg.offline:
            raise NLLlmError(
                "NLBT_OFFLINE is set: LLM calls are disabled",
                details={"offline": True},
                hint="Unset NLBT_OFFLINE to call the LLM endpoint.",
            )
        if not cfg.nvidia_api_key:
            raise NLLlmError(
                "NVIDIA_API_KEY is not set; the LLM layer cannot run",
                details={"env_var": "NVIDIA_API_KEY"},
                hint="Set NVIDIA_API_KEY in your environment.",
            )
        key = cfg.nvidia_api_key  # local variable; used ONLY for the header below
        model_id = model if model is not None else cfg.llm_model
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        body = self._build_body(model_id, messages, schema, temperature)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        url = cfg.llm_base_url.rstrip("/") + "/chat/completions"

        attempt = 0
        last_retry_after: float | None = None
        while True:
            attempt += 1
            try:
                response = self._session.post(
                    url, headers=headers, json=body, timeout=self._timeout
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= MAX_ATTEMPTS:
                    logger.warning(
                        "llm transport failed: %s after %d attempts (model=%s)",
                        type(exc).__name__,
                        attempt,
                        model_id,
                    )
                    return self._demo_or_raise(system, user, schema, temperature, model_id, attempt)
                delay = RETRY_DELAYS[attempt - 1]
                logger.info(
                    "llm transport %s; retrying in %.1fs (attempt %d/%d)",
                    type(exc).__name__,
                    delay,
                    attempt + 1,
                    MAX_ATTEMPTS,
                )
                self._sleep(delay)
                continue

            if response.status_code == 429:
                last_retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                if attempt >= MAX_ATTEMPTS:
                    logger.warning(
                        "llm endpoint rate limited after %d attempts (model=%s)",
                        attempt,
                        model_id,
                    )
                    raise NLLlmError(
                        "LLM endpoint rate limited (429) after retries",
                        details={
                            "status": 429,
                            "attempts": attempt,
                            "retry_after": last_retry_after,
                        },
                        hint="Slow down; the endpoint free tier is rate-limited.",
                    )
                delay = (
                    last_retry_after if last_retry_after is not None else RETRY_DELAYS[attempt - 1]
                )
                logger.info(
                    "429 from llm endpoint; sleeping %.1fs (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    MAX_ATTEMPTS,
                )
                self._sleep(delay)
                continue

            if response.status_code in (400, 422):
                logger.warning(
                    "llm endpoint rejected the request: status=%d attempts=%d (model=%s)",
                    response.status_code,
                    attempt,
                    model_id,
                )
                raise NLLlmError(
                    "LLM endpoint rejected the request (no retry)",
                    details={
                        "status": response.status_code,
                        "attempts": attempt,
                        "retry_after": None,
                    },
                    hint="Check the request body, model id and structured_mode.",
                )
            if not 200 <= response.status_code < 300:
                logger.warning(
                    "llm endpoint error: status=%d attempts=%d (model=%s)",
                    response.status_code,
                    attempt,
                    model_id,
                )
                raise NLLlmError(
                    "LLM endpoint returned an error status",
                    details={
                        "status": response.status_code,
                        "attempts": attempt,
                        "retry_after": None,
                    },
                    hint="Inspect the endpoint status; see docs/verified_apis.md.",
                )
            break

        payload = self._parse_and_validate(response)
        logger.info("llm call ok model=%s source=live status=%s", model_id, payload.get("status"))
        return LLMResponse(payload=payload, source="live")

    # -------------------------------------------------------------- internals

    def _build_body(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            # Reasoning models (Nemotron 3.5 family) spend tokens on
            # ``reasoning_content`` before emitting ``content``; 1024 truncated
            # a live recording mid-JSON on 2026-10-25 (E_NL_LLM, loud).
            "max_tokens": 4096,
        }
        if self._structured_mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "nlbt_envelope",
                    "schema": flatten_schema(schema),
                    "strict": True,
                },
            }
        else:  # nvext_guided_json — NIM-documented structured mode
            body["nvext"] = {"guided_json": schema}
        return body

    def _parse_and_validate(self, response: requests.Response) -> dict[str, Any]:
        try:
            body_data = response.json()
        except ValueError as exc:
            raise NLLlmError(
                "LLM response body is not JSON",
                details={"reason": "body_not_json"},
                hint="The endpoint or a proxy returned a non-JSON body.",
            ) from exc
        try:
            content = body_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise NLLlmError(
                "LLM response is missing choices[0].message.content",
                details={"reason": "shape"},
                hint="Unexpected response shape; see docs/verified_apis.md.",
            ) from exc
        if not isinstance(content, str):
            raise NLLlmError(
                "LLM response content is missing (null)",
                details={"reason": "null_content"},
                hint="Raise max_tokens or pick a model that answers directly.",
            )
        try:
            payload: Any = json.loads(content)
        except json.JSONDecodeError as exc:
            raise NLLlmError(
                "LLM content is not JSON despite schema forcing",
                details={"reason": "content_not_json"},
                hint="The model ignored the schema; consider structured_mode='nvext_guided_json'.",
            ) from exc
        if not isinstance(payload, dict):
            raise NLLlmError(
                "LLM content is not a JSON object",
                details={"reason": "not_an_object"},
                hint="The envelope must be a JSON object.",
            )
        try:
            Envelope.model_validate(payload)
        except ValidationError as exc:
            raise NLLlmError(
                "LLM payload failed the envelope schema",
                details={"reason": "envelope_invalid", "errors": len(exc.errors())},
                hint="Re-prompt or repair (P6-T3 repair loop).",
            ) from exc
        return payload

    def _demo_or_raise(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float,
        model: str,
        attempts: int,
    ) -> LLMResponse:
        """Unreachable endpoint: optional labelled demo replay, else E_NL_LLM."""
        if os.environ.get("NLBT_LLM_DEMO") == "1" and self._recordings_dir is not None:
            recorded = RecordedClient(
                fixture_dir=self._recordings_dir, structured_mode=self._structured_mode
            )
            try:
                replay = recorded.complete_structured(
                    system, user, schema, temperature=temperature, model=model
                )
            except NLLlmError:
                pass  # no matching recording → the normal loud failure below
            else:
                print(DEMO_WARNING, file=sys.stderr)
                logger.warning(DEMO_WARNING)
                return LLMResponse(payload=replay.payload, source="recorded-demo")
        raise NLLlmError(
            "LLM endpoint unreachable after retries",
            details={"status": None, "attempts": attempts, "retry_after": None},
            hint="Check network/base_url, or set NLBT_LLM_DEMO=1 for labelled replay.",
        )

    # ----------------------------------------------------------- convenience

    def fingerprint(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> str:
        """The request hash this client would use (recorder tooling)."""
        model_id = model if model is not None else self._config.llm_model
        return request_fingerprint(
            model=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=schema,
            temperature=temperature,
            structured_mode=self._structured_mode,
        )
