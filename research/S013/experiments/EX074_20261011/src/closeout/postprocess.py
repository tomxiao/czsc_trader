"""EX074 Candidate59 -> Candidate60 closeout; explicit root approval required.

No financial evaluation or preparation API. Scientific conclusions come from
the exact public root review, separately from original-four-gate eligibility.
"""

from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from czsc_trader.application import (
    CandidateRegistrationRequest,
    assemble_delivery,
    load_candidate,
    publish_evidence,
    register_candidate,
    validate_delivery,
)
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as api
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from strategy_evaluator import AssessmentPanel
from strategy_manager import CandidateDerivationKind, CandidateKey

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-pressure-early-exit"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def refs_in(value):
    if isinstance(value, dict):
        if value.get("type") == "EvidenceRef":
            yield EvidenceRef.from_dict(value)
        else:
            for x in value.values():
                yield from refs_in(x)
    elif isinstance(value, (tuple, list)):
        for x in value:
            yield from refs_in(x)


def run(reviewref, expected_sha):
    if digest(__file__) != expected_sha:
        raise ValueError("Root-reviewed closeout source drift")
    authority = read(WORK / "closeout/root_execution_authorization.json")
    if (
        authority.get("status") != "APPROVED_EX074_CANDIDATE60_CLOSEOUT"
        or authority.get("source_sha256") != expected_sha
        or authority.get("root_review_reference") != reviewref.to_dict()
    ):
        raise ValueError("Exact root closeout authorization required")
    if (reviewref.experiment.strategy_id, reviewref.experiment.experiment_id) != (
        "S013",
        "EX074_20261011",
    ):
        raise ValueError("Root review must belong to EX074")
    review = read(reviewref.resolve(ROOT))
    sys.path.insert(0, str(WORK / "standard"))
    import perturbation_driver as p

    d = p.d
    ctx, exp, path, common, state, method, requests, fee, auditor = p.stage()
    if state["status"] != "FINANCIAL34_COMPLETE" or set(state["accounts"]) != {
        *(f"P{i:02}" for i in range(32)),
        "FEE",
    }:
        raise ValueError("Exact complete standard32+fee actual roles required")
    analysis_ref = EvidenceRef.from_dict(read(path / "protocols/analysis_reference.json"))
    if (
        review.get("status") != "ROOT_SCIENTIFIC_REVIEWED"
        or review.get("analysis_reference") != analysis_ref.to_dict()
        or review.get("analysis_sha256") != analysis_ref.sha256
        or not isinstance(review.get("objective_achieved"), bool)
        or not isinstance(review.get("selection_summary"), str)
        or not review["selection_summary"].strip()
        or not isinstance(review.get("report_markdown"), str)
        or not review["report_markdown"].strip()
    ):
        raise ValueError(
            "Exact complete public analysis and explicit root scientific conclusion required"
        )
    analysis = read(analysis_ref.resolve(ROOT))
    counts = {
        "new_centre": 1,
        "new_standard32": 32,
        "new_fee": 1,
        "new_integer_neighbours": 0,
        "new_financial_total": 34,
        "new_technical_financial": 0,
        "baseline_reuse_standard": 33,
        "baseline_reuse_fee": 1,
        "all_native_accounts_including_reuse": 68,
    }
    if analysis["status"] != "COMPLETE" or analysis["counts"] != counts:
        raise ValueError("Finite34 new+34 readonly reused budget required")
    if (
        analysis["comparison"]["paired_geometry"] is not False
        or analysis["comparison"]["new_dimensions"] != 15
        or analysis["comparison"]["baseline_dimensions"] != 13
    ):
        raise ValueError("Own-standard15D/13D descriptive comparison required")
    if analysis["integer_coverage"] != {
        "pressure_exit.lookback": {"4": 32},
        "pressure_exit.early_hold_cap": {"2": 12, "1": 11, "3": 7, "4": 2},
    }:
        raise ValueError("Actual integer coverage disclosure differs")
    if set(analysis["fivechecks"]) != {"B0", "N_PRESSURE_EARLY_EXIT"}:
        raise ValueError("Both latest fivecheck panels required")
    for x in analysis["fivechecks"].values():
        AssessmentPanel.from_dict(x["panel"]).validate()
    baseline_ref = EvidenceRef.from_dict(
        read(path / "protocols/baseline_selfchecks_reference.json")
    )
    baseline = read(baseline_ref.resolve(ROOT))
    if (
        baseline["status"] != "PASS"
        or baseline["actual_new_accounts"] != 0
        or baseline["baseline_reused_standard"] != 33
        or baseline["baseline_reused_fee"] != 1
        or len(baseline["audits"]) != 33
    ):
        raise ValueError("Readonly old34 completeness required")
    AssessmentPanel.from_dict(baseline["panel"]).validate()
    if (
        baseline["panel"] != analysis["fivechecks"]["B0"]["panel"]
        or baseline["economics"] != analysis["fivechecks"]["B0"]["economics"]
    ):
        raise ValueError("Actual baseline latest diagnostics differ from analysis")
    if [x["native_reference"] for x in baseline["audits"]] != [
        x["reference"]
        for x in [method["baseline_reuse"]["center"], *method["baseline_reuse"]["points"]]
    ] or baseline["fee_audit"]["native_reference"] != method["baseline_fee_reuse"]["reference"]:
        raise ValueError("Actual baseline reference roles differ")
    for x in [*baseline["audits"], baseline["fee_audit"]]:
        if x["status"] != "PASS" or x["whole_formal_native_exact"] is not True:
            raise ValueError("Baseline whole native audit failed")
    refs = {}

    def add(ref):
        if ref.experiment.strategy_id != "S013":
            raise ValueError("Only S013 evidence allowed")
        ref.resolve(ROOT)
        refs[ref.repository_path] = ref

    add(reviewref)
    add(analysis_ref)
    add(baseline_ref)
    for doc in [analysis, baseline, method]:
        for ref in refs_in(doc):
            add(ref)
    for q in (path / "protocols").glob("*.json"):
        for ref in refs_in(read(q)):
            add(ref)
    for label, item in state["accounts"].items():
        if item["status"] != "AUDITED" or digest(ROOT / item["cache"]) != item["cache_sha256"]:
            raise ValueError("Native cache/audit role failed: " + label)
        pair = common.cache_read(ROOT / item["cache"])
        expected_request = fee if label == "FEE" else requests[int(label[1:])]
        if (
            pair[0].strategy.candidate_id != expected_request.strategy.candidate_id
            or p.spec.plain(pair[0].strategy.payload)
            != p.spec.plain(expected_request.strategy.payload)
            or pair[0].lineage != expected_request.lineage
            or pair[0].costs != expected_request.costs
        ):
            raise ValueError("Actual native account role differs from declared request: " + label)
        ref = EvidenceRef.from_dict(item["reference"])
        if serialize_evaluation_evidence(*pair) != read(ref.resolve(ROOT)):
            raise ValueError("Whole public native differs: " + label)
        proof = read(EvidenceRef.from_dict(item["audit_reference"]).resolve(ROOT))
        if proof["status"] != "PASS" or proof["whole_formal_native_exact"] is not True:
            raise ValueError("Whole public native audit failed: " + label)
    complete = read(WORK / "execution_complete.json")
    if digest(WORK / "centre.pkl.gz") != complete["cache_sha256"]:
        raise ValueError("Centre cache identity drift")
    centre = common.cache_read(WORK / "centre.pkl.gz")
    if (
        centre[0].strategy.candidate_id != "C9074"
        or centre[1].request_hash != complete["request_hash"]
        or centre[1].result_hash != complete["result_hash"]
    ):
        raise ValueError("Exact centre candidate/request/result identity required")
    centre_ref = EvidenceRef.from_dict(read(path / "protocols/centre_reference.json"))
    if serialize_evaluation_evidence(*centre) != read(centre_ref.resolve(ROOT)):
        raise ValueError("Whole centre public native differs")
    proof = read(
        EvidenceRef.from_dict(
            read(path / "protocols/result_references.json")["verification"]
        ).resolve(ROOT)
    )
    econ = analysis["rows"]["N_PRESSURE_EARLY_EXIT"]["center"]
    if (
        proof["status"] != "PASS"
        or proof["whole_formal_native_exact"] is not True
        or proof["economics"] != econ
        or not econ["qualified"]
        or not all(econ["gates"].values())
    ):
        raise ValueError("Original-four-qualified complete centre audit required")
    derivation = centre[0].lineage.derivation
    if (
        derivation.kind is not CandidateDerivationKind.IMPLEMENTATION
        or derivation.parent != CandidateKey("S013", "C8880")
        or derivation.child != CandidateKey("S013", "C9074")
    ):
        raise ValueError("Exact implementation C8880 -> C9074 lineage required")
    predecessors = tuple(
        api.DeliveryReference.from_dict(
            read(ROOT / f"research/S013/assets/deliveries/{stage}/{revision}/receipt.json")[
                "reference"
            ]
        )
        for stage, revision in (("MANDATE", 6), ("CANDIDATES", 59), ("COMPONENTS", 10))
    )
    for ref in predecessors:
        if (
            validate_delivery(
                ctx.repository, ref, scope=api.DeliveryValidationScope.INTEGRITY
            ).status
            is not api.ValidationStatus.PASS
        ):
            raise ValueError("Declared predecessor integrity failed")
    previous = api.DeliveryContent.from_dict(
        read(ROOT / "research/S013/assets/deliveries/CANDIDATES/59/delivery.json")["content"]
    ).payload
    if CandidateKey("S013", "C9074") in {x.identity.key for x in previous.candidates}:
        raise ValueError("Centre already present in predecessor")
    for x in previous.candidates:
        for evaluation in x.evaluations:
            add(EvidenceRef.from_dict(evaluation.evidence.to_dict()))
    out = WORK / "formal-closeout"
    if out.exists():
        raise ValueError("Prior formal attempt must be preserved; no implicit replay")
    out.mkdir()
    registration = register_candidate(
        ctx.repository,
        CandidateRegistrationRequest(
            centre[0].strategy, exp, (centre_ref,), centre[0].dependencies, derivation
        ),
    )
    if (
        ctx.runtime.identify(
            load_candidate(ctx.repository, registration.key), dependencies=centre[0].dependencies
        ).content_sha256
        != econ["candidate"]["content_sha256"]
    ):
        raise ValueError("Registered centre content identity differs")
    d.write(out / "registration.json", registration.to_dict())
    manifest = {
        "status": "PASS",
        "counts": counts,
        "qualified_registered": ["C9074"],
        "retained_previous_keys": [x.identity.key.to_dict() for x in previous.candidates],
        "retained_handoff": [x.to_dict() for x in previous.handoff],
        "standard_points_not_registered": True,
        "baseline_not_reregistered": True,
        "prepare": 0,
        "evaluate": 0,
        "root_scientific_review": reviewref.to_dict(),
        "objective_achieved": review["objective_achieved"],
        "lookback_integer_sensitivity_not_sampled": True,
        "path_comparison_descriptive_only": True,
    }
    d.write(out / "verification.json", manifest)
    files = [
        Path(__file__),
        *(path / "src").rglob("*.py"),
        *(path / "protocols").glob("*.json"),
        WORK / "analysis.json",
        WORK / "perturbation_state.json",
        WORK / "verification.json",
        WORK / "preflight.json",
        WORK / "execution_complete.json",
        WORK / "publication_review_rejection.json",
        WORK / "verify_local_publication.py",
        *(WORK / "parameters").glob("*-audit.json"),
        *(WORK.glob("root_*.py")),
        *(WORK.glob("root_*.json")),
        *(out.glob("*.json")),
    ]
    for frozen in (WORK / "freeze_v2.json", WORK / "standard/freeze.json"):
        files.append(frozen)
        for name, expected in read(frozen)["files"].items():
            source = ROOT / name
            if digest(source) != expected:
                raise ValueError("Declared frozen source or prior technical version drift")
            files.append(source)
    for q in files:
        add(
            publish_evidence(
                ctx,
                MaterialEvidenceWrite(
                    exp,
                    "pressure-early-exit-closeout-" + digest(q)[:32],
                    q.read_bytes(),
                    "application/json" if q.suffix == ".json" else "text/plain",
                    q.suffix[1:],
                ),
            )
        )
    entry = api.CandidateEntry(
        api.CandidateIdentityRef(CandidateKey("S013", "C9074"), derivation.child_content_sha256),
        "原C8880熊市入场锁存隔夜卖压标记，标记持仓使用固定提前TIME上限",
        "原四项经济硬门合格；稳健性与科学优选结论见根公开评审",
        (api.EvaluationEvidenceRef(centre_ref),),
    )
    summary = api.SearchSummary(
        exp.experiment_id + "-fixed-pressure-entry-latched-early-time",
        "固定15有效参数/.05/32/seed13/HALF_EVEN；centre通过原四门后执行32+独立双费；无邻点/择优/参数救援",
        "共同HFQ开发池/原资金/原10bp每侧费用/LimitBuyHold1%；新34完整账户，旧B0 34仅认证复用；15D与13D各自标准仅描述对照",
        68,
        66,
        review["selection_summary"],
        (
            "反复开发池研究选择未校正，PBO/DSR不可用不能作零",
            "标准32 lookback均4，未检验窗口整数敏感性；cap覆盖1/2/3/4不择优",
            "15D与13D未逐点配对，不宣称同坐标扰动强度或隔离因果机制优势",
            "提前TIME改变退出记忆和后续机会，账本新增/消失路径只作描述",
            "硬门年度DD与全区间DD尾部诊断分开，无新增硬门；尚无封存证明",
        ),
        tuple(refs.values()),
    )
    payload = api.CandidateSet(
        (*previous.candidates, entry), previous.handoff, (summary,), review["selection_summary"]
    )
    text = review["report_markdown"] + "\n\n完整本地研究证据：\n"
    for ref in refs.values():
        text += f"\n- [证据 {ref.name}]({ref.path})"
    receipt = assemble_delivery(
        ctx.repository,
        api.DeliveryDefinition(ctx.batch, api.DeliveryStage.CANDIDATES, 60, predecessors),
        api.DeliveryContent(
            payload, api.DeliveryStatus.COMPLETE, (), (), report=text, evidence=tuple(refs.values())
        ),
    )
    d.write(out / "delivery_reference.json", receipt.reference.to_dict())
    check = validate_delivery(
        ctx.repository, receipt.reference, scope=api.DeliveryValidationScope.FULL
    )
    d.write(out / "delivery_validation.json", check.to_dict())
    if check.status is not api.ValidationStatus.PASS:
        raise ValueError("FULL validation failed; preserve attempted delivery")
    return receipt.reference.to_dict()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-reference", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(EvidenceRef.from_dict(read(args.review_reference)), args.source_sha256),
            ensure_ascii=False,
        )
    )
