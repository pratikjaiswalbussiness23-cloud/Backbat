"""Structured logging with secret redaction — ROADMAP §2A (R13), P0-T4.

Two parts:
- :class:`SecretRedactionFilter` — a ``logging.Filter`` that rewrites records
  whose rendered message contains something that looks like an API key
  (``sk-ant-…``, ``ghp_…``, ``Bearer …`` tokens, or the live
  ``ANTHROPIC_API_KEY`` value if one is set). The matched span is replaced with
  ``[REDACTED]``.
- :func:`setup_logging` — installs a JSON formatter + the redaction filter on
  the **root logger** (P0-T4 requirement).

Stdlib-semantics note (why the filter is attached twice): a filter attached to
the root *logger* is only evaluated for records emitted by the root logger
itself; records from child loggers propagate straight to the root's *handlers*.
To satisfy the letter of the requirement (root logger) **and** actually protect
child-logger output, the singleton filter is attached to both the root logger
and the nlbt root handler.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import TextIO

__all__ = ["JsonFormatter", "SecretRedactionFilter", "setup_logging"]

#: Fixed secret-shaped patterns. Each entry: (compiled regex, replacement).
_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Anthropic keys: sk-ant-<long token>
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "[REDACTED]"),
    # GitHub personal access tokens: ghp_ / gho_ / github_pat_
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"), "[REDACTED]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED]"),
    # Bearer tokens (case-insensitive scheme, token = unreserved chars)
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-=]{8,}"), "Bearer [REDACTED]"),
)


class SecretRedactionFilter(logging.Filter):
    """Rewrite ``[REDACTED]`` over anything that looks like an API key.

    Runs on every record that passes through it and **always returns True**
    (a leaked secret must still be logged — redacted, never dropped).

    %-format safety: the record is rendered with ``record.getMessage()`` first.
    If rendering succeeds and something was redacted, the fully-rendered,
    redacted string becomes ``record.msg`` and ``record.args`` is cleared, so a
    later ``str(msg) % args`` cannot resurrect raw argument values.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # Broken %-formatting on this record (e.g. stray args). Stringify the
            # raw msg and DROP the args: losing detail is acceptable; leaking a
            # secret that would have flowed through args is not (R13).
            message = str(record.msg)
            record.args = None

        redacted = self._redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True

    def _redact(self, message: str) -> str:
        for pattern, replacement in _REDACTION_PATTERNS:
            message = pattern.sub(replacement, message)
        live_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if live_key:
            message = message.replace(live_key, "[REDACTED]")
        return message


class JsonFormatter(logging.Formatter):
    """One JSON object per log line (structured output, P0-T4)."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),  # runs AFTER filters → redacted
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=True)


class _NlbtStreamHandler(logging.StreamHandler[TextIO]):
    """StreamHandler carrying a marker attribute so ``setup_logging`` is idempotent."""

    _nlbt_handler: bool = True


#: One shared filter instance: every setup reuses it (no duplicate stacking).
_REDACTION_FILTER = SecretRedactionFilter()


def setup_logging(level: str = "INFO") -> logging.Handler:
    """Configure the root logger: JSON lines + secret redaction.

    Idempotent: re-calling removes the handler a previous call installed
    (marked ``_nlbt_handler``) before adding a fresh one, so tests and the CLI
    can reconfigure freely without duplicating output.

    Returns the installed handler (tests use ``setStream`` to capture output).
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    for handler in list(root.handlers):
        if getattr(handler, "_nlbt_handler", False):
            root.removeHandler(handler)

    # Singleton filter: attached to the root logger (literal P0-T4 requirement)
    # AND to the handler below (actual coverage of child-logger records — see
    # module docstring).
    if _REDACTION_FILTER not in root.filters:
        root.addFilter(_REDACTION_FILTER)

    handler = _NlbtStreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_REDACTION_FILTER)
    root.addHandler(handler)
    return handler
