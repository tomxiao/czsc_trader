"""Plot authenticated development accounts; no new simulation or data fetch."""
import os
from hashlib import sha256
import json

from run import ROOT, WORK, read
from czsc_trader.research_tools import EvidenceRef

os.environ['MPLCONFIGDIR'] = str(ROOT/'.tmp/matplotlib-s017-background')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd


def main():
    analysis = read(WORK/'others/analysis.json')
    fig, axes = plt.subplots(2,1,figsize=(12,7),sharex=True,layout='constrained',height_ratios=(2,1))
    for key, color in (('C0000','#64748b'),('C0013','#db2777'),('C0029','#f59e0b'),
                       ('C0030','#94a3b8'),('C0031','#0891b2'),('C0032','#7c3aed')):
        reference = EvidenceRef.from_dict(analysis['source_accounts'][key])
        content = reference.resolve(ROOT).read_bytes()
        if sha256(content).hexdigest() != reference.sha256:
            raise ValueError('account evidence hash differs')
        points = json.loads(content)['runs']['candidate']['account_points']
        dates = pd.to_datetime([point['time'] for point in points],utc=True)
        wealth = pd.Series([point['equity']/100000. for point in points])
        peak = wealth.cummax().clip(lower=1.)
        axes[0].plot(dates,wealth,color=color,label=key,linewidth=1.1)
        axes[1].plot(dates,100*(wealth/peak-1),color=color,linewidth=.8)
    axes[0].set_yscale('log')
    axes[0].set_ylabel('Net wealth / initial (log scale)')
    axes[0].legend(ncols=3,loc='upper left')
    axes[0].set_title('S017 LITE | Development only: 2019-2025 | Recovery background comparison')
    axes[1].set_ylabel('Drawdown (%)')
    for ax in axes:
        ax.grid(alpha=.2)
    fig.savefig(WORK/'others/equity_drawdown.png',dpi=150)
    plt.close(fig)


if __name__ == '__main__':
    main()
