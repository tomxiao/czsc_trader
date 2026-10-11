"""EX074 exact15D32 plus independentfee; explicit frozen continuation authority."""
# ruff: noqa: E402 -- Bootstrap frozen research module paths before imports.

from __future__ import annotations
import os

for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import driver as d
import specification as spec
from strategy_evaluator import ParameterPerturbationDesign
from strategy_runtime import StrategyCandidate
from strategy_manager import (
    CandidateDerivation,
    CandidateDerivationKind,
    CandidateEvidence,
    CandidateKey,
)
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (
    EvaluationCost,
    EvaluationEvidenceWrite,
    EvaluationLineage,
    ParameterEvaluationPlan,
)
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan

ROOT, WORK = d.ROOT, d.WORK


def save_state(value):
    (WORK / "perturbation_state.json").write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", "utf-8"
    )


def material(ctx, exp, path, name, value):
    path = Path(path)
    if path.exists():
        assert d.read(path) == value, "immutable prospective content differs"
    else:
        d.write(path, value)
    return d.put(ctx, exp, path, name)


def context():
    exp, plan, path = d.stage()
    common = d.oldcommon()
    return common.context(1), exp, plan, path, common


def authority():
    approval = d.read(WORK / "standard/root_execution_authorization.json")
    assert approval["status"] == "APPROVED_EX074_STANDARD32_FEE"
    assert approval["freeze_sha256"] == d.digest(WORK / "standard/freeze.json")
    freeze = d.read(WORK / "standard/freeze.json")
    for name, expected in freeze["files"].items():
        assert d.digest(ROOT / name) == expected, name
    return approval, freeze


