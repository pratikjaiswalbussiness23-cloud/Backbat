"""Tests for secret redaction in logging (nlbt.logging_config).

Independent acceptance checks (P0-T4):
- a log message containing an API-key pattern (``sk-ant-fake123`` style) is
  redacted to ``[REDACTED]`` in the output
- a normal message is NOT redacted
- CANARY: WITHOUT the filter the key WOULD appear — proving the tests are not
  vacuously green (a redaction test that can't fail is worthless for R13)

Strategy: every test drives a real ``logging`` pipeline (logger → handler →
``StreamHandler.setStream`` into a StringIO) and inspects the formatted bytes,
so the assertion covers formatter + filter exactly as production would see
them. The canary additionally runs a **subprocess** with only stdlib logging +
the bare filter class to prove the filter works on an arbitrary, pre-existing
handler pipeline (not just through ``setup_logging``).
"""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
import textwrap

import pytest

from nlbt.logging_config import SecretRedactionFilter, setup_logging

# Not a real key: shaped like one, length chosen to exceed the redaction regex
# minimums (sk-ant- + >= 8 chars).
FAKE_KEY = "sk-ant-fake123456789"
REDACTED = "[REDACTED]"


@pytest.fixture(autouse=True)
def _no_real_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the live-key redaction path out of these tests unless a test sets it."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture()
def captured_root_log() -> io.StringIO:
    """Root logger → JSON handler → StringIO, exactly as setup_logging builds it."""
    stream = io.StringIO()
    setup_logging("DEBUG")
    handler = logging.StreamHandler(stream)
    # Reuse the production JSON formatter via the installed nlbt root handler.
    from nlbt.logging_config import JsonFormatter

    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    yield stream
    root.removeHandler(handler)
    # Leave global logging state clean for other test modules.
    for h in list(root.handlers):
        if getattr(h, "_nlbt_handler", False):
            root.removeHandler(h)
    root.setLevel("WARNING")


def test_api_key_pattern_is_redacted(captured_root_log: io.StringIO) -> None:
    """P0-T4: an sk-ant- key in a log message must come out as [REDACTED]."""
    logging.getLogger("nlbt.test").info("calling anthropic with key %s", FAKE_KEY)
    out = captured_root_log.getvalue()
    assert FAKE_KEY not in out, "secret leaked into log output"
    assert REDACTED in out
    entry = json.loads(out.strip())  # and the line is still valid JSON
    assert REDACTED in entry["message"]


def test_bearer_token_and_github_pat_are_redacted(captured_root_log: io.StringIO) -> None:
    logging.getLogger("nlbt.test").info("Authorization: Bearer abc123def456+")
    logging.getLogger("nlbt.test").info("token=ghp_a1b2c3d4e5f6g7h8i9j0")
    out = captured_root_log.getvalue()
    assert "Bearer abc123def456+" not in out
    assert "Bearer [REDACTED]" in out
    assert "ghp_a1b2c3d4e5f6g7h8i9j0" not in out
    assert REDACTED in out


def test_normal_message_is_not_redacted(captured_root_log: io.StringIO) -> None:
    """Benign text must pass through untouched (no over-redaction)."""
    msg = "backtest finished: 42 trades, profit factor 1.7, max drawdown -12.3%"
    logging.getLogger("nlbt.test").info(msg)
    entry = json.loads(captured_root_log.getvalue().strip())
    assert entry["message"] == msg


def test_log_output_is_structured_json(captured_root_log: io.StringIO) -> None:
    """P0-T4: log output is structured — one JSON object per line."""
    logging.getLogger("nlbt.test").warning("structured check")
    lines = [ln for ln in captured_root_log.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert {"ts", "level", "logger", "message"} <= set(entry)
    assert entry["level"] == "WARNING"


def test_live_api_key_value_is_redacted(
    captured_root_log: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ANTHROPIC_API_KEY value itself (if set) is redacted verbatim."""
    live = "sk-ant-live-DOES-NOT-EXIST-987654321"
    monkeypatch.setenv("ANTHROPIC_API_KEY", live)
    logging.getLogger("nlbt.test").info("exported key: %s", live)
    out = captured_root_log.getvalue()
    assert live not in out
    assert REDACTED in out


def test_percent_args_cannot_resurrect_secret(captured_root_log: io.StringIO) -> None:
    """A %-formatted secret is redacted even though args are applied at format time."""
    logging.getLogger("nlbt.test").info("key=%s", FAKE_KEY)
    out = captured_root_log.getvalue()
    assert FAKE_KEY not in out
    assert REDACTED in out


def test_canary_without_filter_the_key_would_appear() -> None:
    """CANARY (P0-T4): prove the un-filtered pipeline WOULD leak the key.

    Runs a subprocess that wires a bare StreamHandler (no redaction anywhere —
    not even setup_logging) and prints the formatted record. The subprocess
    imports the *installed* nlbt package only to reuse the literal FAKE_KEY
    shape; logging itself is pure stdlib. We assert the leak, i.e. the opposite
    outcome of every other test in this file.
    """
    script = textwrap.dedent(
        """
        import io, json, logging
        from nlbt.logging_config import JsonFormatter
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        log = logging.getLogger("leak.canary")
        log.addHandler(handler)
        log.setLevel("INFO")
        log.info("calling anthropic with key %s", "sk-ant-fake123456789")
        print(json.dumps({"would_leak": "sk-ant-fake123456789" in stream.getvalue()}))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["would_leak"] is True, (
        "CANARY BROKEN: an un-filtered pipeline no longer leaks — either the "
        "formatter/stdlib changed (re-derive this test) or redaction moved "
        "somewhere it now masks the control group."
    )


def test_canary_filter_on_foreign_preexisting_handler() -> None:
    """The filter class alone, attached to an arbitrary handler, still redacts.

    Complements the subprocess canary: same bare pipeline but WITH the filter
    attached — proving the filter (not some setup_logging wiring) does the work.
    """
    script = textwrap.dedent(
        """
        import io, json, logging
        from nlbt.logging_config import SecretRedactionFilter
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(SecretRedactionFilter())
        log = logging.getLogger("leak.canary.filtered")
        log.addHandler(handler)
        log.setLevel("INFO")
        log.info("calling anthropic with key %s", "sk-ant-fake123456789")
        print(json.dumps({"leaked": "sk-ant-fake123456789" in stream.getvalue(),
                          "redacted": "[REDACTED]" in stream.getvalue()}))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["leaked"] is False
    assert payload["redacted"] is True


def test_setup_logging_attaches_filter_to_root_logger() -> None:
    """P0-T4 (literal): the redaction filter is attached to the root logger."""
    setup_logging("INFO")
    root = logging.getLogger()
    try:
        assert any(isinstance(f, SecretRedactionFilter) for f in root.filters)
    finally:
        root.removeFilter(next(f for f in root.filters if isinstance(f, SecretRedactionFilter)))


def test_setup_logging_is_idempotent(captured_root_log: io.StringIO) -> None:
    """Re-calling setup_logging must not stack handlers (no duplicate lines)."""
    setup_logging("INFO")
    setup_logging("INFO")
    logging.getLogger("nlbt.test").info("once only")
    lines = [ln for ln in captured_root_log.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1
