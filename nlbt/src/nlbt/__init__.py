"""nlbt — natural-language trading strategy backtester.

Status: Phase 0 (P0-T4 — errors, config, logging). No engine code yet.
Ground rule (ROADMAP §0.3 C1): the LLM only translates; it never computes
numbers or runs code.
"""

from nlbt.config import Config, get_config, reset_config
from nlbt.errors import NlbtError
from nlbt.logging_config import SecretRedactionFilter, setup_logging

__version__ = "0.1.0"

__all__ = [
    "Config",
    "NlbtError",
    "SecretRedactionFilter",
    "get_config",
    "reset_config",
    "setup_logging",
]
