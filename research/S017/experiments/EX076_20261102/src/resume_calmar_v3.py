"""Explicit manifest recovery with independent, single-batch subprocesses.

No shared process-pool queues, automatic retries, checkpoint mode fallback,
or changes to prior completed evidence. Each worker owns one <=4-point batch.
"""
# ruff: noqa: E402
from resume_calmar_v2 import (
    ROOT, WORK, PLANS, RECORDS, KEYS, E, NEW, REUSE, STATE, CONTROL,
    read, metrics, context_for, bound_request, verify_envelope,
)

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import psutil
from czsc_trader.application import RepositoryContext, load_candidate, publish_evidence_many
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity, build_equity_assessment
from strategy_evaluator.equity_assessment import EquityCertificationScope
from strategy_manager import CandidateKey

MANIFEST = WORK / "others/calmar_v3_recovery_manifest.json"
SCRATCH = ROOT / ".tmp/s017-calmar-v3"
GIB = 2**30


def require(condition, message):
    if not condition:
        raise ValueError(message)


def relative(path):
    return path.resolve().relative_to(ROOT).as_posix()


def owned_path(value):
    require(type(value) is str and not Path(value).is_absolute(), "Expected repository-relative path")
    path = (ROOT / value).resolve()
    require(path.is_relative_to(WORK.resolve()), "Recovery path outside EX076")
    return path


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, value):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    temporary = SCRATCH / (path.name + f".{os.getpid()}.staging")
    with temporary.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def output_path(job):
    return (REUSE if job["mode"] == "REUSE" else NEW) / (job["label"] + ".json")


def load_manifest():
    manifest = read(MANIFEST)
    require(manifest["schema"] == "s017-calmar-v3-recovery/v1"
            and manifest["execution_revision"] == "v3", "Recovery schema/revision differs")
    owned_path(manifest["failure_review"]).read_bytes()
    for item in (manifest["archived_state"], *manifest["archived_batches"]):
        require(digest(owned_path(item["path"])) == item["sha256"], "Archived evidence hash differs")
    for item in manifest["archived_batches"]:
        require(not owned_path(item["original_path"]).exists(), "Old RUNNING output was not archived")
    jobs = manifest["jobs"]
    require(type(jobs) is list and len({x["label"] for x in jobs}) == len(jobs), "Duplicate job label")
    checkpoints, coordinates = set(), set()
    for job in jobs:
        require(job["mode"] in ("REUSE", "REPLAY") and job["center"] in KEYS, "Unknown recovery job")
        require(all(type(job[name]) is str and re.fullmatch(r"[A-Za-z0-9_-]+", job[name])
                    for name in ("label", "source_label")), "Unsafe batch alias")
        indices = job["indices"]
        require(type(indices) is list and 1 <= len(indices) <= 4
                and all(type(x) is int and x >= 0 for x in indices)
                and len(set(indices)) == len(indices), "Invalid batch indices")
        for index in indices:
            key = (job["mode"], job["center"], index)
            require(key not in coordinates, "Duplicate manifest point")
            coordinates.add(key)
        checkpoint = job["checkpoint"]
        if job["mode"] == "REUSE":
            require(checkpoint is None, "REUSE must not create a replay checkpoint")
        else:
            mode = d.CheckpointMode(checkpoint["mode"])
            d.ExecutionCheckpointRequest(checkpoint["run_id"], mode)
            require(checkpoint["run_id"] not in checkpoints, "Duplicate checkpoint writer")
            checkpoints.add(checkpoint["run_id"])
            for name in ("minimum_reused_results", "minimum_reused_publications"):
                require(type(checkpoint.get(name, 0)) is int
                        and 0 <= checkpoint.get(name, 0) <= len(indices), "Invalid reuse minimum")
    return manifest


def completed_record(path, job=None):
    value = read(path)
    require(value["status"] == "COMPLETED", f"Existing incomplete batch needs review: {relative(path)}")
    require(value["center"] in KEYS and value["point_count"] == len(value["indices"]) == len(value["records"]),
            "Completed batch count differs")
    require([x["index"] for x in value["records"]] == value["indices"], "Completed record indices differ")
    if job is not None:
        require((value["mode"], value["center"], value["indices"], value.get("source_label"))
                == (job["mode"], job["center"], job["indices"], job["source_label"]), "Completed recovery job differs")
        require(value.get("execution_revision") == "v3", "Recovery output revision differs")
        require(value.get("checkpoint") == job["checkpoint"], "Recovery checkpoint alias differs")
    return value


