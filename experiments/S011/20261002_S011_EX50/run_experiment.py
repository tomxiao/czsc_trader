"""Publish the fixed diagnostic report after managed aggregation, then seal once."""

from pathlib import Path
import json
import shutil
import traceback
from research_experiment import (
    load_experiment,
    load_experiment_input,
    experiment_source_sha256,
    ExperimentResources,
    ExperimentWorkspace,
)
from czsc_trader.research_tools import (
    preflight_experiment,
    create_formal_experiment_context,
    execute_experiment,
)
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    assert not (ROOT / "artifacts").exists()
    inputs = json.loads((ROOT / "inputs.json").read_text())
    names = (
        "experiment.py",
        "run_experiment.py",
        "run_batch.py",
        "inputs.json",
        "batch_specs.json",
        "perturbation_protocol.json",
        "01_goal.md",
        "02_design.md",
    )
    write(
        ROOT / "experiment_binding.json",
        dict(
            schema_version=3,
            module="experiment",
            qualname="Experiment",
            source_files=list(names),
            source_sha256=experiment_source_sha256(ROOT, names),
            dependencies=inputs["dependencies"],
        ),
    )
    loaded = load_experiment(ROOT)
    predecessors = tuple(
        load_experiment_input(ROOT.parent / ex / "artifacts", expected_receipt_sha256=digest)
        for ex, digest in inputs["predecessors"].items()
    )
    resources = ExperimentResources(1, 20261002, 1)
    report = preflight_experiment(loaded, resources=resources, predecessors=predecessors)
    write(ROOT / "preflight.json", report.to_dict())
    report.require_pass()
    workspace = ExperimentWorkspace(REPO / ".tmp/s011-c0621-selfcheck/workspaces" / ROOT.name, REPO)
    context = create_formal_experiment_context(
        loaded.definition,
        repository_root=REPO,
        resources=resources,
        workspace=workspace,
        predecessors=predecessors,
    )
    failure = None
    try:
        result = execute_experiment(loaded, context)
    except Exception:
        failure = traceback.format_exc()
        workspace.path("technical_failure.txt").write_text(failure, encoding="utf-8", newline="\n")
    shutil.copytree(workspace.root, ROOT / "artifacts")
    if failure:
        status = "TECHNICAL_FAILURE"
        execution = conclusion = failure
    else:
        status = "COMPLETE"
        s = json.loads((workspace.path("selfcheck_summary.json")).read_text())
        panel = json.loads(workspace.path("assessment_panel.json").read_text())
        write(ROOT / "selfcheck_summary.json", s)
        write(ROOT / "assessment_panel.json", panel)
        write(
            ROOT / "derivation_map.json",
            json.loads(workspace.path("derivation_map.json").read_text()),
        )
        execution = f"受管汇总完成，回执 `{result.receipt.sha256}`。9个前驱实验、17次受管评价、18份完整账户；16个Optuna固定trial全部完成，8个独立spawn进程。中心跨进程复算的账户、成交、闭合交易及基准权益与EX40完全一致。"
        a, b = s["center"], s["stress"]
        conclusion = "固定候选 **S011-C0621**。窗口2025-02-06至2026-09-28，共403交易日；100万元，100股整手，显式限价BuyHold。\n\n"
        conclusion += "## 成本压力\n\n| 指标 | 每侧10bp | 每侧20bp |\n| --- | ---: | ---: |\n"
        for label, key, fmt in [
            ("收益率", "return", ".2%"),
            ("最大回撤", "max_drawdown", ".2%"),
            ("闭合交易数", "closed_trades", "d"),
            ("卡玛比率", "calmar", ".4f"),
            ("盈亏比", "win_loss_ratio", ".4f"),
            ("交易胜率", "win_rate", ".2%"),
        ]:
            conclusion += f"| {label} | {format(a['metrics'][key], fmt)} | {format(b['metrics'][key], fmt)} |\n"
        conclusion += f"\n净年化收益：{a['cagr']:.2%} → {b['cagr']:.2%}，降低 **{s['cost_annual_loss'] * 100:.2f} 个百分点**。压力基准净年化 {b['benchmark_cagr']:.2%}，其1.5倍为 {b['benchmark_cagr'] * 1.5:.2%}；策略未达到该收益目标。压力为诊断，不新增经济硬门。\n\n"
        conclusion += "## 联合参数邻域\n\n"
        conclusion += f"16个固定联合点仅 **{s['neighbor_pass_count']}/16** 满足全部原目标。净年化范围 {s['neighbor_annual_min']:.2%}—{s['neighbor_annual_max']:.2%}，中位数 {s['neighbor_annual_median']:.2%}，Q10为 {s['neighbor_annual_q10']:.2%}；相对中心年化退化 **{s['annual_degradation'] * 100:.2f}个百分点**。回撤幅度Q90为 {s['neighbor_drawdown_q90']:.2%}，较中心恶化 **{s['drawdown_degradation'] * 100:.2f}个百分点**。\n\n"
        conclusion += "| 后继候选 | 净年化 | 最大回撤 | 闭合交易 | 全部原目标 |\n| --- | ---: | ---: | ---: | --- |\n"
        for x in s["neighbors"]:
            conclusion += f"| {x['candidate_id']} | {x['cagr']:.2%} | {x['metrics']['max_drawdown']:.2%} | {x['metrics']['closed_trades']} | {'满足' if x['all_targets_met'] else '未满足'} |\n"
        conclusion += "\n原C1145—C1160登记保持原样；C1577—C1592保留相同内容，补齐与EX40当前父评价绑定的派生记录，见[映射](derivation_map.json)。不计作新增搜索发现，也不计作独立样本。\n\n"
        conclusion += "## 判断与边界\n\n中心在原标准成本下达标，但周围大部分固定点未达收益要求，费用翻倍后也未达原收益倍数要求。当前证据支持“中心参数和成本敏感”，不足以认定稳健。建议先解释收益对入场及联合参数变化的依赖，再由用户决定是否修改研究路线；不直接推进冻结。\n\n"
        conclusion += "SE诊断见[完整面板](assessment_panel.json)。本轮未更新完整搜索族PBO/DSR，也未重发完整阶段四交付。历史选择偏差、已见开发池和复权数据历史发布时间未核实的限制继续存在。无阶段五、冻结或部署批准。\n\n"
        conclusion += (
            "机器账本及评价证据位于各前驱实验artifacts，按仓库规则仅保留本地；Git不包含这些制品。\n"
        )
    (ROOT / "03_execution.md").write_text(
        "# EX50 执行\n\n" + execution + "\n", encoding="utf-8", newline="\n"
    )
    (ROOT / "04_conclusion.md").write_text(
        "# C0621 邻域与成本压力自检\n\n" + conclusion + "\n", encoding="utf-8", newline="\n"
    )
    build_experiment_manifest(
        ROOT,
        dict(
            experiment_id=ROOT.name,
            strategy_id="S011",
            symbol="159326.SZ",
            status=status,
            development_cutoff="2026-09-28",
        ),
    )
    validate_experiment_archive(ROOT)
    print(json.dumps(dict(status=status, experiment=ROOT.name)), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
