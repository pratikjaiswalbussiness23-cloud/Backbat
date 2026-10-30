"""Single-page Streamlit UI; all strategy/run rules live in UIController.

A dark, dashboard-style "backtest lab": brand header + mode chips, a 4-step
progress rail (Describe → Interpret → Confirm → Results), KPI cards and a
tabbed report. Rendering only — no engine, metrics or service logic lives
here (tests/unit/test_ui_controller.py pins UIController instead).
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from nlbt.ui.controller import DISCLAIMER_TEXT, UIController
from nlbt.ui.demo_cases import DEMO_CASES

DATA_MODES = ("Bundled Demo CSV (offline)", "yfinance (cached)")
LLM_MODES = ("Live NIM (with Recorded Demo fallback)", "Recorded Demo Mode (offline)")

#: In-app demo guide (sidebar checkbox expands it). Trade counts verified by
#: replaying each prompt offline against demo_spy_daily.csv (522 bars,
#: 2024-01-02..2025-12-31); see docs/demo_script.md for the full script.
DEMO_GUIDE_MD = """
**Five steps** (about a minute):

1. **Set the modes** in the sidebar — data source `Bundled Demo CSV (offline)`
   and LLM mode `Recorded Demo Mode (offline)` give you a fully offline run:
   no network, no API key. Click **Apply modes**.
2. **Pick a prompt** from *Demo prompt*, or type your own strategy in plain
   English in the box below.
3. **Interpret** — nlbt translates through the schema-forced LLM, validates
   the spec, resolves dates in code, verifies the ticker, then renders back
   exactly what will run, in deterministic English, with every default
   disclosed.
4. **Confirm Spec** — nothing runs until you confirm the exact spec on
   screen. Editing the JSON invalidates the confirmation, so you can never
   run something you did not confirm.
5. **Run Confirmed Backtest** — results show headline KPIs, strategy vs
   benchmark, the equity/drawdown curves, the trade log and the honesty bar
   (data source, fees, slippage, versions).

**The five built-in prompts and what to expect**

| Prompt | Status | Expected outcome |
|---|---|---|
| SMA 50/200 crossover | `ok` | runs — **4 trades** |
| RSI mean reversion with stop | `ok` | runs — **20 trades** + drawdown warning |
| 20-day high breakout | `ok` | runs — **5 trades** |
| Ambiguous moving averages | `needs_clarification` | asks which lengths; Confirm disabled |
| Options + earnings + sentiment | `unsupported` | refused outright; Confirm disabled |

The last two are the product working as designed — **fail loudly beats
guessing**, and nlbt never silently approximates options into stock rules.

