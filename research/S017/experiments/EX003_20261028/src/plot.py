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
    os.environ['MPLCONFIGDIR'] = str(ROOT/'.tmp/s017-stage2/matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import pandas as pd
    old = read(ROOT/'research/S017/experiments/EX002_20261028/others/accounts.json')
    new = read(WORK/'others/accounts.json')
    accounts = {**old, **new}
    selected = [('C0000','Buy & hold','#222222'),('C0001','No buffer','#d97706'),
                ('C0011','Entry buffer 1 ATR','#8b5cf6'),('C0012','Two-sided 1 ATR','#0284c7'),
                ('C0013','Two-sided 2 ATR','#059669')]
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
    axes[0].set_title('S017 LITE: trend buffers versus fixed execution benchmarks',loc='left',fontweight='bold')
    axes[0].legend(loc='upper left',fontsize=9,ncol=2)
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


if __name__=='__main__':
    main()
