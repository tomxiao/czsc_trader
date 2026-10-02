"""Publish reviewed successor deliveries; current public contracts only."""

from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
from research_experiment import load_experiment_input
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m
from czsc_trader.application import RepositoryContext, assemble_delivery, validate_delivery
import czsc_trader.research_tools as d

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
OLD = ROOT.parent / "20261002_S011_EX33"
COMP = ROOT.parent / "20261002_S011_EX34"
CTX = RepositoryContext.discover(REPO)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def attach(path, name=None):
    return d.EvidenceFile(
        path.relative_to(REPO).as_posix(),
        d.EvidenceRef(
            "attachments/" + (name or path.name),
            sha256(path.read_bytes()).hexdigest(),
            "application/json" if path.suffix == ".json" else "text/plain",
        ),
    )


def closure(*names):
    refs = {}

    def visit(name):
        if name in refs:
            return
        path = ROOT.parent / name / "artifacts"
        receipt = read(path / "execution_receipt.json")
        load_experiment_input(path, expected_receipt_sha256=receipt["receipt_sha256"])
        refs[name] = d.ExperimentEvidenceRef(
            name,
            path.relative_to(REPO).as_posix(),
            receipt["receipt_sha256"],
            d.ExperimentEvidenceUse.CURRENT_EVALUATION,
        )
        for previous in receipt["predecessor_receipts"]:
            visit(previous)

    for name in names:
        visit(name)
    return tuple(refs[k] for k in sorted(refs))


class Deliverable(d.ResearchDeliverable):
    def __init__(self, definition, content):
        self._definition, self.content = definition, content

    @property
    def definition(self):
        return self._definition

    def build(self):
        return self.content


def published_content(directory):
    content = d.DeliveryContent.from_dict(read(directory / "delivery.json")["content"])
    # Existing published copies are the authoritative immutable attachment sources.
    attachments = tuple(
        replace(x, source_path=(directory / x.reference.path).relative_to(REPO).as_posix())
        for x in content.attachments
    )
    return replace(content, attachments=attachments)


def publish(stage, content, predecessors, experiments):
    definition = d.DeliveryDefinition(
        d.ExperimentOwner("S011", ROOT.name), stage, 1, predecessors, experiments
    )
    content = replace(
        content,
        attachments=(
            *content.attachments,
            attach(ROOT / "publish_deliveries.py", "successor_publication.py"),
        ),
    )
    receipt = assemble_delivery(CTX, Deliverable(definition, content))
    checked = validate_delivery(CTX, receipt.reference)
    assert checked.status is d.ValidationStatus.PASS, checked
    write(ROOT / (stage.value.lower() + "_receipt.json"), receipt.to_dict())
    print(
        json.dumps(
            {
                "published": stage.value,
                "status": content.status.value,
                "validation": checked.status.value,
            }
        ),
        flush=True,
    )
    return receipt.reference


