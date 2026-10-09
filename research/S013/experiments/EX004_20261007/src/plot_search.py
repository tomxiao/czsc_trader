"""Research figure for the literal return and closed-trade targets."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from common import RUNS


def main():
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    rows = json.loads((RUNS / 'search_results.json').read_text(encoding='utf-8'))['rows']
    valid = [r for r in rows if r['status'] == 'SUCCEEDED']
    fig, ax = plt.subplots(figsize=(10, 6), dpi=160)
    for passed, color, marker, label in ((True, '#286faa', 'o', '逐年回撤通过'),
                                       (False, '#b76a5c', 'x', '逐年回撤未通过')):
        subset = [r for r in valid if r['gates']['annual_drawdown'] == passed]
        ax.scatter([r['closed_trades'] for r in subset], [r['net_cagr'] * 100 for r in subset],
                   c=color, marker=marker, s=23, alpha=.65, label=label)
    qualified = [r for r in valid if r['qualified']]
    ax.scatter([r['closed_trades'] for r in qualified], [r['net_cagr'] * 100 for r in qualified],
               c='#1d7848', marker='o', s=42, label='三项目标同时通过', zorder=4)
    offsets = {'C0001': (5, 5), 'C0351': (5, 5), 'C0371': (8, 0),
               'C0375': (5, 5), 'C0385': (5, 5)}
    for row in valid:
        if row['candidate_id'] in offsets:
            ax.annotate(row['candidate_id'], (row['closed_trades'], row['net_cagr'] * 100),
                        xytext=offsets[row['candidate_id']], textcoords='offset points', fontsize=8)
    threshold = valid[0]['return_threshold'] * 100
    ax.axvline(110, color='#444444', linestyle='--', linewidth=1)
    ax.axhline(threshold, color='#444444', linestyle='--', linewidth=1)
    ax.axhline(valid[0]['buyhold_cagr'] * 100, color='#777777', linestyle=':', linewidth=1)
    ax.set_title(f'S013后复权研究账户：{len(valid)}个独立配置', fontproperties=font)
    ax.set_xlabel('开发池闭合交易数量（达标线110笔）', fontproperties=font)
    ax.set_ylabel(f'净年化收益（达标线{threshold:.3f}%）', fontproperties=font)
    ax.legend(prop=font, loc='lower right')
    ax.grid(alpha=.18)
    ax.set_ylim(top=max(threshold + 1, max(r['net_cagr'] * 100 for r in valid) + 1))
    fig.tight_layout()
    fig.savefig(RUNS / 'performance_frequency.png')
    plt.close(fig)


if __name__ == '__main__':
    main()
