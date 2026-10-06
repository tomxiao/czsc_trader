"""Root-invoked public owner preflight/context/execute driver; no auto retry."""
from pathlib import Path
import json
import shutil
import sys

from dataflows import DataSpace
from research_experiment import ExperimentResources, ExperimentWorkspace, load_experiment
from czsc_trader.research_tools import (
    create_formal_experiment_context, execute_experiment, preflight_experiment,
)
from owner_contract import read, validate_plan, verify_references, authenticate_predecessors, require


def main():
    root, exp = Path.cwd().resolve(), Path(__file__).resolve().parent
    loaded = load_experiment(exp)
    if "--synthetic-only" in sys.argv:
        result = loaded.implementation.synthetic_precheck()
        print("SYNTHETIC_ONLY", len(result.checks))
        return
    require(sys.argv[1:] == [], "unknown driver arguments; no hidden execution modes")
    require(exp == root / "experiments/S012" / loaded.definition.experiment_id, "actual owner path is not formally allocated")
    require(not (exp / "experiment_manifest.json").exists(), "owner is sealed")
    require(not (exp / "artifacts/rex").exists(), "owner already executed or has partial evidence")
    plan = validate_plan(read(exp / "plan.json"), loaded.definition.experiment_id)
    verify_references(root, plan)
    predecessors, _ = authenticate_predecessors(root, plan)
    resources = ExperimentResources(1, loaded.definition.random_seed, 1)
    report = preflight_experiment(loaded, resources=resources, predecessors=predecessors)
    report.require_pass()
    preflight_path = exp / "artifacts/preflight.json"
    preflight_path.parent.mkdir(exist_ok=True)
    preflight_path.write_text(json.dumps({"status": "PASS", "command": "experiment.preflight",
        "result": report.to_dict()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    workspace_root = root / ".tmp/s012-stage3-native-20261006" / loaded.definition.experiment_id / "execution"
    require(not workspace_root.exists(), "execution workspace must be fresh; no retry/overwrite")
    context = create_formal_experiment_context(loaded.definition, repository_root=root,
        data_space=DataSpace(Path("data/backtest")), resources=resources,
        workspace=ExperimentWorkspace(workspace_root, root), predecessors=predecessors)
    try:
        result = execute_experiment(loaded, context)
        print("FORMAL_OWNER", result.outcome.value, dict(result.facts), flush=True)
    finally:
        shutil.copytree(context.workspace.root, exp / "artifacts/rex")


if __name__ == "__main__":
    main()
