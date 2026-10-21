"""Run a disjoint tail with eight additional workers after user authorization.

Temporarily reserve the tail's first request cache. The original forward runner
waits at that cache until the entire tail is published, then skips saved rows.
Only a reproducible temporary cache moves; immutable evidence never moves.
"""
from datetime import datetime
import cloudpickle
from common import ROOT, EROOT, WORK, EXPERIMENT, context, read, save
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from run_assessment import TEMP, store_block


def main():
    centers = read(WORK / "centers.json")
    tail = centers[71:]
    assert len(centers) == 98 and len(tail) == 27 and tail[0]["candidate_id"] == "C0307"
    assert read(EROOT / "others/precheck.json")["status"] == "PASS"
    assert all((WORK / "plans" / f"{r['candidate_id']}.json").exists() for r in tail)
    first = tail[0]["candidate_id"]
    source = (TEMP / f"{first}.pkl").resolve()
    held = (ROOT / ".tmp/s015_stage4/parallel_tail" / source.name).resolve()
    temporary_root = (ROOT / ".tmp/s015_stage4").resolve()
    assert source.is_relative_to(temporary_root) and held.is_relative_to(temporary_root)
    assert source.exists() and not held.exists()
    assert all(not (WORK / "results" / f"{r['candidate_id']}.json").exists() for r in tail)
    # The original runner is well before this boundary. Its cache readiness gate
    # prevents it from reaching any tail candidate until this reservation ends.
    active = [i for i, r in enumerate(centers) if
              (WORK / "results" / f"{r['candidate_id']}.json").exists()]
    assert active and max(active) < 65
    ctx = context()
    addendum = {
        "user_text": "是否可以增加并行，以提高速度",
        "authorized_action": "增加并行，保留全部研究口径和已发布证据",
        "created_at": datetime.now().astimezone().isoformat(),
        "hardware": {"physical_cores": 8, "logical_cores": 16, "memory_gb": 127.8},
        "original_max_workers": 8, "aggregate_max_workers": 16,
        "pools": 2, "workers_per_pool": 8, "native_threads_per_worker": 1,
        "forward_centers": [r["candidate_id"] for r in centers[:71]],
        "tail_centers": [r["candidate_id"] for r in tail],
        "boundary": first, "tail_block_size": 33,
        "preserved": ["original protocol bytes", "candidate identities", "32 prescribed parameter points",
                      "fees", "data", "execution contracts", "targets", "ranking policy"],
        "precheck_basis": "Each pool retains the already verified8-worker/1-native-thread configuration; independent candidate sets share no output file.",
        "partition_guard": "The original forward runner waits while the temporary C0307 request cache is held. Restore only after all27 tail centers have33 published results.",
    }
    path = EROOT / "others/resource_addendum.json"
    assert not path.exists()
    save(path, addendum)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(
        EXPERIMENT, "user_authorized_parallel_increase", path.read_bytes(), "application/json", "json"))
    save(EROOT / "others/resource_addendum_ref.json", reference.to_dict())
    held.parent.mkdir(parents=True, exist_ok=True)
    source.rename(held)
    save(WORK / "parallel_tail_state.json", {"status": "RUNNING", "boundary": first,
         "held_cache": held.relative_to(ROOT).as_posix(), "resource_evidence": reference.to_dict()})
    try:
        for ordinal, row in enumerate(tail, start=72):
            cid = row["candidate_id"]
            cache = held if cid == first else TEMP / f"{cid}.pkl"
            requests = cloudpickle.loads(cache.read_bytes())
            assert len(requests["parameters"]) == 32
            items = [(cid, "parameter", index, request)
                     for index, request in enumerate(requests["parameters"])]
            items.append((cid, "stress", None, requests["stress"]))
            assert not (WORK / "results" / f"{cid}.json").exists()
            outputs = ctx.evaluation.evaluate_many(tuple(item[3] for item in items))
            store_block(ctx, items, outputs)
            assert len(read(WORK / "results" / f"{cid}.json")) == 33
            print({"parallel_tail_center": cid, "original_ordinal": ordinal,
                   "tail_completed": ordinal - 71, "tail_total": 27}, flush=True)
        assert all(len(read(WORK / "results" / f"{r['candidate_id']}.json")) == 33 for r in tail)
        assert not source.exists()
        held.rename(source)
        save(WORK / "parallel_tail_state.json", {"status": "COMPLETE", "centers": 27,
             "account_scenarios": 891, "boundary_cache_restored": True,
             "resource_evidence": reference.to_dict()})
    except BaseException as error:
        save(WORK / "parallel_tail_failure.json", {"type": type(error).__name__,
             "message": str(error), "boundary_cache_remains_held": held.exists()})
        raise


if __name__ == "__main__":
    main()
