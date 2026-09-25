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


PREDECESSOR = "20260926_S009_EX12"
PREDECESSOR_RECEIPT = "e6da86da816065d34e01d35e253456e8fe5ff79eae88146cce7961b52af0ab09"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX13 already has immutable output: {name}")
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
        "# S009 EX13 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX12 前序 receipt=`{predecessor.receipt_sha256}`。"
        "经用户评审确认，四个原型改用前收盘价与交易所涨幅上界推导的限价买入、市价卖出。"
        "合成 SRT/TXE 在10bp和30bp成本下验证订单类型、开盘成交、涨停未成交、现金安全和闭合交易。"
        "本轮无真实收益、参数搜索、优胜者或候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S009 EX13 结论\n\n"
        f"机器裁决：`{facts['decision']}`；技术门槛通过的原型数={facts['prototype_count']}。"
        "仅允许进入开发期真实账户评估，不构成 Alpha 或硬目标达成证据。"
        "真实数据须报告买单未成交率、资金利用率、涨停未成交与漏涨；限价预留现金可能降低收益。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s009_limit_buy_market_sell_execution_successor",
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
