# ADR-0003: RSI Seed Convention

## Status: Accepted

## Context

RSI Wilder smoothing requires a seed value.
Two conventions:

1. SMA-seeded (chosen): seed avg_gain and avg_loss
   with SMA of first `period` gains/losses
2. EMA-seeded: use pandas ewm(adjust=False)

## Decision

Use SMA-seeded Wilder smoothing.
alpha = 1/period (Wilder's alpha, not 2/(period+1))
warmup = period (first valid at index period)

## Consequences

- Matches standard RSI definition (Wilder 1978)
- Consistent with ADR-0002 (SMA-seeding)
- Converges to ta library after warmup window

## Implementation notes (P2-T3, 2026-09-20)

- Implemented from the formulas — no `pandas ewm()`, no `ta` in production
  code (both banned by the task text; `ta` is a dev-only oracle).
- Probed reality: `ta` 0.11.0 is NOT SMA-seeded — its installed source uses
  `ewm(alpha=1/window, min_periods=window, adjust=False)` from index 0, so
  ta's RSI is valid from index `window-1` (one bar earlier than Wilder's
  `period`) and its early values reflect a phantom-zero seed. Divergence is
  asserted and documented in `test_oracle_rsi_divergence_documented`, not
  hidden (OQ-0017). Convergence probed on 300-bar random walks: max
  |ours − ta| after bar 100 = 0.000000 (period 5) / 0.006190 (period 14).
- Special cases (task-mandated): avg_loss == 0 → RSI = 100.0;
  avg_gain == 0 and avg_loss == 0 → RSI = 50.0 (flat); output always in
  [0, 100], never inf/NaN outside warmup/contaminated inputs.

## Alternatives considered

- ewm(adjust=False): different seed, diverges from
  Wilder's original definition
