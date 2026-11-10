"""Summarize joint-search outcomes and choose explicit business-audit cases."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
OWNER = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def review(experiment):
    work = OWNER.parent / experiment
    design, summary, execution = [read(work / p) for p in ("protocols/search.json", "others/summary.json", "others/execution.json")]
    trials = read(work / "others/trials.json")["trials"]
    assert len(trials) == 48 and all(t["state"] == "COMPLETE" for t in trials)
    eligible = sorted([(name, row) for name, row in summary.items() if row["candidate"]["eligible"]],
                      key=lambda x: x[1]["candidate"]["nar"], reverse=True)
    economic = [(name, row) for name, row in summary.items() if all(v for k, v in row["candidate"]["gates"].items() if k != "calmar")]
    frontier = eligible[0] if eligible else max(economic or list(summary.items()), key=lambda x: x[1]["candidate"]["calmar"] or -1)
    counts = {k: sum(row["candidate"]["gates"][k] for row in summary.values()) for k in frontier[1]["candidate"]["gates"]}
    bounds = {k: v for k, v in frontier[1]["parameters"].items() if k in design["space"] and v in (design["space"][k]["low"], design["space"][k]["high"])}
    milestones = []
    for end in (16, 32, 48):
        seen = {t["account_name"] for t in trials[:end]}
        qualifying = [summary[name] for name in seen if summary[name]["candidate"]["eligible"]]
        milestones.append({"proposals": end, "unique_configurations": len(seen), "eligible": len(qualifying),
            "best_eligible_nar": max((r["candidate"]["nar"] for r in qualifying), default=None)})
    audit_names = {frontier[0], "trial000", *[name for name, _ in eligible]}
    challengers = [(name, row) for name, row in economic if row["parameters"] != design["center"]]
    best_challenger = max(challengers, key=lambda item: item[1]["candidate"]["calmar"], default=None)
    if best_challenger is not None:
        audit_names.add(best_challenger[0])
    # Include a genuinely changed entry window, if present, to audit its generalization.
    changed = next((name for name, row in summary.items() if row["parameters"]["down_days"] != 1), None)
    if changed:
        audit_names.add(changed)
    # This round expands the volume-history span while fixing the entry window.
    span_extremes = {}
    for label, select in (("minimum", min), ("maximum", max)):
        name = select(summary, key=lambda n: summary[n]["parameters"]["participation_days"])
        audit_names.add(name)
        span_extremes[label] = {"account_name": name,
            "participation_days": summary[name]["parameters"]["participation_days"]}
    manifest = [{"definition": f"research/S019/experiments/{experiment}/others/{name}_definition.json",
                 "account": f"research/S019/experiments/{experiment}/others/{name}_account.json"} for name in sorted(audit_names)]
    result = {"parent": design["parent"], "proposals": len(trials), "unique_configurations": len(summary),
        "duplicates": sum(t.get("duplicate", False) for t in trials), "eligible_ids_by_nar": [row["id"] for _, row in eligible],
        "frontier_name": frontier[0], "frontier": frontier[1], "frontier_boundary_parameters": bounds,
        "audited_span_extremes": span_extremes,
        "best_new_challenger": None if best_challenger is None else
            {"name": best_challenger[0], "row": best_challenger[1]},
        "individual_gate_pass_counts": counts, "milestones": milestones,
        "candidate_accounts": execution["equity_statistics"]["candidate_runs"],
        "benchmark_accounts": execution["equity_statistics"]["benchmark_runs"]}
    save(work / "others/search_review.json", result)
    save(work / "others/audit_manifest.json", manifest)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def report(experiment):
    work = OWNER.parent / experiment
    design, summary, review, narrative = [read(work / p) for p in
        ("protocols/search.json", "others/summary.json", "others/search_review.json", "others/interpretation.json")]
    lines = [f"# {design['parent']}的Optuna联合搜索", "", narrative["conclusion"], "", "## 尝试与认识", "",
        narrative["findings"], "", "## 下一步", "", narrative["next"], "", "## 预算、方法与核验", "",
        f"新授权第{design['round']}/10轮；48次提议，{review['unique_configurations']}个不同配置，"
        f"{review['duplicates']}次精确重复复用；实际新策略账户{review['candidate_accounts']}、买持{review['benchmark_accounts']}。"
        "Optuna 4.9.0多变量TPE，启动16次，4个一批固定顺序反馈，完整账户无剪枝。",
        "", "所有结果来自MANDATE/2批准的2022-01-03至2026-10-30连续已见历史，2021预热；"
        "中心NAR≥55%、Calmar≥5，MDD与频率按原合同。先核验全部中心硬门，达标后按未舍入NAR降序。"
        "源码、证据、信号时序、目标比例、现金及成交核验随账户保存；基线对照核验逐日经济路径、全部目标时点和成交。"
        "独立业务核验另见下列证据，正式80%参数扰动及阶段四五项自检尚未开展。",
        "", "|已完成提议|不同配置|中心达标数|达标最高NAR|", "|---:|---:|---:|---:|"]
    for row in review["milestones"]:
        value = "—" if row["best_eligible_nar"] is None else f"{row['best_eligible_nar']:.4%}"
        lines.append(f"|{row['proposals']}|{row['unique_configurations']}|{row['eligible']}|{value}|")
    lines += ["", "## 全部配置与账户", "", "固定下跌1日、持有5日。参数顺序：弱势仓位／ATR距离／成交跨度／参与阈值／低参与仓位。", "",
        "|试验|身份|参数|NAR|MDD|Calmar|60日中位数|≥3笔覆盖|中心达标|", "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for name, row in summary.items():
        m, p = row["candidate"], row["parameters"]
        parameters = "/".join(f"{p[k]:g}" for k in design["space"])
        calmar = "—" if m["calmar"] is None else f"{m['calmar']:.4f}"
        lines.append(f"|{name}|{row['id']}|{parameters}|{m['nar']:.4%}|{m['drawdown']:.4%}|{calmar}|{m['frequency_median']:g}|{m['frequency_coverage']:.4%}|{m['eligible']}|")
    lines += ["", "[事前方案](protocols/plan.md) · [搜索空间](protocols/search.json) · [全部提议](others/trials.json) · "
        "[完整账户结果](others/summary.json) · [逐批及边界分析](others/search_review.json) · "
        "[基线等价核验](others/center_parity.json) · [独立业务核验](others/semantic_audit.json) · [执行统计](others/execution.json)", "",
        "搜索编排见[本轮源码](src/joint_search.py)，沿用EX036的Optuna适配；账户由公共TDR执行，行情来自批次DFLS资产。"
        "此前试验与本轮选择历史均保留；本轮固定入场与持有，在五维条件空间中搜索，结果仅覆盖实际搜索。"
        "历史发布时间、停牌覆盖和频率粒度限制承接EX003，远端数据资产同步状态尚未核验。", ""]
    if (work / "protocols/technical_note.md").exists():
        lines += ["[接入与恢复修正记录](protocols/technical_note.md)：完整账户复用，金融规则与参数域保持。", ""]
    (work / "report.md").write_bytes("\n".join(lines).encode())
    print("REPORT_READY", experiment, flush=True)


if __name__ == "__main__":
    {"review": review, "report": report}[sys.argv[1]](sys.argv[2])
