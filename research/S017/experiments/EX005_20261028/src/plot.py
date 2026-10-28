"""A descriptive figure of retained full accounts; no strategy recalculation."""
import json
import os
from pathlib import Path
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    os.environ['MPLCONFIGDIR'] = str(ROOT/'.tmp/s017-trend/matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import pandas as pd
    old = read(ROOT/'research/S017/experiments/EX002_20261028/others/accounts.json')
    new = read(WORK/'others/accounts.json')
    prior = read(ROOT/'research/S017/experiments/EX004_20261028/others/accounts.json')
    accounts = {**old, **prior, **new}
    selected = [('C0000','Buy & hold','#222222'),('C0025','Initial 3 ATR / trail 3 ATR','#d97706'),
                ('C0027','Initial 1 ATR','#8b5cf6'),('C0028','Cost-floor protection','#0284c7'),
                ('C0029','Initial 1 ATR + cost floor','#059669')]
    fig, axes = plt.subplots(2,1,figsize=(12,8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for key,label,color in selected:
        ref = EvidenceRef.from_dict(accounts[key]['evidence'])
        run = read(ref.resolve(ROOT))['runs']['candidate']
        daily = pd.DataFrame(run['account_daily'])
        points = pd.DataFrame(run['account_points'])
        assert daily.session.between('2019-01-02','2025-12-31').all()
        peak = points.equity.cummax().clip(lower=100000.)
        points['drawdown'] = 100*(points.equity/peak-1)
        worst = points.groupby('session').drawdown.min()
        style = '--' if key=='C0000' else '-'
        axes[0].plot(pd.to_datetime(daily.session),daily.equity/100000.,style,color=color,lw=1.3,label=key+' '+label)
        axes[1].plot(pd.to_datetime(worst.index),worst.values,style,color=color,lw=1.1)
    axes[0].set_yscale('log')
    axes[0].set_ylabel('Equity / initial cash (log scale)')
    axes[0].set_title('S017 LITE: initial risk and cost-floor protection',loc='left',fontweight='bold')
    axes[0].legend(loc='upper left',fontsize=8,ncol=2)
    axes[1].set_ylabel('BAR_CLOSE drawdown (%)\nWorst observation per session')
    axes[1].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    for ax in axes:
        ax.grid(alpha=.2)
        ax.axvspan(pd.Timestamp('2025-01-01'),pd.Timestamp('2025-12-31'),color='grey',alpha=.08)
        ax.spines[['top','right']].set_visible(False)
    axes[1].set_xlim(pd.Timestamp('2019-01-01'),pd.Timestamp('2025-12-31'))
    fig.text(.08,.015,'Development sample only | 0.1% one-way fees | fixed 1% buy limit premium | No 2026 data',fontsize=9,color='#555555')
    fig.tight_layout(rect=(0,.035,1,1))
    path=WORK/'others/equity_drawdown.png'
    fig.savefig(path,dpi=160)
    plt.close(fig)
    print(path)
    # C0029 is the pre-specified combined initial-risk / cost-floor expression, not
    # selected as a winner. The illustration covers the already-seen 2024-25.
    run = read(EvidenceRef.from_dict(new['C0029']['evidence']).resolve(ROOT))['runs']['candidate']
    point_by_time = {point['time']:point for point in run['account_points']}
    points = pd.DataFrame(run['account_points'])
    shown = points.loc[points.session.between('2024-01-01','2025-12-31')]
    fig, ax = plt.subplots(figsize=(12,5))
    ax.plot(pd.to_datetime(shown.time,utc=True),shown.close,color='#444444',lw=.8,label='Observed 30-minute close')
    cycles = {}
    for decision in run['decisions']:
        explanation = decision['explanation']
        if explanation is None:
            continue
        basis = {item['key']:item['text'] for item in explanation['basis']}
        if basis['held'] != 'True' or 'stop' not in basis:
            continue
        point = point_by_time[decision['observed_through']]
        if not '2024-01-01' <= point['session'] <= '2025-12-31':
            continue
        if point['quantity'] <= 0 or point['cycle_id'] is None:
            raise ValueError('stop illustration requires actual-cycle observation')
        cycles.setdefault(point['cycle_id'],[]).append((decision['observed_through'],float(basis['stop'])))
    for i,rows in enumerate(cycles.values()):
        ax.plot(pd.to_datetime([r[0] for r in rows],utc=True),[r[1] for r in rows],color='#dc2626',lw=1.1,
                label='Ratcheting stop at observed close' if i==0 else None)
    for side,marker,color in [('BUY','^','#059669'),('SELL','v','#2563eb')]:
        fills = [row for row in run['fills'] if row['side']==side and '2024-01-01' <= row['interval_end'][:10] <= '2025-12-31']
        ax.scatter(pd.to_datetime([r['interval_end'] for r in fills],utc=True),[r['price'] for r in fills],
                   marker=marker,s=35,color=color,zorder=4,label=side+' actual fill price')
    ax.set_title('C0029: initial 1 ATR + cost floor + ATR trail | 2024-2025 illustration',loc='left',fontweight='bold')
    ax.set_ylabel('USD (log scale)')
    ax.set_yscale('log')
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.grid(alpha=.2)
    ax.legend(loc='upper left',fontsize=8,ncol=2)
    fig.text(.08,.015,'Stops use observed information; fills occur later. Markers show fill-interval END, not exact fill time. Development only.',fontsize=8,color='#555555')
    fig.tight_layout(rect=(0,.04,1,1))
    path=WORK/'others/trailing_path.png'
    fig.savefig(path,dpi=160)
    plt.close(fig)
    print(path)


if __name__=='__main__':
    main()
