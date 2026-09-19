"""P0-T1 smoke test: the package installs and imports.

P0-T1 acceptance: `make all` passes with a minimal test suite.
No numerical logic exists yet (Phases 1+ add it), so this test only proves
that the src-layout package is importable *as installed by uv sync*.
"""

import nlbt


def test_package_imports() -> None:
    assert nlbt.__version__ == "0.1.0"