def component_audit():
    for filename, expected in read(COMP / "historical_sources.json").items():
        assert sha256((REPO / filename).read_bytes()).hexdigest() == expected
    summary = read(COMP / "artifacts/summary.json")
    role_tests = pd.read_csv(COMP / "artifacts/role_evidence.csv")
    assert (
        len(role_tests) == 63
        and role_tests.Factor.nunique() == 9
        and role_tests.Label.nunique() == 7
    )
    assert len(pd.read_csv(COMP / "artifacts/role_folds.csv")) == 189
    assert len(pd.read_csv(COMP / "artifacts/leave_month.csv")) == 945
    primary = read(ROOT.parent / "20260929_S011_EX12/component_panel.json")["components"]
    for component in primary:
        saved = component["primary_evidence"]
        row = role_tests.loc[
            role_tests.Factor.eq(component["field"]) & role_tests.Label.eq(saved["label"])
        ]
        assert len(row) == 1 and int(row.iloc[0].N) == saved["n"]
        for column, field in [
            ("RawIC", "raw_rank_ic"),
            ("PanelPartialIC", "panel_partial_ic"),
            ("LeaveMonthMinIC", "leave_month_min_ic"),
        ]:
            assert abs(row.iloc[0][column] - saved[field]) <= 5e-7
    assert [
        summary[k] for k in ("definition_count", "role_tests", "folds", "leave_month_paths")
    ] == [9, 63, 189, 945]
    ledger = pd.read_csv(ROOT.parent / "20260929_S011_EX12/artifacts/full_screening_ledger.csv")
    assert len(ledger) == ledger.Factor.nunique() == 185 and ledger.ReviewRoute.notna().all()
    doc = published_content(COMP / "deliveries/COMPONENTS/1")
    assert len(doc.payload.components) == 4
    report = {
        "status": "COMPLETE",
        "decision": "Four role-bounded components are fully delivered; research limitations retained.",
        "checks": [
            {
                "item": "definitions_and_roles",
                "status": "PASS",
                "evidence": "EX34 current ComponentEntry for opportunity, entry, risk and confirmation roles",
            },
            {
                "item": "actual_current_tests",
                "status": "PASS",
                "counts": {"definitions": 9, "tests": 63, "folds": 189, "leave_month_paths": 945},
            },
            {
                "item": "full_screening_ledger",
                "status": "PASS",
                "fields": 185,
                "routes": {str(k): int(v) for k, v in ledger.ReviewRoute.value_counts().items()},
            },
            {
                "item": "historical_routes_and_failures",
                "status": "PASS",
                "evidence": "EX01-EX12 historical research path, including EX05/EX11 failures, five-mechanism data gates and binary non-admission",
            },
            {
                "item": "adverse_evidence",
                "status": "PASS",
                "evidence": "Weak SPX multiplicity evidence, poor magnitude prediction, empty later absolute-risk bins, redundant and unsupported information explicitly retained",
            },
            {
                "item": "closeout",
                "status": "PASS",
                "judgment": "Available distinct roles support a complete falsifiable strategy hypothesis; no additional independent hold/exit predictor is a universal stage-two requirement.",
            },
        ],
        "limitations": [
            "All samples already seen; no new independent evidence.",
            "Historical supplier publication and revision vintages unverified.",
            "Old EX01 manifest reference discrepancy preserved; no claim to have repaired or machine-replayed historical contracts.",
            "The broad survey and binary paths remain historical evidence; current EX34 reruns the nine selected definitions only.",
            "Forecast basket and NAV/premium routes lacked required time-qualified data; explicitly closed as data gaps, not silently omitted.",
        ],
        "stage_five_started": False,
    }
    write(ROOT / "component_completeness_audit.json", report)
    return doc, report


