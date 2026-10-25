"""``python -m nlbt`` entry point (P5-T5) -- delegates to :func:`nlbt.cli.main`."""

from __future__ import annotations

from nlbt.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
