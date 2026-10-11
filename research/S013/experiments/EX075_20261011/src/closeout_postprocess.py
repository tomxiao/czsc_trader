"""EX075 COMPONENTS11 source-only draft; main requires separate exact authority."""

from hashlib import sha256
import json
from pathlib import Path
import sys

from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

EXPERIMENT = ExperimentRef("S013", "EX075_20261011")
PLAN_SHA = "c213535e04d7a9289132cbf02961e0ebbe80e2d6c17348698847132bed88d1da"
MANDATE_SHA = "e2128159814ccf64784aa50588379e802a581d6e5867349069b0fb0fc751af46"
LABELS = ("return4_net", "downside4_oc")


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def evidence(root, value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("S013-only immutable evidence required")
    path = ref.resolve(root)
    if digest(path) != ref.sha256:
        raise ValueError("evidence content hash mismatch")
    return ref, path


def build_payload(review, refs):
    """Pure typed assembly: no evidence resolve, statistics or publication."""
    if set(review["roles"]) != set(LABELS):
        raise ValueError("exactly two independently reviewed label roles required")
    if review["objective_achieved"] is not False or review["new_accounts"] != 0:
        raise ValueError("component-only evidence cannot prove financial target")
    if review["original_four_hard_gates_changed"] is not False:
        raise ValueError("original four financial gates remain unchanged")
    tests = tuple(
        d.ComponentTestResult(
            "DOWN-VOLUME-COV-" + label.upper(),
            EXPERIMENT.experiment_id,
            EvidenceRef.from_dict(refs["plan.json"]),
            d.ComponentTestStatus(review["roles"][label]["status"]),
            review["roles"][label]["judgment"],
            tuple(
                EvidenceRef.from_dict(refs[name])
                for name in ("statistics.json", "verification.json", "root_review.json")
            ),
        )
        for label in LABELS
    )
    entry = d.ComponentEntry(
        "DOWN-VOLUME-BODY-COVARIANCE",
        d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs["component_draft.py"]), "features"),
        "当日成交量是否集中在自身负实体bar；收益与风险用途分别评审",
        "4日固定两侧10bp净收益；OPEN/CLOSE观察下行风险，两者独立判断",
        "T+1 OPEN至T+5 OPEN；风险观察T+1..T+4 O/C与T+5 OPEN",
        "18固定控制；raw/partial Spearman、500x40全日历bootstrap；年度成熟训练 controls18 vs18+x及pastmean，五相位，禁止优化",
        "T完整8根30m O/C/V于T17可得；过去20日量时钟profile严格shift1，无缺失兜底；不独立证明历史发布时间",
        "原授权510500 HFQ后复权研究价格及认证anchor；标签理想OPEN并扣两侧10bp，非1%限价账户；原四门保持，0账户",
        "完整原开发日历；成交量非卖方流，负实体遗漏bar间/隔夜变化；非实际交易、账户回撤或自检达标证据；保留2022/2023、薄样本与开发选择偏差",
        review["judgment"],
        tests,
    )
    return d.ComponentPanel((entry,), review["judgment"])


def report_links(refs):
    return "\n\n正式证据：\n\n" + "".join(
        f"- [{name}]({EvidenceRef.from_dict(value).path})\n" for name, value in refs.items()
    )