def assessment(candidate_ref, mandate_ref):
    old = d.CandidateAssessmentDelivery.from_dict(
        read(OLD / "deliveries/ASSESSMENT/1/delivery.json")["content"]["payload"]
    )
    evidence = list(old.assessment_request.evidence)
    original = {(x.candidate, x.window_id, x.scenario_id): x for x in evidence}
    for path in sorted((ROOT / "artifacts/assessment").glob("*.json")):
        for value in read(path):
            item = m.AssessmentEvidence.from_dict(value)
            prior = original.get((item.candidate, item.window_id, item.scenario_id))
            if prior is not None:
                assert (
                    item.candidate.candidate_id == "S011-CFG000193R2"
                    and item.scenario_id == "standard"
                )
                assert (
                    item.account == prior.account
                    and item.fills == prior.fills
                    and item.closed_cycles == prior.closed_cycles
                )
                assert item.benchmark_equity == prior.benchmark_equity
            else:
                evidence.append(item)
    assert len(evidence) == 648
    links = list(old.assessment_request.perturbations)
    links.extend(
        m.PerturbationLink(x.parent, x.candidate, 1.0, x.derivation_sha256)
        for x in evidence
        if x.experiment_id == ROOT.name and x.parent is not None
    )
    assert len(links) == 576
    standard = [x for x in evidence if x.scenario_id == "standard"]
    assert len(standard) == 612
    selected = next(x.candidate for x in standard if x.candidate.candidate_id == "S011-CFG000621R2")
    # Full current cohort, including duplicate economic behaviors: correlation-aware diagnostic;
    # wider historical proposal correction is reported separately in authenticated attachments.
    matrix = np.column_stack(
        [
            np.array([a.equity for a in x.account])
            / np.r_[x.initial_cash, [a.equity for a in x.account[:-1]]]
            - 1
            for x in standard
        ]
    )
    family = m.FamilyReturnEvidence(
        tuple(x.candidate for x in standard),
        tuple(x.session for x in standard[0].account),
        tuple(map(tuple, matrix)),
        selected,
        612,
        (
            "Current authenticated diagnostic cohort only, including replayed centers; not the full historical search.",
            "Expanded historical correction uses 1284/1381 proposals in the separate audited family attachment.",
            "No independent samples; identical economic behaviors do not become independent observations.",
        ),
    )
    request = replace(
        old.assessment_request,
        evidence=tuple(evidence),
        perturbations=tuple(links),
        incomplete=(),
        family_returns=family,
    )
    panel = assess_candidates(request)
    comparison_request = replace(old.comparison_request, panel=panel)
    comparison = compare_candidates(comparison_request)
    write(ROOT / "assessment_request.json", request.to_dict())
    write(ROOT / "assessment_panel.json", panel.to_dict())
    write(ROOT / "comparison.json", comparison.to_dict())
    missing = [
        {
            "candidate": row.candidate.candidate_id,
            "metric": x.metric.value,
            "status": x.status.value,
            "reason": x.reason,
        }
        for row in panel.rows
        for x in row.diagnostics
        if x.value is None
    ]
    assert not missing, missing
    assert all(x.status is m.DiagnosticStatus.AVAILABLE for x in panel.family_diagnostics), (
        panel.family_diagnostics
    )
    counts = Counter(x.parent.candidate_id for x in links)
    assert len(counts) == 36 and set(counts.values()) == {16}
    coverage = {
        "status": "COMPLETE",
        "centers": 36,
        "joint_slots": 576,
        "joint_per_center": dict(counts),
        "same_source_pressure": 36,
        "current_unique_evidence_accounts": 648,
        "missing_diagnostics": missing,
        "layers": max(x.pareto_layer for x in comparison.rows),
        "partial_candidates": sum(
            x.status is m.ComparisonStatus.PARTIALLY_ORDERED for x in comparison.rows
        ),
        "incomparable_pairs": sum(
            x.relation is m.PairwiseRelation.INCOMPARABLE for x in comparison.pairs
        ),
        "target_checks": dict(
            Counter(x.status.value for row in comparison.rows for x in row.target_checks)
        ),
        "first_layer": [
            x.candidate.candidate_id
            for x in sorted(comparison.rows, key=lambda x: (x.pareto_layer, x.rank_min))
            if x.pareto_layer == 1
        ],
        "boundary_design": read(ROOT / "inputs.json")["boundary_design"],
        "standard_193_exactly_matches_EX33": True,
        "stage_five_started": False,
        "new_user_selection_record": False,
    }
    write(ROOT / "coverage_summary.json", coverage)
    write_report(panel, comparison, coverage, evidence)
    attachments = (
        attach(ROOT / "coverage_summary.json"),
        attach(ROOT / "artifacts/expanded_family_statistics.json"),
        attach(ROOT / "artifacts/historical_account_audit.json"),
        attach(ROOT / "artifacts/trial_states.json"),
        attach(ROOT / "inputs.json"),
        attach(ROOT / "02_design.md"),
        attach(ROOT / "family_statistics.py"),
        attach(ROOT / "COMPLETION_REPORT.md"),
        attach(
            ROOT.parent / "20261002_S011_EX35/experiment_manifest.json",
            "EX35_precheck_failure.json",
        ),
        attach(
            ROOT.parent / "20261002_S011_EX36/experiment_manifest.json",
            "EX36_execution_failure.json",
        ),
        attach(
            ROOT.parent / "20261002_S011_EX36/artifacts/technical_failure.txt", "EX36_failure.txt"
        ),
        attach(
            REPO / "research/S011/stage4/closeout_01/decision.json", "historical_user_decision.json"
        ),
    )
    adverse = tuple(
        x.reference
        for x in attachments
        if x.reference.path.endswith(
            ("expanded_family_statistics.json", "COMPLETION_REPORT.md", "02_design.md")
        )
    )
    payload = replace(
        old,
        source_candidates=candidate_ref,
        source_mandate=mandate_ref,
        assessment_request=request,
        assessment=panel,
        comparison_request=comparison_request,
        comparison=comparison,
        recommendation="36中心缺失诊断补齐；原经济目标与排序政策不变。621历史选择保留，完整新证据待用户审阅；不将覆盖完整解释为稳健性充分。",
        contrary_evidence=adverse,
        pending_decisions=("阶段五暂缓；请审阅新证据后明确下一步研究或技术检验范围。",),
    )
    content = d.DeliveryContent(
        payload,
        d.DeliveryStatus.COMPLETE,
        (),
        (
            d.Explanation(
                d.ExplanationKind.RESEARCH_JUDGMENT,
                "覆盖完成。000137使用受源码上限约束的单侧lookback设计，000664保持3天持有期；联合检验均16点，但不宣称所有邻域设计同构。已见样本、选择偏差和固定局部尺度局限继续披露。",
                supporting=adverse,
            ),
        ),
        d.ReproductionSpec(
            "当前公开API验证回执及交付；复算使用后继实验，禁止覆盖封存证据。",
            (),
            "原授权DFLS输入；历史账户由研究代码逐项审计，平台不承诺历史机器复验。",
            "固定设计、种子和输入哈希；相同开发池，不增加独立样本。",
        ),
        (),
        attachments,
    )
    return content, coverage


