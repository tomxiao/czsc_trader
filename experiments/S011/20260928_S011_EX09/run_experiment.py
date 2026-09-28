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
    "20260928_S011_EX07": "880c200549e4f8da5abaca569b502461b5255876403543fb1f7bdff8f1549491",
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
            raise FileExistsError(f"EX09 already has immutable output: {name}")
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
        resources=ExperimentResources(max_workers=1, random_seed=2026092808),
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
        "# S011 EX09 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。schema v3 合成预检和 EX07 收据核验通过；"
        f"30分钟完整交易日 {facts['intraday_sessions']} 日，日线覆盖率"
        f" {facts['calendar_coverage']:.2%}，特征完整行 {facts['complete_rows']} 日；去冗余后保留"
        f" {facts['selected_feature_count']} 项，其中 {facts['dense_feature_count']} 项通过状态密度门。"
        "本实验没有读取状态日之后的收益。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX09 结论\n\n"
        f"机器裁决：`{facts['decision']}`。通过只表示日内特征的数据、差异性和状态变化频率足以"
        "支持下一项固定收益信息检验，不代表已经发现 Alpha、形成交易规则或取得候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "s011_intraday_feature_data_gate_successor",
            "strategy_id": "S011",
            "credential_id": "SGC-S011-001",
            "symbol": "159326.SZ",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": facts["decision"],
            "promotion_allowed": False,
            "reads_post_state_returns": False,
            "technical_predecessor_experiment_id": "20260928_S011_EX08",
            "technical_predecessor_manifest_sha256": "ec5811f3447df10485804b1bfe4644d6543d84c4a80dfdd2fa7e49efe13b33ca",
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
