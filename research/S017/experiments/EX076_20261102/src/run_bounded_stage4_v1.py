"""RSCH fixed-point execution through one public TDR session; no nested pools."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OUT = WORK / "others/bounded_v1"
SCRATCH = ROOT / ".tmp/s017-bounded-v1"
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH / "pycache")
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

import argparse
from dataclasses import asdict, replace
import json
import math
from threading import Event, Thread
from time import perf_counter, time
from uuid import uuid4

import psutil
from czsc_trader.application import RepositoryContext, load_candidate, publish_evidence, publish_evidence_many
from czsc_trader import research_tools as d
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import ExecutionResources, canonical_sha256
from strategy_runtime.equity import equity_hash
from strategy_evaluator import ParameterPerformanceEvidence, assessment_benchmark_fingerprint
from strategy_evaluator import research_models as m
from neighborhoods import E, KEYS, request_for, context_for, child_candidate


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = SCRATCH / (uuid4().hex + ".json")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def metric(run):
    values = run["metrics"]
    annual, dd = values["annualized_return"], values["bar_max_drawdown"]
    ratio = annual / dd if dd > 1e-12 else None
    return {"annualized_return": annual, "drawdown": dd,
            "calmar": ratio if ratio is not None and math.isfinite(ratio) else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    proposal = read(WORK / "others/bounded_parameter_check_proposal.json")
    require((WORK / "protocols/confirmed_bounded_stage4_v3.json").is_file()
            and (OUT / "mandate_reference.json").is_file(), "New RSCH protocol and mandate must precede calculation")
    construction = canonical_sha256(proposal["construction"])
    require(construction == "d7d8ce3141d97f7502bef9a7df5213e320c8388e037ac718c10fa682f9471534",
            "Fixed construction differs")
    selection = {key: tuple(p["source_full_plan_point_index"] for p in proposal["centers"][key]["proposed_points"])
                 for key in KEYS}
    require(sum(map(len, selection.values())) == 257, "Declared workload differs")
    declared_protocol = read(WORK / "protocols/confirmed_bounded_stage4_v3.json")
    require(all(selection[key] == tuple(declared_protocol["point_sets"][key]["source_point_indices"])
                and len(selection[key]) == len(set(selection[key]))
                and proposal["centers"][key]["source_full_design_sha256"]
                    == declared_protocol["point_sets"][key]["source_full_design_sha256"] for key in KEYS),
            "Declared per-candidate indices or source designs differ from protocol")
    path, control = OUT / "manifest.json", OUT / "control.json"
    if args.resume:
        manifest = read(path)
        require(manifest["construction_sha256"] == construction and manifest["planned_strategy_accounts"] == 269,
                "Recovery workload differs")
    else:
        require(not path.exists(), "Existing execution requires explicit --resume after review")
        manifest = {"schema": "s017-bounded-stage4-execution/v1", "status": "PREPARING",
            "construction_sha256": construction, "planned_strategy_accounts": 269,
            "planned_parameter_points": 257, "standards": {}, "pressures": {},
            "parameters": {key: [] for key in KEYS}, "batches": [], "old_accounts_mixed": False,
            "sealed_2026_market_data_accessed": False, "independent_account_audits": 0}
        save(path, manifest)
    manifest.setdefault("started_at_unix_seconds", path.stat().st_ctime)
    def elapsed():
        return time() - manifest["started_at_unix_seconds"]
    save(control, {"schema": "s017-bounded-stage4-control/v1", "pause_requested": False,
        "max_workers": 12, "batch_size": 12,
        "user_instruction": "切换RSCH，继续完成阶段四；内存允许时12并发"})
    memory = psutil.virtual_memory()
    require(memory.available > 32 * 2**30, "Insufficient memory for declared execution; review resources")
    repository = RepositoryContext.discover(ROOT)
    centers = {key: load_candidate(repository, CandidateKey("S017", key)) for key in KEYS}
    context = context_for(repository, centers[KEYS[0]])
    context.evaluation.resources = ExecutionResources(12, 1, 17)
    process = psutil.Process()
    memory_stats = {"peak_tree_rss": 0, "minimum_available": memory.available, "samples": 0}
    stopped = Event()

    def observe_memory():
        while not stopped.is_set():
            rss = 0
            for item in (process, *process.children(recursive=True)):
                try:
                    rss += item.memory_info().rss
                except psutil.Error:
                    continue
            memory_stats["peak_tree_rss"] = max(memory_stats["peak_tree_rss"], rss)
            memory_stats["minimum_available"] = min(memory_stats["minimum_available"], psutil.virtual_memory().available)
            memory_stats["samples"] += 1
            stopped.wait(1)

    def progress(value):
        save(OUT / "progress.json", {"phase": value.phase.value, "completed": value.completed,
            "total": value.total, "failed": value.failed, "unknown": value.unknown,
            "elapsed_seconds": elapsed(), "memory": dict(memory_stats)})

    watcher = Thread(target=observe_memory, daemon=True)
    watcher.start()
    try:
        checkpoint = d.ExecutionCheckpointRequest("EX076-bounded-v1-c2640d04c",
            d.CheckpointMode.RESUME if args.resume else d.CheckpointMode.CREATE)
        with d.ResearchExecutionSession(context, experiment=E, checkpoint=checkpoint, on_progress=progress) as execution:
            center_handles, plans, references = {}, {}, {}
            for key in KEYS:
                central = context.evaluation.prepare(request_for(centers[key]), execution=execution)
                center_handles[key] = central
                old_entry = read(WORK / "others/parameter_plans" / (key + "-reference.json"))
                old = d.ParameterEvaluationPlan.from_dict(read(WORK / "others/parameter_plans" / (key + ".json")))
                require(old.design.sha256 == proposal["centers"][key]["source_full_design_sha256"], "Source geometry changed")
                plan_path, ref_path = OUT / "plans" / (key + ".json"), OUT / "plans" / (key + "-reference.json")
                if args.resume and plan_path.exists():
                    plan = d.ParameterEvaluationPlan.from_dict(read(plan_path))
                    entry = read(ref_path)
                    reference = d.EvidenceRef.from_dict(entry["reference"])
                    require(reference.resolve(ROOT).read_bytes() == plan_path.read_bytes(), "Published plan bytes differ")
                else:
                    children = tuple(context.evaluation.prepare(request_for(child_candidate(centers[key], old.design,
                        index, old_entry["start"])), execution=execution) for index in range(old.design.point_count))
                    plan = d.ParameterEvaluationPlan.create(old.design, central, children,
                        mapping_evidence=old.mapping_evidence, feasibility_evidence=old.feasibility_evidence,
                        dataflows=context.data, execution=execution)
                    del children
                    save(plan_path, plan.to_dict())
                    reference = publish_evidence(context, d.MaterialEvidenceWrite(E, "bounded-v1-plan-" + key,
                        plan_path.read_bytes(), "application/json", "json"), execution=execution)
                    entry = {"reference": reference.to_dict(), "start": old_entry["start"],
                        "N": plan.design.point_count, "selected_N": len(selection[key]),
                        "design_sha256": plan.design.sha256, "center_request_sha256": plan.center_request_sha256}
                    save(ref_path, entry)
                require(plan.center_request_sha256 == equity_hash(central.identity(context.evaluation.execution_spec)),
                        "New plan center differs from current implementation")
                plans[key], references[key] = plan, (reference, entry["start"])
                print("PLAN_READY", key, len(selection[key]), flush=True)
            benchmark_metrics = {}

            def calculate(jobs):
                require(not read(control)["pause_requested"], "User requested pause")
                require(psutil.virtual_memory().available > 16 * 2**30
                        and memory_stats["peak_tree_rss"] < 48 * 2**30, "Memory review required before next batch")
                handles = []
                for kind, key, index in jobs:
                    if kind == "standard":
                        handle = center_handles[key]
                    elif kind == "pressure":
                        handle = context.evaluation.prepare(replace(request_for(centers[key]), scenario_id="PRESSURE",
                            measurement_tier="STRESS", fee_rate=.002), execution=execution)
                    else:
                        plan = plans[key]
                        reference, start = references[key]
                        child = child_candidate(centers[key], plan.design, index, start)
                        derivation = CandidateDerivation(centers[key].key, centers[key].content_identity.content_sha256,
                            child.key, child.content_identity.content_sha256, CandidateDerivationKind.PARAMETERS,
                            {v.name: v.value for v in plan.design.points[index].values}, plan.design.protocol.sha256,
                            CandidateEvidence(reference.repository_path, reference.sha256))
                        handle = context.evaluation.prepare(replace(request_for(child), lineage=d.EvaluationLineage(
                            derivation, plan.bind_point(reference, index, repository_root=ROOT))), execution=execution)
                    handles.append(handle)
                handles = tuple(handles)
                batch_begun = perf_counter()
                outcomes = context.evaluation.evaluate_many(handles, execution=execution)
                require(all(o.status.value == "SUCCEEDED" and o.result is not None for o in outcomes),
                        "Account batch failed: " + repr([(o.status.value, o.error) for o in outcomes]))
                publications = publish_evidence_many(context, tuple(d.EvaluationEvidenceWrite(E,
                    f"bounded-v1-{kind}-{handle.candidate.candidate_id}", handle, outcome.result)
                    for (kind, _, _), handle, outcome in zip(jobs, handles, outcomes, strict=True)), execution=execution)
                require(all(p.status.value == "PUBLISHED" for p in publications), "Publication batch incomplete")
                for (kind, key, index), handle, outcome, publication in zip(jobs, handles, outcomes, publications, strict=True):
                    result = outcome.result
                    header = result.payload
                    objects = {item.sha256: item for item in result.artifacts}
                    candidate_run = read_bytes(objects[header["candidate_ref"]["sha256"]].content)["run"]
                    bh_sha = header["benchmark_ref"]["sha256"]
                    if bh_sha not in benchmark_metrics:
                        benchmark_metrics[bh_sha] = metric(read_bytes(objects[bh_sha].content)["run"])
                    row = {"candidate": handle.candidate.candidate_id,
                        "identity": handle.candidate.content_identity.content_sha256,
                        "candidate_metrics": metric(candidate_run), "benchmark_metrics": benchmark_metrics[bh_sha],
                        "evidence": publication.reference.to_dict(), "evaluation_id": header["evaluation_id"],
                        "request_hash": header["request_hash"], "benchmark_ref": header["benchmark_ref"]}
                    del candidate_run
                    if kind == "standard":
                        fact, = d.build_assessment_evidence(handle, result, execution=execution)
                        row.update(metric_context_sha256=fact.context_sha256, metric_version=fact.metric_version,
                            benchmark_equity_sha256=assessment_benchmark_fingerprint(fact))
                        del fact
                        manifest["standards"][key] = row
                    elif kind == "pressure":
                        manifest["pressures"][key] = row
                    else:
                        baseline = manifest["standards"][key]
                        require(header["benchmark_ref"] == baseline["benchmark_ref"], "Parameter benchmark differs")
                        values, bh = row["candidate_metrics"], row["benchmark_metrics"]
                        scene = m.EvaluationScenarioContext(.001, "FORMAL", handle.request.benchmark.benchmark_id,
                            handle.request.benchmark.kind,
                            handle.request.benchmark.fingerprint)
                        binding = handle.request.lineage.parameter_binding
                        projection = ParameterPerformanceEvidence(m.PerformanceFacts(
                            plans[key].children[index].candidate, header["evaluation_id"], scene,
                            values["annualized_return"], values["drawdown"], bh["annualized_return"], bh["drawdown"], index),
                            E.experiment_id, result.result_hash[:32], result.request_hash, result.result_hash,
                            baseline["metric_context_sha256"], "TRAIN_2024_2025", "STANDARD", baseline["metric_version"],
                            100000., 60, baseline["benchmark_equity_sha256"], plans[key].design.center,
                            canonical_sha256(handle.request.lineage.derivation.to_dict()),
                            m.AssessmentDerivationKind.PARAMETERS, binding.point)
                        row.update(index=index, parameter_binding=binding.to_dict(), performance_projection=projection.to_dict())
                        manifest["parameters"][key].append(row)
                    save(path, manifest)
                    print("ACCOUNT_PUBLISHED", kind, key, index, flush=True)
                manifest["batches"].append({"jobs": jobs, "elapsed_seconds": perf_counter() - batch_begun})
                manifest.update(status="RUNNING", elapsed_seconds=elapsed(),
                    execution_stats=asdict(execution.stats), equity_statistics=asdict(execution.equity_statistics),
                    memory=dict(memory_stats))
                save(path, manifest)

            central_jobs = [(kind, key, None) for kind, bucket in (("standard", "standards"), ("pressure", "pressures"))
                            for key in KEYS if key not in manifest[bucket]]
            for offset in range(0, len(central_jobs), 12):
                calculate(central_jobs[offset:offset + 12])
            jobs = [("parameter", key, index) for key in KEYS for index in selection[key]
                    if index not in {r["index"] for r in manifest["parameters"][key]}]
            for offset in range(0, len(jobs), 12):
                calculate(jobs[offset:offset + 12])
            require(len(manifest["standards"]) == len(manifest["pressures"]) == 6
                    and all({row["index"] for row in manifest["parameters"][key]} == set(selection[key]) for key in KEYS),
                    "Final declared workload incomplete")
            require(execution.equity_statistics.benchmark_runs <= 2, "More than two shared benchmarks replayed")
            require(execution.equity_statistics.candidate_runs + execution.stats.reused_results == len(central_jobs) + len(jobs),
                    "Actual successful or restored strategy workload differs")
            manifest.update(status="COMPLETED", elapsed_seconds=elapsed(),
                execution_stats=asdict(execution.stats), equity_statistics=asdict(execution.equity_statistics),
                memory=dict(memory_stats))
            save(path, manifest)
            print("BOUNDED_EXECUTION_COMPLETED", manifest["elapsed_seconds"], flush=True)
    except BaseException as exc:
        manifest.update(status="PAUSED_BY_USER" if read(control)["pause_requested"] else "FAILED_NO_IMPLICIT_RETRY",
            error=repr(exc), elapsed_seconds=elapsed(), memory=dict(memory_stats))
        save(path, manifest)
        raise
    finally:
        stopped.set()
        watcher.join()


def read_bytes(value):
    return json.loads(value)


if __name__ == "__main__":
    main()
