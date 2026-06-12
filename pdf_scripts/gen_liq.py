from fpdf import FPDF
from datetime import datetime

class R(FPDF):
    def header(self):
        self.set_font('Helvetica','B',9)
        self.set_text_color(100,100,100)
        self.cell(0,8,'Liquidity Identifier - Results & Guide',align='L')
        self.cell(0,8,'Generated: '+datetime.now().strftime('%Y-%m-%d'),align='R',new_x='LMARGIN',new_y='NEXT')
        self.set_draw_color(200,200,200)
        self.line(10,self.get_y(),200,self.get_y())
        self.ln(3)
    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica','I',8)
        self.set_text_color(150,150,150)
        self.cell(0,10,'Page '+str(self.page_no())+'/{nb}',align='C')
    def st(self,t,lv=1):
        if lv==1:
            self.set_font('Helvetica','B',16)
            self.set_text_color(20,60,120)
            self.cell(0,12,t,new_x='LMARGIN',new_y='NEXT')
            self.set_draw_color(20,60,120)
            self.line(10,self.get_y(),200,self.get_y())
            self.ln(4)
        elif lv==2:
            self.set_font('Helvetica','B',13)
            self.set_text_color(40,80,140)
            self.cell(0,10,t,new_x='LMARGIN',new_y='NEXT')
            self.ln(2)
        elif lv==3:
            self.set_font('Helvetica','B',11)
            self.set_text_color(60,60,60)
            self.cell(0,8,t,new_x='LMARGIN',new_y='NEXT')
            self.ln(1)
    def bt(self,t):
        self.set_font('Helvetica','',10)
        self.set_text_color(40,40,40)
        self.multi_cell(0,5.5,t)
        self.ln(2)
    def tbl(self,hdrs,rows,cw=None):
        if cw is None:
            cw=[190/len(hdrs)]*len(hdrs)
        self.set_font('Helvetica','B',9)
        self.set_fill_color(30,60,120)
        self.set_text_color(255,255,255)
        for i,hd in enumerate(hdrs):
            self.cell(cw[i],7,hd,border=1,fill=True,align='C')
        self.ln()
        self.set_font('Helvetica','',9)
        self.set_text_color(30,30,30)
        for ri,row in enumerate(rows):
            if ri%2==0:
                self.set_fill_color(240,245,255)
            else:
                self.set_fill_color(255,255,255)
            for i,c in enumerate(row):
                al='L' if i==0 else 'C'
                self.cell(cw[i],6.5,str(c),border=1,fill=True,align=al)
            self.ln()
        self.ln(3)
    def hbox(self,t,clr='blue'):
        cs={'blue':(230,240,255,20,60,120),'green':(230,255,230,20,100,40),'orange':(255,245,230,180,100,20)}
        br,bg,bb,tr,tg,tb=cs.get(clr,cs['blue'])
        self.set_fill_color(br,bg,bb)
        self.set_text_color(tr,tg,tb)
        self.set_font('Helvetica','B',11)
        self.multi_cell(190,7,t,fill=True,align='C')
        self.set_text_color(40,40,40)
        self.ln(3)

