# Crypto Liquidity Finder - Research Resources

## 1. Free Data Sources / APIs

### Binance API (Recommended - Primary Source)
- REST + WebSocket - completely free
- Endpoints:
  - GET /api/v3/depth (order book, up to 5000 levels)
  - GET /api/v3/trades (recent trades)
  - GET /api/v3/aggTrades (aggregate trades)
  - GET /api/v3/klines (candlestick data)
  - GET /fapi/v1/forceOrders (liquidations, futures)
  - GET /fapi/v1/openInterest (open interest)
  - WSS /ws/<stream> (WebSocket streams)
- Libraries: python-binance, ccxt

### Other Free Sources
- CoinGecko / CoinMarketCap - Market metrics
- CryptoQuant - On-chain exchange flows
- Glassnode - Advanced on-chain
- TradingView - Pine Script indicators

## 2. Liquidity Detection Indicators
- Order Book Cluster Detection (z-score walls)
- Swing Point Liquidity Zones (pivot highs/lows)
- Volume Profile HVN/LVN (POC, Value Area)
- Cumulative Volume Delta (CVD, order flow)
- Liquidation Level Clustering (force orders)
- Smart Money Concepts (Order Blocks, FVG, sweeps)

## 3. Algorithms
- Swing point detection with configurable lookback
- Volume profile with rolling window
- CVD divergence detection
- Order book imbalance ratios
- Liquidity zone merger with weighted scoring

## 4. Architecture
- Data Layer: Binance REST + WebSocket
- Order Book Manager: L2 depth maintenance
- Swing Point Analyzer: Pivot detection
- Volume Profile Engine: Period configurable
- CVD Calculator: Per-candle delta
- Liquidation Monitor: Futures force orders
- SMC Module: OB, FVG, sweep detection
- Liquidity Merger: Unified zone ranking
- Alert Engine: Threshold-based
- Visualization: Charts + HTML dashboard

## 5. Python Libraries
- python-binance / ccxt - API client
- asyncio + websockets - Streaming
- pandas + numpy - Data processing
- matplotlib + plotly - Visualization
- fpdf2 - PDF reports
- Flask + socketio - Web dashboard
- scipy - Signal processing
- SQLite / InfluxDB - Persistence
