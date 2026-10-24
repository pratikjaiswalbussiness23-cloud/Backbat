"""§4.6 result + manifest for one run (ROADMAP P5-T4a).

Only ``result.json`` persistence lives here; parquet files, ``load_run``
and ``nlbt replay`` arrive with P5-T4b.
"""

from __future__ import annotations

from nlbt.results.execute import RunResult, execute_run

__all__ = ["RunResult", "execute_run"]
