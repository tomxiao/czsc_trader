"""Complete stage-two panel, preserving every inherited research judgment."""

from dataclasses import replace
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
    DeliveryReference,
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

EID = "EX039_20261006"
PANELS = ("EX019_20261005", "EX029_20261006", "EX031_20261006", "EX036_20261006")
CURRENT = ("EX037_20261006", "EX038_20261006", EID)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def remap(value, paths, fact_ids):
    if isinstance(value, list):
        return [remap(v, paths, fact_ids) for v in value]
    if not isinstance(value, dict):
        return value
    out = {k: remap(v, paths, fact_ids) for k, v in value.items()}
    if out.get("type") == "EvidenceRef" and out["path"].startswith("attachments/"):
        out["path"] = paths[out["path"]]
    if "fact_id" in out:
        out["fact_id"] = fact_ids[out["fact_id"]]
    if "fact_ids" in out:
        out["fact_ids"] = [fact_ids[x] for x in out["fact_ids"]]
    return out


class CompleteStageTwo(ResearchDeliverable[ComponentPanel]):
    def __init__(self, root):
        self.root = Path(root).resolve()

    @property
    def definition(self):
        references = {}
        predecessors = []

        def visit(eid):
            if eid in references:
                return
            path = f"experiments/S012/{eid}/artifacts/rex"
            r = read(self.root / path / "execution_receipt.json")
            references[eid] = ExperimentEvidenceRef(
                eid,
                path,
                r["receipt_sha256"],
                ExperimentEvidenceUse.CURRENT_EVALUATION
                if eid in CURRENT
                else ExperimentEvidenceUse.HISTORICAL_REFERENCE,
            )
            for parent in r["predecessor_receipts"]:
                visit(parent)

        for eid in PANELS:
            base = self.root / f"experiments/S012/{eid}/deliveries/COMPONENTS/1"
            predecessors.append(
                DeliveryReference.from_dict(read(base / "receipt.json")["reference"])
            )
            for r in read(base / "delivery.json")["definition"]["experiments"]:
                visit(r["experiment_id"])
        for eid in CURRENT:
            visit(eid)
        return DeliveryDefinition(
            ExperimentOwner("S012", EID),
            DeliveryStage.COMPONENTS,
            1,
            predecessors=tuple(predecessors),
            experiments=tuple(references[k] for k in sorted(references)),
        )

    def build(self):
        entries, facts, attachments = [], [], []
        for eid in PANELS:
            relative = f"experiments/S012/{eid}/deliveries/COMPONENTS/1"
            old = read(self.root / relative / "delivery.json")["content"]
            paths = {}
            for raw in old["attachments"]:
                item = EvidenceFile.from_dict(raw)
                source = f"{relative}/{item.reference.path}"
                if digest(self.root / source) != item.reference.sha256:
                    raise ValueError("changed historical attachment " + source)
                destination = f"attachments/historical/{eid}/{item.reference.path.removeprefix('attachments/')}"
                paths[item.reference.path] = destination
                attachments.append(EvidenceFile(source, replace(item.reference, path=destination)))
            fids = {v["fact_id"]: f"{eid}__{v['fact_id']}" for v in old["facts"]}
            facts += [FactValue.from_dict(remap(v, paths, fids)) for v in old["facts"]]
            panel = ComponentPanel.from_dict(remap(old["payload"], paths, fids))
            entries += [
                replace(c, component_id=f"H_{eid}_{c.component_id}") for c in panel.components
            ]

        refs = {}
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
                    "role_coverage.json",
                    "full_research_ledger.json",
                    "experiment_inventory.json",
                    "completion_checklist.json",
                    "cycle_summary.json",
                    "phase_summary.json",
                    "delivery.py",
                    "publication_driver.py",
                    "artifacts/verification/completion_audit.json",
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
            receipt = read(p / "execution_receipt.json")
            definition = ExperimentDefinitionRef(
                eid, receipt["definition_sha256"], receipt["source_sha256"], "experiment:Experiment"
            )
            rows = read(p / "opportunities.json")
            judgments = read(exp / "hypothesis_judgments.json")
            for spec in read(p / "hypothesis_definitions.json"):
                key = spec["id"]
                row = next(
                    x
                    for x in rows
                    if (x["signal"], x["horizon"], x["delay"], x["fee"])
                    == (key, spec["primary_horizon"], 0, 0.001)
                )
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
                    "fixed_parent_limit_base",
                    "fixed_parent_limit_filtered",
                    "fixed_parent_limit_delta",
                    "fixed_parent_limit_slots",
                    "fixed_parent_limit_base_fills",
                    "fixed_parent_limit_kept_fills",
                ]
                ids = []
                for field in fields:
                    fid = f"{eid}_{key}_{field}"
                    ids.append(fid)
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
                            None if value is not None else "无事件或无法识别的矩阵",
                        )
                    )
                # A split on own_day has structurally zero matched residual, not evidence of no information.
                judgment = judgments[key]["judgment"]
                test = ComponentTestResult(
                    f"{eid}_{key}_primary",
                    eid,
                    refs[eid, "02_design.md"],
                    ComponentTestStatus(judgments[key]["status"]),
                    judgment,
                    (rr, ar, ir, refs[eid, "04_conclusion.md"]),
                    tuple(ids),
                )
                entries.append(
                    ComponentEntry(
                        f"CURRENT_{eid}_{key}",
                        definition,
                        spec["role"],
                        "T+1至T+6原始开盘费用后事件收益，固定父槽限价零填贡献另报；"
                        + spec["hypothesis"],
                        "主5交易日；1/3/5日、延迟0/1/2、每侧10/20bp反证",
                        spec["parent"] + "同有效窗口、同费用；日线四控制、父匹配/OLS及固定父时间表",
                        "T17已完整可得；分钟仅当日已发布8格、宏观承接已审计保守时点、旧门阈值精确继承",
                        "518850原始OHLCVA；收盘向下0.001限价Low触价仅潜在成交，非净值或账户",
                        "全部1535日开发池及前驱已见；年度/费用/延迟/源时点与质量局限保留；当前角色以role_coverage为准",
                        judgment,
                        (test,),
                    )
                )

        for name in (
            "stage2_return_discovery_authorization_20261006.json",
            "return_discovery_scope_note_20261006.md",
        ):
            source = "research/S012/materials/" + name
            attachments.append(
                EvidenceFile(
                    source,
                    EvidenceRef(
                        "attachments/current/" + name,
                        digest(self.root / source),
                        "text/markdown" if name.endswith(".md") else "application/json",
                    ),
                )
            )
        summary = read(self.root / f"experiments/S012/{EID}/cycle_summary.json")
        for field in (
            "panel_records",
            "recommended_distinct_components",
            "opportunity_count",
            "risk_state_count",
            "confirmation_count",
            "new_paths",
            "new_annual_rows",
            "independent_fields_checked",
        ):
            facts.append(
                FactValue(
                    field,
                    summary[field],
                    "count",
                    FactStatus.AVAILABLE,
                    (refs[EID, "cycle_summary.json"],),
                )
            )
        if len(entries) != 142 or len({x.component_id for x in entries}) != 142:
            raise ValueError("complete research panel count/identity differs")
        conclusion = "阶段二在既有授权资源内完成：142研究记录、6个当前不同职责（O01/M05两机会、C01/C02/C03三风险、Q07仅O01确认），另保留N09候选。新增分钟门未支持、并集增量依赖2025、费用与执行反证完整；阶段三和完整账户目标等待新批准。"
        return DeliveryContent(
            ComponentPanel(tuple(entries), conclusion),
            DeliveryStatus.COMPLETE,
            tuple(facts),
            (
                Explanation(
                    ExplanationKind.RESEARCH_JUDGMENT,
                    conclusion,
                    supporting=(refs[EID, "stage2_report.md"], refs[EID, "role_coverage.json"]),
                    contrary=(
                        refs[EID, "phase_summary.json"],
                        refs[EID, "full_research_ledger.json"],
                    ),
                ),
                Explanation(
                    ExplanationKind.FACT,
                    "142包含历史判据、重复复验和缺资源记录，6为当前推荐职责数；原SUPPORTED不覆盖，N09当前不推荐默认门。",
                    supporting=(
                        refs[EID, "full_research_ledger.json"],
                        refs[EID, "role_coverage.json"],
                    ),
                ),
                Explanation(
                    ExplanationKind.STATISTICAL_EVIDENCE,
                    "六相位全部固定，未选最佳；平均覆盖并不保证单一起点，去2025并集增量负；随机区间跨零/年度与延期为诊断，未新增用户经济硬门。",
                    supporting=(refs[EID, "phase_summary.json"], refs[EID, "04_conclusion.md"]),
                ),
            ),
            ReproductionSpec(
                "仓库根运行EX037/38/39各自reproduction/verify.py；历史源码/验证按继承附件，正式重跑须新后继实验。",
                tuple(refs[eid, "experiment_binding.json"] for eid in CURRENT),
                "依赖同版本numpy/pandas及完整S012正式回执/真实输入闭包，不再获取新行情；跨机器须同步Git忽略DFLS制品。",
                "worker=1/native_threads=1/seed12037至12039；全开发池已见；逐条真实发布时间、实际成交及账户目标不由复算证明。",
            ),
            attachments=tuple(attachments),
        )
