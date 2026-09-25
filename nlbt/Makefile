# nlbt — Makefile (P0-T1 scaffold, P0-T2 quality tooling)
# Works with GNU make and mingw32-make (Windows).
# Plain `uv` (installed by `pip install uv` locally, by setup-uv on CI) so the
# same recipes run on developer machines and in GitHub Actions.

UV ?= uv

.PHONY: all lint type test generate-docs sync clean

all: lint type test
	@echo "== make all: PASSED =="

sync:  ## create venv + install everything from the lockfile
	$(UV) sync

lint:
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests

type:
	$(UV) run mypy

test:
	$(UV) run pytest --cov --cov-report=term-missing --cov-report=xml

# P2-T8: regenerate docs/indicators.md + docs/indicators.json from the
# registry. Run manually or as a CI pre-step — NOT part of `all`; freshness
# on every PR is enforced by the staleness tests in
# tests/unit/test_indicators_docs.py (they fail if these files drift).
generate-docs:
	$(UV) run python -m nlbt.indicators.generate_docs

clean:
	$(RM) -r .pytest_cache .mypy_cache .ruff_cache .coverage
