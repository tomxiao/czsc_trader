from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from dataflows import Dataflows
from research_experiment import (
    ExperimentResources,
    ExperimentWorkspace,
    load_experiment,
    load_experiment_input,
)
from czsc_trader.experiment_archive import (
    build_experiment_manifest,
    validate_experiment_archive,
)
from czsc_trader.research_tools import create_experiment_context, execute_experiment


PREDECESSOR_RECEIPT = "b5677eb58d844166dd8e255a4afa04e9c07569ab3b613b54a360da6af784056b"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    if (experiment_root / "experiment_manifest.json").exists():
        raise FileExistsError("completed experiment manifest already exists")
    for name in ("artifacts", "03_execution.md", "04_conclusion.md"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"experiment output already exists: {name}")

    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX67" / "artifacts",
        expected_receipt_sha256=PREDECESSOR_RECEIPT,
    )
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
        resources=ExperimentResources(max_workers=1, random_seed=2026096801),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)

    artifacts = experiment_root / "artifacts"
    shutil.copytree(workspace.root, artifacts)
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX68 执行\n\n"
        f"通过公共接口从EX67恢复前序输入，receipt=`{PREDECESSOR_RECEIPT}`；"
        f"EX68 receipt=`{result.receipt.sha256}`。本实验没有重新计算金融证据、读取封存验证区、"
        "运行搜索、创建原型或形成候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX68 结论\n\n"
        f"机器裁决：`{facts['decision']}`。EX66共{facts['valid_trial_count']}个有效trial，"
        f"收益门通过{facts['return_gate_pass_count']}个，回撤门通过"
        f"{facts['drawdown_gate_pass_count']}个（{facts['drawdown_gate_pass_rate']:.2%}）；"
        f"最高年化{facts['maximum_annualized_return']:.4%}，低于BuyHold年化"
        f"{facts['buyhold_annualized_return']:.4%}和硬门{facts['required_annualized_return']:.4%}。"
        "主导缺口确认为上涨捕获不足。下一阶段只允许审计具有第一性原理依据、决策时点可得的"
        "领先上涨参与信息；不得扩展EX66参数、直接创建原型或启动搜索。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "rex_upside_capture_gap_review_archive_successor",
            "strategy_id": loaded.definition.strategy_id,
            "credential_id": "SGC-S008-001",
            "symbol": "518880.SH",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": facts["decision"],
            "promotion_allowed": False,
            "predecessor_experiment_id": predecessor.experiment_id,
            "predecessor_receipt_sha256": predecessor.receipt_sha256,
            "rex_receipt_sha256": result.receipt.sha256,
        },
    )
    validate_experiment_archive(experiment_root)
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
