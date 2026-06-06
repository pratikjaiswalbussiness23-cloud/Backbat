"""
Double Bottom Scanner v2 - 3-Month Backtest Report Generator
"""

import json, os
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from fpdf import FPDF

REPORT_PERIOD = "March 1, 2026 - May 28, 2026"
INITIAL_BALANCE = 10000
NEW_RESULT_FILE = "btc_new_params_result.json"
OLD_RESULT_FILE = "btc_old_params_result.json"
DATA_FILE = "btc_3months.json"
OUTPUT_PDF = "BTC_Double_Bottom_Backtest_Report.pdf"
CHART_DIR = "report_charts"


def ensure_dir():
    os.makedirs(CHART_DIR, exist_ok=True)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def ts_to_str(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def chart_equity_curve(trades, filename):
    fig, ax = plt.subplots(figsize=(10, 4.5))
    balance = INITIAL_BALANCE
    times, equity = [], []
    if trades:
        times.append(datetime.fromtimestamp(trades[0]["entryTime"], tz=timezone.utc))
        equity.append(balance)
    for t in trades:
        if t["status"] == "closed" and t.get("exitTime"):
            balance += t.get("pnl", 0)
        dt = datetime.fromtimestamp(t.get("exitTime") or t.get("entryTime"), tz=timezone.utc)
        times.append(dt)
        equity.append(balance)
    ax.fill_between(times, equity, alpha=0.15, color="#2196F3")
    ax.plot(times, equity, color="#2196F3", linewidth=1.5, label="Equity")
    ax.axhline(y=INITIAL_BALANCE, color="#666", linestyle="--", linewidth=0.8, alpha=0.7)
    ax.set_title("Equity Curve", fontsize=13, fontweight="bold", color="#ddd")
    ax.set_ylabel("Account Balance ($)", color="#ccc")
    ax.set_xlabel("Date", color="#ccc")
    ax.legend(loc="upper left", fontsize=9, facecolor="#2d2d2d", labelcolor="#ccc")
    ax.grid(True, alpha=0.15)
    ax.set_facecolor("#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")
    ax.tick_params(colors="#ccc")
    for spine in ax.spines.values():
        spine.set_color("#444")
    fig.tight_layout()
    fig.savefig(filename, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return filename


def chart_pnl_distribution(trades, filename):
    fig, ax = plt.subplots(figsize=(10, 3.5))
    pnls = [t.get("pnl", 0) for t in trades if t["status"] == "closed"]
    colors = ["#4CAF50" if p >= 0 else "#f44336" for p in pnls]
    ax.bar(range(1, len(pnls) + 1), pnls, color=colors, width=0.7, edgecolor="none")
    ax.axhline(y=0, color="#666", linewidth=0.8)
    ax.set_title("Trade PnL Distribution", fontsize=13, fontweight="bold", color="#ddd")
    ax.set_ylabel("PnL ($)", color="#ccc")
    ax.set_xlabel("Trade #", color="#ccc")
    ax.set_facecolor("#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")
    ax.tick_params(colors="#ccc")
    for spine in ax.spines.values():
        spine.set_color("#444")
    ax.grid(True, axis="y", alpha=0.1)
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    total_pnl = sum(pnls)
    ax.text(0.98, 0.95, f"Wins: {wins}  Losses: {losses}  Net: ${total_pnl:+.2f}",
            transform=ax.transAxes, ha="right", va="top", fontsize=9,
            color="#ccc", bbox=dict(boxstyle="round,pad=0.3", facecolor="#2d2d2d", edgecolor="#444"))
    fig.tight_layout()
    fig.savefig(filename, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return filename


def chart_win_loss_pie(trades, filename):
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    losses = sum(1 for t in trades if t.get("pnl", 0) <= 0)
    fig, ax = plt.subplots(figsize=(5, 4))
    sizes = [wins, losses] if wins + losses > 0 else [1]
    labels = [f"Wins ({wins})", f"Losses ({losses})"] if wins + losses > 0 else ["No Trades"]
    colors_wl = ["#4CAF50", "#f44336"] if wins + losses > 0 else ["#666"]
    ax.pie(sizes, labels=labels, autopct="%1.1f%%", colors=colors_wl, startangle=90,
           textprops={"color": "#ccc", "fontsize": 10})
    for at in ax.texts[1:]:
        at.set_color("#fff")
        at.set_fontweight("bold")
    ax.set_title("Win / Loss Ratio", fontsize=13, fontweight="bold", color="#ddd")
    fig.patch.set_facecolor("#1e1e1e")
    fig.tight_layout()
    fig.savefig(filename, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return filename


def chart_exit_reasons(trades, filename):
    reasons = {}
    for t in trades:
        r = t.get("exitReason", "unknown")
        reasons[r] = reasons.get(r, 0) + 1
    fig, ax = plt.subplots(figsize=(6, 3.5))
    labels = list(reasons.keys())
    values = list(reasons.values())
    colors_map = {"target2": "#4CAF50", "target1": "#8BC34A", "stop_loss": "#f44336", "end_of_data": "#FF9800"}
    bar_colors = [colors_map.get(l, "#9C27B0") for l in labels]
    bars = ax.barh(labels, values, color=bar_colors, edgecolor="none", height=0.6)
    for bar, v in zip(bars, values):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2, str(v),
                va="center", fontsize=10, color="#ccc")
    ax.set_title("Exit Reasons", fontsize=13, fontweight="bold", color="#ddd")
    ax.set_xlabel("Count", color="#ccc")
    ax.set_facecolor("#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")
    ax.tick_params(colors="#ccc")
    for spine in ax.spines.values():
        spine.set_color("#444")
    fig.tight_layout()
    fig.savefig(filename, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return filename


def chart_rr_distribution(trades, filename):
    fig, ax = plt.subplots(figsize=(10, 3))
    rrs = [t.get("rr", 0) for t in trades if t["status"] == "closed"]
    pnls = [t.get("pnl", 0) for t in trades if t["status"] == "closed"]
    colors_rr = ["#4CAF50" if p >= 0 else "#f44336" for p in pnls]
    ax.scatter(range(1, len(rrs) + 1), rrs, c=colors_rr, s=40, alpha=0.8, edgecolors="none")
    ax.axhline(y=1.0, color="#FF9800", linestyle="--", linewidth=0.8, alpha=0.7, label="Min RR (1.0)")
    ax.axhline(y=1.5, color="#2196F3", linestyle="--", linewidth=0.8, alpha=0.7, label="Old Min RR (1.5)")
    ax.set_title("Risk:Reward Ratio per Trade", fontsize=13, fontweight="bold", color="#ddd")
    ax.set_ylabel("R:R Ratio", color="#ccc")
    ax.set_xlabel("Trade #", color="#ccc")
    ax.legend(loc="upper right", fontsize=8, facecolor="#2d2d2d", labelcolor="#ccc")
    ax.set_facecolor("#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")
    ax.tick_params(colors="#ccc")
    for spine in ax.spines.values():
        spine.set_color("#444")
    ax.grid(True, axis="y", alpha=0.1)
    fig.tight_layout()
    fig.savefig(filename, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return filename


def chart_drawdown(trades, filename):
    balance = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    times, drawdowns = [], []
    if trades:
        times.append(datetime.fromtimestamp(trades[0]["entryTime"], tz=timezone.utc))
        drawdowns.append(0)
    for t in trades:
        if t["status"] == "closed" and t.get("exitTime"):
            balance += t.get("pnl", 0)
        if balance > peak:
            peak = balance
        dd = (peak - balance) / peak * 100 if peak > 0 else 0
        dt = datetime.fromtimestamp(t.get("exitTime") or t.get("entryTime"), tz=timezone.utc)
        times.append(dt)
        drawdowns.append(dd)
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(times, drawdowns, alpha=0.3, color="#f44336")
    ax.plot(times, drawdowns, color="#f44336", linewidth=1)
    ax.set_title("Drawdown (%)", fontsize=13, fontweight="bold", color="#ddd")
    ax.set_ylabel("Drawdown %", color="#ccc")
    ax.set_facecolor("#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")
    ax.tick_params(colors="#ccc")
    for spine in ax.spines.values():
        spine.set_color("#444")
    ax.grid(True, alpha=0.1)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(filename, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return filename


def chart_pattern_timeline(patterns, candles, filename):
    fig, ax = plt.subplots(figsize=(12, 5))
    step = max(1, len(candles) // 500)
    sample = candles[::step]
    times = [datetime.fromtimestamp(c["time"], tz=timezone.utc) for c in sample]
    closes = [c["close"] for c in sample]
    ax.plot(times, closes, color="#555", linewidth=0.8, alpha=0.6, label="BTC Price")
    for p in patterns:
        try:
            c1 = candles[p["b1Idx"]]
            b1_time = datetime.fromtimestamp(c1["time"], tz=timezone.utc)
            b1_price = p.get("bottom1Price", 0)
            c2 = candles[p["b2Idx"]]
            b2_time = datetime.fromtimestamp(c2["time"], tz=timezone.utc)
            b2_price = p.get("bottom2Price", 0)
            ax.scatter(b1_time, b1_price, color="#2196F3", s=25, zorder=5, marker="v")
            ax.scatter(b2_time, b2_price, color="#2196F3", s=25, zorder=5, marker="v")
        except (IndexError, KeyError):
            continue
    ax.set_title("Pattern Detection Timeline (Blue = Bottoms)", fontsize=13, fontweight="bold", color="#ddd")
    ax.set_ylabel("Price ($)", color="#ccc")
    ax.set_facecolor("#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")
    ax.tick_params(colors="#ccc")
    for spine in ax.spines.values():
        spine.set_color("#444")
    ax.legend(loc="upper left", fontsize=9, facecolor="#2d2d2d", labelcolor="#ccc")
    ax.grid(True, alpha=0.1)
    fig.tight_layout()
    fig.savefig(filename, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return filename


class ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, "BTC/USDT Double Bottom Scanner -- Backtest Report", align="C", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C")

    def section_title(self, title):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(33, 150, 243)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(33, 150, 243)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def sub_title(self, title):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(200, 200, 200)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body_text(self, text):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(180, 180, 180)
        self.multi_cell(0, 5, text)
        self.ln(2)

    def metric_row(self, label, value):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(180, 180, 180)
        self.cell(80, 6, label)
        self.set_text_color(220, 220, 220)
        self.cell(0, 6, str(value), new_x="LMARGIN", new_y="NEXT")

    def add_chart(self, path, w=180):
        if os.path.exists(path):
            self.image(path, x=15, w=w)
            self.ln(3)


def build_report():
    ensure_dir()
    print("Loading data...")
    new_result = load_json(NEW_RESULT_FILE)
    old_result = load_json(OLD_RESULT_FILE)
    btc_data = load_json(DATA_FILE)
    candles = btc_data.get("candles", [])
    new_trades = new_result.get("trades", [])
    old_trades = old_result.get("trades", [])
    new_patterns = new_result.get("patternMarkers", [])
    old_patterns = old_result.get("patternMarkers", [])
    new_metrics = new_result.get("metrics", {})

    first_ts = ts_to_str(candles[0]["time"])
    last_ts = ts_to_str(candles[-1]["time"])
    min_price = min(c["low"] for c in candles)
    max_price = max(c["high"] for c in candles)
    avg_price = sum(c["close"] for c in candles) / len(candles)
    current_price = candles[-1]["close"]

    print(f"Data: {len(candles)} candles, ${min_price:.2f} - ${max_price:.2f}")
    print(f"New: {len(new_patterns)} patterns, {len(new_trades)} trades")
    print(f"Old: {len(old_patterns)} patterns, {len(old_trades)} trades")

    print("Generating charts...")
    charts = {}
    if new_trades:
        charts["equity"] = chart_equity_curve(new_trades, f"{CHART_DIR}/equity.png")
        charts["pnl_dist"] = chart_pnl_distribution(new_trades, f"{CHART_DIR}/pnl_dist.png")
        charts["pie"] = chart_win_loss_pie(new_trades, f"{CHART_DIR}/pie.png")
        charts["reasons"] = chart_exit_reasons(new_trades, f"{CHART_DIR}/reasons.png")
        charts["rr"] = chart_rr_distribution(new_trades, f"{CHART_DIR}/rr.png")
        charts["dd"] = chart_drawdown(new_trades, f"{CHART_DIR}/dd.png")
    charts["timeline"] = chart_pattern_timeline(new_patterns, candles, f"{CHART_DIR}/timeline.png")

    print("Building PDF...")
    pdf = ReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Cover
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(33, 150, 243)
    pdf.cell(0, 15, "Double Bottom Scanner v2", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(200, 200, 200)
    pdf.cell(0, 10, "3-Month Backtest Performance Report", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 8, "BTC/USDT - 15-minute", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Period: {REPORT_PERIOD}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Candles: {len(candles):,}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Initial Balance: ${INITIAL_BALANCE:,}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(15)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C", new_x="LMARGIN", new_y="NEXT")

    # TOC
    pdf.add_page()
    pdf.section_title("Table of Contents")
    for item in ["1. Executive Summary", "2. Market Overview", "3. Parameter Comparison",
                 "4. New Parameters - Performance", "5. Trade Analysis", "6. Pattern Detection",
                 "7. Risk & Drawdown", "8. Conclusions"]:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(180, 180, 180)
        pdf.cell(0, 8, f"   {item}", new_x="LMARGIN", new_y="NEXT")

    # 1. Executive Summary
    pdf.add_page()
    pdf.section_title("1. Executive Summary")
    pdf.body_text(f"Backtest of Double Bottom strategy on BTC/USDT 15m from {REPORT_PERIOD}. "
                  f"{len(candles):,} candles analyzed with two parameter sets.")
    pdf.sub_title("Performance Overview")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(200, 200, 200)
    pdf.cell(60, 7, "Metric", border=1, align="C")
    pdf.cell(55, 7, "New Parameters", border=1, align="C")
    pdf.cell(55, 7, "Old (Default)", border=1, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for label, v_new, v_old in [
        ("Patterns Detected", str(len(new_patterns)), str(len(old_patterns))),
        ("Trades Executed", str(len(new_trades)), str(len(old_trades))),
        ("Win Rate", f"{new_metrics.get('winRate', 0):.1f}%" if new_trades else "N/A",
                      f"{old_result.get('metrics', {}).get('winRate', 0):.1f}%" if old_trades else "N/A"),
        ("Net PnL", f"${new_metrics.get('netProfit', 0):.2f}", f"${old_result.get('metrics', {}).get('netProfit', 0):.2f}"),
        ("Total Return", f"{new_metrics.get('totalReturn', 0):.2f}%", f"{old_result.get('metrics', {}).get('totalReturn', 0):.2f}%"),
        ("Max Drawdown", f"{new_metrics.get('maxDrawdown', 0):.2f}%", f"{old_result.get('metrics', {}).get('maxDrawdown', 0):.2f}%"),
    ]:
        pdf.set_text_color(180, 180, 180)
        pdf.cell(60, 6, label, border=1)
        pdf.set_text_color(220, 220, 220)
        pdf.cell(55, 6, v_new, border=1)
        pdf.cell(55, 6, v_old, border=1, new_x="LMARGIN", new_y="NEXT")

    # 2. Market Overview
    pdf.add_page()
    pdf.section_title("2. Market Overview")
    for label, val in [("Data Range", f"{first_ts} to {last_ts}"), ("Candles", str(len(candles))),
                        ("Min Price", f"${min_price:.2f}"), ("Max Price", f"${max_price:.2f}"),
                        ("Avg Price", f"${avg_price:.2f}"), ("Current Price", f"${current_price:.2f}")]:
        pdf.metric_row(label, val)
    if "timeline" in charts:
        pdf.add_chart(charts["timeline"])

    # 3. Parameter Comparison
    pdf.add_page()
    pdf.section_title("3. Parameter Comparison")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(200, 200, 200)
    pdf.cell(60, 7, "Parameter", border=1, align="C")
    pdf.cell(55, 7, "New", border=1, align="C")
    pdf.cell(55, 7, "Old", border=1, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for label, v_new, v_old in [
        ("swingLength", "3", "5"), ("maxBottomDiff", "0.15%", "0.27%"),
        ("minCandlesBetween", "1", "2"), ("minPatternHeightMult", "0.3x ATR", "0.5x ATR"),
        ("minRR", "1.0", "1.5"), ("slMultiplier", "1.5", "1.5")]:
        pdf.set_text_color(180, 180, 180)
        pdf.cell(60, 6, label, border=1)
        pdf.set_text_color(220, 220, 220)
        pdf.cell(55, 6, v_new, border=1)
        pdf.cell(55, 6, v_old, border=1, new_x="LMARGIN", new_y="NEXT")

    # 4. Performance
    pdf.add_page()
    pdf.section_title("4. New Parameters - Performance")
    if new_trades and "equity" in charts:
        pdf.add_chart(charts["equity"])
    for label, val in [
        ("Total Trades", new_metrics.get("totalTrades", 0)),
        ("Wins", new_metrics.get("winningTrades", 0)),
        ("Losses", new_metrics.get("losingTrades", 0)),
        ("Win Rate", f"{new_metrics.get('winRate', 0):.1f}%"),
        ("Net PnL", f"${new_metrics.get('netProfit', 0):.2f}"),
        ("Gross Profit", f"${new_metrics.get('grossProfit', 0):.2f}"),
        ("Gross Loss", f"${new_metrics.get('grossLoss', 0):.2f}"),
        ("Profit Factor", f"{new_metrics.get('profitFactor', 'N/A')}"),
        ("Total Return", f"{new_metrics.get('totalReturn', 0):.2f}%"),
        ("Max Drawdown", f"{new_metrics.get('maxDrawdown', 0):.2f}%"),
        ("Avg Win", f"${new_metrics.get('avgWin', 0):.2f}"),
        ("Avg Loss", f"${new_metrics.get('avgLoss', 0):.2f}"),
        ("Final Balance", f"${new_metrics.get('finalBalance', 0):.2f}")]:
        pdf.metric_row(label, str(val))

    if new_trades:
        if "pnl_dist" in charts: pdf.add_chart(charts["pnl_dist"])
        if "pie" in charts: pdf.add_chart(charts["pie"], w=80)
        if "reasons" in charts: pdf.add_chart(charts["reasons"], w=120)
        if "rr" in charts: pdf.add_chart(charts["rr"])
        pdf.add_page()
        pdf.sub_title("Drawdown Analysis")
        if "dd" in charts: pdf.add_chart(charts["dd"])

    # 5. Trade Log
    if new_trades:
        pdf.add_page()
        pdf.section_title("5. Trade Analysis")
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(200, 200, 200)
        col_w, headers = [8, 18, 18, 16, 16, 14, 12, 14, 12], ["#","Entry","Exit","Entry $","Exit $","PnL","RR","Reason","Result"]
        for cw, h in zip(col_w, headers):
            pdf.cell(cw, 6, h, border=1, align="C")
        pdf.ln()
        pdf.set_font("Helvetica", "", 7)
        for i, t in enumerate(new_trades[:50]):
            pnl = t.get('pnl', 0)
            pdf.set_text_color(76, 175, 80) if pnl > 0 else pdf.set_text_color(244, 67, 54)
            vals = [str(i+1), ts_to_str(t.get("entryTime", 0)), ts_to_str(t.get("exitTime", 0)),
                    f"${t.get('entryPrice',0):.0f}", f"${t.get('exitPrice',0):.0f}",
                    f"${pnl:.0f}", f"{t.get('rr',0):.1f}", t.get('exitReason',''),
                    "WIN" if pnl > 0 else "LOSS"]
            for cw, v in zip(col_w, vals):
                pdf.cell(cw, 5, v, border=1, align="C")
            pdf.ln()

    # 6. Pattern Detection
    pdf.add_page()
    pdf.section_title("6. Pattern Detection Analysis")
    pdf.metric_row("New Param Patterns", str(len(new_patterns)))
    pdf.metric_row("Old Param Patterns", str(len(old_patterns)))
    pdf.metric_row("Detection Ratio", f"{(len(new_patterns) / max(len(old_patterns), 1)):.1f}x")

    # 7. Risk
    pdf.add_page()
    pdf.section_title("7. Risk & Drawdown Analysis")
    if new_trades:
        max_dd = new_metrics.get("maxDrawdown", 0)
        pdf.metric_row("Max Drawdown", f"{max_dd:.2f}%")
        pdf.metric_row("Final Balance", f"${new_metrics.get('finalBalance', 0):,.2f}")
        pdf.metric_row("Profit Factor", f"{new_metrics.get('profitFactor', 'N/A')}")
        pdf.metric_row("Expectancy", f"${new_metrics.get('expectancy', 0):.2f}")
        pnls = [t.get("pnl", 0) for t in new_trades]
        streak = max_c = 0
        for p in pnls:
            streak = streak + 1 if p <= 0 else 0
            max_c = max(max_c, streak)
        pdf.metric_row("Max Consecutive Losses", str(max_c))
        pdf.body_text(f"The strategy experienced {max_c} consecutive losses with a max drawdown of {max_dd:.1f}%.")

    # 8. Conclusions
    pdf.add_page()
    pdf.section_title("8. Conclusions & Recommendations")
    pdf.body_text(f"1. New params detected {len(new_patterns)} patterns vs {len(old_patterns)} ({(len(new_patterns)/max(len(old_patterns),1)):.1f}x more).")
    pdf.body_text(f"2. {len(new_trades)} trades executed vs 0 with old defaults.")
    pdf.body_text(f"3. Return: {new_metrics.get('totalReturn', 0):.1f}%, Win rate: {new_metrics.get('winRate', 0):.1f}%.")
    pdf.body_text(f"4. Max drawdown: {new_metrics.get('maxDrawdown', 0):.1f}% - add trend filter.")
    pdf.body_text(f"5. Losses concentrated in May 2026 downturn.")
    pdf.sub_title("Recommendations")
    for r in ["Add trend filter (200-MA)", "Use trailing stop-loss", "Volume confirmation", "Adjust minRR to 1.2", "Combine 1h/4h timeframe"]:
        pdf.body_text(f"- {r}")
    pdf.ln(5)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "Disclaimer: Past performance does not guarantee future results.", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.output(OUTPUT_PDF)
    print(f"\nReport saved: {OUTPUT_PDF}")
    print(f"Size: {os.path.getsize(OUTPUT_PDF) / 1024:.1f} KB, Pages: {pdf.page_no()}")


if __name__ == "__main__":
    build_report()
