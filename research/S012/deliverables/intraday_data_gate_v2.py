"""Incremental data-gate delivery. Prior opportunity panel remains in EX010."""
import json
from pathlib import Path
from hashlib import sha256
from czsc_trader.research_tools import (
    ComponentPanel, DeliveryContent, DeliveryDefinition, DeliveryReference,
    DeliveryStage, DeliveryStatus, EvidenceFile, EvidenceRef, ExperimentEvidenceRef,
    ExperimentEvidenceUse, ExperimentOwner, Explanation, ExplanationKind,
    FactStatus, FactValue, ReproductionSpec, ResearchDeliverable,
)


class IntradayDataGate(ResearchDeliverable[ComponentPanel]):
    def __init__(self, root: Path):
        self.root = root

    def read(self, path):
        return json.loads((self.root / path).read_text(encoding="utf-8"))

    @property
    def definition(self):
        prior = self.read("research/S012/materials/components_opportunities_v2_validation.json")["reference"]
        experiments = []
        for eid in ("EX001_20261004", "EX003_20261004", "EX004_20261004", "EX005_20261004",
                    "EX006_20261004", "EX007_20261004", "EX008_20261004", "EX010_20261004", "EX011_20261004", "EX012_20261004"):
            path = f"experiments/S012/{eid}/artifacts/rex"
            receipt = self.read(path + "/execution_receipt.json")
            experiments.append(ExperimentEvidenceRef(eid, path, receipt["receipt_sha256"],
                ExperimentEvidenceUse.CURRENT_EVALUATION if eid == "EX012_20261004"
                else ExperimentEvidenceUse.HISTORICAL_REFERENCE))
        return DeliveryDefinition(ExperimentOwner("S012", "EX012_20261004"), DeliveryStage.COMPONENTS, 1,
            predecessors=(DeliveryReference.from_dict(prior),), experiments=tuple(experiments))

    def build(self):
        base = "experiments/S012/EX012_20261004/"
        def attach(source, name, media="application/json"):
            return EvidenceFile(source, EvidenceRef("attachments/" + name,
                sha256((self.root / source).read_bytes()).hexdigest(), media))
        attachments = (
            attach(base + "02_design.md", "protocol.md", "text/markdown"),
            attach(base + "04_conclusion.md", "research_report.md", "text/markdown"),
            attach("research/S012/materials/intraday_scope_confirmation_20261004.json", "scope.json"),
            attach("research/S012/materials/intraday_authorization_20261004.json", "authorization.json"),
            attach(base + "artifacts/dev_diagnostic_summary.json", "dev_diagnostic_summary.json"),
            attach("research/S012/deliverables/intraday_data_gate_v2.py", "delivery_implementation.py", "text/x-python"),
        )
        path = base + "artifacts/rex/data_audit.json"
        audit = self.read(path)
        evidence = EvidenceRef("experiments/EX012_20261004/data_audit.json",
                               sha256((self.root / path).read_bytes()).hexdigest(), "application/json")
        ready = audit["target_full"]["status"] == "READY"
        assert not ready, "Changed source outcome requires a fresh research interpretation"
        facts = (
            FactValue("target_full_history_ready", False, "boolean", FactStatus.AVAILABLE, (evidence,)),
            FactValue("peer_full_history_ready", audit["peer_full"]["status"] == "READY", "boolean", FactStatus.AVAILABLE, (evidence,)),
            FactValue("return_paths", 0, "count", FactStatus.AVAILABLE, (evidence,)),
        )
        return DeliveryContent(
            ComponentPanel((), "本轮为EX010后继数据门补充。原组件面板保持EX010；全历史目标分钟价格冲突未解决，未新增日内收益组件。"),
            DeliveryStatus.BLOCKED, facts, (
                Explanation(ExplanationKind.FACT, "目标全历史分钟请求仍失败；已核验7日成交量修复。", ("target_full_history_ready",), supporting=(evidence,)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "遵照用户要求，完整历史通过前暂停收益检验；不能以日线值覆盖分钟路径后的一致性作为独立真值证据。", supporting=(attachments[2].reference, attachments[4].reference)),
                Explanation(ExplanationKind.FACT, "AvailableDate是明确的市场观察假设，历史API逐条发布时间及实时延迟未验证。", supporting=(evidence,)),
            ), ReproductionSpec(
                "核验EX011及前驱；新数据快照或修复通过后创建后继实验复验完整历史，不覆盖本实验。",
                (attachments[0].reference,), "受管输入为DFLS/Tushare；DEV原始诊断保存在本机artifacts/dev_source_support，未用于收益计算。",
                "身份与文件哈希严格；供应商修订需重新留证。"),
            incomplete_items=("解决目标ETF全历史分钟价格冲突，并复验完整覆盖。", "期货分钟权限缺失，真实实时数据可得性待核验。", "尚未进行新增日内机会收益检验。"),
            attachments=attachments,
        )
