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
nlbt ask TEXT [--yes] [--data-csv FILE] [--runs-dir DIR] [--no-persist] [--json]
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

### `ask` (P6-T4/T5/T10, hackathon subset)

`ask` translates plain-English strategy text with the configured
`OpenAICompatibleClient`, validates and renders it deterministically, and
verifies the parsed ticker by fetching bars through the selected provider.
Without `--data-csv`, the CLI lazily uses `CachedProvider(YFinanceProvider(),
Config().data_cache_dir)`; with `--data-csv FILE`, it uses `CSVProvider` and
passes the CSV path as the provider's `symbol` argument. Provider fetch results
are retained and reused for the backtest: a confirmed run does not fetch a
second time.

Before any run, the CLI presents the parsed summary, deterministic English
rendering, assumptions, warnings, unsupported items and data summary. It then
requires confirmation: `--yes` confirms non-interactively (and prints
`confirmed: yes (--yes)`); otherwise the exact prompt is
`Confirm run? [y/N]: `. Only `y`/`yes` confirms; `n`, empty input, EOF or any
other response cancels. Clarification/unsupported responses are displayed and
exit 0 without a confirmation prompt or a run. An `E_DATA_EMPTY` response
becomes a clarification asking which symbol to use; no alternative ticker is
suggested because the current providers do not support symbol search.

| `ask` option | Meaning |
|---|---|
| `--yes` | Confirm the displayed spec without prompting; `user_confirmed_at` is recorded in `manifest.nl`. |
| `--data-csv FILE` | Verify/load data from this CSV; its path is passed to `CSVProvider` while the resolved strategy symbol remains the parsed ticker. |
| `--runs-dir DIR` | Where `<run_id>/result.json` is written (default: `NLBT_RUNS_DIR`). |
| `--no-persist` | Do not write the result file. |
| `--json` | On a run, print only the same result payload serializer as `result.json`; on clarification/unsupported/cancel, print the documented interpretation object. The interactive prompt and confirmation log go to stderr so stdout remains valid JSON. |

The `ask` client uses `Config` for endpoint/model/key settings. If the
endpoint is unreachable, it raises `E_NL_LLM` unless `NLBT_LLM_DEMO=1` and a
matching recording exists under `tests/fixtures/llm`; demo replay emits the
`[nlbt][DEMO]` warning on stderr and records `llm_source="recorded-demo"`.
Missing credentials, offline mode, and a recording miss remain loud `E_NL_LLM`
errors. Keys are not printed.

`run_confirmed()` is the sole NL service path to `execute_run`: it requires a
confirmation bound to both the logic and full spec hashes. Any edit after
confirmation invalidates it. The NL manifest section is additive and
conditional, preserving existing `nlbt run` manifest/golden output; the
legacy `manifest.llm` fields remain null.

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
