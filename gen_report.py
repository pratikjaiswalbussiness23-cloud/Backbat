"""Liquidity Finder Report Generator"""
import os
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from fpdf import FPDF

OPDF = "BTC_Liquidity_Finder_Research_Report.pdf"
CDIR = "liq_charts"
RDATE = datetime.now().strftime("%Y-%m-%d %H:%M")

def ed():
    os.makedirs(CDIR, exist_ok=True)

def chart_volume_profile():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
    fig.patch.set_facecolor('#1a1a2e')
    for ax in (ax1, ax2):
        ax.set_facecolor('#16213e')
    pl = np.linspace(72000, 75000, 300)
    vp = 200*np.exp(-((pl-72800)**2)/(60**2)) + 180*np.exp(-((pl-73400)**2)/(50**2)) + 150*np.exp(-((pl-74000)**2)/(70**2)) + 100*np.exp(-((pl-72500)**2)/(90**2)) + 80*np.random.rand(300)
    step = 3
    levels = pl[::step]
    vols = vp[::step]
    colors_vp = ['#4CAF50' if v > np.median(vols) else '#FF9800' for v in vols]
    ax1.barh(levels, vols, height=(pl[1]-pl[0])*step, color=colors_vp, alpha=0.7, edgecolor='none')
    ax1.axhline(y=73500, color='#64B5F6', ls='--', lw=1.5, alpha=0.8, label='Current Price')
    ax1.axhspan(72700, 73000, alpha=0.15, color='#4CAF50', label='HVN (Support)')
    ax1.axhspan(73800, 74200, alpha=0.15, color='#f44336', label='HVN (Resistance)')
    ax1.set_title('Volume Profile - HVN/LVN', fontsize=11, fontweight='bold', color='#ddd')
    ax1.set_ylabel('Price ($)', color='#aaa')
    ax1.set_xlabel('Volume', color='#aaa')
    ax1.tick_params(colors='#aaa')
    ax1.legend(loc='lower right', fontsize=7, facecolor='#1a1a2e', edgecolor='#333', labelcolor='#ccc')
    ax1.grid(alpha=0.15)
    t = np.arange(200)
    cvd = np.cumsum(np.random.randn(200)*10 + np.sin(t/8)*15) + np.linspace(0, -200, 200)
    pt = 73500 + np.sin(t/12)*400 + np.linspace(0, -800, 200) + np.random.randn(200)*20
    ax2_tw = ax2.twinx()
    ax2.fill_between(t, cvd, 0, where=(cvd>=0), alpha=0.4, color='#4CAF50', label='Buy Pressure')
    ax2.fill_between(t, cvd, 0, where=(cvd<0), alpha=0.4, color='#f44336', label='Sell Pressure')
    ax2.plot(t, cvd, color='#FF9800', lw=1.5, label='CVD')
    ax2.axhline(y=0, color='#fff', ls='-', lw=0.8, alpha=0.3)
    ax2_tw.plot(t, pt, color='#64B5F6', lw=1.2, alpha=0.7, label='Price')
    ax2.set_title('Cumulative Volume Delta (CVD)', fontsize=11, fontweight='bold', color='#ddd')
    ax2.set_xlabel('Time (bars)', color='#aaa')
    ax2.set_ylabel('CVD (BTC)', color='#FF9800')
    ax2_tw.set_ylabel('Price ($)', color='#64B5F6')
    ax2.tick_params(colors='#aaa')
    ax2_tw.tick_params(colors='#aaa')
    from matplotlib.patches import Patch
    bp = Patch(color='#4CAF50', alpha=0.4, label='Buy')
    sp = Patch(color='#f44336', alpha=0.4, label='Sell')
    ax2.legend([bp, sp, ax2.get_lines()[0], ax2_tw.get_lines()[0]], ['Buy', 'Sell', 'CVD', 'Price'], loc='lower left', fontsize=7, facecolor='#1a1a2e', edgecolor='#333', labelcolor='#ccc')
    ax2.grid(alpha=0.15)
    plt.tight_layout()
    p = os.path.join(CDIR, 'volume_profile_cvd.png')
    plt.savefig(p, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    return p

def chart_liq_heatmap():
    fig, ax = plt.subplots(figsize=(8, 5))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    np.random.seed(42)
    pb = np.linspace(72000, 75000, 80)
    tb = np.arange(100)
    ld = np.zeros((len(pb), len(tb)))
    for t in tb:
        base = 73500 - t*8
        ld[:, t] = 0.8*np.exp(-((pb-(base+300))**2)/(100**2)) + 0.6*np.exp(-((pb-(base-200))**2)/(80**2)) + 0.4*np.exp(-((pb-(base+700))**2)/(120**2)) + 0.3*np.exp(-((pb-(base-500))**2)/(60**2)) + np.random.rand(len(pb))*0.1
        if 30 < t < 50:
            ld[:, t] += 0.5*np.exp(-((pb-(base+500))**2)/(40**2))
        if t > 70:
            ld[:, t] += 0.6*np.exp(-((pb-(base+100))**2)/(50**2))
    im = ax.imshow(ld, aspect='auto', cmap='hot', interpolation='bilinear', extent=[tb[0], tb[-1], pb[-1], pb[0]], alpha=0.9)
    plt.colorbar(im, ax=ax, label='Liquidity Density', shrink=0.8)
    ax.set_title('Liquidity Heatmap Over Time', fontsize=12, fontweight='bold', color='#ddd')
    ax.set_xlabel('Time (bars)', color='#aaa')
    ax.set_ylabel('Price ($)', color='#aaa')
    ax.tick_params(colors='#aaa')
    ax.axhline(y=74000, color='#64B5F6', ls='--', lw=1, alpha=0.5, label='Resistance')
    ax.axhline(y=72800, color='#FF9800', ls='--', lw=1, alpha=0.5, label='Support')
    ax.legend(loc='upper right', fontsize=7, facecolor='#1a1a2e', edgecolor='#333', labelcolor='#ccc')
    plt.tight_layout()
    p = os.path.join(CDIR, 'liquidity_heatmap.png')
    plt.savefig(p, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    return p

def chart_orderbook_depth():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
    fig.patch.set_facecolor('#1a1a2e')
    for ax in (ax1, ax2):
        ax.set_facecolor('#16213e')
    price = np.linspace(72500, 74500, 200)
    bv = 30 + 150*np.exp(-((price-73150)**2)/(80**2)) + 100*np.exp(-((price-72800)**2)/(60**2)) + 80*np.exp(-((price-73500)**2)/(50**2))
    av = 30 + 130*np.exp(-((price-73800)**2)/(70**2)) + 110*np.exp(-((price-74200)**2)/(90**2)) + 90*np.exp(-((price-73650)**2)/(40**2))
    np.random.seed(42)
    bv += np.random.rand(200)*12
    av += np.random.rand(200)*12
    ax1.fill_between(price, bv, alpha=0.5, color='#4CAF50', label='Bids')
    ax1.fill_between(price, av, alpha=0.5, color='#f44336', label='Asks')
    ax1.axvline(x=73500, color='#FF9800', ls='--', lw=1.5, alpha=0.8, label='Current Price')
    ax1.set_title('Order Book Depth Profile', fontsize=11, fontweight='bold', color='#ddd')
    ax1.set_xlabel('Price ($)', color='#aaa')
    ax1.set_ylabel('Volume (BTC)', color='#aaa')
    ax1.tick_params(colors='#aaa')
    ax1.legend(loc='upper left', fontsize=7, facecolor='#1a1a2e', edgecolor='#333', labelcolor='#ccc')
    ax1.grid(alpha=0.15)
    cum_bid = np.cumsum(bv[::-1])[::-1]
    cum_ask = np.cumsum(av)
    ax2.plot(price, cum_bid/1e6, color='#4CAF50', lw=2, label='Cum Bids')
    ax2.plot(price, cum_ask/1e6, color='#f44336', lw=2, label='Cum Asks')
    ax2.axvline(x=73500, color='#FF9800', ls='--', lw=1.5, alpha=0.8)
    ax2.set_title('Cumulative Order Book Depth', fontsize=11, fontweight='bold', color='#ddd')
    ax2.set_xlabel('Price ($)', color='#aaa')
    ax2.set_ylabel('Cum Volume (M BTC)', color='#aaa')
    ax2.tick_params(colors='#aaa')
    ax2.legend(loc='upper left', fontsize=7, facecolor='#1a1a2e', edgecolor='#333', labelcolor='#ccc')
    ax2.grid(alpha=0.15)
    plt.tight_layout()
    p = os.path.join(CDIR, 'orderbook_depth.png')
    plt.savefig(p, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    return p

def chart_liquidity_zones():
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    np.random.seed(42)
    n = 150
    x = np.arange(n)
    price = 73500 + 1800*np.sin(x/18) + 500*np.sin(x/5) + np.random.randn(n)*80
    price += np.linspace(0, -1200, n)
    ax.plot(x, price, color='#64B5F6', lw=1.5, alpha=0.8, label='BTC Price')
    ax.fill_between(x, price, price.min()-500, alpha=0.05, color='#64B5F6')
    sh_idx = [i for i in range(5, n-5) if price[i] == max(price[i-5:i+6])]
    sl_idx = [i for i in range(5, n-5) if price[i] == min(price[i-5:i+6])]
    sh_p = [price[i] for i in sh_idx]
    sl_p = [price[i] for i in sl_idx]
    ax.scatter(sh_idx, sh_p, color='#f44336', s=40, marker='v', zorder=5, label='Swing Highs')
    ax.scatter(sl_idx, sl_p, color='#4CAF50', s=40, marker='^', zorder=5, label='Swing Lows')
    for idx, p in zip(sh_idx, sh_p):
        ax.axhspan(p+20, p+150, xmin=max(0,idx-10)/n, xmax=min(n,idx+10)/n, alpha=0.12, color='#f44336')
    for idx, p in zip(sl_idx, sl_p):
        ax.axhspan(p-150, p-20, xmin=max(0,idx-10)/n, xmax=min(n,idx+10)/n, alpha=0.12, color='#4CAF50')
    ax.annotate('Liq Above High (Stop Hunts)', xy=(sh_idx[-1], sh_p[-1]), xytext=(sh_idx[-1]-25, sh_p[-1]+800), arrowprops=dict(arrowstyle='->', color='#f44336', lw=1.5), fontsize=8, color='#f44336', fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', edgecolor='#f44336', alpha=0.8))
    ax.annotate('Liq Below Low (Stop Hunts)', xy=(sl_idx[-3], sl_p[-3]), xytext=(sl_idx[-3]+20, sl_p[-3]-800), arrowprops=dict(arrowstyle='->', color='#4CAF50', lw=1.5), fontsize=8, color='#4CAF50', fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', edgecolor='#4CAF50', alpha=0.8))
    ax.set_title('Liquidity Zones Detection - Swing Points to Stop Hunts', fontsize=12, fontweight='bold', color='#ddd')
    ax.set_xlabel('Candle Index', color='#aaa')
    ax.set_ylabel('Price ($)', color='#aaa')
    ax.tick_params(colors='#aaa')
    ax.legend(loc='upper right', fontsize=7, facecolor='#1a1a2e', edgecolor='#333', labelcolor='#ccc')
    ax.grid(alpha=0.15)
    plt.tight_layout()
    p = os.path.join(CDIR, 'liquidity_zones.png')
    plt.savefig(p, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    return p

# ============================================================
class ReportPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font('Helvetica', 'B', 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 8, 'Crypto Liquidity Finder -- Research Report', align='C', new_x='LMARGIN', new_y='NEXT')
            self.set_draw_color(60, 60, 60)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(3)
    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 7)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}} | {RDATE}', align='C')
    def stitle(self, t):
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(33, 150, 243)
        self.cell(0, 10, t, new_x='LMARGIN', new_y='NEXT')
        self.set_draw_color(33, 150, 243)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)
    def sub(self, t):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(200, 200, 200)
        self.cell(0, 8, t, new_x='LMARGIN', new_y='NEXT')
        self.ln(1)
    def txt(self, t):
        self.set_font('Helvetica', '', 9)
        self.set_text_color(180, 180, 180)
        self.multi_cell(0, 4.5, t, align='L')
        self.ln(2)
    def bul(self, t):
        self.set_font('Helvetica', '', 9)
        self.set_text_color(180, 180, 180)
        self.cell(15, 4.5, '  -')
        self.multi_cell(0, 4.5, t, align='L')
        self.ln(1)
    def img2(self, p, w=170):
        if os.path.exists(p):
            self.image(p, x=(210-w)/2, w=w)
            self.ln(3)

# ============================================================
def build_report():
    ed()
    print('Generating charts...')
    c1 = chart_orderbook_depth()
    c2 = chart_liquidity_zones()
    c3 = chart_volume_profile()
    c4 = chart_liq_heatmap()
    print('Charts done. Building PDF...')
    pdf = ReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    # Cover
    pdf.add_page()
    pdf.ln(35)
    pdf.set_font('Helvetica', 'B', 28)
    pdf.set_text_color(33, 150, 243)
    pdf.cell(0, 15, 'Crypto Liquidity Finder', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)
    pdf.set_font('Helvetica', '', 16)
    pdf.set_text_color(200, 200, 200)
    pdf.cell(0, 10, 'Research Report & Implementation Guide', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(8)
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 7, 'Data Sources, APIs, Algorithms & Architecture for BTC/USDT', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(10)
    pdf.set_draw_color(33, 150, 243)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(10)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 7, f'Date: {RDATE}', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 7, 'BTC/USDT | Binance | Multi-Timeframe', align='C', new_x='LMARGIN', new_y='NEXT')
    # Section 1
    pdf.add_page()
    pdf.stitle('1. What is Liquidity?')
    pdf.txt('Liquidity is the ability to trade without causing significant price impact. In crypto, liquidity concentrates in specific price zones where large orders sit on the order book. Algorithms and smart money push price toward these areas to fill large orders, trigger stop losses, or hunt for liquidity before reversing.')
    pdf.sub('Key Concepts')
    for t in ['Liquidity Pools: Price areas with concentrated limit orders (bid/ask walls).','Stop Hunts: Price spikes beyond swing highs/lows to trigger stop-losses.','Order Blocks: Large institutional orders left unfilled, creating S/R zones.','Fair Value Gap: Imbalance between buy/sell orders causing inefficient price moves.','Volume Profile: Trading activity at different price levels over time.']:
        pdf.bul(t)
    # Section 2
    pdf.add_page()
    pdf.stitle('2. Types of Liquidity Data')
    pdf.txt('Building a liquidity finder requires multiple data types:')
    for t in ['Order Book Data: L2 data showing all bid/ask orders, depth, spread, imbalance.','Trade Data: Raw trade feed with price, volume, timestamp, aggressor side.','Candlestick Data: OHLCV for swing point detection and volume profile.','Liquidation Data: Forced closure of long/short positions (Binance Futures).','Open Interest: Total outstanding futures contracts, market participation.','Funding Rate: Periodic payments between long/short traders.','WebSocket Feed: Real-time streaming for order book deltas and trade flow.']:
        pdf.bul(t)
    # Section 3
    pdf.add_page()
    pdf.stitle('3. Data Sources / APIs')
    pdf.sub('Free APIs (Binance - Primary)')
    pdf.txt('Binance API (REST+WS): Free L2 order book (depth), trades, klines (1000 per req), aggregate trades, WebSocket streams. Futures: forceOrders (liquidations), openInterest.')
    pdf.sub('Other Sources')
    for s in ['CoinGecko/CoinMarketCap: Market-wide liquidity metrics (free).','Kaiko: Professional market data (paid, high quality).','CryptoQuant: On-chain exchange flows and reserves.','Glassnode: On-chain metrics, MVRV, liquidity indicators.','TradingView: Pine Script custom indicators with webhooks.','Dune Analytics: DeFi liquidity pools via SQL queries.']:
        pdf.bul(s)
    pdf.sub('Key Metrics')
    for m in ['Bid-Ask Spread: Narrow = high liquidity, wide = low liquidity.','Order Book Depth: Total volume within X% of mid price.','Order Book Imbalance: (Bid - Ask) / (Bid + Ask).','Trade Flow Imbalance: Aggressive buy vs sell ratio.','Liquidation Cluster Size: Total notional at key price levels.']:
        pdf.bul(m)
    # Section 4
    pdf.add_page()
    pdf.stitle('4. Detection Algorithms')
    pdf.sub('A. Order Book Cluster Detection')
    pdf.txt('Scan order book for abnormally high order concentration using rolling z-score. Walls identified when single orders exceed threshold.')
    pdf.sub('B. Swing Point Liquidity Zones')
    pdf.txt('Detect pivot highs/lows with configurable lookback. Add buffer zone above/below. Higher TF = more significant zones.')
    pdf.sub('C. Volume Profile HVN/LVN')
    pdf.txt('Compute rolling volume profile. HVN = high liquidity (S/R), LVN = low liquidity (fast moves). Track POC and Value Area.')
    pdf.sub('D. Cumulative Volume Delta')
    pdf.txt('CVD = sum(Buy Vol - Sell Vol). Divergence between CVD and price = potential reversal. Acceleration = aggressive order flow.')
    pdf.sub('E. Order Flow Imbalance')
    pdf.txt('Delta = aggressive buys - sells per candle. High imbalance + high volume = institutional activity.')
    pdf.sub('F. Liquidation Clustering')
    pdf.txt('Cluster liquidation events by price. High density = cascading potential. Monitor open interest changes.')
    pdf.sub('G. Smart Money Concepts')
    pdf.txt('Order Blocks: last candle before impulse move. FVG: gap between adjacent candles. Liquidity Sweeps: break of swing point then reversal.')

    # Section 5: Charts
    pdf.add_page()
    pdf.stitle('5. Order Book Analysis')
    pdf.txt('The order book is the most direct source of liquidity information. By analyzing L2 data from Binance, we can identify exactly where liquidity sits.')
    pdf.img2(c1, w=175)
    # Section 6: Volume Profile
    pdf.add_page()
    pdf.stitle('6. Volume Profile & CVD')
    pdf.txt('Volume Profile shows trading activity at each price level. CVD shows net buying/selling pressure over time.')
    pdf.img2(c3, w=175)
    pdf.sub('CVD Signals')
    for t in ['Bullish CVD + Rising Price = Strong Trend','Bearish CVD + Falling Price = Strong Down Trend','Bullish CVD + Falling Price = Bullish Divergence (reversal)','Bearish CVD + Rising Price = Bearish Divergence (reversal)','Flat CVD + Range Price = Indecision/Consolidation','CVD Acceleration = Breakout confirmation']:
        pdf.bul(t)
    # Section 7: Liquidation Levels
    pdf.add_page()
    pdf.stitle('7. Liquidation & SMC')
    pdf.txt('Liquidation levels create cascading events that smart money exploits. Key: long liquidations (price drops), short liquidations (price rises), stop hunts.')
    pdf.sub('SMC Implementation')
    for t in ['Order Block: Last candle before a strong impulse move.','FVG: Three adjacent candles with gap between candle 1 and 3.','Liquidity Sweep: Price breaks swing high/low >0.1% then reverses.','Market Structure Shift: Break of structure line.']:
        pdf.bul(t)
    pdf.img2(c2, w=175)
    # Section 8: Architecture
    pdf.add_page()
    pdf.stitle('8. Architecture Design')
    pdf.sub('System Components')
    for t in ['Data Layer: Binance REST+WS, memory buffer + optional DB.','Order Book Manager: L2 snapshots, depth ratios, wall detection.','Swing Point Analyzer: Pivot detection with configurable lookback.','Volume Profile Engine: Rolling VP, POC, VA, HVN/LVN.','CVD Calculator: Per-candle delta, divergences.','Liquidation Monitor: Poll forceOrders, cluster by price.','SMC Module: OB, FVG, sweep detection.','Liquidity Merger: Unified weighted scoring.','Alert Engine: Threshold-based zone alerts.','Visualization: Charts, heatmap, HTML dashboard, PDF export.']:
        pdf.bul(t)
    pdf.sub('Data Flow')
    pdf.txt('API -> Data Fetcher -> Buffer\n  |-> Order Book Manager -> Depth Metrics\n  |-> Trade Stream -> CVD Calculator\n  |-> Kline Stream -> Swing Points -> Volume Profile\n  |-> Force Orders -> Liquidation Clusters\nAll -> Liquidity Merger -> Unified Zones -> Visualization')
    # Section 9: Implementation
    pdf.add_page()
    pdf.stitle('9. Implementation Plan')
    pdf.sub('Phase 1: Foundation (Week 1-2)')
    for t in ['Binance API client (python-binance/ccxt)','Order book fetcher (REST+WS deltas)','Swing point detector','Volume profile calculator','CVD calculator from trade stream','Data caching layer']:
        pdf.bul(t)
    pdf.sub('Phase 2: Detection (Week 3-4)')
    for t in ['Order book cluster/wall detection','Liquidity zone merger (weighted scoring)','SMC module (OB, FVG, sweeps)','Liquidation monitor (Futures)','Alert system (console + webhook)','Visualization (matplotlib heatmap)']:
        pdf.bul(t)
    pdf.sub('Phase 3: Integration (Week 5-6)')
    for t in ['Integrate with Flask Double Bottom Scanner backend','REST API for active liquidity zones','HTML dashboard with zone markers on price chart','PDF export of liquidity map (fpdf2)','Strategy integration: double bottoms near liquidity zones']:
        pdf.bul(t)
    # Section 10: Risk
    pdf.add_page()
    pdf.stitle('10. Risk Management')
    pdf.txt('Liquidity zones should never be traded blindly. Always combine with:')
    for t in ['Price Action: Wait for rejection at the zone (pin bar, engulfing)','Structure: Zone aligned with HTF S/R is stronger','Divergence: CVD/RSI divergence = higher probability','Volume: Increasing volume on approach = activation','Multi-TF: Zone visible on higher TF = more significant','Sizing: Risk 1-2% per trade, ATR-based stops behind zone']:
        pdf.bul(t)
    pdf.txt('Visualization: (1) Price chart with highlighted liquidity zone bands, (2) Order book depth with cumulative lines, (3) Heatmap overlay of live liquidity density, (4) Dashboard with zone-strength rankings and proximity alerts.')
    # Save
    pdf.output(OPDF)
    sz = os.path.getsize(OPDF)
    pn = pdf.page_no()
    print(f'Complete! PDF: {OPDF}')
    print(f'Size: {sz} bytes, Pages: {pn}')

if __name__ == '__main__':
    build_report()