def declare():
    approval, freeze = authority()
    ctx, exp, centreplan, path, common = context()
    assert not (WORK / "perturbation_state.json").exists()
    assert d.read(WORK / "verification.json")["economics"]["qualified"]
    prepared, outcome = common.cache_read(WORK / "centre.pkl.gz")
    centre_ref = d.read(path / "protocols/centre_reference.json")
    assert serialize_evaluation_evidence(prepared, outcome) == d.read(d.public(centre_ref))
    specification = d.read(WORK / "standard/point_specification15.json")
    assert specification["budget"]["total_new_financial"] == 34
    assert specification["budget"]["neighbours"] == 0
    assert spec.plain(prepared.strategy.payload) == specification["centre_payload"]
    design = ParameterPerturbationDesign.from_dict(specification["design"])
    design.validate()
    coords = specification["coordinates"]
    assert coords[:13] == d.read(d.OLD / "protocols/geometry.json")["coordinates"]
    mapping_ref = d.put(ctx, exp, WORK / "standard/mapping15.json", "pressure-early-exit-mapping15")
    feasibility_ref = d.put(
        ctx, exp, WORK / "standard/feasibility15.json", "pressure-early-exit-feasibility15"
    )
    assert design.space.mapping_sha256 == mapping_ref["sha256"]
    assert design.space.feasibility_sha256 == feasibility_ref["sha256"]
    spec_ref = d.put(
        ctx,
        exp,
        WORK / "standard/point_specification15.json",
        "pressure-early-exit-exact-point-specification15",
    )
    children = []
    for point in specification["points"]:
        ident = point["candidate_id"]
        assert not (ROOT / "research/S013/assets/candidates" / ident).exists()
        assert not (ROOT / "research/registrations/S013/candidates" / (ident + ".json")).exists()
        candidate = StrategyCandidate(
            "S013", ident, point["payload"], prepared.strategy.source_root
        )
        child = replace(
            prepared,
            strategy=candidate,
            runtime_binding={**prepared.runtime_binding, "candidate_id": candidate.reference_id},
            input_bindings={},
            lineage=None,
        )
        children.append(ctx.evaluation.prepare(child))
    plan = ParameterEvaluationPlan.create(
        design,
        prepared,
        tuple(children),
        mapping_evidence=EvidenceRef.from_dict(mapping_ref),
        feasibility_evidence=EvidenceRef.from_dict(feasibility_ref),
        dataflows=ctx.data,
    )
    plan_ref = material(
        ctx,
        exp,
        WORK / "parameter_plan15.json",
        "pressure-early-exit-parameter-plan15",
        plan.to_dict(),
    )
    bound = []
    centre_params = spec.plain(prepared.strategy.payload["parameters"])
    for i, child in enumerate(children):
        changes = {
            name: {
                "before": spec.get(centre_params, name),
                "after": spec.get(child.strategy.payload["parameters"], name),
            }
            for name, *_ in coords
            if spec.get(centre_params, name) != spec.get(child.strategy.payload["parameters"], name)
        }
        derive = CandidateDerivation(
            CandidateKey("S013", "C9074"),
            centreplan["content_sha256"],
            CandidateKey("S013", child.strategy.candidate_id),
            plan.children[i].candidate.content_sha256,
            CandidateDerivationKind.PARAMETERS,
            changes,
            design.protocol.sha256,
            CandidateEvidence(
                EvidenceRef.from_dict(centre_ref).repository_path, centre_ref["sha256"]
            ),
        )
        bound.append(
            replace(
                child,
                lineage=EvaluationLineage(
                    derive,
                    plan.bind_point(EvidenceRef.from_dict(plan_ref), i, repository_root=ROOT),
                ),
            )
        )
    fee = replace(prepared, costs=(EvaluationCost("stress_20bp_per_side", 0.002, "STRESS"),))
    common.cache_write(WORK / "parameter_prepared.pkl.gz", (tuple(bound), fee))
    formal_files = []
    for name in (
        "specification.py",
        "perturbation_driver.py",
        "native_point_audit.py",
        "analyze.py",
        "point_checks.py",
        "freeze_source.py",
    ):
        formal = path / "src/standard" / name
        formal.parent.mkdir(exist_ok=True)
        shutil.copyfile(WORK / "standard" / name, formal)
        formal_files.append(formal)
    source_refs = {
        q.name: d.put(ctx, exp, q, "pressure-early-exit-standard-" + q.stem.replace("_", "-"))
        for q in formal_files
    }
    old_method_ref = d.read(
        ROOT
        / "research/S013/experiments/EX070_20261011/protocols/perturbation_method_reference.json"
    )
    old_method = d.read(d.public(old_method_ref))
    root_refs = {}
    for name in (
        "root_centre_economics.py",
        "root_centre_economics.json",
        "root_point_geometry.py",
        "root_point_geometry.json",
    ):
        root_refs[name] = d.put(
            ctx,
            exp,
            WORK / name,
            "root-centre-independent-" + name.replace("_", "-").replace(".", "-"),
        )
    method = {
        "status": "PROSPECTIVE_FROZEN",
        "authorization": approval,
        "freeze": freeze,
        "protocol": design.protocol.to_dict(),
        "parameter_plan_reference": plan_ref,
        "mapping_reference": mapping_ref,
        "feasibility_reference": feasibility_ref,
        "point_specification_reference": spec_ref,
        "effective_dimensions": 15,
        "old_baseline_dimensions": 13,
        "paired_point_comparison": False,
        "comparability": specification["comparison"],
        "integer_coverage": specification["integer_coverage"],
        "effective_marked_bear_H": specification["effective_marked_bear_H"],
        "generator_validity": specification["generator_validity"],
        "candidate_ids": [x["candidate_id"] for x in specification["points"]],
        "prepared_cache_sha256": d.digest(WORK / "parameter_prepared.pkl.gz"),
        "source_files": {q.relative_to(ROOT).as_posix(): d.digest(q) for q in formal_files},
        "source_references": source_refs,
        "root_centre_reconciliation_refs": root_refs,
        "budget": specification["budget"],
        "fee": specification["fee"],
        "baseline_reuse": old_method["baseline_reuse"],
        "baseline_fee_reuse": old_method["baseline_fee_reuse"],
        "baseline_method_reference": old_method_ref,
        "fivechecks_definition": specification["fivechecks"],
        "centre_strong_counterevidence": specification["selection_history"],
        "no_window_integer_coverage": "All32 lookback remains4; no sampled window-integer robustness, no extra neighbours or replacement",
        "technical_financial_policy": "Each new FULL once only; native-complete account audit/publication issues repaired read-only with original evidence and explicit public amendment. Uncertain INFLIGHT never reevaluated. No repeat already successful account",
        "provider_calls": common.SOURCE_CALLS,
    }
    assert not common.SOURCE_CALLS
    ref = material(
        ctx,
        exp,
        WORK / "perturbation_method.json",
        "pressure-early-exit-perturbation-method",
        method,
    )
    d.write(path / "protocols/perturbation_method_reference.json", ref)
    d.write(path / "protocols/parameter_plan15_reference.json", plan_ref)
    save_state({"status": "DECLARED", "accounts": {}, "method_reference": ref})
    return {
        "status": "DECLARED",
        "integer_coverage": method["integer_coverage"],
        "new_financial_in_declaration": 0,
        "new_remaining_budget": 33,
    }


