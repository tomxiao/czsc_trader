"""Schedule all fixed points with bounded live batches and explicit failure states."""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from hashlib import sha256
from multiprocessing import get_context
import time

import psutil

from neighborhoods import ROOT, WORK, SCRATCH, PLANS, RECORDS, KEYS, read, save, run_batch, point_order
from strategy_evaluator import research_models as m


def main():
    state_path = WORK / "others/neighborhood_execution.json"
    if state_path.exists():
        raise RuntimeError("Existing execution requires explicit review; no blind resume or retry")
    existing, covered = [], {key: set() for key in KEYS}
    for path in sorted(RECORDS.glob("*.json")):
        record = read(path)
        if record["status"] != "COMPLETED":
            assert record["status"] == "PREPARATION_TYPE_COMPARISON_FAILED_ZERO_ACCOUNTS"
            continue
        assert record["center"] in KEYS
        assert covered[record["center"]].isdisjoint(record["indices"])
        covered[record["center"]].update(record["indices"])
        existing.append({"batch": path.stem, "center": record["center"],
                         "point_count": record["point_count"], "peak_rss": record["peak_rss"],
                         "elapsed_seconds": record["elapsed_seconds"]})
    jobs, full_counts = [], {}
    for key in ("C0338", "C0342", "C0339", "C0340", "C0341", "C0352"):
        design = m.ParameterNeighborhoodDesign.from_dict(read(SCRATCH / "proposed_designs" / (key + ".json")))
        full_counts[key] = design.point_count
        # All points remain scheduled, including centers already failing pressure.
        wrapper = type("Geometry", (), {"design": design})()
        indices = [index for index in point_order(wrapper) if index not in covered[key]]
        for offset in range(0, len(indices), 4):
            jobs.append((key, indices[offset:offset + 4], f"b-{key}-{offset // 4:04d}"))
    assert sum(full_counts.values()) == 2829
    assert sum(len(job[1]) for job in jobs) + sum(map(len, covered.values())) == 2829
    source_hashes = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
                     for path in (WORK / "src/neighborhoods.py", WORK / "src/run_neighborhoods.py",
                                  WORK / "protocols/rsch_bounded_execution.md")}
    save(WORK / "others/neighborhood_job_plan.json", {"all_N": full_counts, "batch_size": 4,
         "prior_completed": {key: sorted(value) for key, value in covered.items()},
         "jobs": [{"center": key, "indices": indices, "label": label} for key, indices, label in jobs],
         "source_hashes": source_hashes, "point_count": 2829, "new_searches": 0})
    started = time.perf_counter()
    state = {"status": "RUNNING", "total_points": 2829, "batch_size": 4,
             "initial_parallel_batches": 2, "maximum_parallel_batches": 8,
             "native_threads_per_worker": 1, "nested_process_pools": False,
             "completed_points": sum(map(len, covered.values())), "completed_batches": existing,
             "failed_batches": [], "resource_decisions": [], "source_hashes": source_hashes,
             "max_tree_rss": 0, "last_update_elapsed_seconds": 0.0}
    pending, successes, peak_batch = {}, 0, 0
    process = psutil.Process()
    budget = min(48 * 2**30, int(psutil.virtual_memory().total * .4))
    save(state_path, state)
    with ProcessPoolExecutor(max_workers=8, mp_context=get_context("spawn"), max_tasks_per_child=1) as executor:
        while jobs or pending:
            tree_rss = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    tree_rss += child.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            state["max_tree_rss"] = max(state["max_tree_rss"], tree_rss)
            # Preparation uses two other bounded processes until its index is complete.
            cap = 2 if successes < 2 else (8 if (PLANS / "index.json").exists() else 6)
            available = psutil.virtual_memory().available
            if peak_batch:
                cap = min(cap, max(1, int(budget / (peak_batch * 1.35))))
            while len(pending) < cap and jobs and tree_rss < budget and available > 16 * 2**30:
                position = next((i for i, job in enumerate(jobs)
                                 if (PLANS / (job[0] + "-reference.json")).exists()), None)
                if position is None:
                    break
                task = jobs.pop(position)
                pending[executor.submit(run_batch, task)] = task
                reservation = int(peak_batch * 1.35) if peak_batch else 2 * 2**30
                tree_rss += reservation
                available -= reservation
            if not state["resource_decisions"] or state["resource_decisions"][-1]["cap"] != cap:
                state["resource_decisions"].append({"elapsed_seconds": time.perf_counter() - started,
                    "cap": cap, "measured_peak_batch_rss": peak_batch, "rss_budget": budget,
                    "available_rss": available})
                print("BOUND_CONCURRENCY", cap, "peak_batch_GiB", round(peak_batch / 2**30, 3), flush=True)
            if not pending:
                state["status"] = "WAITING_FOR_PROSPECTIVE_PLANS_OR_RESOURCE_HEADROOM"
                state["last_update_elapsed_seconds"] = time.perf_counter() - started
                save(state_path, state)
                time.sleep(2)
                continue
            done, _ = wait(pending, timeout=2, return_when=FIRST_COMPLETED)
            for future in done:
                task = pending.pop(future)
                try:
                    result = future.result()
                except BaseException as exc:
                    state["failed_batches"].append({"center": task[0], "indices": task[1],
                        "batch": task[2], "error": type(exc).__name__, "message": str(exc)})
                    state["status"] = "FAILED_EXPLICIT_REVIEW_NO_RETRY"
                    state["remaining_unscheduled_batches"] = len(jobs)
                    save(state_path, state)
                    for other in pending:
                        other.cancel()
                    raise
                assert covered[result["center"]].isdisjoint(task[1])
                covered[result["center"]].update(task[1])
                peak_batch = max(peak_batch, result["peak_rss"])
                successes += 1
                state["completed_batches"].append(result)
                state["completed_points"] += result["point_count"]
                print("FULL_NEIGHBORHOOD_PROGRESS", state["completed_points"], 2829,
                      "batch", result["batch"], "peak_GiB", round(result["peak_rss"] / 2**30, 3), flush=True)
            state["status"] = "RUNNING"
            state["last_update_elapsed_seconds"] = time.perf_counter() - started
            state["running_batches"] = [{"center": task[0], "indices": task[1], "batch": task[2]}
                                         for task in pending.values()]
            save(state_path, state)
    assert state["completed_points"] == 2829 and not state["failed_batches"]
    for key, count in full_counts.items():
        assert covered[key] == set(range(count))
    assert all(sha256((ROOT / path).read_bytes()).hexdigest() == value for path, value in source_hashes.items())
    state.update(status="ALL_2829_POINTS_COMPLETED", elapsed_seconds=time.perf_counter() - started,
                 coverage={key: len(value) for key, value in covered.items()})
    save(state_path, state)
    print("ALL_FULL_NEIGHBORHOODS_COMPLETE", state["coverage"], flush=True)


if __name__ == "__main__":
    main()
