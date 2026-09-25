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


PREDECESSOR = "20260925_S008_EX89"
PREDECESSOR_RECEIPT = "6c4f9b604f9095039c88f5706f7b070f07203c9b11300c5cc845deadf71197c6"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX90 already has immutable output: {name}")
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
        loaded.definition, repository_root=repository_root,
        dataflows=Dataflows(), workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=20260990),
        predecessors=(predecessor,), real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX90 执行\n\n"
        f"REX receipt={result.receipt.sha256}；EX89 数据门 receipt={predecessor.receipt_sha256}。"
        "合成日期/状态/比较预检后仅读取截至 2024-12-31 的已见开发池；"
        f"固定比较={facts['comparisons']}，可估计={facts['estimable']}。"
        "逐年预测、模型可辨识度及完整不利结果见 artifacts/。未读取封存验证或创建策略。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX90 结论\n\n"
        f"机器标签：`{facts['decision']}`；可估计比较数={facts['estimable']}/{facts['comparisons']}；"
        f"探索性线索={json.dumps(list(facts['exploratory_clues']), ensure_ascii=False)}。"
        "该结果只评价已见开发期中基差的条件信息增量，不证明可交易 Alpha 或独立样本外表现；"
        "不授予原型、搜索、候选和封存验证资格。完整结果见 artifacts/basis_incremental_ledger.csv。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s008_spot_futures_basis_incremental_audit",
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
        "status": "PASS", "decision": facts["decision"],
        "comparisons": facts["comparisons"], "estimable": facts["estimable"],
        "exploratory_clues": list(facts["exploratory_clues"]),
        "receipt_sha256": result.receipt.sha256,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