def inventory(manifest, *, worker=False):
    """Validate complete point partitions without loading account/checkpoint ledgers."""
    old, completed, peaks = {}, {}, []
    for path in sorted(RECORDS.glob("*.json")):
        value = read(path)
        if value["status"] == "PREPARATION_TYPE_COMPARISON_FAILED_ZERO_ACCOUNTS":
            require(not value.get("records"), "Failed preparation has unexpected records")
            continue
        value = completed_record(path)
        for row in value["records"]:
            key = value["center"], row["index"]
            require(key not in old, "Duplicate old point")
            old[key] = row
        peaks.append(value["peak_rss"])
    require(len(old) == 252, "Original published point count differs")
    sources = manifest["completed_sources"]
    require(type(sources) is dict, "completed_sources must be keyed by original label")
    for label, source in sources.items():
        path = owned_path(source["path"])
        require(path.stem == label and digest(path) == source["sha256"], "Preserved completed source differs")
        value = completed_record(path)
        require(value["mode"] == source["mode"] and value["point_count"] == source["point_count"],
                "Preserved completed source mode/count differs")
    allowed = {owned_path(item["path"]) for item in sources.values()}
    allowed.update(output_path(job).resolve() for job in manifest["jobs"])
    coverage = {"REPLAY": set(), "REUSE": set()}
    jobs_by_path = {output_path(job).resolve(): job for job in manifest["jobs"]}
    for directory in (NEW, REUSE):
        for path in sorted(directory.glob("*.json")):
            require(path.resolve() in allowed, "Unreviewed output in recovery directories")
            if worker and path.resolve() in jobs_by_path:
                current = read(path)
                if current["status"] != "COMPLETED":
                    require(current.get("execution_revision") == "v3"
                            and current.get("recovery_manifest_sha256") == digest(MANIFEST),
                            "Unreviewed active/failed recovery output")
                    # Sibling subprocesses may still be writing their own jobs.
                    # The coordinator alone decides whether dispatch must stop.
                    continue
            value = completed_record(path, jobs_by_path.get(path.resolve()))
            require(value["mode"] == ("REUSE" if directory == REUSE else "REPLAY"), "Batch directory/mode differs")
            for row in value["records"]:
                coordinate = value["center"], row["index"]
                require(coordinate not in coverage[value["mode"]], "Duplicate completed point")
                coverage[value["mode"]].add(coordinate)
                if value["mode"] == "REUSE":
                    require(coordinate in old and all(row[name] == old[coordinate][name] for name in (
                        "candidate", "identity", "evaluation_id", "request_hash", "evidence", "parameter_binding",
                        "candidate_metrics", "benchmark_metrics")), "Reuse receipt differs from original")
                else:
                    require(coordinate not in old, "Replay duplicates old published point")
            completed[path.stem] = value
            peaks.append(value["peak_rss"])
    base_counts = {"REPLAY": 0, "REUSE": 0}
    for source in sources.values():
        base_counts[source["mode"]] += source["point_count"]
    require(manifest["preserved_completed"] == {
        "previous_published_points": 252, "new_published_points": base_counts["REPLAY"],
        "reuse_verified_points": base_counts["REUSE"]}, "Preserved count declaration differs")
    required = set()
    for key in KEYS:
        plan = d.ParameterEvaluationPlan.from_dict(read(PLANS / (key + ".json")))
        required.update((key, i) for i in range(plan.design.point_count))
    require(len(required) == 2829 and set(old) <= required, "Complete design point set differs")
    for mode, expected in (("REPLAY", required - set(old)), ("REUSE", set(old))):
        declared = set(coverage[mode])
        for job in manifest["jobs"]:
            if job["mode"] == mode and job["label"] not in completed:
                points = {(job["center"], i) for i in job["indices"]}
                require(declared.isdisjoint(points), "Job duplicates completed point")
                declared.update(points)
        require(declared == expected, "Recovery jobs do not cover the exact remaining full point set")
    return old, completed, max(peaks)


