"""Retain the second pool failure and resume its missing tail in the live forward pool."""
import argparse
from datetime import datetime
import re
from common import ROOT, EROOT, WORK, EXPERIMENT, context, read, save
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def finish():
    centers = read(WORK / "centers.json")
    assert len(centers) == 98
    assert all(len(read(WORK / "results" / f"{row['candidate_id']}.json")) ==
               (1 if row["candidate_id"] in ("C0030", "C0062") else 33) for row in centers)
    state = read(WORK / "parallel_tail_state.json")
    assert state["status"] == "RESUMED_BY_FORWARD"
    state.update(status="COMPLETE", centers=27, account_scenarios=891,
                 additional_pool_completed_centers=22, forward_resumed_centers=5,
                 execution_mode="resumed_by_forward_after_tail_failure")
    save(WORK / "parallel_tail_state.json", state)
    print({"tail_reconciled": "COMPLETE", "additional_pool": 22, "forward_completed": 5}, flush=True)


def recover():
    failure = WORK / "failure.json"
    detail = read(failure)
    assert detail["parent_id"] == "C0400" and detail["point_index"] == 0
    assert detail["status"] == "UNKNOWN" and detail["error"]["code"] == "BrokenProcessPool"
    assert not (WORK / "results/C0400.json").exists()
    centers = read(WORK / "centers.json")
    tail = centers[71:]
    assert len(tail) == 27 and tail[22]["candidate_id"] == "C0400"
    assert all(len(read(WORK / "results" / f"{r['candidate_id']}.json")) == 33 for r in tail[:22])
    assert all(not (WORK / "results" / f"{r['candidate_id']}.json").exists() for r in tail[22:])
    pattern = re.compile(rb"S015-C(?:39(?:7[6-9]|[89][0-9])|400[0-7]|0400)")
    matches = []
    for path in (ROOT / "research/S015/assets/evidence/EX005_20261022").glob("*.json"):
        if pattern.search(path.read_bytes()):
            payload = read(path)
            matches.append({"file": path.name, "account_evidence": "assessment_evidence" in payload})
    assert matches and all(not item["account_evidence"] for item in matches)
    ctx = context()
    refs = {}
    for name in ("failure", "parallel_tail_failure", "parallel_tail_state"):
        path = WORK / f"{name}.json"
        refs[name] = publish_evidence(ctx, MaterialEvidenceWrite(
            EXPERIMENT, "second_pool_" + name, path.read_bytes(), "application/json", "json"))
        save(EROOT / "others" / f"second_pool_{name}.json", read(path))
    recovery = {
        "created_at": datetime.now().astimezone().isoformat(),
        "reason": "second WinError6/BrokenProcessPool under aggregate16; stable cause not established",
        "decision": "return to one existing8-worker parallel pool; no serial fallback, no platform change",
        "aggregate_max_workers": 8, "native_threads_per_worker": 1,
        "retained_tail_centers": [r["candidate_id"] for r in tail[:22]],
        "forward_resume_centers": [r["candidate_id"] for r in tail[22:]],
        "unknown_evaluation_batch": {"parent": "C0400", "requested_scenarios": 33,
                                     "actual_started_or_finished_count": None,
                                     "status": "UNKNOWN", "first_request_hash": detail["request_hash"]},
        "published_account_matches": 0, "matched_materials": matches,
        "retry": "explicitly retry the same33 C0400 requests, then execute the remaining4 tail centers; retain all published results",
        "boundary_release": "additional pool has exited; restore its held cache so the live forward runner can skip22 completed tail centers and evaluate5 missing centers",
        "failure_references": {key: value.to_dict() for key, value in refs.items()},
    }
    path = EROOT / "others/recovery_02.json"
    assert not path.exists()
    save(path, recovery)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(
        EXPERIMENT, "explicit_tail_recovery_02", path.read_bytes(), "application/json", "json"))
    save(EROOT / "others/recovery_02_ref.json", reference.to_dict())
    temporary_root = (ROOT / ".tmp/s015_stage4").resolve()
    held = (temporary_root / "parallel_tail/C0307.pkl").resolve()
    restored = (temporary_root / "requests/C0307.pkl").resolve()
    assert held.is_relative_to(temporary_root) and restored.is_relative_to(temporary_root)
    assert held.exists() and not restored.exists()
    held.rename(restored)
    save(WORK / "parallel_tail_state.json", {
        "status": "RESUMED_BY_FORWARD", "boundary_cache_restored": True,
        "additional_pool_completed_centers": 22, "remaining_tail_centers": 5,
        "resource_evidence": read(EROOT / "others/resource_addendum_ref.json"),
        "recovery_evidence": reference.to_dict(), "aggregate_max_workers_after_recovery": 8,
    })
    failure.unlink()
    (WORK / "parallel_tail_failure.json").unlink()
    print({"recovery": reference.to_dict(), "workers": 8, "retained_tail_centers": 22}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("recover", "finish"))
    args = parser.parse_args()
    finish() if args.mode == "finish" else recover()
