from fpdf import FPDF
from datetime import datetime

class DBReport(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Double Bottom Scanner - Results & Guide", align="L")
        self.cell(0, 8, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")
    def st(self, t, lv=1):
        if lv==1:
            self.set_font("Helvetica","B",16); self.set_text_color(20,60,120)
            self.cell(0,12,t,new_x="LMARGIN",new_y="NEXT")
            self.set_draw_color(20,60,120); self.line(10,self.get_y(),200,self.get_y()); self.ln(4)
        elif lv==2:
            self.set_font("Helvetica","B",13); self.set_text_color(40,80,140)
            self.cell(0,10,t,new_x="LMARGIN",new_y="NEXT"); self.ln(2)
        elif lv==3:
            self.set_font("Helvetica","B",11); self.set_text_color(60,60,60)
            self.cell(0,8,t,new_x="LMARGIN",new_y="NEXT"); self.ln(1)
    def bt(self, t):
        self.set_font("Helvetica","",10); self.set_text_color(40,40,40)
        self.multi_cell(0,5.5,t); self.ln(2)
    def tbl(self, hdrs, rows, cw=None):
        if cw is None: cw=[190/len(hdrs)]*len(hdrs)
        self.set_font("Helvetica","B",9); self.set_fill_color(30,60,120); self.set_text_color(255,255,255)
        for i,h in enumerate(hdrs): self.cell(cw[i],7,h,border=1,fill=True,align="C")
        self.ln()
        self.set_font("Helvetica","",9); self.set_text_color(30,30,30)
        for ri,row in enumerate(rows):
            f=ri%2==0; self.set_fill_color(240,245,255) if f else self.set_fill_color(255,255,255)
            for i,c in enumerate(row): self.cell(cw[i],6.5,str(c),border=1,fill=f,align="L" if i==0 else "C")
            self.ln()
        self.ln(3)
    def hbox(self, t, clr="blue"):
        cs={"blue":(230,240,255,20,60,120),"green":(230,255,230,20,100,40),"orange":(255,245,230,180,100,20)}
        br,bg,bb,tr,tg,tb=cs.get(clr,cs["blue"])
        self.set_fill_color(br,bg,bb); self.set_text_color(tr,tg,tb); self.set_font("Helvetica","B",11)
        self.multi_cell(190,7,t,fill=True,align="C"); self.set_text_color(40,40,40); self.ln(3)

def gen():
    p=DBReport(); p.alias_nb_pages(); p.set_auto_page_break(True,20)
    # COVER
    p.add_page(); p.ln(40)
    p.set_font("Helvetica","B",32); p.set_text_color(180,60,20)
    p.cell(0,15,"Double Bottom Scanner",align="C",new_x="LMARGIN",new_y="NEXT")
    p.set_font("Helvetica","",16); p.set_text_color(80,80,80)
    p.cell(0,10,"Backtest Results & Complete Usage Guide",align="C",new_x="LMARGIN",new_y="NEXT")
    p.ln(10); p.set_draw_color(180,60,20); p.line(60,p.get_y(),150,p.get_y()); p.ln(10)
    p.set_font("Helvetica","",12); p.set_text_color(100,100,100)
    p.cell(0,8,"Pattern Detection | Risk Management | Multi-Scenario Testing",align="C",new_x="LMARGIN",new_y="NEXT")
    p.cell(0,8,f"Report Date: {datetime.now().strftime('%B %d, %Y')}",align="C",new_x="LMARGIN",new_y="NEXT")
    p.cell(0,8,"Version 2.0 - Visual Backtester",align="C",new_x="LMARGIN",new_y="NEXT")
    p.ln(30); p.set_font("Helvetica","I",10); p.set_text_color(150,150,150)
    p.cell(0,6,"Not financial advice. Past performance does not guarantee future results.",align="C",new_x="LMARGIN",new_y="NEXT")
    # TOC
    p.add_page(); p.st("Table of Contents")
    for t in ["1. Executive Summary","2. What is the Double Bottom Pattern?","3. System Architecture (v2 + v3)","4. Backtest Configuration","5. Simulated Pattern Results (100 Patterns)","6. Real Data Detection (BTC 15m)","7. Strategy Rules & Filters","8. How to Install & Run","9. Complete UI Guide (All Tabs)","10. V3 4-Layer Engine","11. API Reference","12. Key Parameters","13. Risk Disclaimer"]:
        p.set_font("Helvetica","",11); p.set_text_color(40,40,40); p.cell(0,7,t,new_x="LMARGIN",new_y="NEXT")
    # 1. EXEC SUMMARY
    p.add_page(); p.st("1. Executive Summary")
    p.bt("The Double Bottom Scanner is a visual backtesting engine for the classic Double Bottom chart pattern. It detects two swing lows at similar price levels, confirms a neckline breakout, and simulates trades with proper risk management.")
    p.hbox("KEY FEATURES: 10 injected pattern scenarios + Real BTC data detection\nPartial Exit at TP1 + Trailing Stop for remaining position\n200-MA Trend Filter + Volume Confirmation + Daily Loss Limit","green")
    p.bt("The system includes both v2 (classic DB detection) and v3 (4-layer engine with multi-exchange data, spoof filtering, CVD divergence, and walk-forward validation).")
    # 2. WHAT IS DB?
    p.add_page(); p.st("2. What is the Double Bottom Pattern?")
    p.bt("A Double Bottom is a bullish reversal pattern that forms after a downtrend. It consists of:")
    p.bt("  1. Two swing lows at similar price levels (within maxBottomDiff tolerance)\n  2. A neckline rally between the two touches (the high between bottoms)\n  3. A breakout above the neckline with volume confirmation\n  4. A target equal to the pattern height projected from the neckline")
    p.bt("The pattern signals that sellers have exhausted and buyers are taking control. The neckline acts as resistance; once broken, it becomes support.")
    p.st("Pattern Anatomy",3)
    p.bt("  Bottom 1 (B1): First swing low - establishes support level\n  Bottom 2 (B2): Second swing low - must be at or below B1\n  Neckline: Highest high between B1 and B2\n  Breakout: Price closes above neckline\n  Target: Neckline + (Neckline - Bottom Price)")
    # 3. ARCHITECTURE
    p.add_page(); p.st("3. System Architecture")
    p.st("v2 Engine (Classic)",2)
    p.bt("  Data Layer: Binance/Yahoo/Generated candle data\n  Detection: Fractal swing low matching + neckline calculation\n  Filters: 200-MA trend, volume confirmation, daily loss limit\n  Execution: TP1 (1.5R) partial exit + trailing stop for remaining\n  Risk: ATR-based stop loss, position sizing by risk percent")
    p.st("v3 Engine (4-Layer)",2)
    p.bt("  L1 - Data: Multi-exchange ingestion (Binance, Bybit, OKX)\n  L2 - Detection: ATR sweeps, spoof filter, zone classification\n  L3 - Scoring: 5-input scorer (HTF structure + VP + OI + Funding + History)\n  L4 - Signal Gate: Entry conditions, CVD divergence, volume confirmation")
    # 4. CONFIG
    p.add_page(); p.st("4. Backtest Configuration")
    p.tbl(["Parameter","Default","Description"],[["Initial Balance","$2,000","Starting capital"],["Risk Per Trade","2.0%","Capital risked"],["SL Multiplier","1.5x ATR","Stop loss distance"],["Min RR","1.5","Minimum risk:reward"],["Daily Loss Limit","5.0%","Max daily drawdown"],["Swing Length","5","Pivot detection lookback"],["ATR Length","14","ATR period"],["Max Bottom Diff","0.27%","Max price difference between bottoms"],["Min Candles Between","2","Min gap between bottoms"],["Max Candles Between","25","Max gap between bottoms"],["Min Height x ATR","0.5x","Min pattern height in ATR units"],["Trend Filter","200-MA","Price must be above MA200"],["Volume Confirm","0.80","B2 vol <= 80% of B1"],["Breakout Volume","1.5x avg","Min breakout volume"],["TP1 Target","1.5R","First take profit"],["Partial Exit","60%","Position closed at TP1"],["Trailing Stop","0.5x ATR","Trail distance after TP1"]],[55,35,100])
    # 5. SIMULATED RESULTS
    p.add_page(); p.st("5. Simulated Pattern Results")
    p.bt("The system includes 10 pre-defined scenarios testing different pattern characteristics:")
    p.tbl(["Scenario","Bottom Diff","Gap","Height","Expected Move","Outcome"],[["P1 - Tight","0.02%","5 bars","$480","$1,500","Success"],["P2 - Tight","0.03%","8 bars","$520","$1,600","Success"],["P3 - Tight","0.03%","3 bars","$510","$1,574","Success"],["P4 - Tight","0.04%","7 bars","$530","$1,700","Success"],["P5 - Avg","0.05%","15 bars","$500","$1,550","Success"],["P
