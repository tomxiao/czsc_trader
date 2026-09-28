from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.experiment_archive import (
    build_experiment_manifest,
    validate_experiment_archive,
)
from czsc_trader.research_tools import create_experiment_context, execute_experiment
from dataflows import Dataflows
from research_experiment import (
    ExperimentResources,
    ExperimentWorkspace,
    load_experiment,
    load_experiment_input,
)


PREDECESSORS = {
    "20260928_S011_EX06": "2aebd2d959507e4123eb942344df4eeaad48a742dd3c77a4dc47f9fa8eb8bba2",
}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in (
        "artifacts",
        "03_execution.md",
        "04_conclusion.md",
        "experiment_manifest.json",
    ):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX07 already has immutable output: {name}")
    predecessors = tuple(
        load_experiment_input(
            experiment_root.parent / experiment_id / "artifacts",
            expected_receipt_sha256=receipt,
        )
        for experiment_id, receipt in PREDECESSORS.items()
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
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=2026092807),
        real_returns=True,
        predecessors=predecessors,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(
        workspace.root,
        experiment_root / "artifacts",
        ignore=shutil.ignore_patterns("scratch"),
    )
    (experiment_root / "03_execution.md").write_text(
        "# S011 EX07 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。schema v3 合成预检和 EX06 收据核验通过；"
        f"完成 {facts['evaluation_rows']} 个标签成熟的逐日样本。仅读取截至2026-09-24的开发池"
        "行情，没有读取密封验证数据或创建候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX07 结论\n\n"
        f"机器裁决：`{facts['decision']}`。配对平方损失改善={facts['loss_improvement']:.8f}，"
        f"区块 Bootstrap 单边 p={facts['bootstrap_pvalue']:.6f}，总体秩相关="
        f"{facts['overall_rank_ic']:.6f}，预测最高减最低五分位的10日主题超额收益="
        f"{facts['theme_excess_quintile_spread']:.6f}。本实验只裁决固定线性交易属性集合的收益"
        "信息，不构成完整策略、账户结果或候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "s011_price_volume_information_test",
            "strategy_id": "S011",
            "credential_id": "SGC-S011-001",
            "symbol": "159326.SZ",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": facts["decision"],
            "promotion_allowed": False,
            "reads_real_returns": True,
            "predecessor_experiment_ids": list(PREDECESSORS),
            "predecessor_receipt_sha256": dict(PREDECESSORS),
            "rex_receipt_sha256": result.receipt.sha256,
        },
    )
    validate_experiment_archive(experiment_root)
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "outcome": result.outcome.value,
                **facts,
                "receipt_sha256": result.receipt.sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
