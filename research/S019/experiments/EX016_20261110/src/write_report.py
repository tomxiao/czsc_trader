"""Write stage-three working reports from published-account summaries."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]


def read(path):
    return json.loads(path.read_bytes())


def main(experiment):
    work = ROOT / "research/S019/experiments" / experiment
    config, summary, narrative, execution = [read(work / path) for path in
        ("protocols/config.json", "others/summary.json", "others/interpretation.json", "others/execution.json")]
    lines = [f"# S019 阶段三第{config['round']}轮：{narrative['title']}", "", narrative['conclusion'], "",
        "## 尝试与认识", "", narrative['findings'], "", "## 下一步", "", narrative['next'], "",
        "## 完整账户证据", "", "|配置|身份|NAR|日末MDD|Calmar|60日闭合中位数|至少3笔覆盖率|全部中心硬门|",
        "|---|---|---:|---:|---:|---:|---:|---|"]
    for name, row in summary.items():
        m = row['candidate']
        lines.append(f"|{name}|{row['id']}|{m['nar']:.4%}|{m['drawdown']:.4%}|{m['calmar']:.4f}|"
            f"{m['frequency_median']:g}|{m['frequency_coverage']:.4%}|{m['eligible']}|")
    lines += ["", "|年份|" + "|".join(summary) + "|", "|---|" + "---:|" * len(summary)]
    for year in range(2022, 2027):
        label = str(year) + ("截至10月30日" if year == 2026 else "")
        lines.append("|" + label + "|" + "|".join(f"{r['candidate']['year_returns'][str(year)]:.2%}" for r in summary.values()) + "|")
    bh = next(iter(summary.values()))['buy_hold']
    stats = execution['equity_statistics']
    lines += ["", f"同条件买持NAR{bh['nar']:.4%}，MDD{bh['drawdown']:.4%}。"
        f"公共统计新增{stats['candidate_runs']}个策略账户、{stats['benchmark_runs']}个共享买持账户。"
        f"阶段三额度已用{config['round']}/10轮，四进程、每进程一个原生线程；失败情况见执行统计。", "",
        "使用已批准的2022-01-03至2026-10-30连续账户，2021预热；全部窗口按已见历史管理。"
        "标准每侧0.1%费用，HFQ整数模拟单位，限价买入与市价卖出。全部账户认证正式证据哈希与源码，"
        "检查观察—决策—执行顺序、目标比例、非负现金、只做多及整数成交。"
        "年度及46个重叠滚动252日窗口沿用实际连续账户。数据可得性、停牌及粒度限制承接EX003。", "",
        "[事前方案](protocols/plan.md) · [精确配置](protocols/config.json) · "
        "[结果与硬门](others/summary.json) · [滚动窗口和分支](others/diagnostics.json) · [执行统计](others/execution.json)", "",
        "本轮为已见历史上的阶段三优化，保留全部尝试及选择历史。正式阶段四五项自检、80%参数扰动联合通过率和独立前瞻尚待相应授权与执行。", ""]
    (work / "report.md").write_bytes("\n".join(lines).encode())
    print("REPORT_WRITTEN", experiment, flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
