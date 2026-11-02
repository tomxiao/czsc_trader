"""Archive interrupted work files and explicitly bind every remaining task."""
# ruff: noqa: E402
from partial_selfcheck import ROOT, WORK, read, save

from hashlib import sha256
from pathlib import Path

import psutil


def safe(path):
    path = Path(path).resolve()
    assert path.is_relative_to(WORK.resolve()), "Recovery archive escapes the experiment"
    return path


def main():
    output = WORK / "others/calmar_v3_recovery_manifest.json"
    assert not output.exists(), "Recovery already prepared; inspect instead of recreating"
    inventory = read(WORK / "others/calmar_v2_pool_failure_inventory.json")
    state_path = WORK / "others/neighborhood_execution_v2.json"
    assert sha256(state_path.read_bytes()).hexdigest() == inventory["failed_state_sha256"]
    assert all(item["checkpoint_implementation_matches"] is not False for item in inventory["batches"])
    archive = safe(WORK / "others/interrupted_attempts/calmar_v2_pool_failure")
    assert not archive.exists()
    archive.mkdir(parents=True)
    archived_state = archive / "neighborhood_execution_v2.json"
    archived_state.write_bytes(state_path.read_bytes())
    archived_batches = []
    for item in inventory["batches"]:
        path = safe(ROOT / item["path"])
        if not path.exists():
            assert item["batch_status"] is None
            continue
        record = read(path)
        assert record["status"] == "RUNNING" and not record["records"]
        assert not psutil.pid_exists(record["pid"]), "An interrupted worker still exists"
        assert sha256(path.read_bytes()).hexdigest() == item["batch_file_sha256"]
        target = safe(archive / path.name)
        assert not target.exists()
        path.rename(target)
        assert sha256(target.read_bytes()).hexdigest() == item["batch_file_sha256"]
        archived_batches.append({"original_path": path.relative_to(ROOT).as_posix(),
            "path": target.relative_to(ROOT).as_posix(), "sha256": item["batch_file_sha256"]})
    completed = {}
    for folder in ("neighborhood_batches_v2", "neighborhood_reuse_v2"):
        for path in (WORK / "others" / folder).glob("*.json"):
            batch = read(path)
            assert batch["status"] == "COMPLETED"
            completed[path.stem] = {"path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path.read_bytes()).hexdigest(), "mode": batch["mode"],
                "point_count": batch["point_count"]}
    pending = {item["batch"]: item for item in inventory["batches"]}
    jobs = []
    for job in read(WORK / "others/neighborhood_job_plan_v2.json")["jobs"]:
        if job["label"] in completed:
            continue
        label = job["label"] + "-v3"
        checkpoint = None
        if job["mode"] == "REPLAY":
            prior = pending.get(job["label"])
            if prior is not None and prior["checkpoint_exists"]:
                checkpoint = {"run_id": prior["checkpoint_id"], "mode": "RESUME",
                    "minimum_reused_results": prior["completed_result_files"],
                    "minimum_reused_publications": prior["publication_receipt_files"]}
            else:
                checkpoint = {"run_id": "EX076-calmar-v3-" + job["label"], "mode": "CREATE"}
                assert not (ROOT / ".tmp/research-execution/S017" / checkpoint["run_id"]).exists()
        jobs.append({**job, "label": label, "source_label": job["label"], "checkpoint": checkpoint})
    assert sum(job["point_count"] for job in completed.values() if job["mode"] == "REPLAY") == 192
    assert sum(job["point_count"] for job in completed.values() if job["mode"] == "REUSE") == 108
    assert sum(len(job["indices"]) for job in jobs if job["mode"] == "REPLAY") == 2577 - 192
    assert sum(len(job["indices"]) for job in jobs if job["mode"] == "REUSE") == 252 - 108
    manifest = {"schema": "s017-calmar-v3-recovery/v1", "execution_revision": "v3",
        "failure_review": "research/S017/experiments/EX076_20261102/others/calmar_v2_pool_failure_inventory.json",
        "archived_state": {"path": archived_state.relative_to(ROOT).as_posix(),
            "sha256": sha256(archived_state.read_bytes()).hexdigest()}, "archived_batches": archived_batches,
        "preserved_completed": {"previous_published_points": 252, "new_published_points": 192, "reuse_verified_points": 108},
        "completed_sources": completed, "jobs": jobs,
        "scope": "Explicit recovery after technical review; preserve publications and checkpoints, no automatic fallback or new search",
        "root_cause_proven": False, "memory_exhaustion_proven": False,
        "technical_observation": "WinError 6 invalid handle in process-pool queue; use one independent Popen per bounded batch",
        "authoritative_context": [{"url": "https://github.com/python/cpython/issues/115634",
            "interpretation": "Related worker-recycling issues are documented; this does not prove the same root cause"}]}
    save(output, manifest)
    print("EXPLICIT_V3_RECOVERY_PREPARED", len(jobs), "jobs; archived", len(archived_batches), "interrupted work files", flush=True)


if __name__ == "__main__":
    main()
