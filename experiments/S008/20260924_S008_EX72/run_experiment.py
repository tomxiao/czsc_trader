from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from czsc_trader.research_tools import create_experiment_context, execute_experiment
from dataflows import Dataflows
from research_experiment import (
    ExperimentResources,
    ExperimentWorkspace,
    load_experiment,
    load_experiment_input,
)


EX70_RECEIPT = "f56689b29a6602e4ac6df171a40d6b91bbd6bb46a5c343e1952aa74d97f434d9"
EX71_RECEIPT = "57f2d74df5429e0c7dd0ad689d9b4d34c485932b1ab080d1d272702b5a49ae6c"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX72 already has immutable output: {name}")
    predecessors = (
        load_experiment_input(
            experiment_root.parent / "20260924_S008_EX70" / "artifacts",
            expected_receipt_sha256=EX70_RECEIPT,
        ),
        load_experiment_input(
            experiment_root.parent / "20260924_S008_EX71" / "artifacts",
            expected_receipt_sha256=EX71_RECEIPT,
        ),
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
        resources=ExperimentResources(max_workers=1, random_seed=2026097201),
        predecessors=predecessors,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    correlation_summary = json.dumps(
        dict(facts["maximum_existing_absolute_correlation"]),
        ensure_ascii=False,
        sort_keys=True,
    )
    independent = list(facts["independent_new_representatives"])
    if facts["decision"] == "HOLD_INTRADAY_DISCOVERY_ONLY":
        meaning = "存在数值上独立的入场时机线索，但 EX71 仅有方向稳定证据，不具备原型设计资格。"
    elif facts["decision"] == "STOP_INTRADAY_REDUNDANT":
        meaning = "三条新路径均与既有组件或彼此数值冗余，不增加独立组件。"
    else:
        meaning = (
            "有独立且达到 EX71 名义支持的入场时机路径，可由用户评审是否作为已有机会来源的叠加。"
        )
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX72 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。校验 EX70、EX71 receipt 及 EX16、EX18 归档身份，"
        f"完成 {facts['comparison_count']} 组新旧特征相关性比较。"
        "只读取开发池内已封存特征和 EX71 评价账本，未读取新的未来收益标签或密封区。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX72 结论\n\n"
        f"机器裁决：`{facts['decision']}`。独立新代表：`{independent}`；"
        f"数值冗余新路径数={facts['redundant_new_count']}。"
        f"各路径与既有 13 组件的最高绝对相关：`{correlation_summary}`。\n\n"
        "三条路径的经济职责均为 ETF 走弱后的回补入场时机，与 EX18 既有入场组件有业务职责重合，"
        "且不提供独立黄金上涨机会来源。"
        f"{meaning}本实验没有新收益标签、原型、参数搜索或候选。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "intraday_redundancy_and_financial_role_review",
            "strategy_id": "S008",
            "credential_id": "SGC-S008-001",
            "symbol": "518880.SH",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": facts["decision"],
            "promotion_allowed": False,
            "predecessor_experiment_ids": [item.experiment_id for item in predecessors],
            "predecessor_receipt_sha256": {
                item.experiment_id: item.receipt_sha256 for item in predecessors
            },
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
