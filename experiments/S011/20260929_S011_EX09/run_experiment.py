"""One-shot formal execution; preserve every output in a new S011 archive."""
from pathlib import Path
import json
import shutil
from uuid import uuid4

from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment, preflight_experiment
from research_experiment import ExperimentResources, ExperimentWorkspace, load_experiment, load_experiment_input

PREDECESSOR_RECEIPT = "9f89b54fad04a6e5dbda23b67745e75d9428778bc2ec3bdbfc791bc0737df1e2"


def main():
    root=Path(__file__).resolve().parent
    repository=root.parents[2]
    for name in ("artifacts","03_execution.md","04_conclusion.md","experiment_manifest.json"):
        if (root/name).exists():
            raise FileExistsError(f"EX09 immutable output already exists: {name}")
    loaded=load_experiment(root)
    previous=load_experiment_input(root.parent/"20260929_S011_EX03"/"artifacts",expected_receipt_sha256=PREDECESSOR_RECEIPT)
    resources=ExperimentResources(max_workers=1,random_seed=loaded.definition.random_seed)
    report=preflight_experiment(loaded,resources=resources,predecessors=(previous,))
    report.require_pass()
    workspace=ExperimentWorkspace(repository/".tmp"/"research-experiments"/uuid4().hex/loaded.definition.experiment_id,repository)
    context=create_formal_experiment_context(loaded.definition,repository_root=repository,
        workspace=workspace,resources=resources,predecessors=(previous,))
    try:
        result=execute_experiment(loaded,context)
    except Exception as exc:
        # Preserve a failed formal run; a successor is required for another run.
        shutil.copytree(workspace.root,root/"artifacts")
        (root/"03_execution.md").write_text(f"# S011 EX09 执行\n\nTECHNICAL_FAILURE: {type(exc).__name__}: {exc}\n",encoding="utf-8")
        raise
    if result.receipt is None:
        raise RuntimeError("platform receipt missing")
    shutil.copytree(workspace.root,root/"artifacts")
    (root/"03_execution.md").write_text(
        "# S011 EX09 执行\n\n首次执行前 schema v3 preflight 通过；正式执行完成。\n\n"
        f"receipt：`{result.receipt.sha256}`；outcome：`{result.outcome.value}`。"
        "该状态表示历史数据门仍待证实，具体计数与阻断原因见 artifacts/summary.json。\n",
        encoding="utf-8")
    print(json.dumps({"receipt":result.receipt.sha256,"outcome":result.outcome.value,"facts":dict(result.facts)},ensure_ascii=False))


if __name__ == "__main__":
    main()