def run(authority_path):
    """One separately authorized formal closeout, no accounts or stats."""
    work = Path(__file__).resolve().parent
    root = next(p for p in work.parents if (p / "pyproject.toml").exists())
    approval = read(authority_path)
    freeze = read(work / "freeze.json")
    if (
        approval.get("status") != "APPROVED_EX075_COMPONENTS11_CLOSEOUT"
        or approval.get("source_freeze_sha256") != digest(work / "freeze.json")
        or approval.get("experiment") != EXPERIMENT.to_dict()
    ):
        raise PermissionError("separate exact root closeout authorization required")
    for name, expected in freeze["source_files"].items():
        if Path(name).name != name or digest(work / name) != expected:
            raise ValueError("closeout source changed or illegal path")
    if (work / "formal_attempt.json").exists():
        raise ValueError("single formal attempt; root handles any recovery")
    refs = dict(approval["evidence_references"])
    required = {
        "plan.json",
        "statistics.json",
        "verification.json",
        "root_review.json",
        "component_draft.py",
    }
    if not required.issubset(refs):
        raise ValueError("actual plan/statistics/verification/review/source refs required")
    paths = {name: evidence(root, value)[1] for name, value in refs.items()}
    if refs["plan.json"]["sha256"] != PLAN_SHA:
        raise ValueError("original EX075 prospective plan changed")
    for name in required:
        if EvidenceRef.from_dict(refs[name]).experiment != EXPERIMENT:
            raise ValueError("actual EX075 primary evidence required")
    plan = read(paths["plan.json"])
    predecessors = tuple(d.DeliveryReference.from_dict(x) for x in plan["predecessors"])
    if len(predecessors) != 1 or (
        predecessors[0].stage != d.DeliveryStage.MANDATE
        or predecessors[0].batch != d.ResearchBatchRef("S013")
        or predecessors[0].revision != 6
        or predecessors[0].content_sha256 != MANDATE_SHA
    ):
        raise ValueError("MANDATE6 sole exact predecessor required")
    review = read(paths["root_review.json"])
    if review["status"] != "ROOT_SCIENTIFIC_REVIEWED":
        raise ValueError("actual root scientific review required")
    for name in ("plan.json", "statistics.json", "verification.json"):
        if review["evidence_references"][name] != refs[name]:
            raise ValueError("root review must bind actual evidence exactly")
    if read(paths["verification.json"])["status"] != "PASS":
        raise ValueError("independent actual statistics/input verification required")
    panel = build_payload(review, refs)
    definition = d.DeliveryDefinition(
        d.ResearchBatchRef("S013"), d.DeliveryStage.COMPONENTS, 11, predecessors
    )
    # Imports are intentionally after exact authority and all pre-mutation guards.
    from czsc_trader.application import assemble_delivery, publish_evidence, validate_delivery
    from czsc_trader.research_tools import MaterialEvidenceWrite
    import importlib

    common_source = root / "research/S013/experiments/EX058_20261011/src/common.py"
    if digest(common_source) != "f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b":
        raise ValueError("original authorized context helper changed")
    sys.path.insert(0, str(common_source.parent))
    common = importlib.import_module("common")
    if Path(common.__file__).resolve() != common_source.resolve():
        raise ValueError("different common module already imported")
    ctx = common.context(1)
    write_new(
        work / "formal_attempt.json",
        {"experiment": EXPERIMENT.to_dict(), "new_accounts": 0, "statistics_runs": 0},
    )
    for name in ("postprocess.py", "checks.py", "checks.json", "freeze.json"):
        path = work / name
        refs["closeout_" + name] = publish_evidence(
            ctx,
            MaterialEvidenceWrite(
                EXPERIMENT,
                "closeout-" + path.stem,
                path.read_bytes(),
                "text/x-python" if path.suffix == ".py" else "application/json",
                path.suffix[1:],
            ),
        ).to_dict()
    refs["root_closeout_authorization.json"] = publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            EXPERIMENT,
            "root-closeout-authorization",
            Path(authority_path).read_bytes(),
            "application/json",
            "json",
        ),
    ).to_dict()
    receipt = assemble_delivery(
        ctx.repository,
        definition,
        d.DeliveryContent(
            panel,
            d.DeliveryStatus.COMPLETE,
            (),
            (),
            report=review["report_markdown"] + report_links(refs),
            evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in refs.values())),
        ),
    )
    protocols = EXPERIMENT.resolve(root) / "protocols"
    write_new(protocols / "delivery_reference.json", receipt.reference.to_dict())
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    write_new(protocols / "delivery_validation.json", validation.to_dict())
    write_new(protocols / "closeout_references.json", refs)
    if validation.status.value != "PASS":
        raise RuntimeError(validation.to_dict())
    print(
        {
            "experiment": EXPERIMENT.experiment_id,
            "COMPONENTS": 11,
            "FULL": "PASS",
            "new_accounts": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    run(sys.argv[1])
