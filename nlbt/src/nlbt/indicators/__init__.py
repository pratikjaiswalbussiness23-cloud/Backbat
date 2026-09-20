"""Indicator library: registry/base API (P2-T1) + registered indicators.

Importing this package REGISTERS the built-in indicators (sma, ema — P2-T2;
rsi, roc — P2-T3; macd, bbands — P2-T4; atr, stoch, adx — P2-T5; highest,
lowest — P2-T6; obv — P2-T6) in the global :data:`REGISTRY`; registration
happens at import time by design (P2-T1 singleton contract).
"""

from nlbt.indicators.channel import compute_highest, compute_lowest
from nlbt.indicators.momentum import compute_roc, compute_rsi
from nlbt.indicators.oscillator import compute_adx, compute_atr, compute_stoch
from nlbt.indicators.registry import (
    REGISTRY,
    IndicatorSpec,
    ParamSpec,
    Registry,
    register_indicator,
    validate_indicator_params,
)
from nlbt.indicators.trend import compute_ema, compute_sma
from nlbt.indicators.volatility import compute_bbands, compute_macd
from nlbt.indicators.volume import compute_obv

__all__ = [
    "REGISTRY",
    "IndicatorSpec",
    "ParamSpec",
    "Registry",
    "compute_adx",
    "compute_atr",
    "compute_bbands",
    "compute_ema",
    "compute_highest",
    "compute_lowest",
    "compute_macd",
    "compute_obv",
    "compute_roc",
    "compute_rsi",
    "compute_sma",
    "compute_stoch",
    "register_indicator",
    "validate_indicator_params",
]
