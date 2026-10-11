"""Fake-only checks of result publication audit binding; no native reads."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import postprocess as p
from independent_audit import independent_selection


def main():
    reference = SimpleNamespace(to_dict=lambda: {"frozen_method": "fake"})
    rows = [{"label": "BASE", "queue_index": 0, "center_qualified": True,
             "q10_cagr": .06, "q90_drawdown": .28, "joint_pass_count": 0},
            {"label": "IMPROVED", "queue_index": 1, "center_qualified": True,
             "q10_cagr": .08, "q90_drawdown": .25, "joint_pass_count": 2}]
    analysis = {"selection": p.driver.draft.selection(rows)}
    assert independent_selection(rows) == analysis["selection"]
    state = {"pressure_successful": 1, "evaluation_attempts": 264}
    source = p.EXPERIMENT.resolve(p.ROOT) / "src/independent_audit.py"
    audit = {"status": "PASS", "method_reference": reference.to_dict(),
             "source_sha256": p.digest(source), "selection": independent_selection(rows),
             "counts": {"roles": 297, "unique_configurations": 294, "old_unique_native": 33,
                        "new_unique_business": 261, "new_role_evaluations": 262,
                        "center_fee_pressure": 1, "actual_new_evaluations": 264},
             "new_account_evaluations_by_audit": 0, "preparations": 0, "publications": 0}
    p.validate_independent_audit(audit, reference, analysis, state)
    count = 2
    for key, value in (("status", "PARTIAL"), ("method_reference", {}),
                       ("source_sha256", "0" * 64), ("selection", {}),
                       ("selection", {**audit["selection"], "relative_degradation_report_only": False}),
                       ("selection", {**audit["selection"], "tie_break": "changed"}),
                       ("counts", {**audit["counts"], "new_unique_business": 262}),
                       ("new_account_evaluations_by_audit", 1), ("publications", 1)):
        wrong = deepcopy(audit)
        wrong[key] = value
        try:
            p.validate_independent_audit(wrong, reference, analysis, state)
        except ValueError:
            count += 1
        else:
            raise AssertionError(key)
    folder = Path(__file__).resolve().parent
    p.driver.write(folder / "postprocess_audit_checks.json", {
        "status": "PURE_PASS", "checks": count, "native_reads": 0,
        "evaluations": 0, "preparations": 0, "publications": 0,
        "source_sha256": sha256((folder / "postprocess.py").read_bytes()).hexdigest(),
        "check_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest()})
    print({"status": "PURE_PASS", "checks": count})


if __name__ == "__main__":
    main()
