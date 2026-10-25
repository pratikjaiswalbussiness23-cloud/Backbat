# Golden files

Golden results live here per ROADMAP §8.4: **regenerating a golden file
requires an explicit owner-approved PR** that explains *why* the numbers
changed. An agent may not "update goldens" to make CI green (ROADMAP §2A/R5).

## `cli_run_result.json` (P5-T5 CLI v0)

### What it is

The `result.json` payload written by `nlbt run` on the committed fixture
pair, after dropping exactly the volatile fields listed below. Compared by
`tests/integration/test_cli.py::test_run_result_json_matches_golden`.

* spec: `tests/fixtures/spec/cli_golden.json`
  (12 weekday bars 2024-01-02..2024-01-17, zero fees/slippage,
  percent-of-equity 100 %, `close crosses_above 80` entry / `close
  crosses_below 75` exit — the rules fire exactly twice by design)
* data: `tests/fixtures/csv/cli_daily.csv` (hand-designed close series so
  every headline number is computable by hand)

### How it was produced (2026-10-25)

1. The hand-derived arithmetic and the independent numpy oracle assertions
   in `tests/integration/test_cli.py` (constants block at the top of the
   file: `FINAL_EQUITY`, `TOTAL_RETURN`, `NUM_TRADES`, `WIN_RATE`,
   `HAND_MAX_DRAWDOWN`, `EXPECTED_SHARPE`, `EXPECTED_VOLATILITY`,
   `EXPECTED_CAGR`, `EXPECTED_CALMAR`, `EXPECTED_BENCHMARK_TOTAL_RETURN`)
   were written FIRST and passed against the run. The expected values are
   derived from ROADMAP §4.5/§4.7 definitions and the fixture's literal
   prices — never copied from CLI output.
2. Only then the payload of a single real run was written:

   ```
   uv run python -c "main(['run', 'tests/fixtures/spec/cli_golden.json',
       '--data-csv', 'tests/fixtures/csv/cli_daily.csv', '--rf', '0.0',
       '--runs-dir', <tmp>])"   # via nlbt.cli.main, same entry as `nlbt run`
   ```

   with `_strip_volatile()` applied (the test module's own helper), using
   `json.dumps(..., indent=2, sort_keys=True)`.

### Volatile fields dropped before comparison (Phase B rulings Q2/Q5)

| Field | Why |
|-------|-----|
| `run_id` | timestamped per run |
| `manifest.run_started_at` | wall clock |
| `manifest.data.fetched_at` | wall clock (`BarsMeta.fetched_at`) |
| `manifest.data.source.path` | invocation-specific path |
| `manifest.code` (whole section) | git sha / Python / package versions vary by machine and commit; keys+types asserted separately in `test_manifest_code_section_keys_and_types` |
| `data_quality_report.warnings[]` entries with code `STALE_LAST_BAR` | the 2024 fixture ages past `STALE_TRADING_DAYS = 5` business days; `execute_run` is intentionally unchanged (Q2) |

`manifest.data.symbol`/`source.kind`, spec hashes, `data_hash` and all
metric values are NOT dropped: they are deterministic under the locked
toolchain (`uv.lock`, ADR-0001).
