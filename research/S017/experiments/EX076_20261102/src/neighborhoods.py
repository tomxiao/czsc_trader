"""Bounded RSCH orchestration of prospective full parameter neighborhoods."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s017-stage4-20261102"
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
sys.pycache_prefix = str(SCRATCH / "pycache")
for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from datetime import date, datetime
import json
from multiprocessing import get_context
import time
from uuid import UUID
from zoneinfo import ZoneInfo

import psutil
from dataflows import ProviderConfig, PreparedDataRef, SourceRef, TimeInterval
from czsc_trader.application import RepositoryContext, create_research_context, load_candidate, publish_evidence
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity
from czsc_trader.research_tools.parameter_evaluation import equity_parameter_contract
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import ExecutionResources
from strategy_evaluator import research_models as m

KEYS = ("C0338", "C0339", "C0340", "C0341", "C0342", "C0352")
PLANS = WORK / "others/parameter_plans"
RECORDS = WORK / "others/neighborhood_batches"
E = d.ExperimentRef("S017", WORK.name)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def prepared_data():
    value = read(ROOT / "research/S017/experiments/EX072_20261102/others/data_preparation.json")["reference"]
    assert value["manifest_sha256"] == "a671f92acb0723e4054b26247bca52d39186c3a0f87e25e70a133b48987a242d"
    return PreparedDataRef(UUID(value["space_id"]), UUID(value["preparation_id"]), value["manifest_sha256"])


def context_for(repository, candidate):
    return create_research_context(repository, d.ResearchBatchRef("S017"),
        providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(1, 1, 17))


def request_for(candidate):
    zone = ZoneInfo("America/New_York")
    window = TimeInterval(datetime(2024, 1, 2, 9, 30, tzinfo=zone), datetime(2025, 12, 31, 16, tzinfo=zone))
    source = SourceRef("futu", "s017-development-gap-known-interruptions-v1-20261028")
    rules = SourceRef("s017-research-rules", "same-approved-us-assumptions-v4-ex032-v1")
    return d.EquityEvaluationRequest(E, candidate, window, date(2023, 11, 1),
        d.EquitySources(source, source, source, rules), 100000., .001, prepared=prepared_data(),
        benchmark=d.EvaluationBenchmark(d.EquityBuyHold(candidate.definition.execution_spec)),
        window_id="TRAIN_2024_2025", scenario_id="STANDARD", measurement_tier="FORMAL",
        drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE", frequency_window_days=60)


def child_candidate(center, design, index, start):
    parameters = {value.name: value.value for value in design.points[index].values}
    return replace(center, candidate_id=f"C{start + index:04d}", definition=replace(center.definition,
        parameters_json=json.dumps(parameters, sort_keys=True, separators=(",", ":"))))


def make_plans():
    output = PLANS / "index.json"
    if output.exists():
        raise RuntimeError("Prospective plans already exist; inspect and reuse exact immutable references")
    jobs, cursor = [], 4000
    for key in KEYS:
        count = m.ParameterNeighborhoodDesign.from_dict(read(SCRATCH / "proposed_designs" / (key + ".json"))).point_count
        jobs.append((key, cursor))
        cursor += count
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn"), max_tasks_per_child=1) as executor:
        values = dict(executor.map(make_one_plan, jobs))
    assert cursor == 6829 and sum(value["N"] for value in values.values()) == 2829
    save(output, {"status": "COMPLETE_PROSPECTIVE_FULL_PLANS", "plans": values,
                  "first_id": "C4000", "last_id": "C6828", "point_count": 2829, "accounts_run": 0})


def make_one_plan(job):
    key, cursor = job
    repository = RepositoryContext.discover(ROOT)
    standard = read(ROOT / "research/S017/experiments/EX072_20261102/others/all_accounts.json")
    if True:
        center = load_candidate(repository, CandidateKey("S017", key))
        context = context_for(repository, center)
        design = m.ParameterNeighborhoodDesign.from_dict(read(SCRATCH / "proposed_designs" / (key + ".json")))
        with d.ResearchExecutionSession(context, experiment=E) as execution:
            mapping = publish_evidence(context, d.MaterialEvidenceWrite(E, "parameter-mapping-confirmed",
                (WORK / "protocols/parameter_mapping_proposal.json").read_bytes(), "application/json", "json"), execution=execution)
            feasible = publish_evidence(context, d.MaterialEvidenceWrite(E, "parameter-constraints-confirmed",
                (WORK / "protocols/parameter_constraints_proposal.json").read_bytes(), "application/json", "json"), execution=execution)
            central = context.evaluation.prepare(request_for(center), execution=execution)
            children = []
            for index in range(design.point_count):
                children.append(context.evaluation.prepare(request_for(child_candidate(center, design, index, cursor)),
                                                           execution=execution))
                if (index + 1) % 32 == 0:
                    print("PROSPECTIVE_PREPARED", key, index + 1, design.point_count, flush=True)
            children = tuple(children)
            plan = d.ParameterEvaluationPlan.create(design, central, children,
                mapping_evidence=mapping, feasibility_evidence=feasible, dataflows=context.data, execution=execution)
            # Bind the exact existing published center rather than replaying it.
            # The plan's nonparameter and prepared input identity must match it exactly.
            ref = d.EvidenceRef.from_dict(standard[key]["evidence"])
            envelope = read(ref.resolve(ROOT))
            old_request = envelope["request"]
            contract = equity_parameter_contract(old_request)
            assert contract["nonparameter_context_sha256"] == plan.nonparameter_context_sha256
            assert contract["content_sha256"] == plan.center.candidate.content_sha256
            assert contract["input_bindings"] == {item.window_id: json.loads(item.binding_json) for item in plan.center_inputs}
            plan = replace(plan, center_request_sha256=envelope["request_hash"])
            assert plan.center_request_sha256 == standard[key]["request_hash"]
            path = PLANS / (key + ".json")
            save(path, plan.to_dict())
            reference = publish_evidence(context, d.MaterialEvidenceWrite(E, "parameter-plan-" + key,
                path.read_bytes(), "application/json", "json"), execution=execution)
            # These exact bytes and complete child payloads now precede all runs.
            value = {"reference": reference.to_dict(), "start": cursor,
                           "N": design.point_count, "design_sha256": design.sha256,
                           "center_reused": ref.to_dict(), "center_request_sha256": plan.center_request_sha256}
        print("PROSPECTIVE_PLAN", key, design.point_count, reference.sha256, flush=True)
        save(PLANS / (key + "-reference.json"), value)
        return key, value


def metrics(run):
    curve, daily = run["account_points"], run["account_daily"]
    assert len(curve) == 6490 and len(daily) == 502
    peak, dd = 100000., 0.
    for point in curve:
        peak = max(peak, point["equity"])
        dd = max(dd, 1 - point["equity"] / peak)
    annual = (curve[-1]["equity"] / 100000.) ** (252 / 502) - 1
    import math
    assert math.isclose(annual, run["metrics"]["annualized_return"], rel_tol=1e-11, abs_tol=1e-10)
    assert math.isclose(dd, run["metrics"]["bar_max_drawdown"], rel_tol=1e-11, abs_tol=1e-10)
    return {"annualized_return": annual, "drawdown": dd,
            "calmar": annual / dd if dd > 1e-12 and math.isfinite(annual / dd) else None}


def run_batch(task):
    key, indices, label = task
    started = time.perf_counter()
    process = psutil.Process()
    before = process.memory_info().rss
    output = RECORDS / (label + ".json")
    if output.exists():
        raise RuntimeError("Existing batch must be explicitly verified, never blindly rerun")
    item = read(PLANS / (key + "-reference.json"))
    plan = d.ParameterEvaluationPlan.from_dict(read(PLANS / (key + ".json")))
    reference = d.EvidenceRef.from_dict(item["reference"])
    repository = RepositoryContext.discover(ROOT)
    center = load_candidate(repository, CandidateKey("S017", key))
    context = context_for(repository, center)
    record = {"status": "RUNNING", "center": key, "indices": indices, "pid": process.pid,
              "resources": {"work_processes": 1, "native_threads": 1}, "records": []}
    save(output, record)
    with d.ResearchExecutionSession(context, experiment=E,
            checkpoint=d.ExecutionCheckpointRequest("EX076-neighbors-" + label)) as execution:
        handles = []
        for index in indices:
            child = child_candidate(center, plan.design, index, item["start"])
            assert json.dumps(child.payload, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False) == plan.children[index].payload_json
            derivation = CandidateDerivation(center.key, center.content_identity.content_sha256,
                child.key, child.content_identity.content_sha256, CandidateDerivationKind.PARAMETERS,
                {value.name: value.value for value in plan.design.points[index].values}, plan.design.protocol.sha256,
                CandidateEvidence(reference.repository_path, reference.sha256))
            lineage = d.EvaluationLineage(derivation, plan.bind_point(reference, index, repository_root=ROOT))
            handles.append(context.evaluation.prepare(replace(request_for(child), lineage=lineage), execution=execution))
        handles = tuple(handles)
        outcomes = context.evaluation.evaluate_many(handles, execution=execution)
        if any(outcome.status.value != "SUCCEEDED" or outcome.result is None for outcome in outcomes):
            record.update(status="EXPLICIT_EXECUTION_FAILURE_NO_RETRY",
                          outcomes=[{"status": outcome.status.value,
                              "error": None if outcome.error is None else {
                                  "code": outcome.error.code, "message": outcome.error.message}}
                              for outcome in outcomes])
            save(output, record)
            raise RuntimeError("Incomplete parameter batch; inspect explicit statuses")
        from czsc_trader.application import publish_evidence_many
        publications = publish_evidence_many(context, tuple(d.EvaluationEvidenceWrite(E,
            "neighbor-" + handle.candidate.candidate_id, handle, outcome.result)
            for handle, outcome in zip(handles, outcomes, strict=True)), execution=execution)
        assert all(publication.status.value == "PUBLISHED" for publication in publications)
        for index, handle, outcome, publication in zip(indices, handles, outcomes, publications, strict=True):
            payload = materialize_equity(outcome.result).payload
            candidate, benchmark = metrics(payload["runs"]["candidate"]), metrics(payload["runs"]["buy_hold"])
            joint_return = candidate["annualized_return"] >= 1.25 * benchmark["annualized_return"] if benchmark["annualized_return"] > 0 else candidate["annualized_return"] > 0
            result = {"index": index, "candidate": handle.candidate.candidate_id,
                      "identity": handle.candidate.content_identity.content_sha256,
                      "candidate_metrics": candidate, "benchmark_metrics": benchmark,
                      "joint_pass": joint_return and candidate["drawdown"] <= .9 * benchmark["drawdown"],
                      "all_point_dd_pass": candidate["drawdown"] <= .25,
                      "evidence": publication.reference.to_dict(), "evaluation_id": payload["evaluation_id"],
                      "request_hash": payload["request_hash"], "parameter_binding": handle.request.lineage.parameter_binding.to_dict()}
            record["records"].append(result)
            print("PARAMETER_RESULT", key, index, candidate, result["joint_pass"], result["all_point_dd_pass"], flush=True)
        record["execution_stats"] = {"session": asdict(execution.stats), "equity": asdict(execution.equity_statistics)}
    memory = process.memory_info()
    record.update(status="COMPLETED", elapsed_seconds=time.perf_counter() - started,
                  rss_before=before, rss_after=memory.rss, peak_rss=memory.peak_wset,
                  full_N=item["N"], point_count=len(indices))
    save(output, record)
    return {"batch": label, "center": key, "point_count": len(indices),
            "peak_rss": record["peak_rss"], "elapsed_seconds": record["elapsed_seconds"],
            "all_point_failures": [row["index"] for row in record["records"] if not row["all_point_dd_pass"]]}


def point_order(plan):
    centers = {axis.name: axis.center for axis in plan.design.space.axes}
    return sorted(range(plan.design.point_count), key=lambda index: (
        -sum(value.value != centers[value.name] for value in plan.design.points[index].values), index))


def pilot(keys, prefix):
    assert keys and set(keys) <= set(KEYS)
    tasks = []
    for key in keys:
        plan = d.ParameterEvaluationPlan.from_dict(read(PLANS / (key + ".json")))
        tasks.append((key, point_order(plan)[:2], prefix + "-" + key))
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn"), max_tasks_per_child=1) as executor:
        results = list(executor.map(run_batch, tasks))
    save(WORK / "others" / (prefix + "_" + "_".join(keys) + ".json"), {"status": "COMPLETED", "workers": min(2, len(keys)),
         "native_threads": 1, "results": results, "new_parameter_accounts": 2 * len(keys),
         "parameter_search": False, "sealed_prices_accessed": False})
    print("BOUNDED_PILOT_COMPLETE", results, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "pilot"))
    parser.add_argument("--centers", nargs="+", choices=KEYS, default=["C0338", "C0342"])
    parser.add_argument("--prefix", default="pilot")
    args = parser.parse_args()
    make_plans() if args.action == "plan" else pilot(args.centers, args.prefix)
