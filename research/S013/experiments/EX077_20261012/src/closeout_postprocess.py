"""Fail-only single-centre draft. No calls before future exact root authority."""

from hashlib import sha256
import json
from pathlib import Path
import sys

from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

GATES = ("return", "annual_drawdown", "frequency", "negative_buyhold_year_profit")
MANDATE_SHA = "e2128159814ccf64784aa50588379e802a581d6e5867349069b0fb0fc751af46"
ROLES = {"centre_new": 1, "baseline_reused": 1, "standard_new": 0, "fee_new": 0, "technical_new": 0}
PRIMARY = ("plan.json", "native.json", "independent_audit.json", "root_review.json")


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def gate_decision(gates):
    if set(gates) != set(GATES) or any(type(value) is not bool for value in gates.values()):
        raise ValueError(
            "actual four complete strict Boolean gates required; unavailable is not fail"
        )
    return "CENTRE_QUALIFIED_WAIT_ROOT_32_FEE" if all(gates.values()) else "CENTRE_FAILED_STOP"


def build_payload(exp, review, audit, refs):
    """Pure typed construction. No result prefilled, candidate identity not hardcoded."""
    if exp.strategy_id != "S013" or not exp.experiment_id.startswith("EX077_"):
        raise ValueError("actual original EX077 metadata required; no hardcoded date")
    if gate_decision(audit["economics"]["gates"]) != "CENTRE_FAILED_STOP":
        raise PermissionError(
            "centre passed: root decides further validation before formal selection"
        )
    if audit["status"] != "PASS" or audit["independent_signal_state"] != "EXACT":
        raise ValueError("actual independent native audit required")
    if (
        audit["new_accounts"] != 1
        or audit["technical_financial_repeats"] != 0
        or review["financial_roles"] != ROLES
    ):
        raise ValueError("exact one new centre, one reused baseline; no extra financial runs")
    if (
        audit["references"]["centre"] != refs["native.json"]
        or audit["references"]["plan"] != refs["plan.json"]
    ):
        raise ValueError("audit must bind actual whole native publication")
    if review["status"] != "ROOT_SCIENTIFIC_REVIEWED" or review["objective_achieved"] is not False:
        raise ValueError("actual root scientific review; robust target remains unproved")
    if review["original_four_hard_gates_changed"] is not False:
        raise ValueError("no new economic gate or change")
    if review["economics"] != audit["economics"]:
        raise ValueError("review and actual audited economics differ")
    # Actual identity remains typed root-reviewed metadata, never C9077/C9078 literals.
    identity = d.CandidateIdentityRef.from_dict(review["candidate_identity"])
    if identity.key.candidate_id != audit["cash_account"]["candidate_id"]:
        raise ValueError("actual audited candidate ID differs")
    if review["whole_formal_native_exact"] is not True:
        raise ValueError("root must confirm audit's whole serialized public native equality")
    if audit["qualified"] is not False or audit["economics"]["qualified"] is not False:
        raise ValueError("failure qualification must agree with actual original four gates")
    if (
        audit["cash_account"]["quantity_reconciliation"] != "EXACT_EQUAL"
        or audit["orders_first_touch"]["status"] != "PASS"
    ):
        raise ValueError("native cash and first-touch audits required")
    for name in ("plan.json", "native.json", "independent_audit.json"):
        if review["evidence_references"][name] != refs[name]:
            raise ValueError(
                "root scientific review must bind actual prospective/native/audit refs"
            )
    native = EvidenceRef.from_dict(refs["native.json"])
    d.EvaluationEvidenceRef(native)
    all_refs = tuple(dict.fromkeys(EvidenceRef.from_dict(value) for value in refs.values()))
    summary = d.SearchSummary(
        exp.experiment_id + "-single-price-event-centre",
        "固定L20/k1单中心完整价格事件政策；原四门任一失败即停，无参数优化或救援",
        "原HFQ开发池/1million/每侧10bp/1%LimitBuyHold；新centre1；B0复用1仅比较，不计本轮搜索配置",
        1,
        1,
        review["conclusion"],
        (
            "原四门失败，新增合格集合为空、不登记；此前正式候选不被替代或删除",
            "只有一个新完整账户，未运行新32/双费；没有完整新五自检或抗扰动目标证明",
            "低先验与同一已见开发池选择偏差；状态简洁不是alpha证据",
            "完整L[2,120]/k[.25,4]两维声明不同于原13维；未运行标准扰动，不能逐点配对或声称更强稳健",
            "政策HELD/target是意图，实际fill/数量/费用/闭合交易依原生账本；无expiry或微仓刷频率",
        ),
        all_refs,
    )
    return d.CandidateSet((), (), (summary,), review["conclusion"])


