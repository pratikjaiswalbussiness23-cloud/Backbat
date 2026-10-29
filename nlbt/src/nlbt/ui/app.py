"""Single-page Streamlit UI; all strategy/run rules live in UIController."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from nlbt.ui.controller import DISCLAIMER_TEXT, UIController
from nlbt.ui.demo_cases import DEMO_CASES

DATA_MODES = ("Bundled Demo CSV (offline)", "yfinance (cached)")
LLM_MODES = ("Live NIM (with Recorded Demo fallback)", "Recorded Demo Mode (offline)")


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


def _render_warnings(items: list[str]) -> None:
    if items:
        st.subheader("Warnings")
        for item in items:
            st.warning(item)


def _render_results(controller: UIController) -> None:
    result = controller.state.run_result
    if result is None:
        return
    st.header("Backtest Results")
    if controller.weak_sample_warning:
        st.error(controller.weak_sample_warning)
    st.subheader("Simulation honesty bar")
    st.json(controller.honesty_bar)

    metrics = sorted(set(result.metrics) | set(result.benchmark_metrics))
    st.subheader("Strategy vs benchmark metrics")
    st.dataframe(
        pd.DataFrame(
            {
                "metric": metrics,
                "strategy": [result.metrics.get(key) for key in metrics],
                "benchmark": [result.benchmark_metrics.get(key) for key in metrics],
            }
        ),
        width="stretch",
        hide_index=True,
    )
    st.subheader("Equity curve")
    curve = result.equity_curve[["equity"]].rename(columns={"equity": "Strategy"}).copy()
    benchmark_values = result.manifest.get("benchmark_equity_curve")
    if benchmark_values is not None:
        curve["Benchmark"] = benchmark_values
    st.line_chart(curve)
    st.subheader("Drawdown")
    st.line_chart(result.equity_curve[["drawdown"]])
    st.subheader("Trades")
    st.dataframe(
        pd.DataFrame([trade.__dict__ for trade in result.trades]),
        width="stretch",
        hide_index=True,
    )
    _render_warnings(result.warnings)


def main() -> None:
    st.set_page_config(page_title="nlbt Strategy Backtester", layout="wide")
    st.title("Natural-language strategy backtester")
    st.caption(DISCLAIMER_TEXT)
    controller = _controller()

    with st.sidebar:
        data_mode = st.selectbox("Data source", DATA_MODES, key="nlbt_data_mode")
        llm_mode = st.selectbox("LLM mode", LLM_MODES, key="nlbt_llm_mode")
        if st.button("Apply modes", key="nlbt_apply_modes"):
            controller.configure_modes(llm_mode=llm_mode, data_mode=data_mode)
            st.rerun()
        case_labels = [case.title for case in DEMO_CASES]
        selected_label = st.selectbox("Demo prompt", case_labels, key="nlbt_demo_prompt")
        selected = next(case for case in DEMO_CASES if case.title == selected_label)

    if controller.is_recorded_demo:
        st.info(controller.demo_mode_banner)
    text = st.text_area("Describe a strategy", value=selected.prompt, height=120)
    if st.button("Interpret", type="primary", key="nlbt_interpret"):
        with st.spinner("Interpreting request..."):
            new_interpretation = controller.interpret_request(text)
        if new_interpretation.status == "error" and new_interpretation.error is not None:
            st.error(str(new_interpretation.error))
        st.rerun()

    interpretation = controller.state.interpretation
    if interpretation is not None:
        st.subheader("Interpretation")
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

    _render_results(controller)
    st.divider()
    st.caption(DISCLAIMER_TEXT)


if __name__ == "__main__":
    main()
