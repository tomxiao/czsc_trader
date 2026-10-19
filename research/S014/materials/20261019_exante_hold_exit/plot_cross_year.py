"""Visualize audited annual account returns; no selection or new wealth labels."""
import argparse
from pathlib import Path

import matplotlib
from matplotlib import font_manager
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

HOLDS = ("BASE", "ENTRY_GRACE", "TREND_CYCLE")
EXITS = ("BASE", "SHOCK_PROFIT", "PROFIT_GIVEBACK")
NAMES = {
    ("BASE", "BASE"): "原策略复现",
    ("BASE", "SHOCK_PROFIT"): "加速且浮盈时退出",
    ("BASE", "PROFIT_GIVEBACK"): "利润回吐时退出",
    ("ENTRY_GRACE", "BASE"): "买入当天破位宽限一次",
    ("ENTRY_GRACE", "SHOCK_PROFIT"): "宽限一次＋加速退出",
    ("ENTRY_GRACE", "PROFIT_GIVEBACK"): "宽限一次＋回吐退出",
    ("TREND_CYCLE", "BASE"): "趋势条件满足才保护持仓",
    ("TREND_CYCLE", "SHOCK_PROFIT"): "趋势保护＋加速退出",
    ("TREND_CYCLE", "PROFIT_GIVEBACK"): "趋势保护＋回吐退出",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    frame = pd.read_csv(args.source, float_precision="round_trip")
    keys = ["hold_rule", "exit_rule", "year"]
    if len(frame) != 54 or frame.duplicated(keys).any():
        raise ValueError("Expected unique9 policies by6 complete years")
    years = list(range(2020, 2026))
    if sorted(frame.year.unique()) != years:
        raise ValueError("Only the locked2020-2025 economic domain is plotted")
    if args.destination.exists():
        raise FileExistsError("Preserve completed plot")
    base = frame.loc[(frame.hold_rule == "BASE") & (frame.exit_rule == "BASE")].set_index("year")
    rows = []
    labels = []
    for hold in HOLDS:
        for exit_rule in EXITS:
            arm = frame.loc[(frame.hold_rule == hold) & (frame.exit_rule == exit_rule)].set_index("year")
            if set(arm.index) != set(years):
                raise ValueError("A fixed mechanism is missing annual results")
            rows.append([(arm.loc[year, "return"] - base.loc[year, "return"]) * 100 for year in years])
            labels.append(NAMES[hold, exit_rule])
    data = np.array(rows)
    if not np.isfinite(data).all():
        raise ValueError("Finite audited return differences required")
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font_manager.fontManager.addfont(str(font_path))
    matplotlib.rcParams.update({"font.family": font_manager.FontProperties(fname=font_path).get_name(), "axes.unicode_minus": False})
    figure = Figure(figsize=(13, 7.7))
    figure.subplots_adjust(left=.30, right=.90, bottom=.17, top=.85)
    axis = figure.subplots()
    bound = max(1., float(np.abs(data).max()))
    chart = axis.imshow(data, aspect="auto", cmap="RdBu_r", vmin=-bound, vmax=bound)
    axis.set_xticks(range(6), years)
    axis.set_yticks(range(9), labels)
    axis.set_title("同一规则跨年：相对原策略的年度收益变化", pad=16)
    for row in range(9):
        for column in range(6):
            value = data[row, column]
            axis.text(column, row, f"{value:+.1f}", ha="center", va="center",
                      color="white" if abs(value) > .57 * bound else "black", fontsize=10)
    figure.colorbar(chart, ax=axis, fraction=.04, pad=.03, label="百分点（红色改善，蓝色下降）")
    figure.text(.30, .065, "各臂用自身年初权益计算；颜色表示收益变化，达标仍需逐年核对原收益及回撤要求。", fontsize=9)
    figure.text(.30, .035, "全部历史已经见过；本图不代表独立样本外验证，也不把九条路径当九次独立证据。", fontsize=9)
    figure.savefig(args.destination, dpi=160)
    figure.clear()
    print(args.destination.as_posix())


if __name__ == "__main__":
    main()
