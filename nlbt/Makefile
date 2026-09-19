# nlbt — Makefile (P0-T1 scaffold, P0-T2 quality tooling)
# Works with GNU make and mingw32-make (Windows).
# Plain `uv` (installed by `pip install uv` locally, by setup-uv on CI) so the
# same recipes run on developer machines and in GitHub Actions.

UV ?= uv

.PHONY: all lint type test sync clean

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
	$(UV) run pytest --cov --cov-report=term-missing

clean:
	$(RM) -r .pytest_cache .mypy_cache .ruff_cache .coverage
