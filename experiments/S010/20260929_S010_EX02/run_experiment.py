"""Run and seal the S010 EX02 purged chronological comparison."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment
from research_experiment import (
    ExperimentResources, ExperimentWorkspace, load_experiment, load_experiment_input,
)


PREDECESSOR = "20260929_S010_EX01"
RECEIPT = "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77"


def main() -> None:
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (root / name).exists():
            raise FileExistsError(f"S010 EX02 already has immutable output: {name}")
    predecessor = load_experiment_input(root.parent / PREDECESSOR / "artifacts",
                                         expected_receipt_sha256=RECEIPT)
    loaded = load_experiment(root)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_formal_experiment_context(
        loaded.definition, repository_root=repository, workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("experiment platform did not issue a receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, root / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (root / "03_execution.md").write_text(
        "# S010 EX02 执行\n\n"
        f"正式实验 receipt：`{result.receipt.sha256}`；已核验 EX01 receipt 和完整档案。"
        f"隔离边界后可评价比较 {summary['evaluated_comparisons']}/{summary['comparisons']}，"
        f"高度相关因子对 {summary['near_duplicate_pairs']}。"
        "每项每段训练标签终点、样本量与误差见 `artifacts/purged_fold_scores.csv`。"
        "未读取封存期数据或进行账户回放。\n",
        encoding="utf-8",
    )
    (root / "04_conclusion.md").write_text(
        "# S010 EX02 结论\n\n"
        "机器状态：`PURGED_SURVEY_COMPLETE`。EX01 顺序样本增量列因训练标签越过测试段边界，"
        "应以本实验的 `purged_scores.csv` 和逐段账本替代其增量解读。"
        "本轮仍在已见开发池中作单因子筛查；正的误差下降和高相关聚类只供金融职责审查。"
        "尚未确认有效组件、形成策略或取得完整账户证据。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(root, {
        "experiment_id": loaded.definition.experiment_id,
        "strategy_id": "S010", "credential_id": "SGC-S010-001",
        "status": "COMPLETE", "experiment_type": "s010_stage2_purged_factor_review",
        "symbol": "159326.SZ", "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": summary["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": [PREDECESSOR],
        "predecessor_receipt_sha256": {PREDECESSOR: RECEIPT},
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(root)
    print(json.dumps({"status": "PASS", "receipt_sha256": result.receipt.sha256,
                      **{key: summary[key] for key in ("factor_count", "comparisons",
                                                        "evaluated_comparisons", "near_duplicate_pairs")}},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
