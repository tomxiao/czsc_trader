"""Freeze declared exact-point study source for root review, no publication."""
# ruff: noqa: E402 -- Bootstrap frozen research module paths before imports.

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import driver as d

assert not (HERE / "freeze.json").exists()
assert not (HERE / "root_execution_authorization.json").exists()
assert not (d.WORK / "perturbation_state.json").exists()
assert d.read(HERE / "point_checks_final.json")["status"] == "PASS"
point_spec = d.read(HERE / "point_specification15.json")
assert point_spec["budget"]["total_new_financial"] == 34
files = sorted([*HERE.glob("*.py"), *HERE.glob("*.json")])
original = d.read(d.WORK / "freeze_v2.json")
assert all(d.digest(d.ROOT / name) == expected for name, expected in original["files"].items())
root_checks = [
    d.WORK / name
    for name in (
        "root_centre_economics.py",
        "root_centre_economics.json",
        "root_point_geometry.py",
        "root_point_geometry.json",
    )
]
assert all(x.exists() for x in root_checks)
output = {
    "status": "FROZEN_EXACT15D_STANDARD32_FEE_SOURCE_AWAIT_ROOT",
    "files": {x.relative_to(d.ROOT).as_posix(): d.digest(x) for x in [*files, *root_checks]},
    "frozen_centre_source_reference": {
        "freeze_v2_sha256": d.digest(d.WORK / "freeze_v2.json"),
        "financial_runtime_sha256": d.read(d.WORK / "feasibility_plan.json")["source_sha256"],
    },
    "exact_point_specification_sha256": d.digest(HERE / "point_specification15.json"),
    "integer_coverage": point_spec["integer_coverage"],
    "budget": point_spec["budget"],
    "no_candidate_point_selection_or_neighbours": True,
    "old_baseline34_reuse": "Authenticated native33standard+independentfee read-only from public EX070 reuse method; no financial reexecution",
    "centre_counterevidence_retained": "Centre original four gates PASS, CAGR14.3985 vs17.1346 and fullDD16.3764 vs13.6187; fullDD is robustness diagnostic target, original DD hard gate remains each natural year",
    "source_selection_bias": point_spec["selection_history"],
    "financial_runs_during_preparation": 0,
}
d.write(HERE / "freeze.json", output)
print(
    json.dumps(
        {
            "status": output["status"],
            "freeze_sha256": d.digest(HERE / "freeze.json"),
            "exact_spec_sha256": output["exact_point_specification_sha256"],
            "files": len(output["files"]),
        }
    )
)
