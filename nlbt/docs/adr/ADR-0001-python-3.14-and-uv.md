# ADR-0001 — Python 3.14, uv, and initial dependency set

- **Status:** Accepted — 2026-09-19
- **Task:** P0-T1 (ROADMAP.md §5, Phase 0). Covers Appendix G decisions #1 (Python version & package manager) and partially #2 (license: proprietary for now; revisit before any release).
- **Owner instruction:** pin the *newest* Python for which **all** planned dependencies (pandas, numpy, pyarrow, pydantic, numba, yfinance, anthropic, fastapi, streamlit) have official support **and prebuilt wheels**, verified by actually installing them — not assumed. Prefer a mature version over a brand-new one only if a dependency lags. Pin in `.python-version` and `requires-python`; record reasoning as an ADR.

## Context

- The only interpreter on this machine is CPython **3.14.4** (Windows, `C:\Python314`).
- Probe (2026-09-19, `uv 0.12.17`): created a throwaway 3.14 venv and ran
  `uv pip install --only-binary :all: pandas numpy pyarrow pydantic numba yfinance anthropic fastapi streamlit`
  — i.e. **prebuilt wheels only, source builds forbidden** — then imported all nine with
  `python -W error`. Result: everything resolved from wheels and imported cleanly.
  Installed versions observed:

  | Package | Version (probe) |
  |---|---|
  | pandas | 3.0.6 |
  | numpy | 2.5.3 |
  | pyarrow | 25.0.1 |
  | pydantic | 2.13.5 |
  | numba | 0.67.0 |
  | yfinance | 1.7.0 |
  | anthropic | 1.7.0 |
  | fastapi | 0.141.1 |
  | streamlit | 1.64.0 |

  numba/llvmlite (native JIT) was the riskiest candidate; it installs from wheels and imports on 3.14.
- No dependency lags on 3.14, so the "prefer a mature version" fallback did not apply.

## Decision

1. **Python:** pin `3.14` (`requires-python = ">=3.14"`, `.python-version` = `3.14`).
2. **Package manager:** **uv** with a committed `uv.lock`; the one documented install command is `uv sync`.
3. **Dependencies in `pyproject.toml` at this stage** (deterministic core, Phases 1–5 of the roadmap):
   pandas, numpy, pyarrow, pydantic + pydantic-settings, typer; dev group: ruff, mypy, pytest, pytest-cov.
   `anthropic` (Phase 6), `fastapi`/`streamlit` (Phase 7) and `numba` (optional, Phase 10) are **not** added yet —
   they will be added by their own tasks with their own `docs/DEPENDENCIES.md` entries (R12, R9).
   The probe above proves the platform can carry them when the time comes.

## Consequences

- Everything installs without a C compiler on Windows (`--only-binary` verified for all nine planned packages).
- **OneDrive note:** this repo lives inside a OneDrive-synced folder; uv's default hardlink link mode fails there
  (os error 396, observed 2026-09-19). `pyproject.toml` therefore sets `[tool.uv] link-mode = "copy"`.
- 3.14 is current stable; if a future dependency lags 3.14 support, this ADR must be revisited (new ADR), not silently worked around.
- uv.lock pins exact versions; upgrades happen deliberately via `uv lock --upgrade` with tests.

## R12 dependency register (packages actually added now)

| Package | Purpose (roadmap) | License | Alternatives considered |
|---|---|---|---|
| pandas 3.x | Bars container, engine, metrics (P1–P5) | BSD-3 | polars (rejected: ecosystem/conventions in §3.3) |
| numpy 2.x | Numerics under pandas | BSD-3 | — |
| pyarrow 25.x | Parquet data cache (P1-T4) | Apache-2.0 | fastparquet (rejected: less standard) |
| pydantic 2.x | Strategy Spec models, `extra="forbid"` (§4.1, P3) | MIT | dataclasses (rejected: weaker validation) |
| pydantic-settings | Env config §3.5 (P0-T4) | MIT | hand-rolled (rejected: reinvention) |
| typer | CLI (P5-T5) | MIT | argparse (rejected by §3.3) |
| ruff (dev) | Lint + format (P0-T2) | MIT | flake8+black (rejected: §3.3 names ruff) |
| mypy (dev) | `--strict` on `src/` (§3.3) | MIT | pyright (rejected: §3.3 names mypy) |
| pytest (dev) | Test runner (§3.3) | MIT | unittest (rejected: §3.3) |
| pytest-cov (dev) | Coverage (P0-T2) | MIT | — |

## Notes

- No third-party *APIs* are called by code yet (the package is an empty scaffold), so `docs/verified_apis.md`
  has no entries yet; it is created in P0-T3 and will list every verified call from Phase 1 onward (R1).
- The probe venv was deleted after recording results; the committed lockfile is the source of truth.
