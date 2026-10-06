"""Incremental component evidence for five formal return-mechanism successors."""

from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.research_tools import (
    ComponentEntry,
    ComponentPanel,
    ComponentTestResult,
    ComponentTestStatus,
    DeliveryContent,
    DeliveryDefinition,
    DeliveryStage,
    DeliveryStatus,
    EvidenceFile,
    EvidenceRef,
    ExperimentDefinitionRef,
    ExperimentEvidenceRef,
    ExperimentEvidenceUse,
    ExperimentOwner,
    Explanation,
    ExplanationKind,
    FactStatus,
    FactValue,
    ReproductionSpec,
    ResearchDeliverable,
)

EID = "EX036_20261006"
CURRENT = ("EX032_20261006", "EX033_20261006", "EX034_20261006", "EX035_20261006", EID)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


class ReturnDiscoveryComponents(ResearchDeliverable[ComponentPanel]):
    def __init__(self, root):
        self.root = Path(root).resolve()

    @property
    def definition(self):
        references = {}

        def visit(eid):
            if eid in references:
                return
            path = f"experiments/S012/{eid}/artifacts/rex"
            receipt = read(self.root / path / "execution_receipt.json")
            references[eid] = ExperimentEvidenceRef(
                eid,
                path,
                receipt["receipt_sha256"],
                ExperimentEvidenceUse.CURRENT_EVALUATION
                if eid in CURRENT
                else ExperimentEvidenceUse.HISTORICAL_REFERENCE,
            )
            for parent in receipt["predecessor_receipts"]:
                visit(parent)

        visit(EID)
        # This same-stage increment carries the actual experiment receipt closure.
        # Previous immutable delivery identity is attached, not republished as new support.
        return DeliveryDefinition(
            ExperimentOwner("S012", EID),
            DeliveryStage.COMPONENTS,
            1,
            experiments=tuple(references[k] for k in sorted(references)),
        )

    def build(self):
        attachments, refs = [], {}
        for eid in CURRENT:
            exp = self.root / f"experiments/S012/{eid}"
            names = [
                "01_goal.md",
                "02_design.md",
                "03_execution.md",
                "04_conclusion.md",
                "protocol_inheritance_note.md",
                "hypothesis_ledger.json",
                "hypothesis_judgments.json",
                "result_summary.json",
                "experiment_binding.json",
                "execution_driver.py",
                "reproduction/verify.py",
                "artifacts/verification/independent.json",
            ]
            if eid == EID:
                names += [
                    "stage2_report.md",
                    "cycle_summary.json",
                    "delivery.py",
                    "publication_driver.py",
                ]
            for name in names:
                mime = (
                    "text/markdown"
                    if name.endswith(".md")
                    else "application/json"
                    if name.endswith(".json")
                    else "text/x-python"
                )
                ref = EvidenceRef(f"attachments/current/{eid}/{name}", digest(exp / name), mime)
                refs[eid, name] = ref
                attachments.append(EvidenceFile(f"experiments/S012/{eid}/{name}", ref))
        for name in (
            "stage2_return_discovery_authorization_20261006.json",
            "gvz_preliminary_components_reference_20261006.json",
            "gvz_usdollar_preliminary_authorization_20261006.json",
        ):
            path = "research/S012/materials/" + name
            attachments.append(
                EvidenceFile(
                    path,
                    EvidenceRef(
                        "attachments/current/" + name,
                        digest(self.root / path),
                        "application/json",
                    ),
                )
            )

        path = "research/S012/materials/return_discovery_scope_note_20261006.md"
        attachments.append(
            EvidenceFile(
                path,
                EvidenceRef(
                    "attachments/current/scope_note.md", digest(self.root / path), "text/markdown"
                ),
            )
        )
        facts, entries = [], []
        for eid in CURRENT:
            exp = self.root / f"experiments/S012/{eid}"
            p = exp / "artifacts/rex"

            def evidence(name):
                return EvidenceRef(
                    f"experiments/{eid}/{name}", digest(p / name), "application/json"
                )

            rr, ar, ir = (
                evidence("opportunities.json"),
                evidence("annual.json"),
                evidence("inference.json"),
            )
            specs = read(p / "hypothesis_definitions.json")
            judgments = read(exp / "hypothesis_judgments.json")
            rows = read(p / "opportunities.json")
            receipt = read(p / "execution_receipt.json")
            definition = ExperimentDefinitionRef(
                eid, receipt["definition_sha256"], receipt["source_sha256"], "experiment:Experiment"
            )
            for spec in specs:
                key = spec["id"]
                row = next(
                    r
                    for r in rows
                    if (r["signal"], r["horizon"], r["delay"], r["fee"])
                    == (key, spec["primary_horizon"], 0, 0.001)
                )
                fact_ids = []
                fields = [
                    "events",
                    "net_mean",
                    "parent_lift",
                    "parent_matched_increment",
                    "parent_ols_increment",
                    "limit_potential_fills",
                    "limit_potential_net",
                    "potential_per60_original1535",
                    "fixed_parent_filtered_contribution",
                    "fixed_parent_base_contribution",
                ]
                fields += [
                    k
                    for k in (
                        "fixed_parent_limit_base",
                        "fixed_parent_limit_filtered",
                        "fixed_parent_limit_delta",
                        "fixed_parent_limit_slots",
                        "fixed_parent_limit_base_fills",
                        "fixed_parent_limit_kept_fills",
                    )
                    if k in row
                ]
                for field in fields:
                    fid = f"{eid}_{key}_{field}"
                    fact_ids.append(fid)
                    value = row[field]
                    unit = (
                        "count"
                        if field
                        in (
                            "events",
                            "limit_potential_fills",
                            "fixed_parent_limit_slots",
                            "fixed_parent_limit_base_fills",
                            "fixed_parent_limit_kept_fills",
                        )
                        else "potential/60sessions"
                        if field == "potential_per60_original1535"
                        else "decimal return"
                    )
                    facts.append(
                        FactValue(
                            fid,
                            value,
                            unit,
                            FactStatus.AVAILABLE
                            if value is not None
                            else FactStatus.INSUFFICIENT_DATA,
                            (rr,),
                            None if value is not None else "无事件或无法识别的控制矩阵",
                        )
                    )
                test = ComponentTestResult(
                    f"{eid}_{key}_primary",
                    eid,
                    refs[eid, "02_design.md"],
                    ComponentTestStatus(judgments[key]["status"]),
                    judgments[key]["judgment"],
                    (rr, ar, ir, refs[eid, "protocol_inheritance_note.md"]),
                    tuple(fact_ids),
                )
                entries.append(
                    ComponentEntry(
                        f"RETURN_{eid}_{key}",
                        definition,
                        spec["role"],
                        spec["hypothesis"],
                        f"{spec['primary_horizon']}交易日主期限；协议中固定其他期限/费用/执行延迟",
                        spec["parent"]
                        + "同有效窗口同费用父对照、父事件内匹配/OLS和固定时间表；触价不等于账户成交",
                        "T17:00；GVZ初版可得政策、VIX次日08:30、FX源后2自然日08:00；源日配对与过去窗口",
                        "518850原始价格；GVZ期权预期波动；XAU×CNH为参考走势，非官方净值；USDOLLAR有限代理",
                        "全1535日及前驱均已见；来源政策未逐条验证；同日端点仍有跨市场时差，无完整账户",
                        judgments[key]["judgment"],
                        (test,),
                    )
                )
        summary = read(self.root / f"experiments/S012/{EID}/cycle_summary.json")
        for key in (
            "hypothesis_records",
            "paths",
            "annual_rows",
            "new_supported_opportunity_components",
        ):
            facts.append(
                FactValue(
                    key,
                    summary[key],
                    "count",
                    FactStatus.AVAILABLE,
                    (refs[EID, "cycle_summary.json"],),
                )
            )
        conclusion = "五轮收益深化47条检验记录、1152路径、8064年度；新增1个SUPPORTED有边界机会环境（原M05直接必要性复验）。追加GVZ/低比值及价格确认未改善，全部年度与执行反证保留，整体阶段二IN_PROGRESS。"
        return DeliveryContent(
            ComponentPanel(tuple(entries), conclusion),
            DeliveryStatus.PARTIAL,
            tuple(facts),
            (
                Explanation(
                    ExplanationKind.RESEARCH_JUDGMENT,
                    conclusion,
                    supporting=(refs[EID, "stage2_report.md"],),
                    contrary=(refs[EID, "result_summary.json"],),
                ),
                Explanation(
                    ExplanationKind.FACT,
                    "固定父时间表限价零填贡献和重新去重后的触价均值分开；成本敏感改善可能来自少交易，未等同新增收益或账户目标。",
                    supporting=(refs[EID, "02_design.md"], refs[EID, "stage2_report.md"]),
                ),
                Explanation(
                    ExplanationKind.STATISTICAL_EVIDENCE,
                    "父内增量、年度、延期、同日端点和去单年联合反证保留；区间跨零只为诊断，不添加用户未规定的经济硬门。",
                    supporting=(refs[EID, "04_conclusion.md"], refs[EID, "stage2_report.md"]),
                ),
            ),
            ReproductionSpec(
                "仓库根分别运行本轮EX032—36的reproduction/verify.py；正式重跑须新建实验，原回执保持不可变。",
                tuple(refs[eid, "experiment_binding.json"] for eid in CURRENT),
                "所有来源按正式回执及SHA认证，完整S012前驱制品和DFLS资产须保留；Git不携带全部真实制品。",
                "worker=1/native_threads=1；seed12032—12036；EX001—36历史已见；发布时点政策不能代替真实历史核验。",
            ),
            incomplete_items=(
                "已交付1个有边界机会环境，整体阶段二继续；低频及年度/控制反证未消除。",
                "分钟内收益形成及限价兼容机会尚未完成该轮深化；新增来源须授权。",
                "原完整账户三个经济目标未复验；阶段三及生产、合并tag推送均需用户批准。",
            ),
            attachments=tuple(attachments),
        )
