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


EX81_RECEIPT = "36344a16b37ed289c5963f82b4559555b0acbe4c1d1969a06794628a7af0ae95"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX82 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX81" / "artifacts",
        expected_receipt_sha256=EX81_RECEIPT,
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
        resources=ExperimentResources(max_workers=1, random_seed=2026098201),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX82 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX81 前序 receipt=`{predecessor.receipt_sha256}`。"
        "先校验 DFLS 份额、EX16 控制面板、执行价清单及合成时滞，再读取截止 2024-12-31 的开发期收益。"
        "因果日面板和全部三条路径归档；未读取密封验证。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX82 结论\n\n"
        f"机器裁决：`{facts['decision']}`；审计路径={facts['audited_paths']}；"
        f"达到原型评审最低线的窗口={list(facts['promising_horizons'])}。"
        "完整数值见 `artifacts/peer_flow_information_ledger.csv`。两段均是已见开发证据；"
        "无论结果如何，本实验都不授予策略原型或候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "tushare_gold_peer_flow_information_audit",
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
        "audited_paths": facts["audited_paths"],
        "promising_horizons": list(facts["promising_horizons"]),
        "receipt_sha256": result.receipt.sha256,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
