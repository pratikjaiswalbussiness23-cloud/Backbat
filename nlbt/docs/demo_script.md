# nlbt demo script (hackathon)

Historical simulation only; not investment advice.

Five built-in demo prompts live in `src/nlbt/ui/demo_cases.py` and are
replayed from deterministic recorded LLM fixtures in `tests/fixtures/llm/`
against the bundled offline dataset
`tests/fixtures/csv/demo_spy_daily.csv` (522 daily bars,
2024-01-02 → 2025-12-31).

## OQ-0063 check

Per OQ-0063 (take-profit is currently evaluated before the trailing stop on a
shared bar — see [`limitations.md`](limitations.md)), **none of the five
prompts combines a trailing stop with a take-profit**:

- Prompt 2 has a stop loss only.
- Prompt 3 has a trailing stop only (no take-profit).
- The other three have no risk exits at all.

## The 5 demo prompts and their exact expected outcomes

Outcomes below were re-verified today by replaying each prompt through
`RecordedClient` + `demo_spy_daily.csv` (zero network calls).

### 1. SMA 50/200 crossover → `ok`, runs

```text
Buy SPY when the 50-day SMA crosses above the 200-day SMA, and sell when the 50-day SMA crosses below the 200-day SMA, from 2024-01-02 to 2025-12-31.
```

- `status = "ok"`, explicit period 2024-01-02 → 2025-12-31.
- After **Confirm Spec**: **4 trades** on `demo_spy_daily.csv`
  (`num_trades = 4`), 522 bars, 18 metric keys including benchmark.
- Recording: `tests/fixtures/llm/demo_case_1.json`.

### 2. RSI mean reversion with 5% stop → `ok`, runs

```text
Buy SPY when RSI(14) is below 30, sell when RSI(14) is above 70, and use a 5% stop loss from 2024-01-02 to 2025-12-31.
```

- `status = "ok"`; stop loss 5 %, **no take-profit** (OQ-0063-safe).
- After **Confirm Spec**: **20 trades** (`num_trades = 20`), 522 bars.
- Surfaces the expected warning:
  `100% equity sizing with a stop loss may result in large drawdowns.`
- Recording: `tests/fixtures/llm/demo_case_2.json`.

### 3. 20-day high breakout with 8% trailing stop → `ok`, runs

```text
Buy SPY when it closes above its previous 20-day high and use an 8% trailing stop, from 2024-01-02 to 2025-12-31.
```

- `status = "ok"`; `highest` 20 breakout, trailing stop 8 %,
  **no take-profit** (OQ-0063-safe).
- After **Confirm Spec**: **5 trades** (`num_trades = 5`), 522 bars.
- Recording: `tests/fixtures/llm/demo_case_3.json`.

### 4. Ambiguous → `needs_clarification`, blocks confirm/run

```text
Buy SPY when the moving averages cross.
```

