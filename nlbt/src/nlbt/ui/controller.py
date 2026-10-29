"""Pure UI state machine over the nlbt interpretation and confirmation gates."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nlbt.config import Config, load_nvidia_api_key
from nlbt.data.cache import CachedProvider
from nlbt.data.csv_provider import CSVProvider
from nlbt.data.models import DataProvider
from nlbt.data.yf_provider import YFinanceProvider
from nlbt.errors import NLUnsupportedError
from nlbt.nl.client import LLMClient
from nlbt.nl.openai_client import OpenAICompatibleClient
from nlbt.nl.recorded import RecordedClient
from nlbt.nl.service import (
    Confirmation,
    Interpretation,
    confirm_spec,
    interpret,
    require_confirmation,
    run_confirmed,
)
from nlbt.results import RunResult
from nlbt.spec.models import StrategySpec
from nlbt.spec.render import render_spec
from nlbt.spec.validate import validate_spec

__all__ = ["DISCLAIMER_TEXT", "UIController", "UIState"]

DISCLAIMER_TEXT = (
    "Historical simulation only; not investment advice. LLM translation uses NVIDIA NIM "
    "under the NVIDIA API Trial Terms of Service (evaluation/development only)."
)
DEMO_MODE_BANNER = "RECORDED DEMO MODE — serving recorded LLM responses"


@dataclass
class UIState:
    text: str = ""
    interpretation: Interpretation | None = None
    spec: StrategySpec | None = None
    rendering: str = ""
    edit_error: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    confirmation: Confirmation | None = None
    run_result: RunResult | None = None
    llm_source: str | None = None
    data_summary: dict[str, Any] | None = None
    bars_meta: Any = None
    data_source: str = "Bundled Demo CSV (offline)"
    demo_mode: bool = False


class UIController:
    """Controller callable without Streamlit; only injected service boundaries do I/O."""

    def __init__(
        self,
        *,
        client: LLMClient | Any | None = None,
        provider: DataProvider | None = None,
        data_csv: str | Path | None = None,
        config: Config | None = None,
    ) -> None:
        self.config = config or Config()
        self.data_csv = None if data_csv is None else str(data_csv)
        self.provider: DataProvider = provider or CSVProvider()
        self.client: Any = client or self._default_client(recorded=False)
        self.state = UIState()
        self._cached_provider: CachedProvider | None = None
        self._data_source_payload: dict[str, Any] | None = None

    def _runtime_config(self) -> Config:
        config = self.config
        if config.nvidia_api_key:
            return config
        root = Path(__file__).resolve().parents[3]
        for env_file in dict.fromkeys((Path.cwd() / ".env", root / ".env")):
            key = load_nvidia_api_key(env_file)
            if key:
                return config.model_copy(update={"nvidia_api_key": key})
        return config

    def _default_client(self, *, recorded: bool) -> LLMClient:
        recordings = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "llm"
        if recorded:
            return RecordedClient(fixture_dir=recordings)
        return OpenAICompatibleClient(config=self._runtime_config(), recordings_dir=recordings)

    def configure_modes(self, *, llm_mode: str, data_mode: str) -> None:
        self.state.demo_mode = (
            llm_mode == "Recorded Demo Mode (offline)" or os.environ.get("NLBT_LLM_DEMO") == "1"
        )
        if self.state.demo_mode and not isinstance(self.client, RecordedClient):
            self.client = self._default_client(recorded=True)
        elif not self.state.demo_mode and isinstance(self.client, RecordedClient):
            self.client = self._default_client(recorded=False)
        if data_mode == "Bundled Demo CSV (offline)":
            self.data_csv = str(
                Path(__file__).resolve().parents[3]
                / "tests"
                / "fixtures"
                / "csv"
                / "demo_spy_daily.csv"
            )
            self.provider = CSVProvider()
            self._cached_provider = None
            self._data_source_payload = {"kind": "csv", "path": self.data_csv}
        else:
            self.data_csv = None
            self.provider = self._yfinance_provider()
            self._data_source_payload = {"kind": "yfinance"}
        self.state.data_source = data_mode

    def _yfinance_provider(self) -> DataProvider:
        if self._cached_provider is None:
            self._cached_provider = CachedProvider(YFinanceProvider(), self.config.data_cache_dir)
        return self._cached_provider

    def interpret_request(self, text: str) -> Interpretation:
        self.state.text = text
        self.state.confirmation = None
        self.state.run_result = None
        self.state.edit_error = None
        self.state.validation_errors.clear()
        if isinstance(self.client, RecordedClient):
            self.state.demo_mode = True
        result = interpret(
            text,
            client=self.client,
            provider=self.provider,
            data_symbol_override=self.data_csv,
        )
        self.state.interpretation = result
        self.state.spec = result.spec
        self.state.rendering = result.rendering
        self.state.llm_source = (
            result.nl_meta.get("llm_source") if result.nl_meta is not None else None
        )
        self.state.data_summary = result.data_summary
        self.state.bars_meta = result.bars_meta
        return result

    def edit_spec_json(self, raw_json: str) -> bool:
        self.state.confirmation = None
        self.state.run_result = None
        self.state.edit_error = None
        self.state.validation_errors.clear()
        try:
            spec = StrategySpec.model_validate_json(raw_json)
        except ValidationError as exc:
            self.state.edit_error = str(exc)
            return False
        validation = validate_spec(spec)
        if validation.errors:
            self.state.validation_errors = [
                f"[{error.code}] {error.path}: {error.message}" for error in validation.errors
            ]
            self.state.edit_error = "\n".join(self.state.validation_errors)
            return False

        previous = self.state.spec
        if previous is None or previous.universe != spec.universe or previous.period != spec.period:
            try:
                fetch_symbol = self.data_csv or spec.universe.symbols[0]
                bars, meta = self.provider.get_bars(
                    fetch_symbol,
                    spec.period.start,
                    spec.period.end,
                    interval=spec.universe.interval,
                    adjusted=False,
                )
            except Exception as exc:
                self.state.edit_error = f"Data refresh failed: {type(exc).__name__}: {exc}"
                return False
            if self.state.interpretation is not None:
                self.state.interpretation = self.state.interpretation.__class__(
                    **{
                        **self.state.interpretation.__dict__,
                        "spec": spec,
                        "rendering": render_spec(spec),
                        "bars": bars,
                        "bars_meta": meta,
                        "data_summary": {
                            "provider": meta.provider,
                            "symbol": spec.universe.symbols[0],
                            "interval": spec.universe.interval,
                            "adjusted": meta.adjusted,
                            "bars": len(bars),
                            "start": bars.index.min().date().isoformat(),
                            "end": bars.index.max().date().isoformat(),
                        },
                    }
                )
            self.state.bars_meta = meta
            self.state.data_summary = {
                "provider": meta.provider,
                "symbol": spec.universe.symbols[0],
                "interval": spec.universe.interval,
                "adjusted": meta.adjusted,
                "bars": len(bars),
                "start": bars.index.min().date().isoformat(),
                "end": bars.index.max().date().isoformat(),
            }
        self.state.spec = spec
        self.state.rendering = render_spec(spec)
        if self.state.interpretation is not None:
            self.state.interpretation = self.state.interpretation.__class__(
                **{
                    **self.state.interpretation.__dict__,
                    "spec": spec,
                    "rendering": self.state.rendering,
                }
            )
        return True

    @property
    def can_confirm(self) -> bool:
        interp = self.state.interpretation
        return bool(
            interp is not None
            and interp.status == "ok"
            and not interp.unsupported
            and self.state.spec is not None
            and not self.state.edit_error
            and not self.state.validation_errors
        )

    @property
    def can_run(self) -> bool:
        if not self.can_confirm or self.state.spec is None:
            return False
        try:
            require_confirmation(self.state.spec, self.state.confirmation)
        except Exception:
            return False
        return True

    def confirm(self) -> Confirmation | None:
        if not self.can_confirm or self.state.spec is None:
            return None
        self.state.confirmation = confirm_spec(self.state.spec, confirmed_via="ui")
        return self.state.confirmation

    def run(self) -> RunResult:
        if self.state.interpretation is None:
            raise RuntimeError("Interpret a request before running a backtest")
        if (
            self.state.interpretation.status == "unsupported"
            or self.state.interpretation.unsupported
        ):
            raise NLUnsupportedError(
                "The request contains features nlbt cannot express; strict mode refuses to run",
                details={"unsupported": self.state.interpretation.unsupported},
                hint="Rephrase without the unsupported features (see the unsupported list).",
            )
        self.state.interpretation = self.state.interpretation.__class__(
            **{
                **self.state.interpretation.__dict__,
                "spec": self.state.spec,
                "rendering": self.state.rendering,
            }
        )
        result = run_confirmed(
            self.state.interpretation,
            self.state.confirmation,
            data_source=self._data_source_payload,
        )
        self.state.run_result = result
        return result

    @property
    def is_recorded_demo(self) -> bool:
        return bool(
            self.state.demo_mode
            or os.environ.get("NLBT_LLM_DEMO") == "1"
            or isinstance(self.client, RecordedClient)
            or self.state.llm_source in {"recorded", "recorded-demo"}
        )

    @property
    def demo_mode_banner(self) -> str | None:
        return DEMO_MODE_BANNER if self.is_recorded_demo else None

    @property
    def weak_sample_warning(self) -> str | None:
        if self.state.run_result is None:
            return None
        raw = self.state.run_result.metrics.get("num_trades")
        n = int(raw or 0)
        if n < 30:
            return f"Warning: only {n} trades — statistically weak sample (< 30 trades)"
        return None

    @property
    def honesty_bar(self) -> dict[str, Any]:
        result = self.state.run_result
        spec = self.state.spec
        if result is None or spec is None:
            return {}
        data = result.manifest["data"]
        return {
            "data_source": self.state.data_source,
            "adjusted": data.get("adjusted"),
            "start": result.equity_curve.index.min().date().isoformat(),
            "end": result.equity_curve.index.max().date().isoformat(),
            "bars": data.get("bars"),
            "fee_bps": spec.execution.fee_bps,
            "slippage_bps": spec.execution.slippage_bps,
            "num_trades": result.metrics.get("num_trades"),
        }

    @property
    def disclaimer(self) -> str:
        return DISCLAIMER_TEXT
