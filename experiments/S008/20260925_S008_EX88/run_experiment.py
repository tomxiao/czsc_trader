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


PREDECESSOR = "20260925_S008_EX87"
PREDECESSOR_RECEIPT = "40689943d49e0f9832ac0f372803e77fa9b891d652f6e19fd96d5a1a2af73020"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX88 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / PREDECESSOR / "artifacts",
        expected_receipt_sha256=PREDECESSOR_RECEIPT,
    )
    loaded = load_experiment(experiment_root)
    loaded.implementation.synthetic_precheck()
    workspace = ExperimentWorkspace(
        repository_root / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository_root,
    )
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=20260925),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX88 执行\n\n"
        f"REX receipt={result.receipt.sha256}；EX87 前序 receipt={predecessor.receipt_sha256}。"
        "在合成时点、状态和 BH 预检后，仅读取截至 2024-12-31 的已见开发期面板与受管执行开盘价。"
        f"形成{facts['comparison_count']}项预定比较，其中可估计{facts['identifiable_comparisons']}项；"
        "逐折预测、模型秩、状态覆盖和完整比较见 artifacts/。没有读取封存验证或生成策略规则。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX88 结论\n\n"
        f"机器标签：{facts['decision']}；可估计比较数="
        f"{facts['identifiable_comparisons']}/{facts['comparison_count']}；"
        f"探索性 q≤0.10 且增量为正的比较="
        f"{json.dumps(list(facts['exploratory_clues']), ensure_ascii=False)}。"
        "本轮仅检查已见开发池中的条件信息增量，不证明样本外 Alpha 或可交易策略；"
        "不授予新原型、搜索、候选和封存验证资格。完整不利结果见 artifacts/incremental_comparisons.csv。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s008_conditional_upside_information_audit",
        "strategy_id": "S008",
        "credential_id": "SGC-S008-001",
        "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"],
        "promotion_allowed": False,
        "predecessor_experiment_id": predecessor.experiment_id,
        "predecessor_receipt_sha256": predecessor.receipt_sha256,
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment_root)
    print(json.dumps({
        "status": "PASS",
        "decision": facts["decision"],
        "comparison_count": facts["comparison_count"],
        "identifiable_comparisons": facts["identifiable_comparisons"],
        "exploratory_clues": list(facts["exploratory_clues"]),
        "receipt_sha256": result.receipt.sha256,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
