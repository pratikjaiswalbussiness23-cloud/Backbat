import sys, numpy as np
sys.path.insert(0, '.')
from liq_component_backtest import fetch_klines, bt_confluence

def cs(trades, label):
    if not trades:
        print('  %s: No trades' % label)
        return {}
    wins = [t for t in trades if t.get('pnl',0) > 0]
    losses = [t for t in trades if t.get('pnl',0) <= 0]
    tpnl = sum(t.get('pnl',0) for t in trades)
    pf = sum(t['pnl'] for t in wins) / max(sum(abs(t['pnl']) for t in losses), 0.01)
    exp = np.mean([t.get('pnl',0) for t in trades])
    std = np.std([t.get('pnl',0) for t in trades])
    sharpe = (exp / max(std, 0.01)) * np.sqrt(252)
    eq = [0]
    for t in trades:
        eq.append(eq[-1] + t.get('pnl',0))
    pk = eq[0]; mdd = 0
    for e in eq:
        pk = max(pk, e)
        mdd = max(mdd, pk - e)
    print('  %s' % label)
    print('    Trades: %d (W:%d L:%d)' % (len(trades), len(wins), len(losses)))
    print('    Win Rate: %.1f%%' % (len(wins)/len(trades)*100))
    print('    Profit Factor: %.2f' % pf)
    print('    Expectancy: +%.4f%%' % (exp*100))
    print('    Total PnL: +%.2f%%' % (tpnl*100))
    print('    Max DD: %.2f%%' % (mdd*100))
    print('    Sharpe: %.2f' % sharpe)
    return {'n':len(trades),'wr':len(wins)/len(trades)*100,'pf':pf,'exp':exp*100}

print('='*80)
print('  EXTENDED BACKTEST 200+ TRADES')
print('  BTC/ETH/SOL 15m 4000 candles each')
print('  FVG + Swing + Delta only')
print('='*80)
print()

si = [('BTCUSDT','15m',4000),('ETHUSDT','15m',4000),('SOLUSDT','15m',4000)]
all_c = {}
for s,iv,lm in si:
    try:
        c = fetch_klines(s, iv, lm)
        all_c[s] = c
        print('  %s: %d candles (~%d days)' % (s, len(c), len(c)//96))
    except Exception as e:
        print('  ERR %s: %s' % (s, e))

print()
print('--- STANDARD MODE ---')
st = []
for s, tc in all_c.items():
    tr, _ = bt_confluence(tc, hold=30, thresh=0.35, adx_min=20, trend_filter=True, exclude_comps={'OB','Sweep','VP'})
    st.extend(tr)
    print('  %s: %d trades' % (s, len(tr)))
print()
if st:
    cs(st, 'STANDARD')
    regs = {}
    for t in st:
        r = t.get('regime','?')
        regs.setdefault(r,[]).append(t)
    print('  REGIMES:')
    for r, rt in sorted(regs.items()):
        rw = [t for t in rt if t.get('pnl',0)>0]
        rl = [t for t in rt if t.get('pnl',0)<=0]
        rp = sum(t.get('pnl',0) for t in rt)
        rpf = sum(t['pnl'] for t in rw)/max(sum(abs(t['pnl']) for t in rl),0.01)
        print('    %-12s %3d  WR:%5.1f%%  PF:%.2f  PnL:%+.2f%%' % (r,len(rt),len(rw)/max(len(rt),1)*100,rpf,rp*100))

print()
print('--- QUALITY MODE (2+ comps 0.50 thresh) ---')
qt = []
for s, tc in all_c.items():
    tr, _ = bt_confluence(tc, hold=30, thresh=0.50, adx_min=20, trend_filter=True, min_comps=2, exclude_comps={'OB','Sweep','VP'})
    qt.extend(tr)
    print('  %s: %d trades' % (s, len(tr)))
print()
if qt:
    cs(qt, 'QUALITY')
    qregs = {}
    for t in qt:
        r = t.get('regime','?')
        qregs.setdefault(r,[]).append(t)
    print('  REGIMES:')
    for r, rt in sorted(qregs.items()):
        rw = [t for t in rt if t.get('pnl',0)>0]
        rl = [t for t in rt if t.get('pnl',0)<=0]
        rp = sum(t.get('pnl',0) for t in rt)
        rpf = sum(t['pnl'] for t in rw)/max(sum(abs(t['pnl']) for t in rl),0.01)
        print('    %-12s %3d  WR:%5.1f%%  PF:%.2f  PnL:%+.2f%%' % (r,len(rt),len(rw)/max(len(rt),1)*100,rpf,rp*100))

print()
print('--- WALK-FORWARD 70/30 ---')
for s, tc in all_c.items():
    sp = int(len(tc)*0.7)
    trn, tst = tc[:sp], tc[sp:]
    for lb, d in [('TRAIN',trn),('TEST',tst)]:
        x, _ = bt_confluence(d, hold=30, thresh=0.50, adx_min=20, trend_filter=True, min_comps=2, exclude_comps={'OB','Sweep','VP'})
        if x:
            w=[t for t in x if t.get('pnl',0)>0]
            l=[t for t in x if t.get('pnl',0)<=0]
            pfp=sum(t['pnl'] for t in w)/max(sum(abs(t['pnl']) for t in l),0.01)
            ex=np.mean([t.get('pnl',0) for t in x])
            print('  %s %s: %d WR:%5.1f%% PF:%.2f Exp:%+.4f%%' % (lb,s,len(x),len(w)/max(len(x),1)*100,pfp,ex*100))
        else:
            print('  %s %s: 0 trades' % (lb,s))

print()
print('--- EDGE CONFIDENCE ---')
n = len(qt) if qt else 0
if n >= 200:
    print('  OK %d trades STATISTICALLY MEANINGFUL' % n)
elif n >= 100:
    print('  WARN %d trades PROMISING but needs more' % n)
else:
    print('  FAIL %d trades INSUFFICIENT' % n)
print('  Source: LIVE BINANCE DATA')
print('  Bias: lookback in swing/FVG no slippage')
