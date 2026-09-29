"""Run and seal the frozen S010 EX14 historical-basket data gate."""

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

from experiment import RECEIPTS


def main() -> None:
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (root / name).exists():
            raise FileExistsError(f"S010 EX14 already has immutable output: {name}")
    predecessors = tuple(
        load_experiment_input(root.parent / name / "artifacts", expected_receipt_sha256=receipt)
        for name, receipt in RECEIPTS.items()
    )
    loaded = load_experiment(root)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_formal_experiment_context(
        loaded.definition, repository_root=repository, workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        predecessors=predecessors,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("experiment platform did not issue a receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, root / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (root / "03_execution.md").write_text(
        "# S010 EX14 执行\n\n"
        f"正式实验 receipt：`{result.receipt.sha256}`。EX01—EX13 前序身份已核验。"
        f"读取 {summary['weight_snapshot_count']} 期权重、{summary['union_symbol_count']} 只历史成份股；"
        f"股票 READY {summary['stock_ready_count']} 只、失败 {summary['stock_failed_count']} 只。"
        "逐只身份与日期、逐日覆盖见 `artifacts/`。\n",
        encoding="utf-8",
    )
    (root / "04_conclusion.md").write_text(
        "# S010 EX14 结论\n\n"
        f"机器状态：`{summary['decision']}`。权重至少滞后 35 个自然日用于覆盖核查；"
        "来源没有独立可核的权重公布时刻。已封存数据质量与缺口，本实验未读取未来收益，"
        "未形成篮子广度因子、策略或候选。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(root, {
        "experiment_id": loaded.definition.experiment_id, "strategy_id": "S010",
        "credential_id": "SGC-S010-001", "status": "COMPLETE",
        "experiment_type": "s010_stage2_historical_basket_data_gate",
        "symbol": "159326.SZ", "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": summary["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": list(RECEIPTS),
        "predecessor_receipt_sha256": RECEIPTS,
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(root)
    print(json.dumps({"status": "PASS", "receipt_sha256": result.receipt.sha256,
                      "stock_ready_count": summary["stock_ready_count"],
                      "stock_failed_count": summary["stock_failed_count"]},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