def run(authority_path):
    work = Path(__file__).resolve().parent
    root = next(p for p in work.parents if (p / "pyproject.toml").exists())
    authority = read(authority_path)
    freeze = read(work / "freeze.json")
    if authority.get("status") != "APPROVED_EX077_FAILED_CENTRE_CLOSEOUT" or authority.get(
        "source_freeze_sha256"
    ) != digest(work / "freeze.json"):
        raise PermissionError("future exact root fail-only closeout authorization required")
    for name, expected in freeze["source_files"].items():
        if Path(name).name != name or digest(work / name) != expected:
            raise ValueError("closeout source changed")
    exp = ExperimentRef.from_dict(authority["experiment"])
    if ExperimentRef.from_dict(read(exp.resolve(root) / "experiment.json")) != exp:
        raise ValueError("actual allocated experiment metadata differs")
    refs = dict(authority["evidence_references"])
    if not set(PRIMARY).issubset(refs):
        raise ValueError("actual prospective/native/audit/root review refs required")
    paths = {}
    for name, value in refs.items():
        reference = EvidenceRef.from_dict(value)
        if reference.experiment.strategy_id != "S013":
            raise ValueError("only S013 public evidence")
        path = reference.resolve(root)
        if digest(path) != reference.sha256:
            raise ValueError("public evidence changed")
        paths[name] = path
    for name in PRIMARY:
        if EvidenceRef.from_dict(refs[name]).experiment != exp:
            raise ValueError("primary actual experiment reference differs")
    review, audit = read(paths["root_review.json"]), read(paths["independent_audit.json"])
    payload = build_payload(exp, review, audit, refs)
    plan = read(paths["plan.json"])
    if (
        refs["plan.json"] != authority["prospective_plan_reference"]
        or review["prospective_plan_sha256"] != refs["plan.json"]["sha256"]
    ):
        raise ValueError("actual reviewed prospective revision must bind exact public plan")
    actual_identity = d.CandidateIdentityRef.from_dict(review["candidate_identity"])
    if (
        plan["candidate_id"] != actual_identity.key.candidate_id
        or plan["content_sha256"] != actual_identity.content_sha256
    ):
        raise ValueError("actual prospective runtime identity differs; no fixed candidate ID")
    predecessor = d.DeliveryReference.from_dict(authority["mandate_reference"])
    if (
        predecessor.batch != d.ResearchBatchRef("S013")
        or predecessor.stage is not d.DeliveryStage.MANDATE
        or predecessor.revision != 6
        or predecessor.content_sha256 != MANDATE_SHA
    ):
        raise ValueError("sole exact MANDATE6 predecessor required")
    definition = d.DeliveryDefinition(
        d.ResearchBatchRef("S013"),
        d.DeliveryStage.CANDIDATES,
        authority["delivery_revision"],
        (predecessor,),
    )
    if (work / "formal_attempt.json").exists():
        raise ValueError("single formal attempt; no automatic retry")
    from czsc_trader.application import assemble_delivery, publish_evidence, validate_delivery
    from czsc_trader.research_tools import MaterialEvidenceWrite
    import importlib

    source = root / "research/S013/experiments/EX058_20261011/src/common.py"
    if digest(source) != "f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b":
        raise ValueError("original context helper changed")
    sys.path.insert(0, str(source.parent))
    common = importlib.import_module("common")
    if Path(common.__file__).resolve() != source.resolve():
        raise ValueError("different context helper")
    ctx = common.context(1)
    write_new(
        work / "formal_attempt.json",
        {"experiment": exp.to_dict(), "financial_roles": ROLES, "new_accounts_in_closeout": 0},
    )
    # Caller must launch with require_escalated from the FIRST local os.link publication.
    for path in (
        work / "postprocess.py",
        work / "checks.py",
        work / "checks.json",
        work / "freeze.json",
        Path(authority_path),
    ):
        refs["closeout_" + path.name] = publish_evidence(
            ctx,
            MaterialEvidenceWrite(
                exp,
                "price-event-closeout-" + path.stem,
                path.read_bytes(),
                "text/x-python" if path.suffix == ".py" else "application/json",
                path.suffix[1:],
            ),
        ).to_dict()
    links = "\n\n" + "".join(
        f"- [{name}]({EvidenceRef.from_dict(value).path})\n" for name, value in refs.items()
    )
    content = d.DeliveryContent(
        payload,
        d.DeliveryStatus.COMPLETE,
        (),
        (),
        report=review["report_markdown"] + links,
        evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(value) for value in refs.values())),
    )
    receipt = assemble_delivery(ctx.repository, definition, content)
    protocols = exp.resolve(root) / "protocols"
    write_new(protocols / "delivery_reference.json", receipt.reference.to_dict())
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    write_new(protocols / "delivery_validation.json", validation.to_dict())
    write_new(protocols / "closeout_references.json", refs)
    if validation.status is not d.ValidationStatus.PASS:
        raise RuntimeError("FULL failed; retain attempt, no retry")
    print(
        {
            "experiment": exp.experiment_id,
            "delivery": receipt.reference.to_dict(),
            "FULL": "PASS",
            "new_accounts": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    run(sys.argv[1])
