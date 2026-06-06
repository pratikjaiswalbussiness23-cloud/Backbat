"""
BACKBAT v3 -- Central Configuration
Multi-Layer Liquidity-Driven Trading System
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ExchangeConfig:
    name: str
    rest_url: str
    ws_url: str
    enabled: bool = True
    order_book_depth: int = 50


EXCHANGES: Dict[str, ExchangeConfig] = {
    "binance": ExchangeConfig(
        name="binance",
        rest_url="https://api.binance.com",
        ws_url="wss://stream.binance.com:9443/ws",
    ),
    "bybit": ExchangeConfig(
        name="bybit",
        rest_url="https://api.bybit.com",
        ws_url="wss://stream.bybit.com/v5/public/linear",
    ),
    "okx": ExchangeConfig(
        name="okx",
        rest_url="https://www.okx.com",
        ws_url="wss://ws.okx.com:8443/ws/v5/public",
    ),
}


@dataclass
class DataIngestionConfig:
    enable_cvd_aggregator: bool = True
    cvd_timestamp_alignment_ms: int = 100
    enable_oi_delta: bool = True
    oi_poll_interval_seconds: int = 10
    enable_funding_rate: bool = True
    funding_rate_extreme_threshold: float = 0.0008
    enable_order_book: bool = True
    ob_snapshot_interval_ms: int = 1000
    enable_trade_stream: bool = True
    trade_batch_size: int = 100


@dataclass
class DetectionFilterConfig:
    enable_spoof_filter: bool = True
    spoof_wall_min_size_btc: float = 10.0
    spoof_persistence_seconds: int = 30
    spoof_approach_threshold_pct: float = 0.001
    sweep_atr_period: int = 20
    sweep_atr_multiplier: float = 1.3
    enable_zone_classifier: bool = True
    zone_classifier_lookback_bars: int = 50
    zone_classifier_min_samples: int = 10
    swing_lookback: int = 5
    swing_lookforward: int = 5
    atr_length: int = 20


@dataclass
class ScoringConfig:
    weight_htf_structure: float = 0.25
    weight_volume_density: float = 0.20
    weight_oi_buildup: float = 0.20
    weight_funding_bias: float = 0.15
    weight_historical_hit_rate: float = 0.20
    alert_threshold: float = 0.60
    high_conviction_threshold: float = 0.70
    max_zones_tracked: int = 50
    htf_timeframes: List[str] = field(default_factory=lambda: ["4h", "1d"])
    vp_window_bars: int = 100
    vp_hvn_threshold_mult: float = 1.3


@dataclass
class SignalGateConfig:
    db_zone_distance_max_atr: float = 0.5
    db_min_conviction_score: float = 0.70
    require_cvd_divergence: bool = True
    cvd_divergence_window: int = 5
    cvd_divergence_min_delta: float = 0.3
    require_expanding_volume: bool = True
    breakout_volume_mult: float = 1.5
    sl_behind_zone_atr: float = 1.0
    target_rr_min: float = 1.5
    risk_per_trade_pct: float = 0.02
    daily_loss_limit_pct: float = 0.05
    partial_exit_ratio: float = 0.60
    target1_rr: float = 1.5
    trailing_stop_mult: float = 0.5
    max_consecutive_losses: int = 5
    b2_volume_ratio_max: float = 2.0


@dataclass
class ValidationConfig:
    enabled: bool = True
    validation_periods: int = 6
    min_trades_per_period: int = 15
    out_of_sample_pct: float = 0.20
    require_total_trades: int = 100
    regime_detection_enabled: bool = True


@dataclass
class BackbatConfig:
    symbol: str = "BTCUSDT"
    timeframe: str = "15m"
    initial_balance: float = 10000.0
    data_ingestion: DataIngestionConfig = field(default_factory=DataIngestionConfig)
    detection_filter: DetectionFilterConfig = field(default_factory=DetectionFilterConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    signal_gate: SignalGateConfig = field(default_factory=SignalGateConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    active_exchanges: List[str] = field(default_factory=lambda: ["binance", "bybit", "okx"])
    mode: str = "backtest"
    log_level: str = "INFO"
    log_file: str = "backbat_v3.log"


DEFAULT_CONFIG = BackbatConfig()

_ws = DEFAULT_CONFIG.scoring
_s = _ws.weight_htf_structure + _ws.weight_volume_density + _ws.weight_oi_buildup + _ws.weight_funding_bias + _ws.weight_historical_hit_rate
assert 0.99 <= _s <= 1.01, f"Weights must sum to 1.0, got {_s}"
