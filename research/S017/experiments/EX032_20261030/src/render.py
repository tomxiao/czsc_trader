"""Render the exact continuous accounts; no strategy computation or selection."""
from common import WORK, authenticate, read
from czsc_trader.research_tools.equity_replay import materialize_equity


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    manifest = read(WORK/'others/accounts.json')
    runs = {}
    for key in ('C0061', 'C0062'):
        path = authenticate(manifest[key]['evidence'])
        payload = materialize_equity(path.read_bytes(),
            lambda ref: (path.parent/(ref['sha256']+'.json')).read_bytes()).payload
        runs[key] = payload['runs']['candidate']
        if key == 'C0061':
            runs['buy_hold'] = payload['runs']['buy_hold']
    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, height_ratios=(2, 1))
    labels = {'C0061': 'M008: volume + reclaim', 'C0062': 'M005: volume + narrow + reclaim', 'buy_hold': 'Buy and hold'}
    colors = {'C0061': '#dc6b3e', 'C0062': '#167d8d', 'buy_hold': '#777777'}
    for key, run in runs.items():
        points = run['account_points']
        times = pd.to_datetime([p['time'] for p in points], utc=True)
        equity = np.array([p['equity'] for p in points])
        peak = np.maximum.accumulate(np.r_[100000., equity])[1:]
        axes[0].plot(times, equity/100000., label=labels[key], color=colors[key], linewidth=1.2)
        axes[1].plot(times, 100*(equity/peak-1), color=colors[key], linewidth=1.)
    axes[0].set_yscale('log')
    axes[0].set_ylabel('Equity / initial cash (log scale)')
    axes[0].set_title('S017 EX032 | 2019-2025 development | continuous net accounts')
    axes[0].legend(loc='upper left', frameon=False)
    axes[1].set_ylabel('Bar-close drawdown (%)')
    axes[1].set_xlim(pd.Timestamp('2019-01-02', tz='UTC'), pd.Timestamp('2025-12-31 23:59', tz='UTC'))
    for axis in axes:
        axis.grid(alpha=.2)
    figure.tight_layout()
    figure.savefig(WORK/'others/equity_drawdown.png', dpi=145)
    plt.close(figure)
    print('RENDERED', flush=True)


if __name__ == '__main__':
    main()
