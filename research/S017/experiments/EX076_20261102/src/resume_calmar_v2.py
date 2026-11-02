"""Resume fixed neighborhoods under MANDATE/8, with published-result reuse and 12-way bounds."""
# ruff: noqa: E402
from neighborhoods import (ROOT, WORK, PLANS, RECORDS, KEYS, E, read, save, metrics,
    context_for, request_for, child_candidate)

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, replace
from hashlib import sha256
import json
from multiprocessing import get_context
import time

import psutil
from czsc_trader.application import RepositoryContext, load_candidate, publish_evidence_many
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity, build_equity_assessment
from strategy_evaluator.equity_assessment import EquityCertificationScope
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime.equity import equity_hash

NEW = WORK / "others/neighborhood_batches_v2"
REUSE = WORK / "others/neighborhood_reuse_v2"
STATE = WORK / "others/neighborhood_execution_v2.json"
CONTROL = WORK / "others/neighborhood_execution_v2_control.json"


def bound_request(context, center, plan, reference, start, index, execution):
    child = child_candidate(center, plan.design, index, start)
    assert json.dumps(child.payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False) == plan.children[index].payload_json
    derivation = CandidateDerivation(center.key, center.content_identity.content_sha256,
        child.key, child.content_identity.content_sha256, CandidateDerivationKind.PARAMETERS,
        {value.name: value.value for value in plan.design.points[index].values}, plan.design.protocol.sha256,
        CandidateEvidence(reference.repository_path, reference.sha256))
    lineage = d.EvaluationLineage(derivation, plan.bind_point(reference, index, repository_root=ROOT))
    return context.evaluation.prepare(replace(request_for(child), lineage=lineage), execution=execution)


def verify_envelope(payload, key, index, plan, reference):
    request = payload["request"]
    child = plan.children[index].candidate
    assert payload["request_hash"] == equity_hash(request)
    assert request["candidate_id"] == child.candidate_id.split("-")[1]
    assert request["content_sha256"] == child.content_sha256
    assert request["candidate_definition"] == json.loads(plan.children[index].payload_json)["equity_definition"]
    assert request["lineage"]["parameter_binding"]["plan"] == reference.to_dict()
    assert request["lineage"]["parameter_binding"]["point"] == plan.design.bind_point(index).to_dict()
    assert plan.design.center.candidate_id == "S017-" + key
    assert request["fee_rate"] == .001 and request["initial_cash"] == 100000.
    assert request["scenario_id"] == "STANDARD" and request["window_id"] == "TRAIN_2024_2025"
    assert request["window"] == {"start": "2024-01-02T14:30:00+00:00", "end": "2025-12-31T21:00:00+00:00"}
    assert request["drawdown_basis"] == "BAR_CLOSE" and request["frequency_window_days"] == 60


