# nlbt

Natural-language trading strategy backtester.
You describe a strategy in plain English; nlbt turns it into a validated JSON spec,
shows you exactly what will run, then backtests it deterministically.
The LLM only translates — it never computes numbers and never runs code
(ROADMAP.md §0.3, C1/C4/C5).

**Status:** Phase 0 scaffold (P0-T1). No backtest engine exists yet.
Read `ROADMAP.md` for the plan and `docs/adr/ADR-0001-python-3.14-and-uv.md`
for tooling decisions.

## Requirements

- Python **3.14** (pinned in `.python-version`, justified in ADR-0001)
- [uv](https://docs.astral.sh/uv/) — `pip install uv`

## Install (one command)

```bash
uv sync
```

This creates the virtual environment from the committed `uv.lock` and installs
the project in editable mode with dev tools (ruff, mypy, pytest).

## Commands

| Command | What it does |
|---|---|
| `make all` | lint + type-check + tests (the task gate) |
| `make lint` | ruff check + format check |
| `make type` | mypy `--strict` on `src/` |
| `make test` | pytest |

(On Windows without GNU `make` on PATH, `mingw32-make` is equivalent.)

## Not financial advice

This project produces historical simulations, not predictions
(ROADMAP.md, header disclaimer).
