"""Preflight, run once, archive; do not overwrite an executed experiment."""

from datetime import timedelta
from pathlib import Path
import json
import shutil
import traceback
from dataflows import Dataflows, LocalCacheConfig
from research_experiment import (
    load_experiment,
    load_experiment_input,
    experiment_source_sha256,
    ExperimentResources,
    ExperimentWorkspace,
)
from czsc_trader.research_tools import (
    preflight_experiment,
    create_experiment_context,
    execute_experiment,
)
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    assert not (ROOT / "artifacts").exists()
    inputs = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))
    names = ("experiment.py", "run_experiment.py", "inputs.json", "01_goal.md", "02_design.md")
    write(
        ROOT / "experiment_binding.json",
        dict(
            schema_version=3,
            module="experiment",
            qualname="Experiment",
            source_files=list(names),
            source_sha256=experiment_source_sha256(ROOT, names),
            dependencies=inputs["dependencies"],
        ),
    )
    loaded = load_experiment(ROOT)
    predecessors = tuple(
        load_experiment_input(ROOT.parent / ex / "artifacts", expected_receipt_sha256=digest)
        for ex, digest in inputs["predecessors"].items()
    )
    resources = ExperimentResources(1, 20261002, 1)
    cache = LocalCacheConfig(
        REPO / ".tmp/s011-regeneration/cache", "S011-20260928-regeneration-v1", timedelta(days=1)
    )
    flows = Dataflows(env_file=REPO / ".env", cache=cache)
    report = preflight_experiment(
        loaded,
        resources=resources,
        predecessors=predecessors,
        dataflows=flows,
        data_requests=(),
    )
    write(ROOT / "preflight.json", report.to_dict())
    report.require_pass()
    workspace = ExperimentWorkspace(REPO / ".tmp/s011-full-redelivery/workspaces" / ROOT.name, REPO)
    context = create_experiment_context(
        loaded.definition,
        repository_root=REPO,
        resources=resources,
        workspace=workspace,
        predecessors=predecessors,
        dataflows=flows,
    )
    failure = None
    try:
        result = execute_experiment(loaded, context)
    except Exception:
        failure = traceback.format_exc()
        workspace.path("technical_failure.txt").write_text(failure, encoding="utf-8", newline="\n")
    shutil.copytree(workspace.root, ROOT / "artifacts")
    status = "TECHNICAL_FAILURE" if failure else "COMPLETE"
    execution = (
        failure
        if failure
        else f"受管执行完成，回执 `{result.receipt.sha256}`。进程隔离；每进程1 worker、1原生线程。"
    )
    (ROOT / "03_execution.md").write_text(
        "# 执行\n\n" + execution + "\n", encoding="utf-8", newline="\n"
    )
    conclusion = (
        "技术失败；详见执行记录，禁止原地重跑。"
        if failure
        else "完成固定候选顺序登记与身份核验；无行情和账户执行。证据见 [登记结果](artifacts/registration_summary.json)。"
    )
    (ROOT / "04_conclusion.md").write_text(
        "# 结论\n\n" + conclusion + "\n", encoding="utf-8", newline="\n"
    )
    build_experiment_manifest(
        ROOT,
        dict(
            experiment_id=ROOT.name,
            strategy_id="S011",
            symbol="159326.SZ",
            status=status,
            development_cutoff="2026-09-28",
        ),
    )
    validate_experiment_archive(ROOT)
    print(json.dumps(dict(experiment=ROOT.name, status=status)), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