def stage():
    authority()
    ctx, exp, centreplan, path, common = context()
    state = d.read(WORK / "perturbation_state.json")
    method = d.read(d.public(state["method_reference"]))
    for name, expected in method["source_files"].items():
        assert d.digest(ROOT / name) == expected
    assert d.digest(WORK / "parameter_prepared.pkl.gz") == method["prepared_cache_sha256"]
    requests, fee = common.cache_read(WORK / "parameter_prepared.pkl.gz")
    assert len(requests) == 32 and all(
        x.execution_mode == "FULL" and x.workers == 1 for x in (*requests, fee)
    )
    plan_ref = EvidenceRef.from_dict(method["parameter_plan_reference"])
    parameter_plan = read_parameter_plan(plan_ref, repository_root=ROOT)
    specification = d.read(d.public(method["point_specification_reference"]))
    for i, (request, declared) in enumerate(zip(requests, specification["points"], strict=True)):
        assert request.strategy.candidate_id == declared["candidate_id"]
        assert spec.plain(request.strategy.payload) == declared["payload"]
        assert request.lineage.parameter_binding == parameter_plan.bind_point(
            plan_ref, i, repository_root=ROOT
        )
        assert len(request.costs) == 1 and request.costs[0].one_way_cost == 0.001
    centre, _ = common.cache_read(WORK / "centre.pkl.gz")
    assert spec.plain(fee.strategy.payload) == spec.plain(centre.strategy.payload)
    assert len(fee.costs) == 1 and fee.costs[0].one_way_cost == 0.002
    d.audits()
    audit = d.load("pressure_early_point_audit74", path / "src/standard/native_point_audit.py")
    return ctx, exp, path, common, state, method, requests, fee, audit


def run():
    ctx, exp, path, common, state, method, requests, fee, audit = stage()
    for label, request in [(f"P{i:02}", r) for i, r in enumerate(requests)] + [("FEE", fee)]:
        item = state["accounts"].get(label)
        if item and item["status"] == "AUDITED":
            continue
        if item and item["status"] == "INFLIGHT":
            raise RuntimeError("uncertain finance cannot retry " + label)
        cache = WORK / "parameters" / (label + ".pkl.gz")
        if item is None:
            state["accounts"][label] = {"status": "INFLIGHT"}
            save_state(state)
            result = ctx.evaluation.evaluate(request)
            common.cache_write(cache, (request, result))
            ref = publish_evidence(
                ctx,
                EvaluationEvidenceWrite(
                    exp, "pressure-early-exit-" + label.lower() + "-native", request, result
                ),
            ).to_dict()
            item = {
                "status": "NATIVE_COMPLETE",
                "reference": ref,
                "cache": cache.relative_to(ROOT).as_posix(),
                "cache_sha256": d.digest(cache),
                "request_hash": result.request_hash,
                "result_hash": result.result_hash,
            }
            state["accounts"][label] = item
            save_state(state)
        else:
            assert d.digest(cache) == item["cache_sha256"]
            request, result = common.cache_read(cache)
        report = audit.audit(
            ctx,
            request,
            result,
            d.read(d.public(item["reference"])),
            new=True,
            expected_cost=0.002 if label == "FEE" else 0.001,
        )
        assert report["status"] == "PASS" and report["whole_formal_native_exact"] is True
        report["actual_label"] = label
        report["parameter_diagnostic_status"] = (
            "DECLARED15D_STANDARD32" if label != "FEE" else "INDEPENDENT_DOUBLE_FEE"
        )
        report_ref = material(
            ctx,
            exp,
            WORK / "parameters" / (label + "-audit.json"),
            "pressure-early-exit-" + label.lower() + "-independent-audit",
            report,
        )
        item.update(status="AUDITED", audit_reference=report_ref, economics=report["economics"])
        save_state(state)
        assert not common.SOURCE_CALLS
        print(
            json.dumps(
                {
                    "label": label,
                    "status": "AUDITED",
                    "cagr": report["economics"]["net_cagr"],
                    "qualified": report["economics"]["qualified"],
                }
            ),
            flush=True,
        )
    assert set(state["accounts"]) == {*(f"P{i:02}" for i in range(32)), "FEE"}
    state["status"] = "FINANCIAL34_COMPLETE"
    save_state(state)
    return {"status": state["status"], "new_financial_total": 34}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("declare", "run"))
    args = parser.parse_args()
    try:
        print(json.dumps(globals()[args.action](), ensure_ascii=False), flush=True)
    except Exception:
        print(traceback.format_exc(), flush=True)
        raise