def write_report(panel, comparison, coverage, evidence):
    family = read(ROOT / "artifacts/expanded_family_statistics.json")
    selected = next(x for x in panel.rows if x.candidate.candidate_id == "S011-CFG000621R2")
    values = {x.metric.value: x.value for x in selected.diagnostics}
    selected_rank = next(x for x in comparison.rows if x.candidate == selected.candidate)
    baseline = {(x.candidate, x.scenario_id): x for x in evidence}
    request = m.CandidateAssessmentRequest.from_dict(read(ROOT / "assessment_request.json"))
    rows = []
    for center in request.centers:
        own = baseline[(center, "standard")]
        annual_benchmark = (own.benchmark_equity[-1] / own.initial_cash) ** (
            252 / len(own.account)
        ) - 1
        benchmark = np.r_[own.initial_cash, own.benchmark_equity]
        benchmark_dd = -np.min(benchmark / np.maximum.accumulate(benchmark) - 1)
        passed = 0
        for link in request.perturbations:
            if link.parent != center:
                continue
            item = baseline[(link.child, "standard")]
            eq = np.r_[item.initial_cash, [x.equity for x in item.account]]
            annual = (eq[-1] / eq[0]) ** (252 / len(item.account)) - 1
            drawdown = -np.min(eq / np.maximum.accumulate(eq) - 1)
            frequency = 60 * len(item.closed_cycles) / len(item.account)
            passed += bool(
                annual >= 1.5 * annual_benchmark and drawdown < benchmark_dd and 4 <= frequency <= 6
            )
        rows.append(
            {
                "candidate_id": center.candidate_id,
                "qualified_joint_points": passed,
                "joint_points": 16,
            }
        )
    write(ROOT / "joint_goal_coverage.json", rows)
    selected_pass = next(
        x["qualified_joint_points"]
        for x in rows
        if x["candidate_id"] == selected.candidate.candidate_id
    )
    pbo = "、".join(f"{x['block_count']}块 {x['pbo']:.2%}" for x in family["pbo"])
    dsr = [x for x in family["dsr"] if x["candidate_id"] == selected.candidate.candidate_id]
    dsr_text = "；".join(
        f"{x['raw_count']}次口径 {x['result']['raw']['probability']:.2%}" for x in dsr
    )
    table = [
        "| 配置 | 层级 | 同层名次范围 | 标准年化 | 回撤幅度 | 联合达标点 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    by_id = {x.candidate: x for x in panel.rows}
    by_pass = {x["candidate_id"]: x["qualified_joint_points"] for x in rows}
    for row in sorted(
        comparison.rows, key=lambda x: (x.pareto_layer, x.rank_min, x.candidate.candidate_id)
    ):
        metrics = {x.metric.value: x.value for x in by_id[row.candidate].diagnostics}
        table.append(
            f"| {row.candidate.candidate_id.removeprefix('S011-')} | {row.pareto_layer} | {row.rank_min}—{row.rank_max} | {metrics['NET_ANNUAL_RETURN']:.2%} | {metrics['DRAWDOWN_MAGNITUDE']:.2%} | {by_pass[row.candidate.candidate_id]}/16 |"
        )
    text = f"""# S011 阶段二与阶段四完整交付

状态：`COMPLETE_WITH_RESEARCH_LIMITATIONS`。阶段二及阶段四交付要求已覆盖；阶段五继续暂停。完整性表示定义、执行证据、诊断、反证和结论齐备，不表示稳健性充分、选择偏差消失或未来收益得到保证。

## 阶段二结论

保留4项限定职责组件：沪深300当日收益用于机会背景，ETF尾盘90分钟收益用于入场排序，五日平均振幅用于风险环境，严格前序SPX单日收益用于较弱的外部确认。没有扩大组件职责或新设有效性门槛。

EX34当前受管证据覆盖9项定义、7种标签、63条职责检验、189个顺序折及945条留月诊断；185字段筛选台账逐项保留，包含未晋级、重复、常数和二元路径。EX01—EX12路线和EX05/EX11技术失败作为历史证据完整留存。详见[完整性审查](component_completeness_audit.json)及正式阶段二报告。

最强反证继续生效：机会和入场信息的近期幅度预测较弱；风险绝对分组后期出现空组；SPX多重检验和幅度预测不足。盈利预期篮子、真实净值折溢价等路线受历史可得时点或数据缺口限制，未授予组件。旧EX01引用差异明确保留，平台不承诺历史数据机器复验；此问题不自动否定EX34当前证据的交付完整性。

## 阶段四补测和结果

EX37完成513次受管调用、514份账户：512个新固定联合扰动、000193同源码20bp压力及一份配套标准重复账户。原EX33的135份账户继续引用；去除重复标准坐标后，正式自检使用648份账户，含36中心、576联合点和36压力场景。每中心16点；原经济目标、分箱和优先级不变。

000137原源码lookback上限120，其设计为110/120单侧，其余五轴对称；其他中心保留原六轴对称步长。000664保持原3天持有期，其他中心为2天。覆盖完整与设计同构分别判断，这两项差异必须随比较披露。涉及000137的同层顺序以其受限可行域为条件，不能视为对称邻域的严格对照；局部诊断也不能解释为全参数域稳定性。

当前仍为{coverage["layers"]}层；证据不足导致的名次区间涉及{coverage["partial_candidates"]}个配置，存在{coverage["incomparable_pairs"]}对不可比关系。第一层：{" → ".join(coverage["first_layer"])}。下表只交接原36中心，新增扰动点不自动晋升候选。

{chr(10).join(table)}

621保持原内容身份，位于第{selected_rank.pareto_layer}层、同层名次范围{selected_rank.rank_min}—{selected_rank.rank_max}。标准年化{values["NET_ANNUAL_RETURN"]:.4%}、回撤幅度{values["DRAWDOWN_MAGNITUDE"]:.4%}，联合点仅{selected_pass}/16满足原经济目标。原用户选择保留为历史决定；本次没有生成用户已批准新交付的记录。

## 搜索选择风险

扩展研究族覆盖588次原可比提议、EX28的184次固定提议、本轮512次固定提议，共1284次；保守1381次口径另保留96次错误预热提议和1次EX18基线重复。EX33复算和本轮配套标准重复不增加计数。772份历史标准账户核对原始哈希来源、日历、资金和整手、订单类型、费用及指标后复用；旧回执没有被冒充当前平台执行认证。

去除恒定及重复收益路径后为{family["nonconstant_unique_paths"]}条路径。PBO（分块后，训练赢家在验证部分落到后半区的比例）：{pbo}。相关结构的有效试验数约{family["effective_trial_count"]:.4f}；该值是相关性诊断，不是独立样本数。621的原始次数DSR（对多次尝试修正后的夏普证据指标）：{dsr_text}。这些指标均不是未来获利概率。

正式强类型FamilyReturnEvidence另提供612份当前受管标准账户构成的诊断子族，保留重复经济行为且披露范围。它与上述完整可比研究族分列，不以子族替代完整搜索史。既往机制选择、反复观察同一开发池的污染仍未被消除；没有新增独立验证样本。

## 失败、验证和下一步

EX35因000137的8个非法点未通过合成预检，未执行账户。EX36首个压力请求缺standard场景被公共API拒绝，未产生账户；两个失败档案均封存，由EX37承接。所有实际执行及数值/覆盖校验见[执行回执](artifacts/execution_receipt.json)、[覆盖清单](coverage_summary.json)、[逐中心邻域达标](joint_goal_coverage.json)和[扩展族统计](artifacts/expanded_family_statistics.json)。公共交付及档案验收结果另见focused_verification.json。

机器制品和交付实验副本按仓库规则在本地保存，不随Git完整同步，未执行外部备份。下一步建议审阅本次诊断和621的局部脆弱性，再决定继续研究或授权阶段五技术检验；当前不冻结、不部署。
"""
    (ROOT / "COMPLETION_REPORT.md").write_text(text, encoding="utf-8", newline="\n")


def main():
    assert read(ROOT / "artifacts/execution_receipt.json")["trace"]["evaluations"]
    mandate = d.DeliveryReceipt.from_dict(read(OLD / "mandate_receipt.json")).reference
    old_component = d.DeliveryReceipt.from_dict(read(OLD / "components_receipt.json")).reference
    old_candidate = d.DeliveryReceipt.from_dict(read(OLD / "candidates_receipt.json")).reference
    doc, audit = component_audit()
    doc = replace(
        doc,
        status=d.DeliveryStatus.COMPLETE,
        incomplete_items=(),
        payload=replace(
            doc.payload,
            conclusion="阶段二完整交付：4项限定职责组件、定义及当前63条检验、185字段完整去向、历史失败及反证、收口判断齐备。历史机器复验与独立有效性不属于本次完成状态的承诺。",
        ),
        explanations=(
            *doc.explanations,
            d.Explanation(
                d.ExplanationKind.RESEARCH_JUDGMENT,
                "历史旧格式及未全量重跑不自动构成交付缺口。当前证据范围、负面路线和研究局限均明确保留。",
            ),
        ),
        attachments=(
            *doc.attachments,
            attach(ROOT / "component_completeness_audit.json"),
            attach(
                ROOT.parent / "20260929_S011_EX12/COMPONENT_PANEL.md", "EX12_component_report.md"
            ),
            attach(
                REPO / "research/S011/STAGE2_FIVE_MECHANISMS.md", "historical_five_mechanisms.md"
            ),
        ),
    )
    component = publish(
        d.DeliveryStage.COMPONENTS, doc, (mandate, old_component), closure(COMP.name)
    )
    candidate_doc = published_content(OLD / "deliveries/CANDIDATES/1")
    candidate_doc = replace(
        candidate_doc,
        explanations=(
            *candidate_doc.explanations,
            d.Explanation(
                d.ExplanationKind.FACT,
                "候选载荷、36项交接集合、已有搜索记录及账户证据保持原内容，仅承接阶段二完整交付引用。阶段四补测轨迹在ASSESSMENT附件中完整交付。",
            ),
        ),
    )
    candidate = publish(
        d.DeliveryStage.CANDIDATES,
        candidate_doc,
        (mandate, component, old_candidate),
        closure(OLD.name),
    )
    content, coverage = assessment(candidate, mandate)
    assessment_ref = publish(
        d.DeliveryStage.ASSESSMENT, content, (mandate, component, candidate), closure(ROOT.name)
    )
    write(
        ROOT / "delivery_index.json",
        {
            "status": "COMPLETE_WITH_RESEARCH_LIMITATIONS",
            "references": [x.to_dict() for x in (mandate, component, candidate, assessment_ref)],
            "stage_five_started": False,
        },
    )
    print(json.dumps(coverage, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