def batch(job, old):
    begun, process, path = time.perf_counter(), psutil.Process(), output_path(job)
    require(not path.exists(), "Existing batch requires explicit review; no retry")
    entry = read(PLANS / (job["center"] + "-reference.json"))
    plan = d.ParameterEvaluationPlan.from_dict(read(PLANS / (job["center"] + ".json")))
    reference = d.EvidenceRef.from_dict(entry["reference"])
    require(reference.resolve(ROOT).read_bytes() == (PLANS / (job["center"] + ".json")).read_bytes(),
            "Published complete plan differs")
    result = {"status": "RUNNING", "mode": job["mode"], "center": job["center"],
        "indices": job["indices"], "pid": process.pid, "records": [], "execution_revision": "v3",
        "source_label": job["source_label"], "checkpoint": job["checkpoint"],
        "recovery_manifest_sha256": digest(MANIFEST), "rule_version": "MANDATE/8",
        "business_gate_owner": "RSCH", "legacy_annual_joint_gate_used": False}
    write(path, result)
    try:
        if job["mode"] == "REUSE":
            with EquityCertificationScope() as certification:
                for index in job["indices"]:
                    row = old[job["center"], index]
                    ref = d.EvidenceRef.from_dict(row["evidence"])
                    top = ref.resolve(ROOT)
                    data = top.read_bytes()
                    envelope = json.loads(data)
                    allowed = {(envelope[name]["kind"], envelope[name]["sha256"])
                               for name in ("input_ref", "candidate_ref", "benchmark_ref")}

                    def resolve(item):
                        require((item["kind"], item["sha256"]) in allowed, "Unowned account artifact")
                        content = (top.parent / (item["sha256"] + ".json")).read_bytes()
                        require(sha256(content).hexdigest() == item["sha256"], "Account artifact hash differs")
                        return content

                    view = materialize_equity(data, resolve)
                    fact, = build_equity_assessment(view, scope=certification)
                    payload = view.payload
                    verify_envelope(payload, job["center"], index, plan, reference)
                    require(fact.evaluation_id == row["evaluation_id"] and payload["request_hash"] == row["request_hash"],
                            "Reused account identity differs")
                    require(metrics(payload["runs"]["candidate"]) == row["candidate_metrics"]
                            and metrics(payload["runs"]["buy_hold"]) == row["benchmark_metrics"], "Reused metrics differ")
                    result["records"].append({name: row[name] for name in (
                        "index", "candidate", "identity", "candidate_metrics", "benchmark_metrics", "evidence",
                        "evaluation_id", "request_hash", "parameter_binding")})
                result["authenticated_unique_ledgers"] = certification.audit_count
        else:
            checkpoint = job["checkpoint"]
            repository = RepositoryContext.discover(ROOT)
            center = load_candidate(repository, CandidateKey("S017", job["center"]))
            context = context_for(repository, center)
            require(context.evaluation.resources.max_workers == 1, "Batch must have no nested process pool")
            with d.ResearchExecutionSession(context, experiment=E, checkpoint=d.ExecutionCheckpointRequest(
                    checkpoint["run_id"], d.CheckpointMode(checkpoint["mode"]))) as execution:
                handles = tuple(bound_request(context, center, plan, reference, entry["start"], index, execution)
                                for index in job["indices"])
                outcomes = context.evaluation.evaluate_many(handles, execution=execution)
                require(all(x.status.value == "SUCCEEDED" and x.result is not None for x in outcomes),
                        "Explicit evaluation failure/unknown; no retry")
                publications = publish_evidence_many(context, tuple(d.EvaluationEvidenceWrite(E,
                    "neighbor-" + handle.candidate.candidate_id, handle, value.result)
                    for handle, value in zip(handles, outcomes, strict=True)), execution=execution)
                require(all(x.status.value == "PUBLISHED" for x in publications), "Publication incomplete; no retry")
                for index, handle, outcome, publication in zip(job["indices"], handles, outcomes, publications, strict=True):
                    payload = materialize_equity(outcome.result).payload
                    verify_envelope(payload, job["center"], index, plan, reference)
                    result["records"].append({"index": index, "candidate": handle.candidate.candidate_id,
                        "identity": handle.candidate.content_identity.content_sha256,
                        "candidate_metrics": metrics(payload["runs"]["candidate"]),
                        "benchmark_metrics": metrics(payload["runs"]["buy_hold"]),
                        "evidence": publication.reference.to_dict(), "evaluation_id": payload["evaluation_id"],
                        "request_hash": payload["request_hash"],
                        "parameter_binding": handle.request.lineage.parameter_binding.to_dict()})
                stats = execution.stats
                require(stats.pool_starts == 0, "Unexpected nested pool")
                require(stats.reused_results >= checkpoint.get("minimum_reused_results", 0)
                        and stats.reused_publications >= checkpoint.get("minimum_reused_publications", 0),
                        "Expected checkpoint reuse did not occur")
                result["execution_stats"] = {"session": asdict(stats), "equity": asdict(execution.equity_statistics)}
        memory = process.memory_info()
        result.update(status="COMPLETED", elapsed_seconds=time.perf_counter() - begun,
            peak_rss=memory.peak_wset, rss_after=memory.rss, point_count=len(job["indices"]), full_N=entry["N"])
        write(path, result)
        print("CALMAR_V3_BATCH_COMPLETE", job["label"], len(job["indices"]), flush=True)
    except BaseException as exc:
        result.update(status="EXPLICIT_EXECUTION_FAILURE_NO_RETRY", error=type(exc).__name__, message=str(exc),
                      elapsed_seconds=time.perf_counter() - begun)
        write(path, result)
        raise


