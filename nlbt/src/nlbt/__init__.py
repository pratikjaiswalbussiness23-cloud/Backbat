"""nlbt — natural-language trading strategy backtester.

Status: Phase 1 (data layer) complete; Phase 2 started (P2-T1 indicator
registry). Ground rule (ROADMAP §0.3 C1): the LLM only translates; it never
computes numbers or runs code.
"""

from nlbt.config import Config, get_config, reset_config
from nlbt.data.csv_provider import CSVProvider
from nlbt.data.models import Bars, BarsMeta, DataProvider
from nlbt.data.validate import validate_bars_shape
from nlbt.errors import NlbtError
from nlbt.indicators.registry import (
    REGISTRY,
    IndicatorSpec,
    ParamSpec,
    Registry,
    register_indicator,
    validate_indicator_params,
)
from nlbt.logging_config import SecretRedactionFilter, setup_logging

__version__ = "0.1.0"

__all__ = [
    "REGISTRY",
    "Bars",
    "BarsMeta",
    "CSVProvider",
    "Config",
    "DataProvider",
    "IndicatorSpec",
    "NlbtError",
    "ParamSpec",
    "Registry",
    "SecretRedactionFilter",
    "get_config",
    "register_indicator",
    "reset_config",
    "setup_logging",
    "validate_bars_shape",
    "validate_indicator_params",
]
