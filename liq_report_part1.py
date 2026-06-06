"""Crypto Liquidity Finder - Research Report Generator"""
import os
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from fpdf import FPDF

OUTPUT_PDF = "BTC_Liquidity_Finder_Research_Report.pdf"
CHART_DIR = "liq_charts"
REPORT_DATE = datetime.now().strftime("%Y-%m-%d %H:%M")

def ensure_dir():
    os.makedirs(CHART_DIR, exist_ok=True)

def chart_orderbook_depth():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
    price = np.linspace(72500, 74500, 100)
    bv = 50 + 120*np.exp(-((price-73200)**2)/(150**2)) + 80*np.exp(-((price-72900)**2)/(80**2))
    av = 50 + 100*np.exp(-((price-73800)**2)/(120**2)) + 70*np.exp(-((price-74200)**2)/(90**2))
    ax1.fill_between(price, bv, alpha=0.5, color='#4CAF50', label='Bids')
    ax1.fill_between(price, av, alpha=0.5, color='#f44336', label='Asks')
    ax1.axvline(x=73500, color='#FF9800', ls='--', lw=1, alpha=0.7)
    ax1.set_title('Order Book Depth Profile', fontsize=12, fontweight='bold', color='#ddd')
    ax1.set_facecolor('#1e1e1e')
    ax1.tick_params(colors='#ccc')
    ax1.legend(fontsize=8)
    cb = np.cumsum(bv)
    ca = np.cumsum(av[::-1])[::-1]
    ax2.fill_between(price, cb, alpha=0.5, color='#4CAF50')
    ax2.fill_between(price, ca, alpha=0.5, color='#f44336')
    ax2.set_title('Cumulative Depth (Impact)', fontsize=12, fontweight='bold', color='#ddd')
    ax2.set_facecolor('#1e1e1e')
    ax2.tick_params(colors='#ccc')
    for ax in [ax1, ax2]:
        for s in ax.spines.values(): s.set_color('#444')
        ax.grid(True, alpha=0.1)
    fig.patch.set_facecolor('#1e1e1e')
    fig.tight_layout()
    path = f'{CHART_DIR}/ob_depth.png'
    fig.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(fig)
    return path

def chart_liquidity_zones():
    fig, ax = plt.subplots(figsize=(10, 4.5))
    np.random.seed(42)
    prices = np.zeros(200)
    p = 73500
    for i in range(200):
        p += np.random.normal(0, 30)
        prices[i] = p
    ax.plot(range(200), prices, color='#555', lw=0.8, alpha=0.6)
    zones = [
        (30, 73800, 74100, '#f44336', 'Sell Liq'),
        (70, 73400, 73600, '#4CAF50', 'Buy Liq'),
        (110, 74200, 74500, '#f44336', 'Sell Liq'),
        (155, 73000, 73200, '#4CAF50', 'Buy Liq'),
    ]
    for start, lo, hi, c, lbl in zones:
        ax.axhspan(lo, hi, alpha=0.12, color=c)
        ax.annotate(lbl, xy=(start, (lo+hi)/2), fontsize=7, color=c, ha='center',
            bbox=dict(boxstyle='round', facecolor='#1e1e1e', edgecolor=c, alpha=0.8))
    ax.annotate('Liquidity Grab', xy=(105, 74500), fontsize=8, color='#FF9800', ha='center',
        bbox=dict(boxstyle='round', facecolor='#1e1e1e', edgecolor='#FF9800'))
    ax.set_title('Liquidity Zones & Sweeps (SMC)', fontsize=12, fontweight='bold', color='#ddd')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='#ccc')
    for s in ax.spines.values(): s.set_color('#444')
    fig.tight_layout()
    path = f'{CHART_DIR}/liq_zones.png'
    fig.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(fig)
    return path

def chart_volume_profile():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
    np.random.seed(99)
    pl = np.linspace(72000, 75000, 60)
    v = 200 + 400*np.exp(-((pl-73200)**2)/(200**2)) + 300*np.exp(-((pl-73800)**2)/(150**2))
    ax1.barh(pl, v, height=30, color='#2196F3', alpha=0.7)
    mv = np.mean(v)
    for i, val in enumerate(v):
        if val > mv*1.3: ax1.barh(pl[i], val, height=30, color='#4CAF50', alpha=0.7)
        elif val < mv*0.5: ax1.barh(pl[i], val, height=30, color='#FF9800', alpha=0.7)
    ax1.set_title('Volume Profile (HVN/LVN)', fontsize=12, fontweight='bold', color='#ddd')
    ax1.set_facecolor('#1e1e1e')
    ax1.tick_params(colors='#ccc')
    for s in ax1.spines.values(): s.set_color('#444')
    cvd = np.cumsum(np.random.normal(0, 50, 100))
    ax2.plot(cvd, color='#9C27B0', lw=1.5)
    ax2.axhline(y=0, color='#666', lw=0.5, ls='--')
    ax2.set_title('Cumulative Volume Delta (CVD)', fontsize=12, fontweight='bold', color='#ddd')
    ax2.set_facecolor('#1e1e1e')
    ax2.tick_params(colors='#ccc')
    for s in ax2.spines.values(): s.set_color('#444')
    fig.patch.set_facecolor('#1e1e1e')
    fig.tight_layout()
    path = f'{CHART_DIR}/vp_profile.png'
    fig.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(fig)
    return path

print("Chart functions ready")