def gen():
    p=R()
    p.alias_nb_pages()
    p.set_auto_page_break(True,20)
    # COVER
    p.add_page()
    p.ln(40)
    p.set_font('Helvetica','B',32)
    p.set_text_color(20,60,120)
    p.cell(0,15,'Liquidity Identifier',align='C',new_x='LMARGIN',new_y='NEXT')
    p.set_font('Helvetica','',16)
    p.set_text_color(80,80,80)
    p.cell(0,10,'Backtest Results & Complete Usage Guide',align='C',new_x='LMARGIN',new_y='NEXT')
    p.ln(10)
    p.set_draw_color(20,60,120)
    p.line(60,p.get_y(),150,p.get_y())
    p.ln(10)
    p.set_font('Helvetica','',12)
    p.set_text_color(100,100,100)
    p.cell(0,8,'Walk-Forward Validation | Anti-Overfitting | Quality Confluence',align='C',new_x='LMARGIN',new_y='NEXT')
    p.cell(0,8,'Report Date: '+datetime.now().strftime('%B %d, %Y'),align='C',new_x='LMARGIN',new_y='NEXT')
    p.cell(0,8,'Version 3.0 - Institutional-Grade System',align='C',new_x='LMARGIN',new_y='NEXT')
    p.ln(30)
    p.set_font('Helvetica','I',10)
    p.set_text_color(150,150,150)
    p.cell(0,6,'Not financial advice. Past performance does not guarantee future results.',align='C',new_x='LMARGIN',new_y='NEXT')
    # TOC
    p.add_page()
    p.st('Table of Contents')
    for t in ['1. Executive Summary','2. System Overview','3. Backtest Configuration','4. Walk-Forward Results','5. Quality Mode Comparison','6. Component Analysis','7. Aggregate Verdict','8. Install & Run','9. UI Guide (All 9 Tabs)','10. API Reference','11. Key Parameters','12. Component Reference','13. Risk Disclaimer']:
        p.set_font('Helvetica','',11)
        p.set_text_color(40,40,40)
        p.cell(0,7,t,new_x='LMARGIN',new_y='NEXT')
    # 1. EXEC SUMMARY
    p.add_page()
    p.st('1. Executive Summary')
    p.bt('The Liquidity Identifier is an institutional-grade market structure scanner that detects liquidity zones using 6 components: Order Blocks, Fair Value Gaps, Liquidity Sweeps, Swing Points, Volume Profile, and CVD/Delta patterns.')
    p.hbox('KEY: Quality-Only mode achieves PF 5.01 with 76.7% WR on unseen data (Anti-Overfitting PASS)','green')
    p.bt('Walk-Forward Validation across BTC, ETH, SOL, BNB (2500 candles each, 70/30 split) confirms NOT overfitted. Out-of-sample improved slightly.')
    # 2. SYSTEM OVERVIEW
    p.add_page()
    p.st('2. System Overview')
    p.bt('6 detection components based on Smart Money Concepts:')
    for nm,wt,ds in [('Order Blocks (OB)','20%','Institutional unfilled orders before impulse'),('Fair Value Gaps (FVG)','25%','Price imbalance gaps acting as magnets'),('Liquidity Sweeps','10%','Stop hunt + reversal patterns'),('Swing Points','10%','Fractal S/R with BOS/CHoCH'),('Volume Profile','10%','HVN/LVN zones from volume-at-price'),('CVD / Delta','25%','CVD divergence and delta patterns')]:
        p.st(nm+' (Weight: '+wt+')',3)
        p.bt(ds)
    p.st('Quality Confluence Filter',2)
    p.bt('Requires: min score 0.50, 3+ components, symbol not excluded. Reduces trades 62% but PF goes 1.89 to 5.01.')
    # 3. CONFIG
    p.add_page()
    p.st('3. Backtest Configuration')
    p.tbl(['Parameter','Value','Description'],[['Risk Per Trade','2.0%','Capital risked'],['Stop Loss','1.5x ATR','Dynamic stop'],['Take Profit','3.0x ATR','2:1 R:R'],['Tx Cost','0.2%','Binance fee'],['Slippage','0.05%','Realistic'],['ADX Min','20','Trend filter'],['Volume','0.6x avg','Min volume'],['Cooldown','8 bars','Between trades']],[55,35,100])
    p.st('Walk-Forward Method',2)
    p.bt('1. Split 70/30 train/test. 2. Grid search train only. 3. Apply best to test ONCE. 4. Compare degradation.')
    # 4. RESULTS
    p.add_page()
    p.st('4. Walk-Forward Results')
    for sym,tr,te in [('BTCUSDT',['TRAIN','46','54.3%','1.90','+35.47%','5.5%','+0.771%'],['TEST','19','73.7%','4.68','+34.07%','4.4%','+1.793%']),('ETHUSDT',['TRAIN','77','57.1%','2.06','+76.62%','6.5%','+0.995%'],['TEST','30','56.7%','1.93','+26.63%','6.5%','+0.888%']),('SOLUSDT',['TRAIN','75','54.7%','2.08','+81.00%','19.9%','+1.080%'],['TEST','31','48.4%','1.62','+21.80%','19.9%','+0.703%']),('BNBUSDT',['TRAIN','39','48.7%','1.14','+6.34%','10.1%','+0.163%'],['TEST','16','43.8%','1.02','+0.47%','8.5%','+0.029%'])]:
        p.st(sym,2)
        p.tbl(['Period','Trades','WR%','PF','PnL%','MaxDD%','Expect'],[tr,te],[30,20,22,25,28,25,30])
    p.hbox('BTC BEST: TEST PF 4.68 | BNB WEAKEST: excluded from Quality mode','green')
    # 5. QUALITY
    p.add_page()
    p.st('5. Quality Mode Comparison')
    p.tbl(['Mode','Trades','WR%','PF','PnL%','MaxDD%','Expect'],[['Standard','80','56.2%','1.89','+68.44%','10.5%','+0.856%'],['Quality-Only','30','76.7%','5.01','+61.79%','4.4%','+2.060%']],[38,22,22,25,28,25,30])
    p.hbox('QUALITY: WR +20.5% | PF +3.12 | 62% fewer trades','green')
    # 6. COMPONENTS
    p.add_page()
    p.st('6. Component Analysis')
    p.tbl(['Component','Trades','WR%','PF','PnL%','Verdict'],[['Swing Points','281','52.0%','1.72','+202.97%','Strongest'],['FVG','279','45.9%','1.38','+122.81%','Solid'],['Volume Profile','11','45.5%','1.66','+7.54%','High Quality'],['Delta Patterns','17','47.1%','1.29','+5.79%','Good Confirm'],['Order Blocks','92','33.7%','0.81','-25.09%','Weak Alone'],['Liquidity Sweeps','4','0.0%','0.00','-8.80%','Too Few']],[35,22,22,22,35,35])
    # 7. VERDICT
    p.add_page()
    p.st('7. Aggregate Verdict')
    p.tbl(['Period','Trades','WR%','PF','PnL%','MaxDD%','Expect'],[['IN-SAMPLE','237','54.4%','1.86','+199.44%','19.9%','+0.842%'],['OUT-OF-SAMPLE','96','55.2%','1.89','+82.98%','19.9%','+0.864%']],[38,22,22,25,28,25,30])
    p.hbox('FINAL: 96 trades | PF 1.89 | WR 55.2% | PASS','green')
    # 8. INSTALL
    p.add_page()
    p.st('8. Install & Run')
    p.st('Requirements',2)
    p.bt('Python 3.12+ | flask, flask-cors, numpy, pandas, requests, yfinance, gunicorn, websocket-client')
    p.st('Quick Start',2)
    p.bt('Step 1: pip install flask flask-cors numpy pandas requests yfinance gunicorn websocket-client\nStep 2: python liq_app.py\nStep 3: Open http://localhost:5001\nStep 4: Or double-click liq_index.html')
    p.st('Backtest',2)
    p.bt('python liq_component_backtest.py\nResults saved to liq_component_backtest_results.json')
    # 9. UI GUIDE
    p.add_page()
    p.st('9. UI Guide')
    p.st('Header Bar',2)
    p.bt('Symbol selector, Timeframe (5m/15m/1h/4h), Quality Toggle (ON=3+ components), Scan Now, Auto-Refresh, Live Price')
    p.st('Tab 1: Liquidity9 (Main)',2)
    p.bt('Primary scanner. Quality Confluence Filter with LONG/SHORT/WAIT signal. Quality Score bar. Price chart with zone overlays. Support & Resistance zone columns.')
    p.st('Tab 2: Institutional',2)
    p.bt('Whale trades, Open Interest, Funding Rate, Order Book Anomaly, Volume Pressure, CVD Divergence with charts.')
    p.st('Tab 3: S&R Zones',2)
    p.bt('Price chart with horizontal zone lines. Zone cards ranked A+ to D.')
    p.st('Tab 4: Depth & Flow',2)
    p.bt('Buyer/Seller power meter, bid/ask walls table, CVD chart, Volume Profile (HVN/LVN/POC), order book depth.')
    p.st('Tab 5: Delta Patterns',2)
    p.bt('4 patterns: Absorption, Hidden Buying, Stop Hunt, Squeeze. Live delta table.')
    p.st('Tab 6: All Zones',2)
    p.bt('Full sortable table of all zones with tier, type, source, price, strength, score.')
    p.st('Tab 7: Market Phase',2)
    p.bt('Phase detection (Trending/Consolidating/Volatile/Silent). ADX, ATR, Bollinger, Volume, Candle Body, Price Action.')
    p.st('Tab 8: Events',2)
    p.bt('Economic calendar. Fed, CPI, NFP, crypto events with impact ratings.')
    p.st('Tab 9: Indian Stocks',2)
    p.bt('NSE stock scanner. Search any Indian stock. Zones, Volume Profile, CVD.')
    # 10. API
    p.add_page()
    p.st('10. API Reference')
    p.tbl(['Endpoint','Method','Description'],[['/api/scan','POST','Quick scan'],['/api/full-scan','POST','Deep scan'],['/api/delta-live','POST','Live CVD'],['/api/events','POST','Calendar'],['/api/market-phase','POST','Regime'],['/api/health','GET','Health']],[50,25,115])
    # 11. PARAMS
    p.add_page()
    p.st('11. Key Parameters')
    p.tbl(['Parameter','Default','Description'],[['qualityOnly','true','3+ components'],['interval','15m','Timeframe'],['depthLimit','100','Order book depth'],['QUALITY_ONLY_THRESH','0.50','Min score'],['QUALITY_MIN_COMPONENTS','3','Min sources'],['ADX_MIN','20','Trend filter']],[55,35,100])
    # 12. REF
    p.add_page()
    p.st('12. Component Reference')
    p.bt('Zone Scores (0-1): Strength + Proximity + Freshness + Confluence\nTiers: A+ (>=0.70), A (>=0.55), B (>=0.40), C (>=0.25), D (<0.25)\nSources: Order Block, FVG, Sweep, Wall, HVN, Swing\nRegime: Trending (full), Neutral (full), Choppy (half), Squeeze (skip)')
    # 13. DISCLAIMER
    p.add_page()
    p.st('13. Risk Disclaimer')
    p.bt('Educational purposes only. Not financial advice. Past performance does not guarantee future results. Trading crypto involves substantial risk. Always do your own research.')
    p.output('Liquidity_Identifier_Results_and_Guide.pdf')
    print('OK: Liquidity_Identifier_Results_and_Guide.pdf')

gen()
