from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from czsc_trader.research_tools import create_experiment_context, execute_experiment
from dataflows import Dataflows
from research_experiment import ExperimentResources, ExperimentWorkspace, load_experiment, load_experiment_input


PREDECESSOR = "20260925_S009_EX03"
PREDECESSOR_RECEIPT = "5c1b6a6c427c7bbe253a237a90ae5898ea3c1d3d402c4f3b37fc580e266e9b65"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX04 already has immutable output: {name}")
    predecessor = load_experiment_input(experiment_root.parent / PREDECESSOR / "artifacts", expected_receipt_sha256=PREDECESSOR_RECEIPT)
    loaded = load_experiment(experiment_root)
    loaded.implementation.synthetic_precheck()
    workspace = ExperimentWorkspace(repository_root / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id, repository_root)
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=20260904),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S009 EX04 执行\n\n"
        f"REX receipt={result.receipt.sha256}；EX03前序receipt={predecessor.receipt_sha256}。"
        "仅读取截至2024-12-31的已见开发期面板和受管执行开盘价，完成63项预注册年度向前比较；"
        "未读取2025年以后封存验证区，未生成交易规则。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S009 EX04 结论\n\n"
        f"机器裁决：`{facts['decision']}`。FDR支持={facts['fdr_supported']}，名义支持={facts['nominal_supported']}，"
        f"方向稳定={facts['directionally_stable']}；20日面板候选={facts['panel_eligible']}，其中收益机会组件={facts['opportunity_eligible']}。"
        "完整有利和不利结果均见artifacts/information_ledger.csv。本轮只授权组件职责与冗余审查，不证明可交易策略或目标达成。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s009_income_opportunity_information_audit",
        "strategy_id": "S009",
        "credential_id": "SGC-S009-001",
        "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"],
        "promotion_allowed": False,
        "predecessor_experiment_id": predecessor.experiment_id,
        "predecessor_receipt_sha256": predecessor.receipt_sha256,
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment_root)
    print(json.dumps({"status": "PASS", **facts, "receipt_sha256": result.receipt.sha256}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

