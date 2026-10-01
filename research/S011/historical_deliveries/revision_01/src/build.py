"""Build historical reading/index artifacts without publishing TDR deliveries."""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import shutil

import pandas as pd

from czsc_trader.application import RepositoryContext, validate_archives
from research_experiment import load_experiment_input

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
SEED = Path(__file__).resolve().parents[1]
S3 = "research/S011/stage3/iteration_02"
S4 = "research/S011/stage4/iteration_04"
EX12 = "experiments/S011/20260929_S011_EX12"
CLOSE = "research/S011/stage4/closeout_01"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def rows(name):
    with (ROOT / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def table(headers, values):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(cell(v) for v in row) + " |" for row in values),
    ])


def pct(value):
    return "缺失" if value is None else f"{value * 100:.4f}%"


def json_value(value):
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if hasattr(value, "tolist"):
        return json_value(value.tolist())
    if isinstance(value, float):
        if math.isnan(value):
            return None
        require(math.isfinite(value), "infinite historical value")
    return value


def collect_sources():
    paths = set()
    for relative in ("research/S011/stage3", "research/S011/stage4"):
        paths.update(p for p in (ROOT / relative).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for p in (ROOT / "experiments/S011").glob("*/experiment_manifest.json"):
        paths.add(p)
        paths.update(x for x in p.parent.iterdir() if x.is_file())
        paths.update(x for x in (p.parent / "artifacts").glob("execution_*.json"))
    for name in ("STAGE2_MECHANISMS.md", "STAGE2_FIRST_BATCH.md", "STAGE2_FIVE_MECHANISMS.md", "PRICE_BASIS_AUDIT.md"):
        paths.add(ROOT / "research/S011" / name)
    for item in read(CLOSE + "/decision.json")["supplemental_backtests"]:
        base = ROOT / item["package"]
        paths.add(base / "README.md")
        paths.add(base / "src/run.py")
        paths.update((base / "receipts").glob("*.json"))
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def audit_archives():
    context = RepositoryContext.discover(ROOT)
    result = []
    for manifest in sorted((ROOT / "experiments/S011").glob("*/experiment_manifest.json")):
        path = manifest.parent
        document = read(manifest)
        record = {
            "experiment_id": path.name,
            "manifest": manifest.relative_to(ROOT).as_posix(),
            "historical_status": document["status"],
            "declared_files": len(document["files"]),
            "archive_validation": validate_archives(context, path).status,
        }
        receipt_path = path / "artifacts/execution_receipt.json"
        if receipt_path.exists():
            receipt = read(receipt_path)
            loaded = load_experiment_input(receipt_path.parent, expected_receipt_sha256=receipt["receipt_sha256"])
            require(loaded.experiment_id == path.name, "receipt experiment mismatch")
            record.update(receipt_validation="PASS", receipt_schema=receipt["schema_version"], receipt_sha256=receipt["receipt_sha256"])
        else:
            require(document["status"] == "TECHNICAL_FAILURE", "successful archive missing receipt")
            record.update(receipt_validation="ABSENT_TECHNICAL_FAILURE", receipt_schema=None, receipt_sha256=None)
        result.append(record)
    require(len(result) == 28, "historical inventory changed; create a successor supplement")
    return {
        "scope": "S011_EX01_TO_EX28",
        "public_archive_validation": "PASS",
        "archive_count": len(result),
        "manifest_file_entries": sum(x["declared_files"] for x in result),
        "successful_receipts": sum(x["receipt_validation"] == "PASS" for x in result),
        "hash_semantics": "Archive text normalization follows validate_archives; REX artifact hashes follow load_experiment_input. No files rewritten.",
        "experiments": result,
    }


def audit_historical_references():
    checks = []
    snapshot = S4 + "/inputs/RSCH_AGENT.md"
    # Explicit historical mapping; never substitutes silently or changes the old verifier.
    for parent in (S4, CLOSE):
        manifest = read(parent + "/manifest.json")
        for name, expected in manifest["files"].items():
            require(digest(ROOT / parent / name) == expected, f"historical package changed: {parent}/{name}")
        for name, expected in manifest["inputs"].items():
            if name == "research/RSCH_AGENT.md":
                require(digest(ROOT / snapshot) == expected, "historical Agent snapshot differs")
                checks.append({"owner": parent, "original_reference": name, "expected_sha256": expected,
                               "status": "EXPLICIT_HISTORICAL_SNAPSHOT_MATCH", "historical_reference": snapshot})
            else:
                require(digest(ROOT / name) == expected, f"historical input changed: {name}")
    conflicts = []
    prior = read(EX12 + "/prior_input_identities.json")["source_sha256"]
    for name, expected in prior.items():
        actual = digest(ROOT / name)
        if actual != expected:
            conflicts.append({"path": name, "expected_sha256": expected, "actual_sha256": actual})
    require(len(conflicts) == 1 and conflicts[0]["path"] == "experiments/S011/20260929_S011_EX01/experiment_manifest.json", "historical cross-reference drift changed")
    return {"stage4_reference_checks": 335, "historical_document_mappings": checks,
            "stage2_prior_source_checks": len(prior), "unresolved_prior_source_conflicts": conflicts,
            "original_verifier_status": "FAIL_AS_RECORDED_IN_FOCUSED_VALIDATION"}


def materialize(verification):
    panel = read(EX12 + "/component_panel.json")
    summary = read(S3 + "/summary.json")
    protocol = read(S4 + "/protocol.json")
    assessment = read(S4 + "/assessment.json")
    decision = read(CLOSE + "/decision.json")
    registry = read(S4 + "/configurations.json")["configurations"]
    qualified = read(S4 + "/qualified_configurations.json")
    all_rows = rows(S3 + "/all_evaluations.csv")
    unique = rows(S3 + "/unique_parameters.csv")
    good = [x for x in unique if x["qualified"] == "True"]
    for row in all_rows:
        frequency = 60 * int(row["closed_trades"]) / int(row["sessions"])
        require(abs(frequency - float(row["frequency"])) < 1e-10, "historical frequency mismatch")
        annual, benchmark = float(row["cagr"]), float(row["buyhold_cagr"])
        gates = (
            annual >= 1.5 * benchmark and (benchmark > 0 or annual > 0 and annual > benchmark),
            abs(float(row["drawdown"])) < abs(float(row["buyhold_drawdown"])),
            4 <= frequency <= 6,
        )
        require(all(gates) == (row["qualified"] == "True"), "historical goal outcome mismatch")
    require((len(all_rows), len(unique), len(good)) == (573, 559, 26), "stage-three scope differs")
    require(len({x["account_key"] for x in all_rows}) == summary["distinct_accounts"] == 521, "behavior count differs")
    mapping = []
    for row in good:
        matches = [c for c in registry if row["reference"] in c["references"]]
        require(bool(matches), "qualified historical parameter lacks config mapping")
        mapping.append({"historical_evaluation": row, "configurations": matches, "new_candidate_key": None, "new_content_sha256": None})
    ranking = json_value(pd.read_parquet(ROOT / S4 / "rankings.parquet").to_dict(orient="records"))
    require(len(ranking) == 36 and len(registry) == 838, "stage-four scope differs")
    require({x["config_id"] for x in ranking} == {x["config_id"] for x in qualified["configurations"]}, "stage-four intake differs")
    selected = next(c for c in registry if c["config_id"] == decision["selected_config_ids"][0])
    require(selected["config_fingerprint"] == decision["selected_config_fingerprint"], "selection identity differs")
    front = sorted((x for x in ranking if x["pareto_layer"] == 1), key=lambda x: x["rank_min"])
    require([x["config_id"] for x in front] == decision["selection_basis"]["original_first_layer_order"], "original ordering differs")
    shared = {
        "record_kind": "S011_HISTORICAL_STAGE_SUPPLEMENT", "schema_version": 1,
        "strategy_id": "S011", "symbol": "159326.SZ", "development_cutoff": "2026-09-28",
        "formal_delivery_status": "NOT_PUBLISHED", "new_experiments": 0, "new_evaluations": 0,
        "evidence_scope": "SEEN_DEVELOPMENT_POOL_ONLY", "source_path_base": "repository_root",
    }
    stage2 = {
        **shared, "stage": 2, "historical_component_panel": panel,
        "research_path": verification["experiments"][:12],
        "source_reports": [EX12 + "/COMPONENT_PANEL.md", "research/S011/STAGE2_FIVE_MECHANISMS.md"],
        "current_limitations": ["REX_SCHEMA_1_REQUIRES_SUCCESSOR_EVIDENCE", "EX12_PRIOR_EX01_MANIFEST_REFERENCE_DIFFERS"],
    }
    stage3 = {
        **shared, "stage": 3, "historical_summary": summary,
        "strategy_hypothesis": "市场短期回落与ETF尾盘卖压提供次日修复机会，严格较早SPX信息有限确认；固定排序分数、仓位、限价入场及退出时间构成完整策略。",
        "components_used": ["S011-COMP-01", "S011-COMP-02", "S011-COMP-04"],
        "diagnostic_only_component": "S011-COMP-03",
        "historical_frontier": read(S3 + "/frontier_configurations.json"),
        "search_and_attribution": [S3 + "/all_evaluations.csv", S3 + "/unique_parameters.csv", S3 + "/paired_changes.json", S3 + "/paired_orders.csv"],
        "qualified_parameter_mapping": "stage3/qualified_configurations.json",
        "later_stage_four_intake": qualified,
        "later_intake_definitions": [x for x in registry if x["config_id"] in {q["config_id"] for q in qualified["configurations"]}],
        "scope_warning": "26 qualified stage-three parameters and 36 later stage-four configuration identities are distinct historical scopes; later intake is not retroactive stage-three output.",
        "source_reports": ["research/S011/stage3/README.md", "research/S011/stage3/iteration_01/README.md", S3 + "/README.md"],
    }
    stage4 = {
        **shared, "stage": 4, "historical_protocol": protocol,
        "historical_assessment": assessment, "historical_ranking_policy": read(S4 + "/ranking_policy.json"),
        "coverage_gaps": read(S4 + "/additional_checks.json"),
        "historical_recommendation": read(S4 + "/recommendations.json"),
        "effective_user_decision": decision, "selected_configuration": selected,
        "search_ledger": read(S4 + "/search_ledger.json"),
        "metric_overlap_audit": read(S4 + "/metric_audit.json"),
        "sensitivity_source": S4 + "/ranking_sensitivity.json",
        "full_panel": "stage4/rankings.json",
        "source_reports": [S4 + "/README.md", CLOSE + "/README.md"],
        "current_limitations": ["HISTORICAL_VERIFIERS_REFERENCE_CHANGED_LIVE_AGENT_DOC", "CURRENT_FREQUENCY_AND_RANKING_CONTRACTS_DIFFER", "NO_CURRENT_CANDIDATE_REGISTRATION_OR_FORMAL_DELIVERY"],
    }
    return {"stage2/delivery.json": stage2, "stage3/delivery.json": stage3,
            "stage3/qualified_configurations.json": mapping, "stage4/delivery.json": stage4,
            "stage4/rankings.json": ranking}


def reports(data):
    s2, s3, s4 = (data[f"stage{x}/delivery.json"] for x in (2, 3, 4))
    panel = s2["historical_component_panel"]
    component_rows = [(c["component_id"], c["name"], c["role"], "/".join(map(str, c["horizons_sessions"]))) for c in panel["components"]]
    common = "本报告整理已封存的开发池材料；机器索引为[delivery.json](delivery.json)。本次未新增实验或回测，正式TDR交付尚未发布。\n"
    stage2 = "# 阶段二：限定职责的组件交付\n\n" + common + "\n" + table(["组件", "信息", "职责", "作用期（交易日）"], component_rows)
    stage2 += """

四组件均供完整策略研究使用。COMP01/02提供短期反向机会与入场信息，COMP03描述风险环境，COMP04提供证据较弱的外部确认。

## 定义、支持和边界

- COMP01：沪深300当日收益，反向；三日排名相关0.124、控制后0.103。最近段幅度预测弱于均值，十日延续不成立。
- COMP02：ETF 13:30—15:00后复权收益，反向；次日排名相关0.207、控制后0.158。配对损失改善区间跨零，不能据此断言净收益或成交。
- COMP03：过去5个完整交易日的平均振幅，正向刻画未来风险；未来振幅排名相关0.613、控制后0.401。后期风险幅度被低估，尚无已验证的避损或仓位公式。
- COMP04：严格早于中国决策日的最近SPX单日收益，正向；次日排名相关0.134、控制后0.167。首段回归系数反向、幅度预测较差，作为限定的一日确认信息。

机器面板逐项保留公式、方向、数据源、可得时间、缺失处理、标签期限、对照结果、限制及禁止外推的用途。T日完成信息用于T20:30决策，最早T+1执行；收益标签不替代订单、现金和成本。

## 研究路径与反证

EX01—EX08的先前普查与数据门保留；五条路线曾无有效组件，后来由EX09/EX10扩大信息普查，再由EX12形成职责审查结论。EX05、EX11技术失败保留。盈利预期、成分权重历史公布时点、真实折溢价和标的自身期权等缺口不因4项组件入选而消失。

阶段二收口支持进入完整策略假设检验；组件之间可用的角色互补不证明组合获利。全部样本已参与研究，供应商逐日历史版本仍未得到独立证明。

## 原件与本次验证

- [EX12组件人工报告](../../../../../experiments/S011/20260929_S011_EX12/COMPONENT_PANEL.md)及[完整机器面板](../../../../../experiments/S011/20260929_S011_EX12/component_panel.json)。
- [前期五路线结论](../../../STAGE2_FIVE_MECHANISMS.md)，作为早期结论保留。
- 全部档案及已有回执的公共核验通过。EX12原专项验证器最终在前序EX01 manifest的旧指纹核对处失败；该引用差异单列，不能把原专项验证器标为PASS。计算检查已执行到该断言，完整脚本仍为FAIL。

迁移需要解决历史指纹引用与schema 1证据的承接，再发布正式ComponentPanel。见[迁移清单](../MIGRATION.md)。
"""
    summary = s3["historical_summary"]
    stage3 = "# 阶段三：完整策略、搜索与交接范围\n\n" + common
    stage3 += "\n## 假设与实现\n\n" + s3["strategy_hypothesis"] + "\n\n"
    stage3 += "使用COMP01、02、04，COMP03仅诊断。中心表达为历史秩：`(0.575×尾盘反向秩 + 0.425×市场反向秩 + 0.05×SPX正向秩)/1.05`，lookback=130、entry=0.325、持有意图上限2日、买入溢价0.003；收益方向exit=0.025，低回撤方向exit=0.175。按既有SRT/TXE处理实际成交和未成交。\n\n"
    stage3 += "原目标：同口径BuyHold的1.5倍年化，回撤严格更小，全样本每60日折算4—6笔。窗口2025-02-06至2026-09-28、403交易日、100万元、100股整手、每侧10bp、LIMIT买/MARKET卖、只做多无杠杆。\n\n"
    stage3 += table(["来源", "年化", "回撤幅度", "闭合交易", "折算频率"], [(x["reference"], pct(x["cagr"]), pct(abs(x["drawdown"])), x["closed_trades"], f'{x["frequency"]:.6f}') for x in summary["frontier"]])
    stage3 += "\n\n## 搜索、改善与停止依据\n\n"
    stage3 += table(["实验", "可比较评价", "达标评价", "新增参数"], [(x["experiment"], x["evaluations"], x["qualified_evaluations"], x["new_parameters"]) for x in summary["rounds"]])
    stage3 += """

共573条评价、559组参数、521种账户行为，26组达标参数对应18种账户，4个非支配参数对应2种账户。384点Optuna联合搜索的后288点没有改善合格前沿；随后EX22跨退出边界、EX24检验入场与限价交互、EX25进一步下扩和插值。EX24增加2种前沿账户，EX25没有增加。

改善来源分开解释：放宽入场增加两个机会，但频率越界；收紧买入限价减少两次原本盈利的成交，伴随成交价、整手与复利变化后满足原目标；提高退出阈值缩短暴露，以较低收益换取较低回撤。原逐日账务归因保留，净现金流分解不直接当作恒定仓位的因果收益。

搜索域、采样器版本与种子、分轮预算、失败、接续、边界和停止依据见[原阶段三报告](../../../stage3/iteration_02/README.md)。机器索引引用全部评价、去重参数、成对变更、订单和源码身份；EX13/17/18/19/21技术失败、EX14错误预热及EX20修正审计保留。

## 完整达标集合与后续范围

[26组达标参数及配置身份映射](qualified_configurations.json)保留历史评价行、原配置定义、源码与指纹；当前CandidateKey及内容哈希尚未生成。

阶段四后来使用36个配置身份，新增范围包含后续自检形成的记录。该完整集合及其定义另列在机器索引中，保留26参数与36配置的时间和计数边界；配置、参数与账户均不等于独立经济假设。

反复搜索、低成本容错、成交次数贴近原频率上界、样本复用及缺少独立前瞻仍是限制。当前已选621的完整开发池年化低于618；阶段三前沿结论不替代阶段四选型。

下一步按原身份映射补登记，生成新受管账户证据并验证复算差异，再发布正式CandidateSet。见[迁移清单](../MIGRATION.md)。
"""
    stage4 = "# 阶段四：完整自检、比较与用户决定\n\n" + common
    stage4 += "\n当前历史有效状态为`CLOSED_WITH_DISCLOSED_LIMITATIONS`。用户选择S011-CFG-000621，来源S011-EX24T007；iteration_04的待决定状态由closeout_01承接，原快照保持原样。\n\n"
    stage4 += "## 全36配置概览\n\n原七项比较、16层及可能名次范围原样呈现；缺失不填零。完整数值与比较关系见[rankings.json](rankings.json)。\n\n"
    stage4 += table(["配置尾号", "层", "同层名次范围", "年化", "回撤", "折算频率", "状态"], [(x["config_id"][-6:], x["pareto_layer"], f'{x["rank_min"]}—{x["rank_max"]}', pct(x["cagr"]), pct(x["drawdown_magnitude"]), f'{x["frequency"]:.4f}', x["comparison_status"]) for x in data["stage4/rankings.json"]])
    stage4 += """

## 五项自检与覆盖

参数敏感性使用EX28固定2天16位置六参数联合设计，四中心有证据，其余32配置缺失。时间稳定性保留60日滚动累计超额Q10；盈利集中性使用盈利闭合交易前10%净利润占比；执行敏感性使用10/20bp完整账户；统计不确定性保留旧Bootstrap及原研究族PBO/DSR。

000193缺同源码20bp证据；15配置涉及9对不可比，保留可能名次区间。旧PBO/DSR不覆盖EX28追加的184个标准账户和184个压力账户。盘口、容量、冲击、延迟与独立前瞻未验证。无需将未选配置的所有缺口补测完才承认原阶段四收尾。

原分层先按经济分辨率对收益/回撤分箱；同层按七项收益优先规则逐项比较。四种精度敏感性不改变第一层顺序，交换指标优先级可换位。这些结果表达偏好依赖，不能宣称统计显著优势。

## 用户选择与代价

原第一层顺序为618→624→621→628。用户更重视621较低回撤、近期表现及较小联合年化退化，接受其完整开发池年化43.11%低于618的49.81%。621回撤6.15%，618为7.25%。621固定联合邻域仅1/16达标，60日滚动超额Q10约−17.37%，7月起窗口仍亏损；这些反证保留。三个补充TDR窗口相互重叠，均为已见开发池。

机器索引完整保留原选择原文、配置指纹、源评价、机会成本、缺口及后续权限。[原收尾报告](../../../stage4/closeout_01/README.md)及[原决定](../../../stage4/closeout_01/decision.json)继续有效，不把621改排第一。

## 复核状态与正式迁移

公共实验档案及回执核验通过。原iteration_04和closeout验证器依赖已变化的当前RSCH_AGENT.md，因此本次直接执行为FAIL；封存的历史快照与原输入哈希匹配，新历史索引显式指向该快照，原脚本与结论均不改写。

正式迁移需要保留全样本频率、基准相对目标、严格比较及历史分层/偏序语义；当前SE合同与历史政策的差异见[迁移清单](../MIGRATION.md)。阶段五检验、冻结和部署没有在本次启动。
"""
    return {"stage2/report.md": stage2, "stage3/report.md": stage3, "stage4/report.md": stage4}


def validate(package):
    manifest = read(package / "manifest.json")
    actual = {p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file() and p.name != "manifest.json" and "__pycache__" not in p.parts}
    require(actual == set(manifest["files"]), "package inventory differs")
    for name, expected in manifest["files"].items():
        require(digest(package / name) == expected, f"package changed: {name}")
    sources = read(package / "sources.json")
    for name, expected in sources.items():
        require(digest(ROOT / name) == expected, f"source changed: {name}")
    verification = audit_archives()
    verification["historical_reference_audit"] = audit_historical_references()
    require(verification == read(package / "verification.json"), "archive verification differs")
    expected = materialize(verification)
    for name, value in expected.items():
        require(read(package / name) == value, f"historical projection differs: {name}")
    for name, value in reports(expected).items():
        require((package / name).read_text(encoding="utf-8") == value, f"report differs: {name}")
    for path in package.rglob("*.md"):
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            require(not Path(link).is_absolute(), "absolute documentation link")
            # External evidence links are laid out for the final research location.
            target = (path.parent / link.split("#")[0]).resolve()
            if not target.is_relative_to(package):
                original = SEED / path.relative_to(package)
                target = original.parent / link.split("#")[0]
            require(target.exists(), f"missing report link: {link}")
    print(json.dumps({"supplement_validation": "PASS", "formal_delivery_status": "NOT_PUBLISHED", "sources": len(sources), "archives": 28, "receipts": 21, "stage3_evaluations_checked": 573, "stage3_qualified_parameters": 26, "stage4_configurations": 36}, ensure_ascii=False))


def build(output):
    require(output.is_relative_to(ROOT / ".tmp"), "build only into a new repository .tmp directory")
    require(not output.exists(), "existing output cannot be overwritten")
    source_before = collect_sources()
    output.mkdir(parents=True)
    for name in ("README.md", "MIGRATION.md", "migration.json", "focused_validation.json", "src/build.py"):
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SEED / name, output / name)
    verification = audit_archives()
    verification["historical_reference_audit"] = audit_historical_references()
    data = materialize(verification)
    for name, value in data.items():
        dump(output / name, value)
    for name, value in reports(data).items():
        (output / name).write_text(value, encoding="utf-8", newline="\n")
    dump(output / "sources.json", source_before)
    dump(output / "verification.json", verification)
    require(source_before == collect_sources(), "historical sources changed during build")
    dump(output / "manifest.json", {
        "record_kind": "S011_HISTORICAL_SUPPLEMENT_MANIFEST", "schema_version": 1,
        "hash_policy": "RAW_SHA256_FOR_SUPPLEMENT_AND_SOURCE_INDEX; original archives validated by public API",
        "files": {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob("*")) if p.is_file()},
        "formal_delivery_status": "NOT_PUBLISHED", "original_sources_unchanged_during_build": True,
    })
    # Local links to generated siblings are checked using the staged package.
    for name in ("stage2/report.md", "stage3/report.md", "stage4/report.md"):
        require((output / name).exists(), "report missing")
    print(json.dumps({"built": output.relative_to(ROOT).as_posix(), "sources": len(source_before), "archives": 28, "receipts": 21}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build").add_argument("--output", type=Path, required=True)
    commands.add_parser("validate").add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.output.resolve())
    else:
        validate(args.package.resolve())
