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


EX74_RECEIPT = "0d6fd2579ef0caec6af0e1bd3228c81e94695440b02bd8ffa4984872057fd081"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX75 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX74" / "artifacts",
        expected_receipt_sha256=EX74_RECEIPT,
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
        resources=ExperimentResources(max_workers=1, random_seed=2026097501),
        predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX75 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX74 前序 receipt=`{predecessor.receipt_sha256}`。"
        "六项 Tushare 输入均通过 DFLS 请求，不读取 ETF 收益或密封验证。"
        "输入内容身份见 `artifacts/input_inventory.csv`。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX75 结论\n\n"
        f"机器裁决：`{facts['decision']}`；可发布输入={facts['dataset_count']}；"
        f"名义利率与标普 500 同日观测={facts['nominal_spx_overlap']}；"
        f"问题={json.dumps(facts['issues'], ensure_ascii=False)}。\n\n"
        "仅授予后继信息审计资格。PMI 和预算历史时钟、数值回修尚未完成独立逐次校准；"
        "股债相关性只能先使用明确标记的债价近似。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "tushare_five_factor_data_gate",
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
    print(json.dumps({"status": "PASS", **facts, "receipt_sha256": result.receipt.sha256}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
