"""Plot audited2024 cash-account attribution; no hypothetical trade labels."""

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
    if args.destination.exists():
        raise FileExistsError("Preserve completed figure")
    annual = pd.read_csv(args.source / "policy_year_accounting_bridge.csv")
    quarter = pd.read_csv(args.source / "policy_quarter_accounting_bridge.csv")
    policies = ("BASE/BASE", "ENTRY_GRACE/SHOCK_PROFIT")
    selected = annual[annual.year == 2024].set_index("policy_id")
    if set(selected.index) != set(policies):
        raise ValueError("Two audited2024 frozen comparator paths required")
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font_manager.fontManager.addfont(str(font_path))
    matplotlib.rcParams.update(
        {
            "font.family": font_manager.FontProperties(fname=font_path).get_name(),
            "axes.unicode_minus": False,
        }
    )
    fig = Figure(figsize=(12, 6.8))
    axes = fig.subplots(1, 2)
    fig.subplots_adjust(left=.08, right=.97, top=.84, bottom=.22, wspace=.27)
    labels = ("原策略", "宽限＋浮盈加速退出")
    colors = ("#7f8da5", "#bd642e")
    x = list(range(4))
    for offset, policy, label, color in zip((-.19, .19), policies, labels, colors):
        row = selected.loc[policy]
        values = [
            row.entry_day_mark_pnl / row.opening_equity * 100,
            row.continued_holding_mark_pnl / row.opening_equity * 100,
            row.exit_to_actual_fill_pnl / row.opening_equity * 100,
            -row.actual_fees / row.opening_equity * 100,
        ]
        if abs(sum(values) - row.net_annual_contribution_pp) > 1e-9:
            raise ValueError("Phase bridge does not reconcile")
        axes[0].bar([i + offset for i in x], values, .36, label=label, color=color)
        for i, value in enumerate(values):
            axes[0].text(i + offset, value - .5, f"{value:+.2f}", ha="center", va="top", fontsize=9)
        q = quarter[(quarter.policy_id == policy) & quarter.quarter.str.startswith("2024")]
        if list(q.quarter) != [f"2024Q{i}" for i in range(1, 5)]:
            raise ValueError("Four audited calendar-quarter rows required")
        axes[1].bar([i + offset for i in x], q.net_annual_contribution_pp, .36, color=color)
    axes[0].set_xticks(x, ("买入当天", "后续持有", "卖出价差", "交易费用"))
    axes[1].set_xticks(x, ("第一季度", "第二季度", "第三季度", "第四季度"))
    axes[0].set_title("亏损发生在哪一步")
    axes[1].set_title("亏损发生在哪一段")
    axes[0].set_ylim(-17, 3)
    axes[0].legend(frameon=False, loc="upper left", fontsize=9)
    for axis in axes:
        axis.axhline(0, color="#505050", linewidth=.7)
        axis.set_ylabel("对2024全年收益的贡献（百分点）")
        axis.grid(axis="y", alpha=.18)
        axis.set_axisbelow(True)
    fig.suptitle("2024：买入当日损伤突出，下半年持续流失", fontsize=16)
    fig.text(.08, .10, "各策略用自身2024年初权益作分母；季度贡献可以相加，不是各季度独立收益率。", fontsize=10)
    fig.text(.08, .055, "这是实际账本归因；买入当晚才能看到的损伤，不能当作买入前已知的过滤依据。", fontsize=10)
    fig.savefig(args.destination, dpi=160)
    fig.clear()
    print(args.destination.as_posix())


if __name__ == "__main__":
    main()
