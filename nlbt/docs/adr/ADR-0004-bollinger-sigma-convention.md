# ADR-0004: Bollinger Bands Standard Deviation Convention

## Status: Accepted

## Context

Rolling standard deviation has two conventions:
1. Sample std (ddof=1): divides by N-1
2. Population std (ddof=0): divides by N

## Decision

Use sample standard deviation (ddof=1).

## Consequences

- Matches ta library and most charting platforms
- For period=20 the difference is small but testable
- Tests use ddof=1 arithmetic explicitly

## Implementation notes (P2-T4, 2026-09-20)

- Implemented inline in `compute_bbands` (SMA + rolling sample std); the
  vectorised kernel is differential-tested against a literal reference loop
  on three inputs (ramp / constant / NaN-poisoned).
- **Probed reality (correction to the Consequences above):** installed
  ta 0.11.0 uses **ddof=0** — read from `BollingerBands._run` source and
  proven arithmetically from the probe (upper[19] = 22.032562594670797 with
  middle 10.5 → half-width √33.25 = √(665/20), the ddof=0 divisor; ddof=1
  would give √(665/19) = √35). The Decision (ddof=1) stands — it is the
  task mandate and the classical charting convention — but "matches ta" is
  true only for the middle (SMA) column. The divergence is asserted and
  documented in `test_oracle_bbands_middle_matches_ta_bands_diverge`
  (OQ-0020); an in-test ddof=0 recomputation reproduces ta to 1e-9,
  isolating ddof as the only difference.
- For period=20 the band difference is 2·(√35 − √33.25) ≈ 0.2996 on the
  probe series — small, exactly as the ADR anticipated, and testable.

## Alternatives considered

- ddof=0: slightly different values, less common
  in financial reference implementations
