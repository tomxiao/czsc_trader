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


EX84_RECEIPT = "e30c7d917bca87278ee995d61f84dfb624567697cdf34c58a11a370602fcae79"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX85 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / "20260925_S008_EX84" / "artifacts", expected_receipt_sha256=EX84_RECEIPT,
    )
    loaded = load_experiment(experiment_root)
    workspace = ExperimentWorkspace(
        repository_root / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository_root,
    )
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=2026098501),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX85 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX84 前序 receipt=`{predecessor.receipt_sha256}`。"
        "只读取截至 2024-12-31 的已见开发池因果面板及经 DFLS 身份校验的原油指数。"
        "固定 20 交易日锚点、三个核心区间和原油卫星区间，未读取密封验证。"
        "输入与完整审计表见 `artifacts/`。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX85 结论\n\n"
        f"机器标签：`{facts['decision']}`；固定锚点数={facts['anchor_count']}；"
        f"有效比较数={facts['valid_comparisons']}/{facts['tested_comparisons']}；"
        f"切换线索={json.dumps(list(facts['clues']), ensure_ascii=False)}。"
        "此结果仅审计关联，不证明因果或可交易 Alpha，也不产生策略候选。"
        "数值和所有不利比较见 `artifacts/era_correlations.csv` 与 `artifacts/shift_tests.csv`。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s008_historical_driver_shift_audit",
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
        "clues": list(facts["clues"]), "anchor_count": facts["anchor_count"],
        "receipt_sha256": result.receipt.sha256,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
