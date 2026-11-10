"""Write the research interpretation and append comparable account evidence."""
from hashlib import sha256
from pathlib import Path
import json
from review_search import report

WORK = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def main():
    review = read(WORK / "others/search_review.json")
    audit = read(WORK / "others/semantic_audit.json")
    assert audit["manifest_sha256"] == sha256((WORK / "others/audit_manifest.json").read_bytes()).hexdigest()
    assert review["eligible_ids_by_nar"] == [] and review["best_new_challenger"]["row"]["id"] == "C0224"
    comparison = read(WORK / "others/parent_comparison.json")
    control = read(WORK / "others/risk_control_comparison.json")
    assert (comparison["matched_entries"], comparison["different_exit_times"]) == (115, 9)
    assert (control["matched_entries"], control["different_exit_times"]) == (117, 0)
    narrative = {
        "conclusion": "已完成批准的第3轮：C0196短跨度五维Optuna联合搜索，48次提议、48个不同配置、48个新策略账户及1个共享买持账户，技术失败0。全部中心硬门通过数为0，原研究目标尚未达成。C0196保持最高Calmar4.974990416954824；最好的新组合C0224为NAR63.0221%、MDD12.7158%、Calmar4.956187029324225，两者均仅中心Calmar未过线。",
        "findings": "固定下跌1日、持有5日，联合调整成交跨度、参与阈值、两项仓位与ATR退出，实际覆盖3—20日跨度。23个短于10日、25个至少10日的配置均未达标；36个通过NAR，48个全部通过MDD及频率，0个通过Calmar。第27次提议得到C0224，随后21次未改善最高Calmar；这一轮扩边没有改善原中心的收益回撤比。\n\nC0224采用3日跨度、参与阈值1.25、低参与乘数0.55、季度弱势仓位0.30及ATR2.4。相对C0196，NAR提高约1.04个百分点、MDD增加约0.26个百分点，Calmar略降。两者115个闭合入场日期对应、9个退出时点不同，改善与反例并存：2026-10-06周期净收益由−11.24%改善为−7.15%，2024-07-24周期则由−1.93%恶化至−8.03%。这些是实际交易路径比较，仓位与后续机会共同影响完整账户。\n\nC0224恰好沿用C0135的0.30弱势仓位及2.4ATR退出。与C0135的117个闭合入场、退出时点全部一致，主要差异来自成交参与调节后的仓位及账户资金路径；NAR由77.14%降至63.02%，MDD由17.38%降至12.72%，Calmar由4.4387提高至4.9562。这个对照继续支持成交参与规则的风险控制用途，同时显示收益代价。C0224最大回撤仍在2026-10-07至10-30，C0196主要回撤在2022-11-30至2023-04-05，风险时段存在差异。\n\nOptuna内置fANOVA及scikit-learn随机森林对本轮48次记录的诊断中，参与阈值解释了较多NAR和约束缺口差异；跨度的整体贡献较小。该归因来自联合、自适应、有限采样，用于选择后续问题，实际门槛始终按完整账户核验。",
        "next": "本轮按48次事前预算收口，保留C0196、C0224及C0135。下一轮建议先复用账本定位C0196与C0224两段主要回撤中的仓位差异，再检验成交参与强度与缩仓规则的配合；继续使用Optuna处理适用的联合参数优化。当前暂停继续扩大单一跨度范围：3日已是事前保留多个观察值中位数的下限，1—2日尚未检验，需有新增交易路径依据再开展。新增十轮已用3轮、剩余7轮，第4轮尚未启动；原目标、样本与费用合同保持，正式参数扰动及阶段四五项自检尚未开展。"
    }
    (WORK / "others/interpretation.json").write_bytes((json.dumps(narrative,ensure_ascii=False,indent=2)+'\n').encode())
    report(WORK.name)
    summary = read(WORK / "others/summary.json")
    diag = read(WORK / "others/span_diagnostics.json")
    rows = [(r["id"],r["candidate"]) for r in diag["controls"]]
    rows.append(("C0224",summary["trial026"]["candidate"]))
    lines = ["", "## 附录：关键对照与覆盖", "",
        "|配置|NAR|日末MDD|Calmar|闭合交易|", "|---|---:|---:|---:|---:|"]
    for name, m in rows:
        lines.append(f"|{name}|{m['nar']:.4%}|{m['drawdown']:.4%}|{m['calmar']:.8f}|{m['closed_cycles']}|")
    lines += ["", "|年份|C0196|C0224|", "|---|---:|---:|"]
    for year in ("2022","2023","2024","2025","2026"):
        label = "2026截至10月30日" if year == "2026" else year
        lines.append(f"|{label}|{summary['trial000']['candidate']['year_returns'][year]:.4%}|{summary['trial026']['candidate']['year_returns'][year]:.4%}|")
    lines += ["", "逐年收益继承连续账户资金；2026为不完整年度。", "",
        "|成交跨度|不同配置|中心达标|最高Calmar|", "|---:|---:|---:|---:|"]
    for row in diag["by_span"]:
        lines.append(f"|{row['span']}|{row['configurations']}|{row['eligible']}|{row['max_calmar']:.6f}|")
    lines += ["", "跨度分组同时改变其他参数，分组样本来自自适应搜索；以上用于描述实际覆盖。",
        "", "中心与原C0196逐日经济路径、15702条目标决策及3005笔实际成交一致。48个账户完成源码、证据身份、观察—决策—执行时序、现金、目标比例与整数成交核验。中心、最短/最长跨度以及C0224共4个代表账户62808条决策独立业务重建通过。",
        "", "本轮实际资源为4个账户进程、每进程1个原生线程；InMemoryStorage，参数和账户引用JSON留存。公共会话准备16.02秒、账户评价821.01秒、会话总计1126.72秒；后续完整诊断、业务复核和发布另计。",
        "", "[C0196路径比较](others/parent_comparison.json) · [C0135路径比较](others/risk_control_comparison.json) · [跨度分组](others/span_diagnostics.json) · [参数归因](others/search_importance.json)",
        "", "本轮在既有48次提议上作解释性诊断，未追加新账户。正式完整参数邻域≥80%通过率、每侧0.2%费用压力及其他五项自检尚待后续授权。研究记录保持已见开发样本属性，搜索及边界选择历史完整保留。", ""]
    path = WORK / "report.md"
    path.write_bytes(path.read_bytes()+"\n".join(lines).encode())
    print("EX038_REPORT_READY",flush=True)


if __name__ == "__main__":
    main()
