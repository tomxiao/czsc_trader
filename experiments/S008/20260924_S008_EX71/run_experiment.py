from __future__ import annotations

import gzip
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


PREDECESSOR_RECEIPT = "f56689b29a6602e4ac6df171a40d6b91bbd6bb46a5c343e1952aa74d97f434d9"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX71 already has immutable output: {name}")

    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX70" / "artifacts",
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
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=2026097101),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    if facts["decision"] == "STOP_NEW_INPUT_DATA_GATE":
        conclusion = "输入覆盖或因果门未通过，尚未读取未来收益；该结果不评价金融假设。"
        details = (
            f"特征覆盖：`{json.dumps(facts['coverage'], ensure_ascii=False, sort_keys=True)}`。"
        )
    else:
        audit_path = workspace.root / "information_audit.json.gz"
        audit = json.loads(gzip.decompress(audit_path.read_bytes()).decode("utf-8"))
        supported = audit["primary_supported"]
        details = (
            f"完整路径账本 {facts['path_count']} 行；20 日主周期稳定路径"
            f" {facts['primary_supported_count']} 条，日内家族"
            f" {facts['primary_supported_by_family']['INTRADAY']} 条、期货家族"
            f" {facts['primary_supported_by_family']['FUTURES']} 条。"
            f"主周期路径：`{json.dumps(supported, ensure_ascii=False, sort_keys=True)}`。"
        )
        conclusion = (
            "单项信息证据仅决定是否进入职责和冗余复核；尚无可交易策略、账户评价或候选资格。"
        )
    minimum_coverage = facts.get("minimum_feature_coverage")
    if minimum_coverage is None:
        minimum_coverage = min(facts["coverage"].values())
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX71 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`，EX70 前序 receipt=`{predecessor.receipt_sha256}`。"
        f"数据门最低特征覆盖率={minimum_coverage:.4%}。"
        "期货资料严格使用 ETF 决策日前的源交易日；仅消费截至 2024-12-31 的开发池。"
        "没有读取封存验证、创建原型、搜索参数或候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        f"# S008 EX71 结论\n\n机器裁决：`{facts['decision']}`。{details}\n\n{conclusion}\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "upside_information_incremental_audit",
            "strategy_id": "S008",
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
