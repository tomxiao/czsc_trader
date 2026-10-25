"""Authenticate all 177 fixed parameter accounts and reconcile their ledgers.

No account replay, source acquisition, search, publication, or qualification.
The completed 29-candidate fee audit is retained and checked separately.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from hashlib import sha256
from multiprocessing import get_context

from stage4 import ROOT, HOME, OUT, CACHE, EX, read, save, module, assert_protocol
from czsc_trader.application import RepositoryContext, diagnose_accounts
from czsc_trader.research_tools import (
    AccountDiagnosisRequest, AccountRunRef, EvidenceRef, ParameterEvaluationPlan,
)
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_evaluator import research_models as m


@lru_cache(maxsize=1)
def helpers():
    arithmetic = module(HOME.parent / "EX074_20261024/src/account_audit.py", "ex074_arithmetic")
    projection = module(HOME.parent / "EX066_20261024/src/audit.py", "ex066_projection")
    return arithmetic, projection


@lru_cache(maxsize=1)
def planned_children():
    result = {}
    records = read(OUT / "plan_refs.json")
    assert len(records) == 29
    for record in records:
        ref = EvidenceRef.from_dict(record["plan_reference"])
        plan = ParameterEvaluationPlan.from_dict(read(ref.resolve(ROOT)))
        assert plan.to_dict() == record["plan"]
        assert plan.design.to_dict() == record["design"]
        for i, child_id in enumerate(record["child_ids"]):
            assert child_id not in result
            result[child_id] = (plan, ref, i)
    assert len(result) == 177
    return result


def audit_one(row):
    arithmetic, projection_helper = helpers()
    ref = EvidenceRef.from_dict(row["evidence"])
    assert ref.experiment == EX and row["source_role"] == "parameter"
    payload = read(ref.resolve(ROOT))
    validate_evaluation_evidence(payload)
    assert all(payload[k] == row[k] for k in ("request_hash", "result_hash"))
    assert len(payload["runs"]) == len(payload["assessment_evidence"]) == 1
    run, projection = payload["runs"][0], payload["assessment_evidence"][0]
    item = m.AssessmentEvidence.from_dict(projection)
    assert (item.window_id, item.scenario_id) == ("full", "standard")
    assert item.initial_cash == item.opening_cash == 100000. and item.opening_quantity == 0
    assert item.frequency_window_days == 60 and len(item.account) == 434
    assert item.account[0].session == "2025-01-02" and item.account[-1].session == "2026-10-21"
    assert item.scenario_context.one_way_cost == .001
    assert item.scenario_context.measurement_tier == "FORMAL"
    assert payload["request_identity"]["price_basis"] == "HFQ_RESEARCH"
    plan, plan_ref, index = planned_children()[row["candidate_id"]]
    assert item.candidate == plan.children[index].candidate
    assert item.parent == plan.design.center
    assert item.parent.candidate_id == "S015-" + row["parent_candidate_id"]
    assert item.parameter_point == plan.design.bind_point(index)
    assert item.derivation_sha256 is not None
    binding = plan.bind_point(plan_ref, index, repository_root=ROOT)
    assert payload["request_identity"]["parameter_binding"] == binding.to_dict()
    summary = projection_helper.projection_summary(projection)
    description = arithmetic.describe(run, summary)
    description.pop("cycles")
    diagnosis = diagnose_accounts(RepositoryContext.discover(ROOT), AccountDiagnosisRequest(
        AccountRunRef(ref, arithmetic.identity(run)), None, arithmetic.WINDOWS["full"]))
    assert diagnosis.status.value not in ("INVALID_EVIDENCE", "INCOMPARABLE"), diagnosis.issues
    result = {
        "candidate_id": row["candidate_id"], "parent_candidate_id": row["parent_candidate_id"],
        "evidence": ref.to_dict(), "request_hash": row["request_hash"],
        "result_hash": row["result_hash"], "evaluation_id": item.evaluation_id,
        "status": "ARITHMETIC_CHECKS_PASS", "summary": summary,
        "accounting_description": description, "public_diagnosis": diagnosis.to_dict(),
        "plan_reference": plan_ref.to_dict(), "point_index": index,
    }
    return item.to_dict(), result


def main(workers):
    assert_protocol()
    assert not (OUT / "audit.json").exists(), "Preserve completed audit"
    fee_path = OUT / "fee_audit.json"
    fee = read(fee_path)
    assert fee["status"] == "ARITHMETIC_AND_IDENTITY_PASS" and fee["candidates"] == 29
    rows = read(OUT / "results.json")["rows"]
    assert len(rows) == 201
    parameters = [x for x in rows if x["source_role"] == "parameter"]
    assert len(parameters) == 177 and len({x["candidate_id"] for x in parameters}) == 177
    assert {x["candidate_id"] for x in parameters} == set(planned_children())
    assert [x for x in rows if x["source_role"] == "stress"] == read(OUT / "stress_results.json")["rows"]
    projections, accounts = [], []
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        for item, checked in pool.map(audit_one, parameters):
            projections.append(item)
            accounts.append(checked)
            if len(accounts) % 16 == 0:
                print("AUDITED_PARAMETERS", len(accounts), 177, flush=True)
    cache = CACHE / "parameter_accounts.json"
    save(cache, projections)
    result = {
        "status": "PASS", "experiment": EX.experiment_id, "accounts": accounts,
        "parameter_accounts": 177, "new_center_accounts": 0,
        "reused_fee_audit": {"path": fee_path.relative_to(ROOT).as_posix(),
                            "sha256": sha256(fee_path.read_bytes()).hexdigest(),
                            "candidates": 29, "target_passes": fee["stress_target_passes"]},
        "parameter_projection_sha256": sha256(cache.read_bytes()).hexdigest(),
        "official_diagnosis_statuses": sorted({x["public_diagnosis"]["status"] for x in accounts}),
        "limitations": ["Fixed neighbors are checked without promoting them to centers.",
                        "Public UNSUPPORTED is retained; arithmetic is not causal attribution.",
                        "No new account or formal qualification produced by this audit."],
    }
    save(OUT / "audit.json", result)
    print("PARAMETER_AUDIT_PASS", len(accounts), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=8)
    main(parser.parse_args().workers)