def batch(task):
    mode, key, indices, label, old_rows = task
    begun = time.perf_counter()
    process = psutil.Process()
    path = (REUSE if mode == "REUSE" else NEW) / (label + ".json")
    if path.exists():
        raise RuntimeError("Existing batch requires explicit review, not blind retry")
    entry = read(PLANS / (key + "-reference.json"))
    plan = d.ParameterEvaluationPlan.from_dict(read(PLANS / (key + ".json")))
    reference = d.EvidenceRef.from_dict(entry["reference"])
    assert reference.resolve(ROOT).read_bytes() == (PLANS / (key + ".json")).read_bytes()
    result = {"status": "RUNNING", "mode": mode, "center": key, "indices": indices,
              "pid": process.pid, "records": [], "rule_version": "MANDATE/8",
              "business_gate_owner": "RSCH", "legacy_annual_joint_gate_used": False}
    save(path, result)
    if mode == "REUSE":
        with EquityCertificationScope() as certification:
            for index, old in zip(indices, old_rows, strict=True):
                ref = d.EvidenceRef.from_dict(old["evidence"])
                top = ref.resolve(ROOT)
                data = top.read_bytes()
                envelope = json.loads(data)
                allowed = {(envelope[name]["kind"], envelope[name]["sha256"])
                           for name in ("input_ref", "candidate_ref", "benchmark_ref")}

                def resolve(item):
                    assert (item["kind"], item["sha256"]) in allowed
                    content = (top.parent / (item["sha256"] + ".json")).read_bytes()
                    assert sha256(content).hexdigest() == item["sha256"]
                    return content

                view = materialize_equity(data, resolve)
                fact, = build_equity_assessment(view, scope=certification)
                payload = view.payload
                verify_envelope(payload, key, index, plan, reference)
                assert fact.evaluation_id == old["evaluation_id"] and payload["request_hash"] == old["request_hash"]
                candidate, benchmark = metrics(payload["runs"]["candidate"]), metrics(payload["runs"]["buy_hold"])
                assert candidate == old["candidate_metrics"] and benchmark == old["benchmark_metrics"]
                result["records"].append({"index": index, "candidate": old["candidate"],
                    "identity": old["identity"], "candidate_metrics": candidate, "benchmark_metrics": benchmark,
                    "evidence": old["evidence"], "evaluation_id": old["evaluation_id"],
                    "request_hash": old["request_hash"], "parameter_binding": old["parameter_binding"]})
            result["authenticated_unique_ledgers"] = certification.audit_count
    else:
        repository = RepositoryContext.discover(ROOT)
        center = load_candidate(repository, CandidateKey("S017", key))
        context = context_for(repository, center)
        with d.ResearchExecutionSession(context, experiment=E,
                checkpoint=d.ExecutionCheckpointRequest("EX076-calmar-v2-" + label)) as execution:
            handles = tuple(bound_request(context, center, plan, reference, entry["start"], index, execution)
                            for index in indices)
            outcomes = context.evaluation.evaluate_many(handles, execution=execution)
            if any(value.status.value != "SUCCEEDED" or value.result is None for value in outcomes):
                result.update(status="EXPLICIT_EXECUTION_FAILURE_NO_RETRY", outcomes=[{
                    "status": value.status.value, "error": None if value.error is None else {
                        "code": value.error.code, "message": value.error.message}} for value in outcomes])
                save(path, result)
                raise RuntimeError("Evaluation incomplete; explicit review required")
            publications = publish_evidence_many(context, tuple(d.EvaluationEvidenceWrite(E,
                "neighbor-" + handle.candidate.candidate_id, handle, value.result)
                for handle, value in zip(handles, outcomes, strict=True)), execution=execution)
            assert all(value.status.value == "PUBLISHED" for value in publications)
            for index, handle, value, publication in zip(indices, handles, outcomes, publications, strict=True):
                payload = materialize_equity(value.result).payload
                verify_envelope(payload, key, index, plan, reference)
                result["records"].append({"index": index, "candidate": handle.candidate.candidate_id,
                    "identity": handle.candidate.content_identity.content_sha256,
                    "candidate_metrics": metrics(payload["runs"]["candidate"]),
                    "benchmark_metrics": metrics(payload["runs"]["buy_hold"]),
                    "evidence": publication.reference.to_dict(), "evaluation_id": payload["evaluation_id"],
                    "request_hash": payload["request_hash"],
                    "parameter_binding": handle.request.lineage.parameter_binding.to_dict()})
            result["execution_stats"] = {"session": asdict(execution.stats), "equity": asdict(execution.equity_statistics)}
    memory = process.memory_info()
    result.update(status="COMPLETED", elapsed_seconds=time.perf_counter() - begun,
                  peak_rss=memory.peak_wset, rss_after=memory.rss, point_count=len(indices), full_N=entry["N"])
    save(path, result)
    return {"batch": label, "center": key, "mode": mode, "point_count": len(indices),
            "peak_rss": result["peak_rss"], "elapsed_seconds": result["elapsed_seconds"]}


