from pathlib import Path
from hashlib import sha256
import json
from research_experiment import load_experiment_input
from czsc_trader.application import RepositoryContext, assemble_delivery, validate_delivery
import czsc_trader.research_tools as d

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def attach(path, name=None):
    media = "application/json" if path.suffix == ".json" else "application/octet-stream"
    return d.EvidenceFile(
        path.relative_to(REPO).as_posix(),
        d.EvidenceRef(
            "attachments/" + (name or path.name), sha256(path.read_bytes()).hexdigest(), media
        ),
    )


def closure(names):
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
        for prior in receipt["predecessor_receipts"]:
            visit(prior)

    for name in names:
        visit(name)
    return tuple(refs[name] for name in sorted(refs))


class Deliverable(d.ResearchDeliverable):
    def __init__(self, definition, content):
        self._definition, self.content = definition, content

    @property
    def definition(self):
        return self._definition

    def build(self):
        return self.content


def publish():
    inputs = read(ROOT / "inputs.json")
    context = RepositoryContext.discover(REPO)
    mandate = d.DeliveryReceipt.from_dict(read(REPO / inputs["mandate_receipt"])).reference
    components = d.DeliveryReceipt.from_dict(read(REPO / inputs["component_receipt"])).reference
    old = read(REPO / inputs["historical_delivery"])["content"]
    source = (REPO / inputs["historical_delivery"]).parent
    attachments = []
    for item in old["attachments"]:
        if Path(item["reference"]["path"]).name not in {
            "historical_573_evaluations.csv", "historical_failures.json", "historical_proposal_inheritance.json",
            "historical_search_extension.json", "historical_stage3.json", "historical_stage3_summary.json", "historical_trial_events.parquet",
        }:
            continue
        ref = d.EvidenceRef.from_dict(item["reference"])
        path = source / ref.path
        assert sha256(path.read_bytes()).hexdigest() == ref.sha256
        attachments.append(attach(path, "historical_" + path.name))
    for name in ("candidate_set.json", "identity_mapping.json", "center_summary.json"):
        write(ROOT / name, read(ROOT / "artifacts" / name))
        attachments.append(attach(ROOT / name))
    attachments.extend(
        (
            
            attach(ROOT / "publication.py", "current_publication.py"),
        )
    )
    content = d.DeliveryContent(
        d.CandidateSet.from_dict(read(ROOT / "candidate_set.json")),
        d.DeliveryStatus.COMPLETE,
        (),
        (
            d.Explanation(
                d.ExplanationKind.RESEARCH_JUDGMENT,
                "36中心覆盖完整，当前ID、内容哈希和标准评价逐个绑定。历史优化轨迹与失败提议原文保留；本轮仅做固定复算。全部结果属于已见开发池；历史选择偏差及复权数据历史发布时间未核实继续披露。",
            ),
        ),
        d.ReproductionSpec(
            "以当前公共API validate_delivery验证；使用本实验声明的固定输入与受管执行入口。",
            (),
            "原授权DFLS数据范围，2025-02-06至2026-09-28；阶段二引用原有效交付。",
            "固定参数与内容身份；保留原历史搜索计数，不增加独立样本。",
        ),
        (),
        tuple(attachments),
    )
    definition = d.DeliveryDefinition(
        d.ExperimentOwner("S011", ROOT.name),
        d.DeliveryStage.CANDIDATES,
        1,
        (mandate, components),
        closure((ROOT.name,)),
    )
    receipt = assemble_delivery(context, Deliverable(definition, content))
    checked = validate_delivery(context, receipt.reference)
    assert checked.status is d.ValidationStatus.PASS, checked
    write(ROOT / "candidates_receipt.json", receipt.to_dict())
    write(ROOT / "delivery_validation.json", checked.to_dict())
    return receipt
