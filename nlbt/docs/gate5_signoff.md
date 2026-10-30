# Gate 5 Owner Sign-Off (Milestone M1)

- **Date:** 2026-10-30
- **Owner:** Pratik Jaiswal
- **Commit reviewed:** 10ad246

## 1. Reproducibility from JSON Only
- Verified 
lbt run tests/fixtures/spec/cli_golden.json --data-csv tests/fixtures/csv/cli_daily.csv --json across two local runs and a fresh git clone + uv sync.
- Normalized esult.json diff (excluding volatile un_id, un_started_at, etched_at, source.path, and manifest.code): **0 differences**.

## 2. Golden Results Committed
- 	ests/golden/cli_run_result.json and 	ests/golden/README.md committed and verified via uv run pytest tests/integration -v (34 passed).

## 3. Manual Review of Backtests vs Independent Tool (acktesting.py 0.6.6)
Reviewed side-by-side trade logs (entry/exit dates and prices), final equity, and total return across both zero-cost (Pass 1) and fee/slippage (10 bps fee, 5 bps slippage, Pass 2) runs:
1. **s2_sma_cross (SMA crossover):** 1 trade (2024-01-16 to 2024-01-27), exact match on prices (101.0 -> 99.0 zero-cost; 101.0505 -> 98.9505 with costs) and final equity (9980.0 / 9976.99999, delta 2e-12).
2. **s3_rsi_reversion (RSI mean-reversion):** 1 trade (2024-01-27 to 2024-02-10), exact match on prices and final equity (10088.136079 / 10085.301137, delta <= 2e-12).
3. **s4_donchian_breakout (Donchian breakout):** 1 trade (2024-01-27 to 2024-02-11), exact match on prices (107.4 -> 109.2 / 107.4537 -> 109.1454) and final equity (10018.0 / 10014.751009).
4. **s6_fixed_stop_loss (Fixed stop-loss supplement):** 2 trades (2024-01-04..08, 2024-01-10..13), exact match on prices and final equity (9830.0 / 9824.669203, delta 4e-12).

All differences are within <= 4e-12 IEEE 754 floating-point rounding as documented in docs/differential_notes.md.

## 4. Package Coverage (Combined Line + Branch >= 90%)
- src/nlbt/engine/*: 625 / 673 = 92.87% (MET)
- src/nlbt/metrics/*: 139 / 144 = 96.53% (MET)
- src/nlbt/spec/*: 766 / 829 = 92.40% (MET)
- Combined across the three core packages: 1530 / 1646 = 92.95% (1,025 passed, 1 skipped, 3 deselected).

**Verdict:** Gate 5 (Milestone M1) APPROVED and SIGNED OFF.
