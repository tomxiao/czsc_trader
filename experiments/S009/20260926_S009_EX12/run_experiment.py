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


PREDECESSOR = "20260926_S009_EX11"
PREDECESSOR_RECEIPT = "450a242f5f60ea1a0040aba0b27a9831df3b840db6ba82a24c021cf8a1eb01bb"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX12 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / PREDECESSOR / "artifacts",
        expected_receipt_sha256=PREDECESSOR_RECEIPT,
    )
    loaded = load_experiment(experiment_root)
    workspace = ExperimentWorkspace(
        repository_root / ".tmp" / "research-experiments" / uuid4().hex
        / loaded.definition.experiment_id,
        repository_root,
    )
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = result.to_dict()["facts"]
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S009 EX12 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX11 前序 receipt=`{predecessor.receipt_sha256}`。"
        "四个原型均经合成 SRT/TXE 双成本场景验证，逐项统计决策、订单、成交和闭合交易。"
        "本轮无真实收益、参数搜索、优胜者或候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S009 EX12 结论\n\n"
        f"机器裁决：`{facts['decision']}`；技术门槛通过的原型数={facts['prototype_count']}。"
        "仅允许进入开发期真实账户评估，不构成 Alpha 或硬目标达成证据。"
        "真实数据必须报告开盘跳高导致的现金不足与不成交；该风险不能由合成门槛消除。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s009_synthetic_srt_txe_implementation_gate",
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
    print(json.dumps(
        {"status": "PASS", **facts, "receipt_sha256": result.receipt.sha256},
        ensure_ascii=False,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
