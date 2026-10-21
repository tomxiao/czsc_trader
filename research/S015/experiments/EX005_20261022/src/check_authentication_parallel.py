"""Four retained accounts: serial/parallel public authentication equivalence only."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from build_assessment import (
    ROOT, WORK, AuthenticatedAccounts, EvidenceRef, authenticate_task,
    load, preload_authentication, read_parameter_plan,
)


def main():
    centers = {row["candidate_id"]: row for row in load(WORK / "centers.json")}
    rows = load(WORK / "results/C0004.json")
    parameter = next(row for row in rows if row["kind"] == "parameter" and row["point_index"] == 0)
    stress = next(row for row in rows if row["kind"] == "stress")
    reference_payload = load(WORK / "plans/C0004.json")["reference"]
    tasks = [(centers["C0004"], None), (centers["C0200"], None),
             (parameter, reference_payload), (stress, None)]
    serial = [authenticate_task(task) for task in tasks]
    parallel = AuthenticatedAccounts()
    preload_authentication(parallel, tasks, 2)
    assert not parallel.evidence and len(parallel.preloaded) == 4
    reference = EvidenceRef.from_dict(reference_payload)
    plan = read_parameter_plan(reference, ROOT)
    for (row, ref), (expected, metadata) in zip(tasks, serial, strict=True):
        actual = parallel.get(row, plan=plan if ref else None, plan_ref=reference if ref else None)
        assert actual.to_dict() == expected.to_dict()
        assert parallel.metadata[actual.evaluation_id] == metadata
    assert not parallel.preloaded
    assert list(parallel.evidence) == [row["evaluation_id"] for row, _ in tasks]
    rejected = []

    def rejects(label, operation):
        try:
            operation()
        except ValueError as error:
            rejected.append({"case": label, "error": str(error)})
        else:
            raise AssertionError(f"cached authentication silently accepted {label}")

    rejects("parameter cache without verified plan", lambda: parallel.get(parameter))
    changed_plan = replace(plan, center_request_sha256="f" * 64)
    rejects("same reference but changed plan object",
            lambda: parallel.get(parameter, plan=changed_plan, plan_ref=reference))
    other_reference = EvidenceRef.from_dict(load(WORK / "plans/C0008.json")["reference"])
    other_plan = read_parameter_plan(other_reference, ROOT)
    rejects("another published parameter plan",
            lambda: parallel.get(parameter, plan=other_plan, plan_ref=other_reference))
    changed_row = deepcopy(parameter)
    changed_row["request_hash"] = "f" * 64
    rejects("changed request identity", lambda: parallel.get(changed_row, plan=plan, plan_ref=reference))
    changed_inputs = deepcopy(parameter)
    changed_inputs["input_bindings"] = {}
    rejects("changed input bindings", lambda: parallel.get(changed_inputs, plan=plan, plan_ref=reference))
    result = {"status": "PASS", "accounts": 4, "authentication_workers": 2,
              "projection_equality": "exact typed to_dict equality", "metadata_equality": "exact",
              "original_consumption_order_preserved": True, "negative_checks": rejected,
              "account_evaluations": 0, "new_account_publications": 0,
              "sources": [row["evidence"] for row, _ in tasks],
              "scope": "Read-only public authentication of retained center, parameter and stress accounts. Does not benchmark8 workers or execute accounts."}
    output = Path(__file__).resolve().parents[1] / "others/authentication_parallel_precheck.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps({key: result[key] for key in ("status", "accounts", "authentication_workers",
                                                  "account_evaluations")}), flush=True)


if __name__ == "__main__":
    main()
