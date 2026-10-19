"""Plot unchanged, same-identity annual account/benchmark wealth paths."""
from hashlib import sha256
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
def main():
    os.environ['MPLCONFIGDIR'] = str(ROOT / '.tmp/mpl-year-drivers')
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.dates as mdates
    from matplotlib.font_manager import FontProperties
    import matplotlib.pyplot as plt
    import pandas as pd

    source = OUT / 'state_driver_daily_panel.csv'
    expected = json.loads((OUT / 'state_driver_analysis.json').read_bytes())['daily_panel_sha256']
    if sha256(source.read_bytes()).hexdigest() != expected:
        raise ValueError('Original panel bytes changed')
    dest = OUT / 'figures/annual_original_paths.png'
    if dest.exists():
        raise ValueError('Refuse overwriting an existing figure')
    dest.parent.mkdir(parents=True, exist_ok=True)
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    frame = pd.read_csv(source, parse_dates=['date'])
    fig, axes = plt.subplots(3, 1, figsize=(12, 10.5), layout='constrained')
    for ax, year in zip(axes, [2022, 2024, 2025], strict=True):
        part = frame.loc[frame.year.eq(year)]
        nav = part.equity / part.annual_open_equity * 100
        bh = part.buyhold_equity / part.buyhold_annual_open_equity * 100
        ax.plot(part.date, nav, color='#1768ac', linewidth=1.8, label='原策略 C0056')
        ax.plot(part.date, bh, color='#6d7278', linewidth=1.4, label='同口径买入持有')
        target = (bh.iloc[-1] / 100 - 1) * 1.5 if bh.iloc[-1] > 100 else 0.
        ax.axhline(100 * (1 + target), color='#c47b12', linestyle='--', linewidth=1,
                   label='期末收益验收线（零线须严格超过）')
        ax.set_title(f'{year}：策略 {nav.iloc[-1]-100:+.2f}% ｜买入持有 {bh.iloc[-1]-100:+.2f}%',
                     fontproperties=font, fontsize=13, loc='left')
        ax.set_ylabel('年初权益 = 100', fontproperties=font)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m月'))
        for label in ax.get_xticklabels():
            label.set_fontproperties(font)
        ax.grid(alpha=.18)
        ax.spines[['top', 'right']].set_visible(False)
        if year == 2022:
            ax.legend(prop=font, loc='lower left', fontsize=9)
    fig.suptitle('原账户路径：三个失败年份的形态不同', fontproperties=font, fontsize=16)
    fig.savefig(dest, dpi=150, facecolor='white')
    plt.close(fig)
    print(json.dumps({'status': 'PLOTTED_ORIGINAL_PATHS', 'sha256': sha256(dest.read_bytes()).hexdigest(),
                      'new_accounts': 0, 'source_panel_sha256': expected}))


if __name__ == '__main__':
    main()
