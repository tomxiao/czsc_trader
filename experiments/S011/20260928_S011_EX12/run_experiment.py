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
    "20260928_S011_EX11": "d47cbf1f83ead77621f389491c2474510db6e78e162adf2f77d39224f92d9119",
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
            raise FileExistsError(f"EX12 already has immutable output: {name}")
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
        resources=ExperimentResources(max_workers=1, random_seed=2026092812),
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
        "# S011 EX12 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。schema v3 合成预检及 EX11 收据核验通过。"
        f"tsfresh {facts['tsfresh_version']} 在 {facts['calendar_sessions']} 个交易日上形成"
        f" {facts['factor_count']} 项固定候选特征，其中日频 {facts['daily_factor_count']} 项、"
        f"30分钟路径 {facts['intraday_factor_count']} 项。未读取未来收益。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX12 结论\n\n"
        f"机器状态：`{facts['decision']}`。{facts['factors_with_95pct_coverage']} 项覆盖率达到 95%，"
        f"{facts['redundant_at_085_count']} 项与至少一项 tsfresh 因子的绝对 Spearman 相关不低于 0.85。"
        "本实验只扩展并盘点尾随时序形态，不证明 Alpha 或策略收益。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "s011_return_blind_tsfresh_census",
            "strategy_id": "S011",
            "credential_id": "SGC-S011-001",
            "symbol": "159326.SZ",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": facts["decision"],
            "promotion_allowed": False,
            "reads_real_returns": False,
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