def coordinate(manifest, completed, peak):
    if STATE.exists():
        previous = read(STATE)
        archived_failure = digest(STATE) == manifest["archived_state"]["sha256"]
        paused = (previous.get("execution_revision") == "v3" and previous["status"] == "PAUSED_BY_USER"
                  and previous.get("recovery_manifest_sha256") == digest(MANIFEST)
                  and not previous.get("running_batches"))
        require(archived_failure or paused, "Live state needs explicit review before replacement")
    jobs = [x for x in manifest["jobs"] if x["label"] not in completed]
    guard = (Path(__file__).resolve(), MANIFEST, WORK / "src/resume_calmar_v2.py", WORK / "src/neighborhoods.py",
             WORK / "others/calmar_v2_targets.json", WORK / "protocols/confirmed_calmar_selfcheck_v2.json")
    hashes = {relative(path): digest(path) for path in guard}
    hashes.update({item["path"]: item["sha256"] for item in manifest["completed_sources"].values()})
    hashes.update({relative(path): digest(path) for path in RECORDS.glob("*.json")})
    hashes.update({relative(path): digest(path) for path in PLANS.glob("*.json")})
    state = {"status": "RUNNING", "execution_revision": "v3", "rule_version": "MANDATE/8",
        "failure_review": manifest["failure_review"], "recovery_manifest_sha256": digest(MANIFEST),
        "recovered_aliases": [{"source_label": x["source_label"], "label": x["label"], "checkpoint": x["checkpoint"]}
                              for x in manifest["jobs"]],
        "maximum_parallel_batches": 12, "batch_size": 4, "native_threads_per_worker": 1,
        "nested_pools": False, "shared_process_pool": False, "previously_published_points": 252,
        "reuse_verified_points": sum(x["point_count"] for x in completed.values() if x["mode"] == "REUSE"),
        "new_published_points": sum(x["point_count"] for x in completed.values() if x["mode"] == "REPLAY"),
        "total_points": 2829, "completed_batches": [], "failed_batches": [], "running_batches": [],
        "max_tree_rss": 0, "source_hashes": hashes, "resource_decisions": []}
    state["completed_points"] = 252 + state["new_published_points"]
    started, pending, pause, stopped = time.perf_counter(), {}, False, False
    process = psutil.Process()
    budget = min(48 * GIB, int(psutil.virtual_memory().total * .4))

    def request_pause(*_):
        nonlocal pause
        pause = True

    signal.signal(signal.SIGINT, request_pause)
    signal.signal(signal.SIGTERM, request_pause)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    def fail(label, exc):
        nonlocal stopped
        stopped = True
        state["failed_batches"].append({"batch": label, "error": type(exc).__name__, "message": str(exc)})
        print("CALMAR_V3_STOP_DISPATCH_DRAINING", label, type(exc).__name__, str(exc), flush=True)

    while jobs or pending:
        try:
            control = read(CONTROL)
            require(control["schema"] == "s017-rsch-execution-control/v1"
                    and type(control["pause_requested"]) is bool, "Invalid execution control")
            require(type(control["max_parallel_batches"]) is int
                    and 1 <= control["max_parallel_batches"] <= 12, "Invalid concurrency cap")
            pause = pause or control["pause_requested"]
            require(all(digest(ROOT / path) == expected for path, expected in hashes.items()), "Frozen input/source changed")
            rss = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            state["max_tree_rss"] = max(state["max_tree_rss"], rss)
            reservation = int(peak * 1.35)
            reserved = process.memory_info().rss
            for item in pending.values():
                try:
                    resident = psutil.Process(item["process"].pid).memory_info().rss
                except psutil.NoSuchProcess:
                    resident = 0
                reserved += max(reservation, resident)
            reserved = max(reserved, rss)
            available = psutil.virtual_memory().available - max(0, reserved - rss)
            cap = min(control["max_parallel_batches"], max(1, int(budget / reservation)))
            if not state["resource_decisions"] or state["resource_decisions"][-1]["cap"] != cap:
                state["resource_decisions"].append({"elapsed_seconds": time.perf_counter() - started,
                    "cap": cap, "measured_batch_peak_rss": peak, "rss_budget": budget})
                print("CALMAR_V3_CONCURRENCY", cap, "budget_GiB", budget / GIB, flush=True)
            while jobs and not pause and not stopped and len(pending) < cap \
                    and reserved + reservation <= budget and available - reservation >= 16 * GIB:
                job = jobs[0]
                require(not output_path(job).exists(), "Unreviewed batch appeared before dispatch")
                log_path = SCRATCH / (job["label"] + ".log")
                with log_path.open("xb") as log:
                    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--single-batch", job["label"]],
                        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        shell=False, creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
                        if os.name == "nt" else 0)
                pending[child.pid] = {"process": child, "job": jobs.pop(0), "log": relative(log_path)}
                reserved += reservation
                available -= reservation
        except Exception as exc:
            if not stopped:
                fail("COORDINATOR", exc)
        for pid, item in tuple(pending.items()):
            code = item["process"].poll()
            if code is None:
                continue
            job = item["job"]
            del pending[pid]
            try:
                require(code == 0, f"Independent batch exited {code}; see {item['log']}")
                result = completed_record(output_path(job), job)
                peak = max(peak, result["peak_rss"])
                field = "reuse_verified_points" if job["mode"] == "REUSE" else "new_published_points"
                state[field] += result["point_count"]
                state["completed_points"] = 252 + state["new_published_points"]
                state["completed_batches"].append({"batch": job["label"], "source_label": job["source_label"],
                    "center": job["center"], "mode": job["mode"], "point_count": result["point_count"],
                    "peak_rss": result["peak_rss"], "log": item["log"]})
                print("CALMAR_V3_PROGRESS", state["completed_points"], "reuse_checked", state["reuse_verified_points"],
                      "batch", job["label"], flush=True)
            except Exception as exc:
                fail(job["label"], exc)
        state.update(status="DRAINING_FAILURE" if stopped else "DRAINING_PAUSE" if pause else "RUNNING",
            elapsed_seconds=time.perf_counter() - started, remaining_unscheduled_batches=len(jobs),
            running_batches=[{"mode": x["job"]["mode"], "center": x["job"]["center"], "indices": x["job"]["indices"],
                              "batch": x["job"]["label"], "pid": pid, "log": x["log"]} for pid, x in pending.items()])
        if not pending and (pause or stopped):
            state["status"] = "FAILED_EXPLICIT_REVIEW_NO_RETRY" if stopped else "PAUSED_BY_USER"
        try:
            write(STATE, state)
        except Exception as exc:
            if not stopped:
                fail("STATE_WRITE", exc)
        if not pending and (pause or stopped):
            if stopped:
                raise RuntimeError("Execution stopped after draining active batches; explicit review required")
            return
        if jobs or pending:
            time.sleep(2)
    require(state["reuse_verified_points"] == 252 and state["new_published_points"] == 2577,
            "Final point totals differ")
    require(all(digest(ROOT / path) == expected for path, expected in hashes.items()), "Frozen sources changed")
    state.update(status="ALL_2829_POINTS_COMPLETED_CALMAR_V2", elapsed_seconds=time.perf_counter() - started,
                 running_batches=[], completed_points=2829)
    write(STATE, state)
    print("CALMAR_V3_ALL_COMPLETE", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--single-batch", metavar="LABEL")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    manifest = load_manifest()
    old, completed, peak = inventory(manifest, worker=args.single_batch is not None)
    if args.check_only:
        print("CALMAR_V3_MANIFEST_AND_FULL_PARTITION_VALID", len(manifest["jobs"]), len(completed), flush=True)
        return
    if args.single_batch is not None:
        chosen = [x for x in manifest["jobs"] if x["label"] == args.single_batch]
        require(len(chosen) == 1, "Batch alias absent from explicit recovery manifest")
        batch(chosen[0], old)
    else:
        coordinate(manifest, completed, peak)


if __name__ == "__main__":
    main()
