"""Root-authorized technical native-reuse check: no prepare/evaluate/provider."""
from hashlib import sha256
import json
from pathlib import Path

import driver


def main():
    common = driver.legacy_pickle_support()
    method = {"reuse_mapping": {
        "center_reference_manifest": "research/S013/assets/runs/EX058_20261011/account_references.json",
        "parameter_matrix": "research/S013/assets/runs/EX058_20261011/parameter_matrix.json"}}
    source = {path.name: sha256(path.read_bytes()).hexdigest() for path in
              (Path(__file__), Path(driver.__file__), Path(driver.draft.__file__))}
    output = {"status": "RUNNING", "source_hashes": source,
              "new_account_evaluations": 0, "preparations": 0, "publications": 0}
    path = Path(__file__).resolve().parent / "authenticate_readonly.json"
    try:
        center, center_ref, points, refs, plan = driver.authenticated_existing(common.context(1), method)
        output.update(status="PASS", native_unique_accounts=33,
            candidate_ids=[center[0].strategy.candidate_id, *[pair[0].strategy.candidate_id for pair in points]],
            refs=[center_ref.to_dict(), *[ref.to_dict() for ref in refs]],
            native_request_hashes=[center[1].request_hash, *[pair[1].request_hash for pair in points]],
            full_formal_serialization_exact=True, old_plan_exact=True,
            provider_calls=list(common.SOURCE_CALLS),
            limits="Technical reuse authentication only; no new economic-selection conclusion")
        if common.SOURCE_CALLS:
            raise AssertionError("Provider unexpectedly called")
    except Exception as exc:
        output.update(status="FAILED", error={"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        path.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "native_unique_accounts": 33}))


if __name__ == "__main__":
    main()
