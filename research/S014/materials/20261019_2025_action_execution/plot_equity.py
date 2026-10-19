"""Plot the independently audited2025 paths with one original opening denominator."""
import argparse
from pathlib import Path

import matplotlib
from matplotlib import font_manager
from matplotlib.figure import Figure
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    frame = pd.read_csv(args.source, parse_dates=["date"])
    if frame.empty or frame["date"].duplicated().any():
        raise ValueError("Unique audited dates required")
    if not frame["date"].dt.year.eq(2025).all():
        raise ValueError("This figure is limited to the fixed2025 diagnostic")
    if args.destination.exists():
        raise FileExistsError("Preserve completed figure")
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if not font_path.is_file():
        raise FileNotFoundError("Chinese figure font missing")
    font_manager.fontManager.addfont(str(font_path))
    matplotlib.rcParams.update({"font.family": font_manager.FontProperties(fname=font_path).get_name(), "axes.unicode_minus": False})
    labels = {"ORIGINAL_R": "原策略", "NOOP": "无干预校验", "SKIP_BUY_ONCE": "取消一次买入", "FORCE_SELL_ONCE": "提前一次卖出", "HOLD_ORIGINAL_CYCLE_H10": "5月30日该笔持有至原期限", "JOINT": "两处固定改动组合"}
    fig = Figure(figsize=(11.5, 6.2))
    fig.subplots_adjust(left=.08, right=.985, bottom=.14, top=.87)
    ax = fig.subplots()
    for column in frame.columns:
        if column in ("date", "NOOP"):
            continue
        ax.plot(frame["date"], (frame[column] / 278758.90799999965 - 1) * 100,
                label=labels[column], linewidth=2 if column == "ORIGINAL_R" else 1.5)
    ax.axhline(40.187863952058545, color="#777777", linestyle="--", linewidth=1, label="原2025收益要求 +40.19%")
    ax.axhline(0, color="#aaaaaa", linewidth=.8)
    ax.set(title="2025收益路径：每次改动均继承原策略资金历史", ylabel="相对同一年初权益的收益（%）", xlabel="日期")
    ax.set_xlim(pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31"))
    ax.text(.01, .02, "已见个案的动作诊断；未证明可事前执行的通用规则。年末持仓按原口径估值。", transform=ax.transAxes, fontsize=9)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=.2)
    fig.savefig(args.destination, dpi=170)
    fig.clear()
    print(args.destination.as_posix())


if __name__ == "__main__":
    main()
