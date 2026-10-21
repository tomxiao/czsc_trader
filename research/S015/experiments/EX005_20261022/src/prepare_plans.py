"""Bind the fixed geometry to original center contracts and immutable child plans."""

import argparse
import cloudpickle
from dataclasses import replace
from common import ROOT, EROOT, WORK, EXPERIMENT, context, read, save, request, account
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (
    ParameterEvaluationPlan,
    EvaluationLineage,
    MaterialEvidenceWrite,
    EvidenceRef,
    EvaluationCost,
)
from strategy_evaluator import ParameterPerturbationDesign
from strategy_runtime import StrategyCandidate, canonical_sha256, StrategyRuntime
from strategy_manager import (
    CandidateKey,
    CandidateDerivation,
    CandidateDerivationKind,
    CandidateEvidence,
)

TEMP = ROOT / ".tmp/s015_stage4/requests"


def authenticate_center(req, row):
    original = account(row)
    q = original["request_identity"]
    actual = {
        "experiment_id": req.experiment_id,
        "strategy_reference": req.strategy.reference_id,
        "strategy_identity": req.strategy.runtime_identity_sha256,
        "content_sha256": StrategyRuntime()
        .identify(req.strategy, dependencies=req.dependencies)
        .content_sha256,
        "runtime_binding_hash": canonical_sha256(dict(req.runtime_binding)),
        "symbol": req.symbol,
        "asset_type": req.asset_type,
        "initial_cash": req.initial_cash,
        "data_cutoff": req.data_cutoff.isoformat(),
        "frequency_window_days": req.frequency_window_days,
        "execution_mode": req.execution_mode,
        "price_basis": req.price_basis.value,
        "windows": [
            {"window_id": w.window_id, "start": w.start.isoformat(), "end": w.end.isoformat()}
            for w in req.windows
        ],
        "costs": [
            {
                "scenario_id": c.scenario_id,
                "one_way_cost": c.one_way_cost,
                "measurement_tier": c.measurement_tier,
            }
            for c in req.costs
        ],
        "benchmark": req.benchmark.to_dict(),
        "input_bindings": {k: v.to_dict() for k, v in req.input_bindings.items()},
        "data_identity": req.execution_data.fingerprint,
        "pricing": req.execution_data.pricing.to_dict(),
        "market_rules": req.execution_data.market_rules.to_dict(),
        "lineage": None,
        "parameter_binding": None,
    }
    for key, value in actual.items():
        assert value == q[key], (row["candidate_id"], key)
    return {
        "status": "PASS",
        "checked_fields": list(actual),
        "original_request_hash": original["request_hash"],
    }


def prepare_one(ctx, row):
    cid = row["candidate_id"]
    target = WORK / "plans" / f"{cid}.json"
    cache = TEMP / f"{cid}.pkl"
    if target.exists() and cache.exists():
        return read(target)
    center = ctx.evaluation.prepare(request(row))
    continuity = authenticate_center(center, row)
    design_doc = read(WORK / "designs" / f"{cid}.json")
    bound = []
    if design_doc["status"] == "COMPLETE":
        design = ParameterPerturbationDesign.from_dict(design_doc["design"])
        children = []
        for spec in design_doc["children"]:
            child = StrategyCandidate(
                "S015",
                spec["candidate_id"],
                {**center.strategy.payload, "parameters": spec["parameters"]},
                center.strategy.source_root,
            )
            child_req = replace(
                center,
                experiment_id=EXPERIMENT.experiment_id,
                strategy=child,
                runtime_binding={**center.runtime_binding, "candidate_id": child.reference_id},
                input_bindings={},
            )
            children.append(ctx.evaluation.prepare(child_req))
        refs = read(EROOT / "others/mapping_refs.json")
        plan = ParameterEvaluationPlan.create(
            design,
            center,
            tuple(children),
            mapping_evidence=EvidenceRef.from_dict(refs["mapping"]),
            feasibility_evidence=EvidenceRef.from_dict(refs["constraints"]),
            dataflows=ctx.data,
        )
        assert plan.center_request_sha256 == row["request_hash"], cid
        path = EROOT / "protocols/plans" / f"{cid}.json"
        save(path, plan.to_dict())
        ref = publish_evidence(
            ctx,
            MaterialEvidenceWrite(
                EXPERIMENT, f"parameter_plan_{cid}", path.read_bytes(), "application/json", "json"
            ),
        )
        for i, child in enumerate(children):
            derivation = CandidateDerivation(
                CandidateKey("S015", cid),
                plan.center.candidate.content_sha256,
                CandidateKey("S015", child.strategy.candidate_id),
                plan.children[i].candidate.content_sha256,
                CandidateDerivationKind.PARAMETERS,
                dict(child.strategy.payload["parameters"]),
                design.protocol.sha256,
                CandidateEvidence(ref.repository_path, ref.sha256),
            )
            bound.append(
                replace(
                    child,
                    lineage=EvaluationLineage(
                        derivation, plan.bind_point(ref, i, repository_root=ROOT)
                    ),
                )
            )
        output = {
            "status": "COMPLETE",
            "design": design.to_dict(),
            "plan": plan.to_dict(),
            "reference": ref.to_dict(),
            "center_continuity": continuity,
        }
    else:
        output = {**design_doc, "center_continuity": continuity}
    stress = replace(
        center,
        experiment_id=EXPERIMENT.experiment_id,
        costs=(EvaluationCost("fee_x2", 0.002, "STRESS"),),
    )
    TEMP.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(
        cloudpickle.dumps({"center": center, "parameters": tuple(bound), "stress": stress})
    )
    save(target, output)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate")
    args = parser.parse_args()
    ctx = context()
    rows = read(WORK / "centers.json")
    for i, row in enumerate(rows):
        if args.candidate and args.candidate != row["candidate_id"]:
            continue
        item = prepare_one(ctx, row)
        print(
            {"prepared": i + 1, "candidate": row["candidate_id"], "status": item["status"]},
            flush=True,
        )


if __name__ == "__main__":
    main()
