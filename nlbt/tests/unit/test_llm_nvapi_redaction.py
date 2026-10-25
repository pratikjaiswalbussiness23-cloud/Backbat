"""P6-T1 (owner-approved logging fix): nvapi- keys and the live NVIDIA key.

New coverage in a NEW file -- tests/unit/test_logging_config.py stays
untouched and green (owner ruling).

Two guarantees:
1. A bare ``nvapi-...`` string (no "Bearer" prefix) is redacted by the fixed
   ``nvapi-`` pattern -- the Phase A gap: the old filter only caught
   ``Bearer ...``, so an NVIDIA key logged bare would have passed through.
2. The LIVE ``NVIDIA_API_KEY`` value is redacted verbatim even when it does
   not match any shape pattern (same mechanism the Anthropic key already has).

Fake keys only; the real key never enters this file.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from nlbt.logging_config import JsonFormatter, setup_logging

FAKE_NVAPI = "nvapi-BARE-FAKE-KEY-1234567890abcdef"
FAKE_LIVE = "justsomeplaintextkeyvalue987654321"  # deliberately NOT nvapi-shaped
REDACTED = "[REDACTED]"


@pytest.fixture()
def captured_root_log() -> io.StringIO:
    """Same pipeline pattern as tests/unit/test_logging_config.py."""
    stream = io.StringIO()
    setup_logging("DEBUG")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    yield stream
    root.removeHandler(handler)
    for h in list(root.handlers):
        if getattr(h, "_nlbt_handler", False):
            root.removeHandler(h)
    root.setLevel("WARNING")


def test_bare_nvapi_key_is_redacted(captured_root_log: io.StringIO) -> None:
    """The Phase A gap: an nvapi- key WITHOUT a Bearer prefix must redact."""
    logging.getLogger("nlbt.test").info("sending key %s to the endpoint", FAKE_NVAPI)
    out = captured_root_log.getvalue()
    assert FAKE_NVAPI not in out, "bare nvapi- key leaked"
    assert REDACTED in out
    entry = json.loads(out.strip())
    assert REDACTED in entry["message"]


def test_live_nvidia_key_value_is_redacted(
    captured_root_log: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-pattern-shaped NVIDIA_API_KEY value still redacts verbatim."""
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_LIVE)
    logging.getLogger("nlbt.test").info("raw value: %s", FAKE_LIVE)
    out = captured_root_log.getvalue()
    assert FAKE_LIVE not in out, "live NVIDIA_API_KEY value leaked"
    assert REDACTED in out


def test_no_nvapi_pattern_means_no_over_redaction(captured_root_log: io.StringIO) -> None:
    """Benign text mentioning 'nvapi docs' is untouched when not a key shape."""
    msg = "read the nvapi documentation before calling the endpoint"
    logging.getLogger("nlbt.test").info(msg)
    entry = json.loads(captured_root_log.getvalue().strip())
    assert entry["message"] == msg
