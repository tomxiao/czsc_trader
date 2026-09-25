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


PREDECESSOR = "20260926_S009_EX13"
PREDECESSOR_RECEIPT = "8a93908cef3c59d2b764abccf787fb8acf95fd8b81c89f0a4dce8c1509949071"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment / name).exists():
            raise FileExistsError(f"EX14 already has immutable output: {name}")
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
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = result.to_dict()["facts"]
    shutil.copytree(workspace.root, experiment / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (experiment / "03_execution.md").write_text(
        "# S009 EX14 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX13前序receipt=`{predecessor.receipt_sha256}`。"
        "EX13四个固定原型和同执行口径BuyHold，在2019-01-02至2024-12-31完整账户上执行，"
        "主10bp、压力30bp单边成本；逐日账本、订单、成交、交易、输入身份和逐年收益见artifacts。"
        "2025年及以后封存数据未读取。\n",
        encoding="utf-8",
    )
    (experiment / "04_conclusion.md").write_text(
        "# S009 EX14 结论\n\n"
        f"开发期机器裁决：`{facts['decision']}`；主成本通过硬门的原型："
        f"{', '.join(facts['primary_qualifiers']) or '无'}。"
        "具体指标与逐年差异以artifacts中的完整账户证据为准。"
        "开发期结果不构成封存期验证或CIO裁决；本轮不生成候选。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s009_development_full_account_evaluation",
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
