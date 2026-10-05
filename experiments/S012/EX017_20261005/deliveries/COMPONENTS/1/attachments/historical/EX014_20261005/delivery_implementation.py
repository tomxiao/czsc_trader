"""Incremental stage-two mechanism publication; prior panel stays immutable."""
from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment
from czsc_trader.research_tools import (
    ComponentPanel, ComponentEntry, ComponentTestResult, ComponentTestStatus,
    ExperimentDefinitionRef, DeliveryContent, DeliveryDefinition, DeliveryReference,
    DeliveryStage, DeliveryStatus, EvidenceFile, EvidenceRef, ExperimentEvidenceRef,
    ExperimentEvidenceUse, ExperimentOwner, Explanation, ExplanationKind,
    FactStatus, FactValue, ReproductionSpec, ResearchDeliverable,
)


class RelativeLagDelivery(ResearchDeliverable[ComponentPanel]):
    def __init__(self, root: Path):
        self.root = root

    def read(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    @property
    def definition(self):
        refs = {}
        def visit(eid):
            if eid in refs:
                return
            path = f"experiments/S012/{eid}/artifacts/rex"
            receipt = self.read(path + "/execution_receipt.json")
            refs[eid] = ExperimentEvidenceRef(eid, path, receipt["receipt_sha256"],
                ExperimentEvidenceUse.CURRENT_EVALUATION if eid == "EX014_20261005"
                else ExperimentEvidenceUse.HISTORICAL_REFERENCE)
            for prior in receipt["predecessor_receipts"]:
                visit(prior)
        visit("EX014_20261005")
        prior = self.read("experiments/S012/EX010_20261004/deliveries/COMPONENTS/1/receipt.json")["reference"]
        return DeliveryDefinition(ExperimentOwner("S012", "EX014_20261005"), DeliveryStage.COMPONENTS, 1,
            predecessors=(DeliveryReference.from_dict(prior),), experiments=tuple(refs[e] for e in sorted(refs)))

    def build(self):
        base = "experiments/S012/EX014_20261005/"
        def attachment(source, name, media="text/markdown"):
            return EvidenceFile(source, EvidenceRef("attachments/" + name,
                sha256((self.root / source).read_bytes()).hexdigest(), media))
        attachments = (
            attachment(base + "02_design.md", "protocol.md"),
            attachment(base + "04_conclusion.md", "research_report.md"),
            attachment(base + "delivery.py", "delivery_implementation.py", "text/x-python"),
            attachment("research/S012/materials/resume_authorization_20261005.json", "authorization.json", "application/json"),
        )
        def evidence(name, media="application/json"):
            path = base + "artifacts/rex/" + name
            return EvidenceRef("experiments/EX014_20261005/" + name,
                sha256((self.root / path).read_bytes()).hexdigest(), media)
        audit = self.read(base + "artifacts/rex/data_audit.json")
        ready = all(v["ready"] for v in audit.values())
        facts = [FactValue("inputs_ready", ready, "boolean", FactStatus.AVAILABLE, (evidence("data_audit.json"),))]
        components = ()
        if ready:
            rows = self.read(base + "artifacts/rex/opportunities.json")
            main = next(r for r in rows if r["signal"] == "event" and r["horizon"] == 3 and r["sensitivity"] == "all")
            clean = next(r for r in rows if r["signal"] == "event" and r["horizon"] == 3 and r["sensitivity"] != "all")
            for key, value in (("main_events", main["events"]), ("main_net_mean", main["net_mean"]),
                               ("main_increment", main["year_matched_excess"]),
                               ("clean_increment", clean["year_matched_excess"]),
                               ("limit_capacity", main["limit_fills_per60"])):
                facts.append(FactValue(key, value, "count" if key == "main_events" else "ratio",
                    FactStatus.AVAILABLE if value is not None else FactStatus.INSUFFICIENT_DATA,
                    (evidence("opportunities.json"),), None if value is not None else "事件不足"))
            loaded = load_experiment(self.root / base)
            definition = ExperimentDefinitionRef("EX014_20261005", loaded.definition.sha256,
                                                  loaded.binding.source_sha256, "mechanism.features")
            nonpositive = main["year_matched_excess"] is not None and main["year_matched_excess"] <= 0
            flipped = (main["year_matched_excess"] is not None and main["year_matched_excess"] > 0
                       and clean["year_matched_excess"] is not None and clean["year_matched_excess"] <= 0)
            rejected = nonpositive or flipped
            judgment = ("主路径费用后增量或异常敏感性未支持机制；保留负面证据。" if rejected
                        else "单轮开发诊断，正增量仍需更多独立机会与稳健性证据。")
            test = ComponentTestResult("RELATIVE_LAG_3D", "EX014_20261005", attachments[0].reference,
                ComponentTestStatus.INEFFECTIVE if rejected else ComponentTestStatus.INSUFFICIENT_DATA,
                judgment, (evidence("opportunities.json"), evidence("annual.json"), evidence("feature_coverage.json")),
                ("main_events", "main_increment", "clean_increment", "limit_capacity"))
            components = (ComponentEntry("O02_LAST_HOUR_RELATIVE_LAG", definition,
                "机会机制诊断", "T+1至T+4开盘净收益", "3交易日；1/5日诊断",
                "年度毛收益基线、绝对下跌事件、O01及并集",
                "T日17:00观察，T+1执行；历史API发布未验证",
                "不复权实际价格；分钟仅同步14:00 Close与日线收盘",
                "全上市开发池；只做多、各侧0.1%费用；异常敏感性预声明",
                judgment, (test,)),)
        return DeliveryContent(
            ComponentPanel(components, "EX010原机会面板保留；本轮只交付独立相对落后机制增量，阶段二继续，未进入阶段三。"),
            DeliveryStatus.COMPLETE if ready else DeliveryStatus.BLOCKED, tuple(facts), (
                Explanation(ExplanationKind.FACT, "所有收益研究前先检查目标与参考全历史数据准备。", ("inputs_ready",), supporting=(evidence("data_audit.json"),)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "事件收益与日线触价不能代替完整账户目标或真实成交验证。", supporting=(attachments[1].reference,)),
            ), ReproductionSpec("按固定协议执行预检、受管prepare/fetch和REX执行，再验证本次交付及档案。",
                (attachments[0].reference,), "既有Tushare；保留S012数据空间及全部前驱制品。", "源码、定义、输入及回执绑定；供应商修订创建后继实验。"),
            incomplete_items=() if ready else ("参考或目标数据门未通过，停止本轮收益检验。",), attachments=attachments)
