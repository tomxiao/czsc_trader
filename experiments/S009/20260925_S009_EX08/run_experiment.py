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


PREDECESSOR = "20260925_S009_EX07"
PREDECESSOR_RECEIPT = "a70a22bc624017354fed4ad43df5fbf779232aeb20d6226164b9403b7be0c349"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX08 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / PREDECESSOR / "artifacts", expected_receipt_sha256=PREDECESSOR_RECEIPT,
    )
    loaded = load_experiment(experiment_root)
    workspace = ExperimentWorkspace(
        repository_root / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository_root,
    )
    context = create_experiment_context(
        loaded.definition, repository_root=repository_root, dataflows=Dataflows(), workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        predecessors=(predecessor,), real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = result.to_dict()["facts"]
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S009 EX08 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX07前序receipt=`{predecessor.receipt_sha256}`。"
        "完成159915两项预注册比较，并与哈希固定的EX06账本执行2/3多数门。未读取封存验证。\n", encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S009 EX08 结论\n\n"
        f"机器裁决：`{facts['decision']}`；第三代理支持={facts['third_proxy_supported']}/2；"
        f"合格组件={facts['eligible_components']}。完整面板见`artifacts/component_panel.csv`。"
        "形成的组件仅属事后假设的开发期支持，不授予策略原型、候选或独立验证资格。\n", encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id, "status": "COMPLETE",
        "experiment_type": "s009_third_proxy_liquidity_replication", "strategy_id": "S009",
        "credential_id": "SGC-S009-001", "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(), "decision": facts["decision"],
        "promotion_allowed": False, "predecessor_experiment_id": predecessor.experiment_id,
        "predecessor_receipt_sha256": predecessor.receipt_sha256, "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment_root)
    print(json.dumps({"status": "PASS", **facts, "receipt_sha256": result.receipt.sha256}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
