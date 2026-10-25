# nlbt CLI (v0, P5-T5)

Historical simulation only; not investment advice.

A thin layer over the existing library: spec validation (`nlbt.spec.validate_spec`),
rendering (`nlbt.spec.render_spec`), the CSV/yfinance providers
(`nlbt.data.*`) and `nlbt.results.execute_run`. All logic stays in those
functions — the CLI only parses argv, formats output and maps errors to
exit codes.

## Install / invoke

```bash
uv sync                      # installs the `nlbt` console script ([project.scripts])
nlbt --help
uv run nlbt ...              # or, equivalently:
uv run python -m nlbt ...
```

Programmatic entry point (tests, future UI/LLM glue):

```python
from nlbt.cli import main
exit_code = main(["run", "spec.json", "--data-csv", "bars.csv"])  # -> int, never raises
```

The Streamlit UI and the LLM layer call `execute_run` directly — they do
NOT shell out to this CLI.

## Commands

```text
nlbt run SPEC.json [--data-csv FILE] [--rf 0.0] [--runs-dir DIR] [--no-persist] [--json]
nlbt validate-spec SPEC.json
nlbt render-spec SPEC.json
```

| Flag | Meaning |
|------|---------|
| `--data-csv FILE` | OHLCV CSV to backtest (the `symbol` argument of `CSVProvider` IS the file path). Without it, bars are fetched with the default provider (yfinance — network). The fetch window is always the spec's `period`; `manifest.data.source.path` records the CSV path verbatim. |
| `--rf FLOAT` | Annual risk-free rate for Sharpe (default `0.0`; always recorded as `risk_free_rate`). |
| `--runs-dir DIR` | Where `<run_id>/result.json` is written (default: `NLBT_RUNS_DIR`). |
| `--no-persist` | Do not write anything to disk (the summary then shows `result:  (not persisted)`). |
| `--json` | Print ONLY the result payload as JSON (byte-identical to the stored `result.json` when persisting; the in-memory payload otherwise). |

`run` prints a compact human summary on success: `run_id:` line, `result:`
path line, a spec line, a strategy-vs-benchmark metric table (undefined
metrics render as `n/a` — `NaN`/`Infinity` are never printed) and the
surfaced warnings.

`--help` carries: `Historical simulation only; not investment advice.`

## Exit codes

| Code | Meaning | Output |
|------|---------|--------|
| `0` | Success | summary / rendered spec / `valid: <path>` (+ any spec warnings) on stdout |
| `1` | Domain error (`nlbt.errors.NlbtError`) or unexpected exception | `[CODE] message (hint: ...)` on stderr (the §4.8 code, printed via `str(exc)`); unexpected exceptions print `unexpected error: <Type>: <message>` — full traceback only when `NLBT_DEBUG=1` |
| `2` | Usage error, or missing/unreadable spec file | plain `error: ...` message on stderr, no error code (owner ruling Q1) |

Examples of §4.8 codes you can see: `E_SPEC_SCHEMA` (malformed JSON /
schema violation), `E_SPEC_REF` / `E_SPEC_RANGE` (semantic validation
failures), `E_DATA_QUALITY` (bad CSV), straight from
`docs/OPEN_QUESTIONS.md`-documented taxonomy (ROADMAP §4.8).

## Deferred

- `nlbt validate-data SYMBOL` — deferred (logged as OQ-0079), not built in v0.
- Partial `--data-csv` coverage of the spec period is silently truncated
  (known limitation, OQ-0078).
