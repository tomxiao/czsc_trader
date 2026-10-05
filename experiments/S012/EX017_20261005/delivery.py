"""S012 consolidated stage-two delivery draft; importing never publishes.

Historical component definitions and test outcomes stay bound to their original
experiments. Attachment paths and fact identifiers are namespaced in this new
delivery; historical experiment artifact paths keep the standard namespace.
"""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import (
    ComponentEntry,
    ComponentPanel,
    DeliveryContent,
    DeliveryDefinition,
    DeliveryReference,
    DeliveryStage,
    DeliveryStatus,
    EvidenceFile,
    EvidenceRef,
    ExperimentEvidenceRef,
    ExperimentEvidenceUse,
    ExperimentOwner,
    Explanation,
    ExplanationKind,
    FactValue,
    ReproductionSpec,
    ResearchDeliverable,
)


HISTORICAL_PANELS = (
    "EX005_20261004",
    "EX010_20261004",
    "EX014_20261005",
)
DEFAULT_OWNER = "EX017_20261005"


def _read(root: Path, name: str):
    return json.loads((root / name).read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _remap_record(value, attachment_paths, fact_ids):
    """Remap serialized typed records without altering historical measurements."""
    if isinstance(value, list):
        return [_remap_record(x, attachment_paths, fact_ids) for x in value]
    if not isinstance(value, dict):
        return value
    result = {k: _remap_record(v, attachment_paths, fact_ids) for k, v in value.items()}
    if result.get("type") == "EvidenceRef":
        old_path = result["path"]
        if old_path.startswith("attachments/"):
            result["path"] = attachment_paths[old_path]
        elif not old_path.startswith("experiments/"):
            raise ValueError(f"Unsupported inherited evidence namespace: {old_path}")
    if "fact_id" in result:
        result["fact_id"] = fact_ids[result["fact_id"]]
    if "fact_ids" in result:
        result["fact_ids"] = [fact_ids[x] for x in result["fact_ids"]]
    return result


def inherit_historical_panels(root: Path):
    """Return all 22 historical entries, facts, and resolvable attachments.

    Duplicate component IDs with different definitions are rejected, rather than
    silently replacing an older research judgment. No old result is recomputed.
    """
    root = root.resolve()
    components = {}
    facts = []
    attachments = []
    for eid in HISTORICAL_PANELS:
        base = f"experiments/S012/{eid}/deliveries/COMPONENTS/1"
        published = _read(root, base + "/delivery.json")
        content = published["content"]
        # Verify the existing typed payload first, before path transformation.
        ComponentPanel.from_dict(content["payload"])
        attachment_paths = {}
        for raw in content["attachments"]:
            attachment = EvidenceFile.from_dict(raw)
            old = attachment.reference
            source = f"{base}/{old.path}"
            if _digest(root / source) != old.sha256:
                raise ValueError(f"Historical attachment digest differs: {source}")
            destination = f"attachments/historical/{eid}/{old.path.removeprefix('attachments/')}"
            attachment_paths[old.path] = destination
            attachments.append(EvidenceFile(source, replace(old, path=destination)))
        fact_ids = {x["fact_id"]: f"{eid}__{x['fact_id']}" for x in content["facts"]}
        for raw in content["facts"]:
            facts.append(FactValue.from_dict(_remap_record(raw, attachment_paths, fact_ids)))
        panel = ComponentPanel.from_dict(
            _remap_record(content["payload"], attachment_paths, fact_ids)
        )
        for component in panel.components:
            prior = components.get(component.component_id)
            if prior is not None and prior != component:
                raise ValueError(f"Conflicting inherited component: {component.component_id}")
            components.setdefault(component.component_id, component)
    return tuple(components.values()), tuple(facts), tuple(attachments)


def historical_references(root: Path):
    return tuple(
        DeliveryReference.from_dict(
            _read(root, f"experiments/S012/{eid}/deliveries/COMPONENTS/1/receipt.json")["reference"]
        )
        for eid in HISTORICAL_PANELS
    )


def experiment_closure(root: Path, owner=DEFAULT_OWNER, current_experiments=None):
    """Recursively include declared delivery inputs and every receipt predecessor."""
    current = set(
        ("EX015_20261005", "EX016_20261005", owner)
        if current_experiments is None
        else current_experiments
    )
    refs = {}

    def visit(eid):
        if eid in refs:
            return
        path = f"experiments/S012/{eid}/artifacts/rex"
        receipt = _read(root, path + "/execution_receipt.json")
        refs[eid] = ExperimentEvidenceRef(
            eid,
            path,
            receipt["receipt_sha256"],
            ExperimentEvidenceUse.CURRENT_EVALUATION
            if eid in current
            else ExperimentEvidenceUse.HISTORICAL_REFERENCE,
        )
        for predecessor in receipt["predecessor_receipts"]:
            visit(predecessor)

    for eid in HISTORICAL_PANELS:
        old = _read(root, f"experiments/S012/{eid}/deliveries/COMPONENTS/1/delivery.json")
        for ref in old["definition"]["experiments"]:
            visit(ref["experiment_id"])
    for eid in sorted(current):
        visit(eid)
    return tuple(refs[eid] for eid in sorted(refs))


def attachment(root: Path, source: str, name: str, media="text/markdown"):
    return EvidenceFile(
        source,
        EvidenceRef(
            "attachments/current/" + name,
            _digest(root / source),
            media,
        ),
    )


def experiment_evidence(root: Path, eid: str, name: str, media="application/json"):
    return EvidenceRef(
        f"experiments/{eid}/{name}",
        _digest(root / f"experiments/S012/{eid}/artifacts/rex/{name}"),
        media,
    )


def verify_references(root: Path, components, facts, attachments):
    """Check inherited protocol/evidence hashes without publishing any files."""
    attachment_sources = {x.reference.path: x.source_path for x in attachments}

    def check(ref):
        if ref.path.startswith("attachments/"):
            source = attachment_sources[ref.path]
        elif ref.path.startswith("experiments/"):
            _, eid, name = ref.path.split("/", 2)
            source = f"experiments/S012/{eid}/artifacts/rex/{name}"
        else:
            raise ValueError(f"Unsupported reference: {ref.path}")
        if _digest(root / source) != ref.sha256:
            raise ValueError(f"Evidence digest differs: {source}")

    for item in attachments:
        check(item.reference)
    for component in components:
        definition = component.definition
        if definition.to_dict().get("type") == "ExperimentDefinitionRef":
            receipt = _read(
                root,
                (
                    f"experiments/S012/{definition.experiment_id}/artifacts/rex/"
                    "execution_receipt.json"
                ),
            )
            if (definition.definition_sha256, definition.source_sha256) != (
                receipt["definition_sha256"],
                receipt["source_sha256"],
            ):
                raise ValueError(f"Historical definition differs: {component.component_id}")
        for test in component.tests:
            check(test.protocol)
            for ref in test.evidence:
                check(ref)
    for fact in facts:
        for ref in fact.evidence:
            check(ref)


class ConsolidatedStageTwoDelivery(ResearchDeliverable[ComponentPanel]):
    """Caller supplies new findings and current attachments after sealing REX.

    Example: current attachments include owner protocol, consolidated report,
    exact user authorization, independent recomputation output, and source code.
    New test protocols must refer to one of these attachment references. Current
    result evidence uses experiment_evidence(...) and bound original definitions.
    """

    def __init__(
        self,
        root: Path,
        *,
        owner=DEFAULT_OWNER,
        current_experiments=("EX015_20261005", "EX016_20261005", "EX017_20261005"),
        new_components: tuple[ComponentEntry, ...],
        new_facts: tuple[FactValue, ...],
        current_attachments: tuple[EvidenceFile, ...],
        conclusion: str,
        current_protocol: EvidenceRef,
        current_report: EvidenceRef,
        extra_explanations: tuple[Explanation, ...] = (),
    ):
        self.root = root.resolve()
        self.owner = owner
        self.current_experiments = tuple(current_experiments)
        self.new_components = new_components
        self.new_facts = new_facts
        self.current_attachments = current_attachments
        self.conclusion = conclusion
        self.current_protocol = current_protocol
        self.current_report = current_report
        self.extra_explanations = extra_explanations

    @property
    def definition(self):
        return DeliveryDefinition(
            ExperimentOwner("S012", self.owner),
            DeliveryStage.COMPONENTS,
            1,
            predecessors=historical_references(self.root),
            experiments=experiment_closure(
                self.root,
                self.owner,
                self.current_experiments,
            ),
        )

    def build(self):
        old_components, old_facts, old_attachments = inherit_historical_panels(self.root)
        components = old_components + self.new_components
        facts = old_facts + self.new_facts
        attachments = old_attachments + self.current_attachments
        verify_references(self.root, components, facts, attachments)
        return DeliveryContent(
            ComponentPanel(components, self.conclusion),
            DeliveryStatus.COMPLETE,
            facts,
            (
                Explanation(
                    ExplanationKind.RESEARCH_JUDGMENT,
                    "历史组件沿用原始定义、协议和检验；本轮新增机会按新实验报告解释。历史风险指标未在本轮复算。",
                    supporting=(self.current_report,),
                ),
                Explanation(
                    ExplanationKind.RESEARCH_JUDGMENT,
                    "阶段二组件证据及机会密度用于后续账户方案设计；完整账户三项目标仍待独立验证。",
                    supporting=(self.current_report,),
                ),
            )
            + self.extra_explanations,
            ReproductionSpec(
                "按本轮固定协议执行预检、受管数据准备及REX，再复算关键事实并验证阶段二交付和档案。",
                (self.current_protocol,),
                "使用现有S012数据空间、原始前驱制品和现有依赖；历史附件完整保留。",
                "历史结果不改写；供应商修订、方法改变或新机制必须形成后继实验。",
            ),
            attachments=attachments,
        )


if __name__ == "__main__":
    # Read-only draft smoke check: current-round experiments need not exist yet.
    root = Path(__file__).resolve().parents[2]
    entries, inherited_facts, inherited_attachments = inherit_historical_panels(root)
    verify_references(root, entries, inherited_facts, inherited_attachments)
    closure = experiment_closure(root, current_experiments=())
    print(
        json.dumps(
            {
                "components": len(entries),
                "facts": len(inherited_facts),
                "attachments": len(inherited_attachments),
                "historical_experiment_closure": [x.experiment_id for x in closure],
                "component_ids": [x.component_id for x in entries],
                "status": "DRAFT_INHERITANCE_VERIFIED_NO_PUBLICATION",
            },
            ensure_ascii=False,
        )
    )
