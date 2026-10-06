"""Publish the preliminary increment without replacing earlier component evidence."""

from hashlib import sha256
from pathlib import Path
import json
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

EID = "EX031_20261006"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


class PreliminaryComponents(ResearchDeliverable[ComponentPanel]):
    def __init__(self, root):
        self.root = Path(root).resolve()

    @property
    def definition(self):
        refs = {}

        def visit(eid):
            if eid in refs:
                return
            path = f"experiments/S012/{eid}/artifacts/rex"
            receipt = read(self.root / path / "execution_receipt.json")
            refs[eid] = ExperimentEvidenceRef(
                eid,
                path,
                receipt["receipt_sha256"],
                ExperimentEvidenceUse.CURRENT_EVALUATION
                if eid == EID
                else ExperimentEvidenceUse.HISTORICAL_REFERENCE,
            )
            for parent in receipt["predecessor_receipts"]:
                visit(parent)

        visit(EID)
        prior = DeliveryReference.from_dict(
            read(
                self.root / "experiments/S012/EX029_20261006/deliveries/COMPONENTS/1/receipt.json"
            )["reference"]
        )
        return DeliveryDefinition(
            ExperimentOwner("S012", EID),
            DeliveryStage.COMPONENTS,
            1,
            predecessors=(prior,),
            experiments=tuple(refs[k] for k in sorted(refs)),
        )

    def build(self):
        root = self.root
        exp = root / f"experiments/S012/{EID}"
        p = exp / "artifacts/rex"
        files = []
        refs = {}
        for name in (
            "01_goal.md",
            "02_design.md",
            "03_execution.md",
            "04_conclusion.md",
            "hypothesis_ledger.json",
            "hypothesis_judgments.json",
            "preliminary_result_summary.json",
            "protocol_inheritance_note.md",
            "experiment_binding.json",
            "execution_driver.py",
            "delivery.py",
            "publication_driver.py",
            "reproduction/verify.py",
            "artifacts/verification/independent.json",
        ):
            ref = EvidenceRef(
                "attachments/current/" + name,
                digest(exp / name),
                "text/markdown"
                if name.endswith(".md")
                else "application/json"
                if name.endswith(".json")
                else "text/x-python",
            )
            files.append(EvidenceFile(f"experiments/S012/{EID}/{name}", ref))
            refs[name] = ref
        for name in (
            "gvz_usdollar_preliminary_authorization_20261006.json",
            "dev_gvz_usdollar_acceptance_20261006.json",
        ):
            path = "research/S012/materials/" + name
            files.append(
                EvidenceFile(
                    path,
                    EvidenceRef(
                        "attachments/current/" + name, digest(root / path), "application/json"
                    ),
                )
            )

        def evidence(name):
            return EvidenceRef(f"experiments/{EID}/{name}", digest(p / name), "application/json")

        result_ref = evidence("opportunities.json")
        annual_ref = evidence("annual.json")
        infer_ref = evidence("inference.json")
        receipt = read(p / "execution_receipt.json")
        definition = ExperimentDefinitionRef(
            EID, receipt["definition_sha256"], receipt["source_sha256"], "experiment:Experiment"
        )
        judgments = read(exp / "hypothesis_judgments.json")
        specs = read(p / "hypothesis_definitions.json")
        rows = read(p / "opportunities.json")
        inference = {x["signal"]: x for x in read(p / "inference.json")}
        components = []
        facts = []
        for spec in specs:
            key = spec["id"]
            row = next(
                x
                for x in rows
                if (x["signal"], x["horizon"], x["delay"], x["fee"])
                == (key, spec["primary_horizon"], 0, 0.001)
            )
            ids = []
            for field in (
                "eligible_days",
                "events",
                "net_mean",
                "parent_lift",
                "matched_increment",
                "ols_increment",
                "nonoverlap_events",
                "limit_potential_fills",
                "limit_potential_net",
                "potential_per60_original1535",
            ):
                fid = key + "_" + field
                value = row[field]
                ids.append(fid)
                unit = (
                    "count"
                    if field
                    in ("eligible_days", "events", "nonoverlap_events", "limit_potential_fills")
                    else "cycles/60sessions"
                    if field == "potential_per60_original1535"
                    else "decimal return"
                )
                facts.append(
                    FactValue(
                        fid,
                        value,
                        unit,
                        FactStatus.AVAILABLE if value is not None else FactStatus.INSUFFICIENT_DATA,
                        (result_ref,),
                        None if value is not None else "无可计算事件或控制矩阵",
                    )
                )
            fid = key + "_q"
            ids.append(fid)
            value = inference[key]["q"]
            facts.append(FactValue(fid, value, "BH diagnostic", FactStatus.AVAILABLE, (infer_ref,)))
            test = ComponentTestResult(
                key + "_fixed_primary",
                EID,
                refs["02_design.md"],
                ComponentTestStatus(judgments[key]["status"]),
                judgments[key]["judgment"],
                (result_ref, annual_ref, infer_ref, refs["protocol_inheritance_note.md"]),
                tuple(ids),
            )
            components.append(
                ComponentEntry(
                    "PRELIM_" + key,
                    definition,
                    spec["role"],
                    spec["hypothesis"],
                    f"{spec['primary_horizon']}交易日主期限；其他期限描述诊断",
                    spec["parent"] + "同有效窗口同费用对照、状态匹配及含VIX水平的OLS",
                    "T17:00；GVZ max观测/初次版本日后次日16:00，FXCM源日后2自然日08:00；均为披露政策",
                    "518850原始价格，GVZ为黄金ETF期权波动，USDOLLAR四币代理非ICE DXY",
                    "全部已见开发池；美元仅截至2023-06-01；初步研究，不代表完整账户绩效",
                    judgments[key]["judgment"],
                    (test,),
                )
            )
        for name, value in (
            ("sessions", 1535),
            ("fixed_hypotheses", 9),
            ("controls", 4),
            ("paths", 260),
            ("annual_rows", 1820),
            ("new_mature_effective_components", 0),
        ):
            facts.append(
                FactValue(
                    name,
                    value,
                    "count",
                    FactStatus.AVAILABLE,
                    (evidence("coverage.json"), refs["04_conclusion.md"]),
                )
            )
        conclusion = "初步GVZ及有限美元验证完成，九条增量研究记录、新成熟有效收益组件0；高VIX/GVZ确认无支持，低比值和美元趋势仅保留线索；整体阶段二IN_PROGRESS。"
        return DeliveryContent(
            ComponentPanel(tuple(components), conclusion),
            DeliveryStatus.PARTIAL,
            tuple(facts),
            (
                Explanation(
                    ExplanationKind.RESEARCH_JUDGMENT,
                    conclusion,
                    supporting=(refs["04_conclusion.md"],),
                    contrary=(annual_ref, infer_ref),
                ),
                Explanation(
                    ExplanationKind.STATISTICAL_EVIDENCE,
                    "九项匹配增量区间均跨零；低比值年度和延迟反证、有限美元历史、重叠事件及选择历史共同披露，不以诊断新增经济硬门。",
                    supporting=(infer_ref, annual_ref, refs["04_conclusion.md"]),
                ),
                Explanation(
                    ExplanationKind.FACT,
                    "EX030保留排序局限，EX031明确最新可得观测；七个特征单元修正但信号和路径点估计未变，随机种子变化不视为研究改善。",
                    supporting=(
                        refs["protocol_inheritance_note.md"],
                        refs["preliminary_result_summary.json"],
                    ),
                ),
            ),
            ReproductionSpec(
                "仓库根运行本实验reproduction/verify.py核验原始输入、信号及全部路径；正式重跑须新建实验，不覆盖原回执。",
                (
                    refs["02_design.md"],
                    refs["protocol_inheritance_note.md"],
                    refs["experiment_binding.json"],
                ),
                "正式DFLS/REX输入与EX029/EX004前驱；保留data/research/S012及完整本地制品闭包。",
                "worker=1、native_threads=1、seed=12031；EX001—EX030均已见；未证明历史逐条发布时刻。",
            ),
            incomplete_items=(
                "本轮初步检验未形成成熟有效收益组件，整体阶段二仍进行中。",
                "美元2023年6月后缺数据，低比值线索须后继固定方向和跨状态归因；其余前轮资源缺口未接入。",
                "原完整账户三项经济目标未复验，阶段三须另获批准。",
            ),
            attachments=tuple(files),
        )
