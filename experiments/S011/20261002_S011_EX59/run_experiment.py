from pathlib import Path
import json
import shutil
import traceback
from research_experiment import (
    load_experiment,
    load_experiment_input,
    experiment_source_sha256,
    ExperimentResources,
    ExperimentWorkspace,
)
from czsc_trader.research_tools import (
    preflight_experiment,
    create_formal_experiment_context,
    execute_experiment,
)
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from publication import publish

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
    inputs = json.loads((ROOT / "inputs.json").read_text())
    names = (
        "experiment.py",
        "run_experiment.py",
        "publication.py",
        "inputs.json",
        "01_goal.md",
        "02_design.md",
    )
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
        load_experiment_input(ROOT.parent / ex / "artifacts", expected_receipt_sha256=h)
        for ex, h in inputs["predecessors"].items()
    )
    resources = ExperimentResources(1, 20261002, 1)
    report = preflight_experiment(loaded, resources=resources, predecessors=predecessors)
    write(ROOT / "preflight.json", report.to_dict())
    report.require_pass()
    workspace = ExperimentWorkspace(REPO / ".tmp/s011-full-redelivery/workspaces" / ROOT.name, REPO)
    context = create_formal_experiment_context(
        loaded.definition,
        repository_root=REPO,
        resources=resources,
        workspace=workspace,
        predecessors=predecessors,
    )
    try:
        result = execute_experiment(loaded, context)
    except Exception:
        workspace.path("technical_failure.txt").write_text(
            traceback.format_exc(), encoding="utf-8", newline="\n"
        )
        shutil.copytree(workspace.root, ROOT / "artifacts")
        raise
    shutil.copytree(workspace.root, ROOT / "artifacts")
    receipt = publish()
    (ROOT / "03_execution.md").write_text(
        f"# 执行\n\n受管执行回执 `{result.receipt.sha256}`；阶段三交付发布及公共校验PASS。\n",
        encoding="utf-8",
        newline="\n",
    )
    (ROOT / "04_conclusion.md").write_text(
        "# 阶段三完整交付\n\n状态COMPLETE。36个当前中心均满足原标准成本目标，全部进入handoff；6组历史搜索记录保留573条完成及3条失败提议，扩展搜索轨迹和反证随附件保留。\n\n[阶段三人工报告](deliveries/CANDIDATES/1/report.md) · [机器产物](deliveries/CANDIDATES/1/delivery.json) · [回执](candidates_receipt.json)\n\n阶段四按同一36中心集合继续。已见开发池、历史选择偏差和复权历史时点局限保留；交付完整性不表示稳健性保证。\n",
        encoding="utf-8",
        newline="\n",
    )
    build_experiment_manifest(
        ROOT,
        dict(
            experiment_id=ROOT.name,
            strategy_id="S011",
            symbol="159326.SZ",
            status="COMPLETE",
            development_cutoff="2026-09-28",
        ),
    )
    validate_experiment_archive(ROOT)
    print(json.dumps(dict(status="COMPLETE", reference=receipt.reference.to_dict())), flush=True)


if __name__ == "__main__":
    main()
