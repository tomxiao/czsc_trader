from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from dataflows import Dataflows
from research_experiment import ExperimentResources, ExperimentWorkspace, load_experiment
from czsc_trader.research_tools import create_experiment_context, execute_experiment


def _file_identity(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    if (experiment_root / "experiment_manifest.json").exists():
        raise FileExistsError("completed experiment manifest already exists")
    for name in ("artifacts", "03_execution.md", "04_conclusion.md"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"experiment output already exists: {name}")

    loaded = load_experiment(experiment_root)
    workspace = ExperimentWorkspace(
        repository_root
        / ".tmp"
        / "research-experiments"
        / uuid4().hex
        / loaded.definition.experiment_id,
        repository_root,
    )
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows({}),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=2026096701),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")

    artifacts = experiment_root / "artifacts"
    shutil.copytree(workspace.root, artifacts)
    facts = dict(result.facts)
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX67 执行\n\n"
        f"REX结果：`{result.outcome.value}`；receipt：`{result.receipt.sha256}`。\n\n"
        f"有效trial={facts['valid_trial_count']}，收益门通过={facts['return_gate_pass_count']}，"
        f"回撤门通过={facts['drawdown_gate_pass_count']}。本实验没有读取封存验证区、运行搜索、"
        "选择参数、形成候选或修改平台。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX67 结论\n\n"
        f"机器裁决：`{facts['decision']}`。EX66最高年化收益为"
        f"{facts['maximum_annualized_return']:.4%}，低于BuyHold的"
        f"{facts['buyhold_annualized_return']:.4%}，更低于硬门"
        f"{facts['required_annualized_return']:.4%}；回撤门通过率为"
        f"{facts['drawdown_gate_pass_rate']:.2%}。因此主导缺口确认是上涨捕获不足，"
        "下一阶段只允许审计具有明确经济传导链的领先上涨参与信息，不允许扩展EX66参数、"
        "直接创建原型或启动搜索。\n",
        encoding="utf-8",
    )

    files: dict[str, dict[str, object]] = {}
    for path in sorted(experiment_root.rglob("*")):
        if not path.is_file() or path.name == "experiment_manifest.json":
            continue
        relative = path.relative_to(experiment_root).as_posix()
        if "__pycache__" in path.parts:
            continue
        files[relative] = _file_identity(path)
    manifest = {
        "schema_version": 1,
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "rex_upside_capture_gap_review",
        "strategy_id": loaded.definition.strategy_id,
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"],
        "promotion_allowed": False,
        "rex_receipt_sha256": result.receipt.sha256,
        "files": files,
    }
    (experiment_root / "experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "decision": facts["decision"],
                "receipt_sha256": result.receipt.sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
