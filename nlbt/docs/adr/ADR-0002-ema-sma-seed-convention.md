# ADR-0002: EMA and SMA Seed Convention

## Status: Accepted

## Context

EMA requires a seed value for the first computation.
Two common conventions exist:

1. SMA-seeded: first EMA = SMA of first `period` values
2. First-value seeded: first EMA = first price value

## Decision

Use SMA-seeded convention for both EMA and RSI.
Warmup = period - 1 for both.

## Consequences

- Matches pandas-ta and most reference implementations
  after the convergence window
- First valid output at index period-1
- Tests after this index are directly comparable to
  pandas-ta oracle (with documented divergence if any)
- RSI (P2-T3) will use the same Wilder smoothing seed

## Implementation notes (P2-T2, 2026-09-20)

- Implemented from the formulas — `pandas ewm()` is deliberately NOT used
  (its seed rule is an implementation detail that can drift across pandas
  versions).
- The task-named oracle `pandas-ta` is uninstallable in this project (its
  `numba==0.61.2` pin requires `numpy<2.3`; nlbt requires `numpy>=2.5` —
  OQ-0015). The oracle is `ta==0.11.0` (bukosabino, MIT, dev-only).
- Probed reality: `ta`'s EMA is FIRST-VALUE seeded — on [10..20] with
  window=3 it produces [nan, nan, 11.25, 12.125, ...], i.e. e[1] =
  0.5·11 + 0.5·10 = 10.5, e[2] = 0.5·12 + 0.5·10.5 = 11.25. Ours produces
  11.0 at that position (SMA seed 33/3). The divergence is asserted and
  documented in `test_oracle_ema_divergence_documented`, not hidden.
  Convergence verified on 120 bars: max |ours − ta| after a 30-bar window
  = 1.55e-9, within the ADR's "matches after the convergence window".

## Alternatives considered

- First-value seeded: simpler but diverges from references
  for longer periods
