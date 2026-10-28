"""Visualize authenticated price decomposition, never a simulated strategy return."""
from hashlib import sha256
import os

from run import WORK, ROOT, read

os.environ['MPLCONFIGDIR'] = str(ROOT / '.tmp/s017-research/matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    data = read(WORK / 'others/session_price_description.json')
    if (data['status'] != 'PASS'
            or data['script_sha256'] != sha256((WORK / 'src/describe_sessions.py').read_bytes()).hexdigest()):
        raise ValueError('price description or source identity changed')
    years = list(data['by_year'])
    intraday = [data['by_year'][year]['intraday']['complete_log_sum'] for year in years]
    overnight = [data['by_year'][year]['overnight']['complete_log_sum'] for year in years]
    full = data['full_period']
    all_day = full['intraday']['complete_log_sum']
    all_night = full['overnight']['complete_log_sum']
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), gridspec_kw={'width_ratios': [3, 1.3]})
    x = np.arange(len(years))
    axes[0].bar(x - .18, intraday, .36, label='Intraday', color='#2878b5')
    axes[0].bar(x + .18, overnight, .36, label='Overnight', color='#d49b22')
    axes[0].plot(x, np.array(intraday) + overnight, 'o', color='#333333', label='Total')
    axes[0].set_xticks(x, years)
    axes[0].set_title('Contributions by arrival year')
    axes[0].set_ylabel('Natural log price change')
    axes[0].legend(frameon=False)
    axes[1].bar(['Intraday', 'Overnight'], [all_day, all_night], color=['#2878b5', '#d49b22'])
    for position, value in enumerate((all_day, all_night)):
        axes[1].text(position, value + .05, f'{value:.3f}', ha='center')
    axes[1].set_ylim(0, max(all_day, all_night) * 1.28)
    axes[1].set_title('Full-period contributions')
    axes[1].text(.5, .92, f'Overnight: {all_night / (all_day + all_night):.1%} of total log change',
                 ha='center', transform=axes[1].transAxes, fontsize=9)
    for ax in axes:
        ax.axhline(0, color='#888888', linewidth=.8)
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
    fig.suptitle('LITE | 2019-2025 | Raw RTH price decomposition', fontsize=13)
    fig.text(.5, .02, 'Price description only: no fees, order execution, causal attribution or strategy performance.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .05, 1, .96))
    fig.savefig(WORK / 'others/price_contributions.png', dpi=160)
    plt.close(fig)
    print('PRICE_DECOMPOSITION_PLOT_SAVED')


if __name__ == '__main__':
    main()
