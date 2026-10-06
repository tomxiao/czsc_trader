"""Local S012 final-owner plan validation and evidence authentication."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re

from research_experiment import load_experiment, load_experiment_input


SHA = re.compile(r"[0-9a-f]{64}")
EID = re.compile(r"EX(?!000)[0-9]{3}_[0-9]{8}")
GOALS = {
    "net_cagr": {"operator": ">=", "benchmark_multiplier": 1.5},
    "absolute_max_drawdown": {"operator": "<", "benchmark": "BuyHold"},
    "closed_cycle_frequency": {"operator": ">=", "threshold": 5, "window_days": 60, "denominator": 1535},
}
PRIORITY = ["net_cagr descending", "absolute_max_drawdown ascending", "actual_closed_frequency descending"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def relative(value):
    require(isinstance(value, str) and value and "\\" not in value and ":" not in value,
            "paths must be non-empty repository-relative POSIX strings")
    path = PurePosixPath(value)
    require(path.parts and not path.is_absolute() and path.as_posix() == value and not any(p in (".", "..") for p in path.parts),
            "relative path contains normalization or traversal")
    return path


def resolve(root, value):
    path = (Path(root).resolve() / relative(value)).resolve()
    path.relative_to(Path(root).resolve())
    return path


def evidence_reference(item, owner_eid):
    require(isinstance(item, dict) and set(item) == {"path", "sha256"}, "evidence must contain exact path/sha256")
    relative(item["path"])
    require(isinstance(item["sha256"], str) and SHA.fullmatch(item["sha256"]), "evidence hash must be raw SHA256")
    require(not item["path"].startswith(f"experiments/S012/{owner_eid}/"), "owner input cannot refer to its future evidence")
    require(item["path"].startswith(("experiments/S012/", "research/S012/", ".tmp/s012")),
            "owner input is outside authorized S012 evidence")


def validate_plan(plan, owner_eid):
    require(isinstance(owner_eid, str) and EID.fullmatch(owner_eid), "owner eid must be root-allocated EXNNN_YYYYMMDD")
    require(isinstance(plan, dict) and plan.get("schema_version") == 1, "plan schema_version must be1")
    required = {"schema_version", "status", "incomplete", "predecessor_receipts", "source_evidence", "frozen_files",
                "three_goals", "priority", "all_window_seen", "research_decision", "allowed_datasets"}
    require(set(plan) == required, "plan fields differ from local schema")
    require(plan["status"] == "COMPLETE" and plan["incomplete"] == [], "scientific plan must explicitly COMPLETE with no incomplete items")
    require(plan["three_goals"] == GOALS and plan["priority"] == PRIORITY and plan["all_window_seen"] is True,
            "original simultaneous goals, return priority and observed window must remain")
    datasets = plan["allowed_datasets"]
    require(isinstance(datasets, list) and datasets and all(isinstance(v, str) and v for v in datasets)
            and len(datasets) == len(set(datasets)), "allowed_datasets must name nonempty existing resources")
    decision = plan["research_decision"]
    require(isinstance(decision, dict) and set(decision) == {"status", "rationale", "evidence"}, "research_decision fields differ")
    require(decision["status"] == "COMPLETE" and isinstance(decision["rationale"], str) and decision["rationale"].strip(),
            "root must supply an explicit completion rationale; no automatic closure")
    require(isinstance(decision["evidence"], list) and decision["evidence"], "completion decision needs real evidence")
    predecessors = plan["predecessor_receipts"]
    require(isinstance(predecessors, dict) and predecessors, "owner must have complete predecessor receipts")
    for eid, value in predecessors.items():
        require(isinstance(eid, str) and EID.fullmatch(eid) and eid != owner_eid, "invalid/self predecessor")
        require(isinstance(value, str) and SHA.fullmatch(value), "predecessor canonical receipt hash invalid")
    require(isinstance(plan["source_evidence"], list) and plan["source_evidence"], "source_evidence must not be empty")
    for item in [*plan["source_evidence"], *decision["evidence"]]:
        evidence_reference(item, owner_eid)
    files = plan["frozen_files"]
    require(isinstance(files, list) and files, "owner must aggregate frozen existing files")
    names = []
    for item in files:
        require(isinstance(item, dict) and set(item) == {"target_name", "path", "sha256"}, "frozen_file fields differ")
        relative(item["target_name"])
        evidence_reference({"path": item["path"], "sha256": item["sha256"]}, owner_eid)
        names.append(item["target_name"])
    normalized_names = [name.casefold() for name in names]
    require(len(names) == len(set(normalized_names)), "frozen target names must be unique on Windows")
    require(not any(a != b and b.startswith(a + "/") for a in normalized_names for b in normalized_names),
            "frozen targets contain a file/directory collision")
    return plan


def verify_references(root, plan):
    items = [*plan["source_evidence"], *plan["research_decision"]["evidence"], *plan["frozen_files"]]
    for item in items:
        require(digest(resolve(root, item["path"])) == item["sha256"], f"evidence SHA changed: {item['path']}")


def authenticate_predecessors(root, plan):
    inputs, checked = [], []
    for eid, expected in plan["predecessor_receipts"].items():
        exp = resolve(root, f"experiments/S012/{eid}")
        loaded = load_experiment(exp)
        previous = load_experiment_input(exp / "artifacts/rex", expected_receipt_sha256=expected)
        receipt = read(exp / "artifacts/rex/execution_receipt.json")
        require(previous.experiment_id == eid and loaded.definition.experiment_id == eid,
                "predecessor actual experiment id differs")
        require(receipt["source_sha256"] == loaded.binding.source_sha256
                and receipt["definition_sha256"] == loaded.definition.sha256,
                "predecessor receipt differs from authenticated source/definition")
        inputs.append(previous)
        checked.append({"experiment_id": eid, "receipt_sha256": expected,
                        "source_sha256": loaded.binding.source_sha256,
                        "definition_sha256": loaded.definition.sha256})
    return tuple(inputs), checked