def main():
    if STATE.exists():
        raise RuntimeError("Existing execution needs explicit state review")
    assert read(WORK / "others/neighborhood_execution.json")["status"] == "PAUSED_BY_USER_SELF_CHECK_STANDARD_REVIEW"
    assert read(WORK / "others/calmar_v2_final_verification.json")["status"] == "PASS"
    old_plan = read(WORK / "others/neighborhood_job_plan.json")
    covered, rows, completed_labels = {key: set() for key in KEYS}, [], set()
    old_peaks = []
    for path in sorted(RECORDS.glob("*.json")):
        value = read(path)
        if value["status"] != "COMPLETED":
            assert value["status"] == "PREPARATION_TYPE_COMPARISON_FAILED_ZERO_ACCOUNTS"
            continue
        assert covered[value["center"]].isdisjoint(value["indices"])
        covered[value["center"]].update(value["indices"])
        rows.extend((value["center"], record) for record in value["records"])
        completed_labels.add(path.stem)
        old_peaks.append(value["peak_rss"])
    assert len(rows) == 252
    audit_jobs = []
    for offset in range(0, len(rows), 4):
        subset = rows[offset:offset + 4]
        # Keep one center per audit batch.
        for key in dict.fromkeys(item[0] for item in subset):
            selected = [item[1] for item in subset if item[0] == key]
            audit_jobs.append(("REUSE", key, [item["index"] for item in selected],
                               f"reuse-{offset:04d}-{key}", selected))
    replay_jobs = []
    for task in old_plan["jobs"]:
        already = [index in covered[task["center"]] for index in task["indices"]]
        if any(already):
            assert all(already) and task["label"] in completed_labels
        else:
            replay_jobs.append(("REPLAY", task["center"], task["indices"], task["label"], []))
    assert sum(len(task[2]) for task in replay_jobs) == 2577
    # Prioritize unresolved candidate C0342, then retain every remaining full point.
    order = {key: index for index, key in enumerate(("C0342", "C0338", "C0339", "C0340", "C0341", "C0352"))}
    replay_jobs.sort(key=lambda task: (order[task[1]], task[3]))
    jobs = []
    while audit_jobs or replay_jobs:
        if audit_jobs:
            jobs.append(audit_jobs.pop(0))
        for _ in range(2):
            if replay_jobs:
                jobs.append(replay_jobs.pop(0))
    # Public input preparation validates the unchanged prospective plan without replay.
    first = next(task for task in jobs if task[0] == "REPLAY")
    key, index = first[1], first[2][0]
    repository = RepositoryContext.discover(ROOT)
    center = load_candidate(repository, CandidateKey("S017", key))
    context = context_for(repository, center)
    plan = d.ParameterEvaluationPlan.from_dict(read(PLANS / (key + ".json")))
    entry = read(PLANS / (key + "-reference.json"))
    reference = d.EvidenceRef.from_dict(entry["reference"])
    with d.ResearchExecutionSession(context, experiment=E) as execution:
        bound_request(context, center, plan, reference, entry["start"], index, execution)
    print("CURRENT_ENGINE_PROSPECTIVE_BINDING_PASS", key, index, flush=True)
    guard_paths = (WORK / "src/resume_calmar_v2.py", WORK / "src/neighborhoods.py",
                   WORK / "others/calmar_v2_targets.json", WORK / "protocols/confirmed_calmar_selfcheck_v2.json")
    hashes = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest() for path in guard_paths}
    save(WORK / "others/neighborhood_job_plan_v2.json", {"jobs": [
        {"mode": mode, "center": key, "indices": indices, "label": label} for mode, key, indices, label, _ in jobs],
        "previous_published": 252, "new_replays": 2577, "source_hashes": hashes})
    save(CONTROL, {"schema": "s017-rsch-execution-control/v1", "pause_requested": False,
                   "max_parallel_batches": 12, "user_instruction": "恢复；内存允许时12并发"})
    state = {"status": "RUNNING", "rule_version": "MANDATE/8", "maximum_parallel_batches": 12,
        "batch_size": 4, "native_threads_per_worker": 1, "nested_pools": False,
        "previously_published_points": 252, "reuse_verified_points": 0, "new_published_points": 0,
        "completed_points": 252, "total_points": 2829, "completed_batches": [], "failed_batches": [],
        "max_tree_rss": 0, "source_hashes": hashes, "resource_decisions": []}
    started = time.perf_counter()
    process, peak, pending = psutil.Process(), max(old_peaks), {}
    budget = min(48 * 2**30, int(psutil.virtual_memory().total * .4))
    save(STATE, state)
    with ProcessPoolExecutor(max_workers=12, mp_context=get_context("spawn"), max_tasks_per_child=1) as executor:
        while jobs or pending:
            control = read(CONTROL)
            assert control["schema"] == "s017-rsch-execution-control/v1" and type(control["pause_requested"]) is bool
            assert type(control["max_parallel_batches"]) is int and 1 <= control["max_parallel_batches"] <= 12
            rss = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            state["max_tree_rss"] = max(state["max_tree_rss"], rss)
            available = psutil.virtual_memory().available
            cap = min(control["max_parallel_batches"], max(1, int(budget / (peak * 1.35))))
            while not control["pause_requested"] and len(pending) < cap and jobs and rss < budget and available > 16 * 2**30:
                task = jobs.pop(0)
                pending[executor.submit(batch, task)] = task
                reservation = int(peak * 1.35)
                rss += reservation
                available -= reservation
            if not state["resource_decisions"] or state["resource_decisions"][-1]["cap"] != cap:
                state["resource_decisions"].append({"elapsed_seconds": time.perf_counter() - started,
                    "cap": cap, "measured_batch_peak_rss": peak, "rss_budget": budget})
                print("CALMAR_V2_CONCURRENCY", cap, "budget_GiB", round(budget / 2**30, 2), flush=True)
            if not pending:
                if control["pause_requested"]:
                    state.update(status="PAUSED_BY_USER", elapsed_seconds=time.perf_counter() - started, running_batches=[])
                    save(STATE, state)
                    return
                time.sleep(2)
                continue
            done, _ = wait(pending, timeout=2, return_when=FIRST_COMPLETED)
            for future in done:
                task = pending.pop(future)
                try:
                    outcome = future.result()
                except BaseException as exc:
                    state["failed_batches"].append({"batch": task[3], "mode": task[0],
                        "error": type(exc).__name__, "message": str(exc)})
                    state.update(status="FAILED_EXPLICIT_REVIEW_NO_RETRY", remaining_unscheduled_batches=len(jobs))
                    save(STATE, state)
                    for remaining in pending:
                        remaining.cancel()
                    raise
                peak = max(peak, outcome["peak_rss"])
                state["completed_batches"].append(outcome)
                field = "reuse_verified_points" if task[0] == "REUSE" else "new_published_points"
                state[field] += outcome["point_count"]
                state["completed_points"] = 252 + state["new_published_points"]
                print("CALMAR_V2_PROGRESS", state["completed_points"], "reuse_checked", state["reuse_verified_points"],
                      "batch", task[3], "peak_GiB", round(peak / 2**30, 3), flush=True)
            state.update(status="DRAINING_PAUSE" if control["pause_requested"] else "RUNNING",
                elapsed_seconds=time.perf_counter() - started,
                running_batches=[{"mode": task[0], "center": task[1], "indices": task[2], "batch": task[3]}
                                 for task in pending.values()])
            save(STATE, state)
    assert state["reuse_verified_points"] == 252 and state["new_published_points"] == 2577
    assert all(sha256((ROOT / path).read_bytes()).hexdigest() == value for path, value in hashes.items())
    state.update(status="ALL_2829_POINTS_COMPLETED_CALMAR_V2", elapsed_seconds=time.perf_counter() - started, running_batches=[])
    save(STATE, state)
    print("CALMAR_V2_ALL_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
