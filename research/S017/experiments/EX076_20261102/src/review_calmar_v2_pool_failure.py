"""Read-only inventory after the explicit Windows process-pool failure."""
# ruff: noqa: E402
from partial_selfcheck import ROOT, WORK, read, save

from collections import Counter
from hashlib import sha256

import psutil
from czsc_trader.research_tools._execution_session import implementation_identity


def main():
    path = WORK / "others/neighborhood_execution_v2.json"
    state = read(path)
    assert state["status"] == "FAILED_EXPLICIT_REVIEW_NO_RETRY"
    running = [p.pid for p in psutil.process_iter(["name", "cmdline"])
               if (p.info["name"] or "").lower().startswith("python")
               and any(str(WORK / "src/resume_calmar_v2.py").lower() in item.lower()
                       for item in p.info["cmdline"] or [])]
    assert not running, "Old coordinator still running"
    identity = implementation_identity()
    batches = []
    counts = Counter()
    for folder in ("neighborhood_batches_v2", "neighborhood_reuse_v2"):
        for item in (WORK / "others" / folder).glob("*.json"):
            record = read(item)
            counts[(folder, record["status"])] += record.get("point_count", len(record.get("indices", [])))
    for task in state["running_batches"]:
        folder = "neighborhood_reuse_v2" if task["mode"] == "REUSE" else "neighborhood_batches_v2"
        file = WORK / "others" / folder / (task["batch"] + ".json")
        record = read(file) if file.exists() else None
        checkpoint_id = "EX076-calmar-v2-" + task["batch"]
        checkpoint = ROOT / ".tmp/research-execution/S017" / checkpoint_id
        manifest = read(checkpoint / "manifest.json") if checkpoint.is_dir() else None
        batches.append({**task, "path": file.relative_to(ROOT).as_posix(),
            "batch_file_sha256": sha256(file.read_bytes()).hexdigest() if file.exists() else None,
            "batch_status": None if record is None else record["status"],
            "record_count": None if record is None else len(record["records"]),
            "checkpoint_id": None if task["mode"] == "REUSE" else checkpoint_id,
            "checkpoint_exists": checkpoint.is_dir(),
            "checkpoint_implementation_matches": None if manifest is None else manifest["payload"]["implementation_identity"] == identity,
            "checkpoint_manifest_sha256": None if manifest is None else sha256((checkpoint / "manifest.json").read_bytes()).hexdigest(),
            "completed_result_files": len(list((checkpoint / "results").glob("*.json"))),
            "publication_receipt_files": len(list((checkpoint / "publications").glob("*.json")))})
    output = {"status": "READ_ONLY_POOL_FAILURE_INVENTORY", "exception": "WinError 6 invalid handle in multiprocessing.Queue._sem.release; BrokenProcessPool",
        "root_cause_proven": False, "memory_exhaustion_proven": False,
        "failed_state_sha256": sha256(path.read_bytes()).hexdigest(),
        "current_implementation_identity": identity,
        "batches": batches, "physical_point_counts": {"/".join(key): value for key, value in counts.items()},
        "failed_state_counts_are_not_final_physical_counts": True,
        "financial_execution_changed": False, "automatic_retry_performed": False}
    save(WORK / "others/calmar_v2_pool_failure_inventory.json", output)
    print(output["physical_point_counts"], flush=True)
    for item in batches:
        print(item["batch"], item["batch_status"], "records", item["record_count"],
              "results", item["completed_result_files"], "publications", item["publication_receipt_files"],
              "same_implementation", item["checkpoint_implementation_matches"], flush=True)


if __name__ == "__main__":
    main()
