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
    ExperimentResources, ExperimentWorkspace, load_experiment, load_experiment_input,
)


PREDECESSOR = "20260926_S009_EX14"
PREDECESSOR_RECEIPT = "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment / name).exists():
            raise FileExistsError(f"EX15 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment.parent / PREDECESSOR / "artifacts",
        expected_receipt_sha256=PREDECESSOR_RECEIPT,
    )
    loaded = load_experiment(experiment)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_experiment_context(
        loaded.definition, repository_root=repository, dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1,
                                      random_seed=loaded.definition.random_seed,
                                      max_evaluations=64),
        real_returns=True, predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = result.to_dict()["facts"]
    shutil.copytree(workspace.root, experiment / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (experiment / "03_execution.md").write_text(
        "# S009 EX15 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX14前序receipt=`{predecessor.receipt_sha256}`。"
        "Optuna固定种子、内存存储、单进程完成64次两维联合阈值搜索。逐点账户、订单、"
        "成交、闭合交易、年度收益和完整trial账本见artifacts；前5个不同参数点执行30bp压力核算。"
        "开发期截至2024-12-31，未读取2025年及以后数据。\n",
        encoding="utf-8",
    )
    (experiment / "04_conclusion.md").write_text(
        "# S009 EX15 结论\n\n"
        f"冻结空间机器裁决：`{facts['decision']}`；64次建议中的不同参数点"
        f"{facts['distinct_points']}个，开发期双硬门通过点{facts['qualifying_points']}个。"
        "本轮为已见开发池搜索；即使有合格点也不构成独立验证或候选资格。"
        "完整试验与逐年、费用证据见artifacts。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE", "experiment_type": "s009_joint_threshold_search",
        "strategy_id": "S009", "credential_id": "SGC-S009-001", "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"], "promotion_allowed": False,
        "predecessor_experiment_id": predecessor.experiment_id,
        "predecessor_receipt_sha256": predecessor.receipt_sha256,
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment)
    print(json.dumps({"status": "PASS", **facts, "receipt_sha256": result.receipt.sha256},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