- `status = "needs_clarification"`, question id
  **`indicator_period_missing`** ("Which moving-average lengths should cross
  (for example 50 and 200)?").
- `Confirm Spec` is disabled, `run()` raises `E_NL_AMBIGUOUS`.
- Recording: `tests/fixtures/llm/demo_case_4.json`.

### 5. Unsupported → `unsupported`, blocks confirm/run

```text
Buy SPY call options before earnings when sentiment is bullish.
```

- `status = "unsupported"`, `unsupported =
  ["options", "earnings events", "sentiment analysis"]`.
- Confirmation is refused and `run()` raises `E_NL_UNSUPPORTED` — the
  product never silently approximates options into stock rules.
- Recording: `tests/fixtures/llm/demo_case_5.json`.

## Offline setup (no network, no API key)

**Streamlit UI:**

```bash
uv sync
uv run streamlit run src/nlbt/ui/app.py
```

Sidebar:

1. **Data source** → `Bundled Demo CSV (offline)`
2. **LLM mode** → `Recorded Demo Mode (offline)` → **Apply modes** (the
   `RECORDED DEMO MODE — serving recorded LLM responses` banner appears)
3. **Demo prompt** → pick one of the five
4. **Interpret** → (for 1–3) **Confirm Spec** → **Run Confirmed Backtest**

The UI also supports the JSON editor demo: expand **Edit Spec JSON**, change
`name`, **Apply Spec Edit** — the confirmation is invalidated (Gate 7) and the
run button disables until you confirm again.

**CLI (recorded replay):** the recorded fixtures are keyed to the *default*
model id and fingerprint, so leave `NLBT_LLM_MODEL` unset, and point the
client at an unreachable endpoint so it falls back to the recording (verified
output below — exit 0, `[nlbt][DEMO]` label on stderr):

```bash
NLBT_LLM_DEMO=1 NVIDIA_API_KEY=unused NLBT_LLM_BASE_URL=http://127.0.0.1:9/v1 \
  uv run nlbt ask "Buy SPY when RSI(14) is below 30, sell when RSI(14) is above 70, and use a 5% stop loss from 2024-01-02 to 2025-12-31." \
  --data-csv tests/fixtures/csv/demo_spy_daily.csv --yes --no-persist
```

Observed on the run above:

```text
status:  ok
resolved symbol: SPY
data:    csv tests/fixtures/csv/demo_spy_daily.csv | 522 bars | 2024-01-02..2025-12-31
=== STRATEGY: SPY RSI 14 mean reversion ===
...
confirmed: yes (--yes)
num_trades                          20          n/a
total_return                 -0.244409   -0.0650578
[nlbt][DEMO] serving RECORDED LLM response -- endpoint unreachable; output is NOT from the model
```

**No-LLM mode** (nothing leaves the machine at all):

```bash
uv run nlbt run tests/fixtures/spec/cli_golden.json \
  --data-csv tests/fixtures/csv/demo_spy_daily.csv --no-persist
```

## 3-minute pitch & talk track

**0:00–0:20 — The problem.**
"Backtests lie. Lookahead bias, missing costs, cherry-picked data, and an LLM
that confidently invents numbers. nlbt is built the other way around: *the LLM
translates, it never calculates, and every result is reproducible.*"

**0:20–0:50 — The flow (show the Mermaid diagram in README.md or the UI).**
"You type a strategy in English. A schema-forced LLM returns a JSON envelope.
It passes pydantic + semantic validation with at most two repair rounds, dates
are resolved in code with an injected clock, the ticker is verified against
real bars — then nlbt renders back, in deterministic English, exactly what
will run, with every default disclosed. Nothing runs until you press Confirm."

**0:50–1:40 — Live demo, prompt 2 (RSI).**
"Watch: Interpret → *status ok*, symbol SPY, 522 bars, nine disclosed
assumptions, the rendering says `rsi strictly below 30` / `stop loss 5%`. I
confirm and run — 20 trades, strategy vs buy-and-hold benchmark side by side,
an honesty bar with the data source, fee and slippage bps, plus the warning
that 100 % equity sizing with a stop can draw down hard. All from recorded
fixtures: zero network, zero API key."

**1:40–2:10 — The gates (prompt 4 and 5).**
"Now the boring English: 'Buy SPY when the moving averages cross.' — it
*refuses to guess* and asks which lengths. And options + earnings + sentiment
— it refuses outright: `unsupported`, the confirm button never enables. Fail
loudly beats guessing. Also: edit the spec JSON and the confirmation is
invalidated — you cannot run something you didn't confirm."

**2:10–2:40 — Why trust it.**
"1,025 passing tests at 88.3 % line+branch coverage. Hypothesis property tests
for all 14 engine invariants, truncation and future-poison lookahead tests with
a red-on-leak canary, differential tests against `backtesting.py` on scenarios
S1–S6 with every difference written up, byte-identical determinism, and golden
CLI tests. On a 100,000-bar series the engine runs in 4.5 seconds
(22,154 bars/s). Known limitations are published, not buried — see
`docs/limitations.md`."

**2:40–3:00 — Close.**
"You can also run a JSON spec with no LLM at all — nothing leaves the machine.
The LLM path talks to NVIDIA NIM under the trial terms, evaluation only. The
numbers you saw are reproducible from a manifest. Historical simulation only —
not investment advice."

**Contingencies**

- *No internet:* everything above is the offline path (recorded fixtures +
  bundled CSV). Just say so and show the `[nlbt][DEMO]` stderr label.
- *Endpoint returns 404/429:* the demo mode falls back to the recording; if
  asked, point at `NLBT_LLM_MODEL` (model ids are account-gated, OQ-0082).
- *Runner asks about the take-profit trailing-stop ordering:* answer honestly —
  OQ-0063: take-profit is checked first today, trailing-stop-first is decided
  and scheduled, and no demo prompt combines the two exits.
