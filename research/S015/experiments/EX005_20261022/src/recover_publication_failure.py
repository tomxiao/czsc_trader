"""Retain the publication failure and authorize one explicit same-point retry."""
from datetime import datetime
import re
from common import ROOT, EROOT, WORK, EXPERIMENT, context, read, save
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def main():
    failure = WORK / "publication_failure.json"
    original_bytes = failure.read_bytes()
    detail = read(failure)
    assert detail["row"]["parent_id"] == "C0243" and detail["row"]["point_index"] == 0
    assert detail["status"] == "FAILED" and "BrokenProcessPool" in detail["error"]
    assert not (WORK / "results/C0243.json").exists()
    pattern = re.compile(rb"S015-C27(?:2[89]|3[0-9]|4[0-3])")
    matched = []
    files = list((ROOT / "research/S015/assets/evidence/EX005_20261022").glob("*.json"))
    for path in files:
        if pattern.search(path.read_bytes()):
            record = read(path)
            matched.append({"name": path.name, "type": record.get("type"),
                            "account_evidence": "assessment_evidence" in record})
    assert matched and all(not item["account_evidence"] for item in matched), matched
    ctx = context()
    save(EROOT / "others/publication_failure_attempt1.json", detail)
    failure_ref = publish_evidence(ctx, MaterialEvidenceWrite(
        EXPERIMENT, "publication_failure_attempt1", original_bytes, "application/json", "json"))
    source = EROOT / "src/run_assessment.py"
    source_ref = publish_evidence(ctx, MaterialEvidenceWrite(
        EXPERIMENT, "orchestration_before_publication_retry", source.read_bytes(), "text/x-python", "py"))
    recovery = {
        "created_at": datetime.now().astimezone().isoformat(),
        "failure": failure_ref.to_dict(), "previous_orchestration": source_ref.to_dict(),
        "phase": "publication", "system_error": "WinError6 / BrokenProcessPool",
        "cause": "not established; no strategy or data failure inferred",
        "parent": "C0243", "point_indices": list(range(16)),
        "candidate_ids": [f"C{x}" for x in range(2728, 2744)],
        "successful_evaluations_without_retained_publication": 16,
        "published_account_matches": 0, "matched_materials": matched,
        "scanned_files": len(files),
        "first_result_hash": detail["row"]["result_hash"],
        "first_request_hash": detail["row"]["request_hash"],
        "decision": "explicitly retry only missing same prescribed identities; retain successful published results; no replacement points",
        "resume_batch_size": 33, "workers_per_pool": 8, "aggregate_limit": 16,
        "publication_resilience": "retain failed future block outputs and all publication statuses for explicit recovery if another failure occurs; no automatic retry or serial fallback",
        "assessment_interruption": "the waiting verifier stopped on failure; restart public authentication in parallel after all account checkpoints complete",
    }
    path = EROOT / "others/recovery_01.json"
    assert not path.exists()
    save(path, recovery)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(
        EXPERIMENT, "explicit_publication_recovery_01", path.read_bytes(), "application/json", "json"))
    save(EROOT / "others/recovery_01_ref.json", reference.to_dict())
    assert failure.read_bytes() == original_bytes
    failure.unlink()  # Resolved mutable stop marker; original bytes are published above.
    print({"retained_failure": failure_ref.to_dict(), "retry_points": 16,
           "published_matches": 0, "recovery": reference.to_dict()}, flush=True)


if __name__ == "__main__":
    main()