Full scripted walkthrough: `docs/demo_script.md`.
"""

#: Dashboard skin on top of the dark theme in .streamlit/config.toml.
CSS = """
<style>
:root{--acc:#00e5a0;--bad:#ff5c7a;--warn:#ffb020;--card:#131a26;
  --line:#1f2a3d;--mut:#8ea3c0;--txt:#e6edf7;}
.stApp{background:radial-gradient(1200px 600px at 12% -10%,#16233a,#0b0f17 55%);}
[data-testid="stHeading"] h1,[data-testid="stHeading"] h2,
[data-testid="stHeading"] h3{color:var(--txt);letter-spacing:.02em;}
.hero{display:flex;justify-content:space-between;align-items:center;gap:12px;
  flex-wrap:wrap;padding:14px 18px;border:1px solid var(--line);
  border-radius:16px;margin:2px 0 10px;
  background:linear-gradient(90deg,#101828,#0b1220);}
.brand{font-size:26px;font-weight:800;letter-spacing:1.5px;color:var(--txt);}
.brand i{color:var(--acc);font-style:normal;}
.tag{font-size:13px;color:var(--mut);margin-left:10px;}
.chips{display:flex;gap:8px;flex-wrap:wrap;}
.chip{font-size:12px;padding:5px 11px;border-radius:999px;
  border:1px solid #2a3a55;color:#cfe0ff;background:#111a2b;white-space:nowrap;}
.chip.ok{border-color:var(--acc);color:var(--acc);}
.chip.warn{border-color:var(--warn);color:var(--warn);}
.steps{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 14px;}
.step{font-size:12.5px;padding:6px 13px;border-radius:999px;
  border:1px solid #26344c;color:#7f93b3;background:#0f1624;}
.step.done{background:var(--acc);border-color:var(--acc);color:#06201a;
  font-weight:700;}
.step.now{border-color:var(--acc);color:var(--acc);font-weight:700;}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
  gap:12px;margin:6px 0 10px;}
.kpi{border:1px solid var(--line);border-radius:14px;padding:12px 14px;
  background:var(--card);}
.kpi .lab{font-size:11px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--mut);}
.kpi .val{font-size:26px;font-weight:800;margin-top:4px;color:var(--txt);}
.kpi .val.up{color:var(--acc);}
.kpi .val.down{color:var(--bad);}
.kpi .val.na{color:#7f93b3;}
.kpi .sub{font-size:12px;color:var(--mut);margin-top:4px;}
[data-testid="stExpander"]{border:1px solid var(--line);border-radius:14px;
  background:#101828;}
[data-testid="stJson"],[data-testid="stCode"]{border:1px solid var(--line);
  border-radius:12px;background:#0f1624;}
[data-baseweb="tab-list"]{gap:8px;background:#0f1624;padding:6px;
  border-radius:12px;border:1px solid var(--line);}
[data-baseweb="tab"]{border-radius:10px;color:var(--mut);}
[data-baseweb="tab"][aria-selected="true"]{color:var(--acc);font-weight:700;}
[data-testid="stBaseButton-primary"]{background:linear-gradient(90deg,#00e5a0,
  #38bdf8);color:#06201a;border:none;font-weight:700;border-radius:10px;}
[data-testid="stButton"] button{border-radius:10px;}
.hint{font-size:13.5px;color:var(--mut);}
</style>
"""


def _controller() -> UIController:
    controller = st.session_state.get("nlbt_ui_controller")
    if not isinstance(controller, UIController):
        controller = UIController()
        controller.configure_modes(
            llm_mode=LLM_MODES[0],
            data_mode=DATA_MODES[0],
        )
        st.session_state["nlbt_ui_controller"] = controller
    return controller


def _fmt_pct(value: float | None) -> str:
    """Metric formatting: ``None`` (undefined metric) renders ``n/a``."""
    if value is None:
        return "n/a"
    return f"{float(value):+.2%}"


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.2f}"


def _fmt_int(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.0f}"


def _tone(value: float | None, *, positive_is_good: bool = True) -> str:
    """Colour class for a KPI value: up / down / na."""
    if value is None:
        return "na"
    good = value >= 0 if positive_is_good else value <= 0
    return "up" if good else "down"


def _kpi(label: str, value: str, tone: str, sub: str) -> str:
    return (
        f'<div class="kpi"><div class="lab">{html.escape(label)}</div>'
        f'<div class="val {tone}">{html.escape(value)}</div>'
        f'<div class="sub">{html.escape(sub)}</div></div>'
    )


def _render_hero(controller: UIController) -> None:
    offline = controller.is_recorded_demo
    data_mode = controller.state.data_source
    llm_chip = (
        '<span class="chip ok">RECORDED DEMO · offline</span>'
        if offline
        else '<span class="chip warn">LIVE NIM · sends strategy text</span>'
    )
    st.markdown(
        '<div class="hero">'
        '<div><span class="brand">nlbt<i>_</i></span>'
        '<span class="tag">the LLM translates, it never calculates — '
        "every result is reproducible</span></div>"
        f'<div class="chips"><span class="chip">'
        f"{html.escape(data_mode)}</span>{llm_chip}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_steps(
    interpretation: object,
    confirmation: object,
    run_result: object,
) -> None:
    s2 = interpretation is not None
    s3 = confirmation is not None
    s4 = run_result is not None

    def cls(done: bool, active: bool) -> str:
        if done:
            return "step done"
        return "step now" if active else "step"

    st.markdown(
        f'<div class="steps">'
        f'<span class="{cls(s2, not s2)}">1 · Describe</span>'
        f'<span class="{cls(s3, s2 and not s3)}">2 · Interpret</span>'
        f'<span class="{cls(s4, s3 and not s4)}">3 · Confirm</span>'
        f'<span class="{cls(s4, False)}">4 · Results</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_warnings(items: list[str]) -> None:
    if items:
        st.subheader("Warnings")
        for item in items:
            st.warning(item)


def _render_run_header(controller: UIController) -> None:
    """Compact strip: what exactly just ran (spec, symbol, window, run id)."""
    result = controller.state.run_result
    if result is None:
        return
    manifest = result.manifest
    spec_info = manifest.get("spec") or {}
    data_info = manifest.get("data") or {}
    quality = result.data_quality_report or {}
    start = quality.get("start") or "?"
    end = quality.get("end") or "?"
    bars = quality.get("bars") or data_info.get("bars") or "?"
    parts = [
        str(spec_info.get("name") or "strategy"),
        str((spec_info.get("universe") or {}).get("symbols", [""])[0]),
        f"{start}..{end}",
        f"{bars} bars",
        f"run {getattr(result, 'run_id', '')}",
    ]
    st.caption("  ·  ".join(part for part in parts if part))


def _render_results(controller: UIController) -> None:
    result = controller.state.run_result
    if result is None:
        return
    st.header("4 · Results")
    _render_run_header(controller)
    if controller.weak_sample_warning:
        st.error(controller.weak_sample_warning)

    metrics = result.metrics
    benchmark = result.benchmark_metrics
    total_return = metrics.get("total_return")
    final_equity = metrics.get("final_equity")
    initial = metrics.get("initial_capital")
    equity_delta = (
        None if final_equity is None or initial is None else float(final_equity) - float(initial)
    )
    num_trades = metrics.get("num_trades") or 0
    win_rate = metrics.get("win_rate")
    if num_trades == 0 or win_rate is None:
        win_tone = "na"
    else:
        win_tone = "up" if float(win_rate) > 0 else "down"
    cards = (
        _kpi(
            "Total return",
            _fmt_pct(total_return),
            _tone(total_return),
            f"benchmark {_fmt_pct(benchmark.get('total_return'))}",
        )
        + _kpi(
            "Final equity", _fmt_num(final_equity), _tone(equity_delta), f"from {_fmt_num(initial)}"
        )
        + _kpi(
            "Trades",
            _fmt_int(metrics.get("num_trades")),
            "na",
            f"exposure {_fmt_pct(metrics.get('exposure'))}",
        )
        + _kpi(
            "Win rate",
            _fmt_pct(win_rate),
            win_tone,
            f"profit factor {_fmt_num(metrics.get('profit_factor'))}",
        )
        + _kpi(
            "Max drawdown",
            _fmt_pct(metrics.get("max_drawdown")),
            _tone(metrics.get("max_drawdown"), positive_is_good=False),
            f"Sharpe {_fmt_num(metrics.get('sharpe'))}",
        )
    )
    st.markdown(f'<div class="kpis">{cards}</div>', unsafe_allow_html=True)

    st.subheader("Simulation honesty bar")
    st.caption("The data, costs and versions behind every number above.")
    st.json(controller.honesty_bar)

    tab_metrics, tab_equity, tab_trades = st.tabs(
        ["Strategy vs benchmark", "Equity & drawdown", "Trades"]
    )
    with tab_metrics:
        rows = sorted(set(metrics) | set(benchmark))
        st.dataframe(
            pd.DataFrame(
                {
                    "metric": rows,
                    "strategy": [metrics.get(key) for key in rows],
                    "benchmark": [benchmark.get(key) for key in rows],
                }
            ),
            width="stretch",
            hide_index=True,
        )
    with tab_equity:
        curve = result.equity_curve[["equity"]].rename(columns={"equity": "Strategy"}).copy()
        benchmark_values = result.manifest.get("benchmark_equity_curve")
        if benchmark_values is not None:
            curve["Benchmark"] = benchmark_values
        st.line_chart(curve)
        st.caption("Drawdown (negative = below the running peak)")
        st.line_chart(result.equity_curve[["drawdown"]])
    with tab_trades:
        st.dataframe(
            pd.DataFrame([trade.__dict__ for trade in result.trades]),
            width="stretch",
            hide_index=True,
        )
    _render_warnings(result.warnings)


def main() -> None:
    st.set_page_config(page_title="nlbt Strategy Backtester", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    controller = _controller()
    _render_hero(controller)
    st.caption(DISCLAIMER_TEXT)

    with st.sidebar:
        st.markdown("### 1 · Modes")
        data_mode = st.selectbox("Data source", DATA_MODES, key="nlbt_data_mode")
        llm_mode = st.selectbox("LLM mode", LLM_MODES, key="nlbt_llm_mode")
        if st.button("Apply modes", key="nlbt_apply_modes"):
            controller.configure_modes(llm_mode=llm_mode, data_mode=data_mode)
            st.rerun()
        st.markdown("### 2 · Strategy")
        case_labels = [case.title for case in DEMO_CASES]
        selected_label = st.selectbox("Demo prompt", case_labels, key="nlbt_demo_prompt")
        selected = next(case for case in DEMO_CASES if case.title == selected_label)
        st.markdown("### Help")
        show_guide = st.checkbox(
            "Show demo guide", value=False, key="nlbt_show_guide", help="Step-by-step walkthrough"
        )

    interpretation = controller.state.interpretation
    _render_steps(
        interpretation,
        controller.state.confirmation,
        controller.state.run_result,
    )

    with st.expander("Demo guide — run your first backtest in 5 steps", expanded=show_guide):
        st.markdown(DEMO_GUIDE_MD)

    if controller.is_recorded_demo:
        st.info(controller.demo_mode_banner)

    st.subheader("1 · Describe")
    if interpretation is None:
        st.markdown(
            '<p class="hint">New here? Open the <b>Demo guide</b> above, or just '
            "hit <b>Interpret</b> with the sample prompt.</p>",
            unsafe_allow_html=True,
        )
    text = st.text_area("Describe a strategy", value=selected.prompt, height=120)
    if st.button("Interpret", type="primary", key="nlbt_interpret"):
        with st.spinner("Interpreting request..."):
            new_interpretation = controller.interpret_request(text)
        if new_interpretation.status == "error" and new_interpretation.error is not None:
            st.error(str(new_interpretation.error))
        st.rerun()

    if interpretation is not None:
        st.subheader("2 · Review the deterministic rendering")
        st.badge(interpretation.status)
        if interpretation.resolved_symbol:
            st.write(f"Resolved symbol: **{interpretation.resolved_symbol}**")
        if interpretation.questions:
            st.markdown("**Questions**")
            st.json(interpretation.questions)
        if interpretation.unsupported:
            st.markdown("**Unsupported requests**")
            st.json(interpretation.unsupported)
        if controller.state.spec is not None:
            st.markdown("**Deterministic strategy rendering**")
            st.code(controller.state.rendering, language="text")
        if interpretation.assumptions:
            st.markdown("**Assumptions**")
            st.json(interpretation.assumptions)
        _render_warnings(interpretation.warnings)

        st.subheader("3 · Confirm and run")
        with st.expander("Edit Spec JSON"):
            initial_json = (
                controller.state.spec.model_dump_json(indent=2)
                if controller.state.spec is not None
                else "{}"
            )
            raw_json = st.text_area(
                "StrategySpec JSON", initial_json, height=300, key="nlbt_spec_json"
            )
            if st.button("Apply Spec Edit", key="nlbt_apply_edit"):
                if controller.edit_spec_json(raw_json):
                    st.success("Spec updated. Confirm it again before running.")
                else:
                    st.error(controller.state.edit_error or "Spec edit is invalid")

        confirm_col, run_col = st.columns(2)
        with confirm_col:
            if st.button("Confirm Spec", disabled=not controller.can_confirm, key="nlbt_confirm"):
                controller.confirm()
                st.success("Current spec confirmed.")
        with run_col:
            if st.button("Run Confirmed Backtest", disabled=not controller.can_run, key="nlbt_run"):
                try:
                    controller.run()
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
        if controller.state.edit_error:
            st.error(controller.state.edit_error)
        for error in controller.state.validation_errors:
            st.error(error)
        if controller.state.run_result is None:
            st.markdown(
                '<p class="hint">Next: hit <b>Run Confirmed Backtest</b> to see '
                "KPIs, curves and the trade log.</p>",
                unsafe_allow_html=True,
            )

    _render_results(controller)
    st.divider()
    st.caption(DISCLAIMER_TEXT)


if __name__ == "__main__":
    main()
