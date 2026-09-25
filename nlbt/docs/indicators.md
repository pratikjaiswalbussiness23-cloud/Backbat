# nlbt Indicator Catalog

*Generated from the indicator registry.
Do not edit manually — run `make generate-docs`.*

*Generated at: 2026-09-25T09:18:43.306876+00:00*

## adx

Average directional index: +DM/-DM per the strict-dominance rule (equal moves -> both 0), Wilder running-sum smoothing seeded with the first `period` values; +DI/-DI = 100*smoothed_DM/smoothed_TR (smTR == 0 -> DI = 0); DX = 100*|+DI - -DI|/(+DI + -DI) (denominator 0 -> DX = 0); ADX = Wilder smoothing of DX with the first valid output at index 2*period-1; all outputs in [0, 100].

**Outputs:** adx, plus_di, minus_di

**Allowed sources:** close

**Warmup:** 27 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|----------------------------------------------------------------------|
| period    | int  | 14      | 2.0 | 100.0 | Wilder smoothing period for DM/TR/DI/ADX; inclusive bounds [2, 100]. |

---

## atr

Average true range: TR = max(high-low, |high-prev_close|, |low-prev_close|), TR[0] = NaN; Wilder smoothing alpha=1/period seeded with the SMA of TR[1..period]; first valid output at index period; output >= 0, never inf.

**Outputs:** value

**Allowed sources:** close

**Warmup:** 14 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|----------------------------------------------------------|
| period    | int  | 14      | 2.0 | 100.0 | Lookback bars for Wilder ATR; inclusive bounds [2, 100]. |

---

## bbands

Bollinger Bands: middle = SMA(period), upper/lower = middle ± k * sample-std(period, ddof=1) per ADR-0004; warmup = period-1.

**Outputs:** upper, middle, lower

**Allowed sources:** open, high, low, close, volume

**Warmup:** 19 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|-------|---------|-----|-------|---------------------------------------------------------|
| period    | int   | 20      | 2.0 | 500.0 | SMA/std window; inclusive bounds [2, 500].              |
| k         | float | 2.0     | 0.1 | 10.0  | Band width in standard deviations; inclusive [0.1, 10]. |

---

## ema

Exponential moving average: alpha = 2/(period+1), seeded with the SMA of the first `period` values (ADR-0002); first valid output at index period-1.

**Outputs:** value

**Allowed sources:** open, high, low, close, volume

**Warmup:** 19 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|---------------------------------------------------|
| period    | int  | 20      | 2.0 | 500.0 | Window length in bars; inclusive bounds [2, 500]. |

---

## highest

Highest high of the PREVIOUS `period` bars (current bar excluded): highest[t] = max(high[t-period..t-1]); first valid output at index period. Breakout signals compare close[t] > highest[t] using only past highs — no lookahead by construction.

**Outputs:** value

**Allowed sources:** high

**Warmup:** 20 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|----------------------------------------------------------------------------------|
| period    | int  | 20      | 2.0 | 500.0 | Lookback bars (PREVIOUS bars only, current excluded); inclusive bounds [2, 500]. |

---

## lowest

Lowest low of the PREVIOUS `period` bars (current bar excluded): lowest[t] = min(low[t-period..t-1]); first valid output at index period. Breakdown signals compare close[t] < lowest[t] using only past lows — no lookahead by construction.

**Outputs:** value

**Allowed sources:** low

**Warmup:** 20 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|----------------------------------------------------------------------------------|
| period    | int  | 20      | 2.0 | 500.0 | Lookback bars (PREVIOUS bars only, current excluded); inclusive bounds [2, 500]. |

---

## macd

MACD: line = EMA(fast) - EMA(slow), signal = EMA(line, signal), hist = line - signal; SMA-seeded EMA per ADR-0002; warmup = slow + signal - 2; source close only.

**Outputs:** line, signal, hist

**Allowed sources:** close

**Warmup:** 33 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|---------------------------------------------------------|
| fast      | int  | 12      | 2.0 | 200.0 | Fast EMA length; inclusive bounds [2, 200].             |
| slow      | int  | 26      | 2.0 | 200.0 | Slow EMA length; inclusive bounds [2, 200].             |
| signal    | int  | 9       | 2.0 | 200.0 | Signal EMA length on the MACD line; inclusive [2, 200]. |

---

## obv

On-balance volume: OBV[0] = volume[0]; up bars add volume, down bars subtract it, FLAT closes carry the previous value (neutral — classic Wilder convention, NOT ta's flat-adds convention); valid from the first bar (warmup 0); can be negative.

**Outputs:** value

**Allowed sources:** close

**Warmup:** 0 bars

**Parameters:**

No parameters.

---

## roc

Rate of change: (price[t]/price[t-period] - 1) * 100; zero or NaN base price -> NaN (never inf); first valid output at index period.

**Outputs:** value

**Allowed sources:** open, high, low, close, volume

**Warmup:** 10 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|--------------------------------------------------------------|
| period    | int  | 10      | 1.0 | 500.0 | Lookback bars for rate of change; inclusive bounds [1, 500]. |

---

## rsi

Relative strength index: Wilder smoothing alpha=1/period, seeded with the SMA of the first `period` gains/losses (ADR-0003); first valid output at index period; flat prices -> 50, only gains -> 100, only losses -> 0; output always in [0, 100].

**Outputs:** value

**Allowed sources:** open, high, low, close, volume

**Warmup:** 14 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|----------------------------------------------------------|
| period    | int  | 14      | 2.0 | 100.0 | Lookback bars for Wilder RSI; inclusive bounds [2, 100]. |

---

## sma

Simple moving average: mean of the last `period` source values; first valid output at index period-1 (ADR-0002).

**Outputs:** value

**Allowed sources:** open, high, low, close, volume

**Warmup:** 19 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-------|---------------------------------------------------|
| period    | int  | 20      | 2.0 | 500.0 | Window length in bars; inclusive bounds [2, 500]. |

---

## stoch

Stochastic oscillator: %K = 100*(close-lowest_low)/(highest_high-lowest_low) over k_period bars; smooth_period > 1 SMA-smooths %K BEFORE %D; %D = SMA(%K, d_period); flat windows (HH == LL) -> %K = 50; outputs k and d, first valid at k_period+smooth_period+d_period-3.

**Outputs:** k, d

**Allowed sources:** close

**Warmup:** 17 bars

**Parameters:**

| Parameter | Type | Default | Min | Max | Description |
|---------------|------|---------|-----|-------|-----------------------------------------------------------------------------------------|
| k_period      | int  | 14      | 2.0 | 100.0 | Raw %K lookback bars; inclusive bounds [2, 100].                                        |
| d_period      | int  | 3       | 2.0 | 100.0 | %D = SMA(%K, d_period); inclusive bounds [2, 100].                                      |
| smooth_period | int  | 3       | 1.0 | 10.0  | SMA smoothing applied to raw %K before %D (1 = no smoothing); inclusive bounds [1, 10]. |

---
