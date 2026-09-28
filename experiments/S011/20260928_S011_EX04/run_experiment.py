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
    "20260928_S011_EX02": "365fcd9a147e4edcb4a3bb393706c737e37cb9bff2e44c15f606d0d33601fd73",
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
            raise FileExistsError(f"EX04 already has immutable output: {name}")
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
        resources=ExperimentResources(max_workers=1, random_seed=2026092803),
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
        "# S011 EX04 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。schema v3 合成预检和 EX02 收据核验通过；"
        f"完成 {facts['evaluation_rows']} 个标签成熟的逐日样本。"
        "仅读取截至 2026-09-24 的开发池行情，没有读取密封验证数据或创建候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX04 结论\n\n"
        f"机器裁决：`{facts['decision']}`。配对平方损失改善="
        f"{facts['loss_improvement']:.8f}，区块 Bootstrap 单边 p="
        f"{facts['bootstrap_pvalue']:.6f}，温度最高减最低五分位的 20 日市场超额收益="
        f"{facts['market_excess_quintile_spread']:.6f}。"
        "本实验只裁决卖方预期温度的收益信息增量；不构成完整策略、账户结果或候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "s011_sell_side_expectation_information_test",
            "strategy_id": "S011",
            "credential_id": "SGC-S011-001",
            "symbol": "159326.SZ",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": facts["decision"],
            "promotion_allowed": False,
            "reads_real_returns": True,
            "technical_predecessor_experiment_id": "20260928_S011_EX03",
            "technical_predecessor_manifest_sha256": "9e3f9171489019c0e8a34d1f0201991263e26d4cae36748ac30e6bca7e4ab4c3",
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
                "decision": facts["decision"],
                "evaluation_rows": facts["evaluation_rows"],
                "loss_improvement": facts["loss_improvement"],
                "bootstrap_pvalue": facts["bootstrap_pvalue"],
                "market_excess_quintile_spread": facts["market_excess_quintile_spread"],
                "receipt_sha256": result.receipt.sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
