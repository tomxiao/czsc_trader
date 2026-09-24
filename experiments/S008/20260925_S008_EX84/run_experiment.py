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


EX83_RECEIPT = "71dc30ae352cfdd7d096d3ca5eb359e6f7792604afac66f7197ce36295807e54"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX84 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX83" / "artifacts", expected_receipt_sha256=EX83_RECEIPT,
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
        resources=ExperimentResources(max_workers=1, random_seed=2026098401),
        predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX84 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX83 前序 receipt=`{predecessor.receipt_sha256}`。"
        "仅经 DFLS 读取 SC.NH 的 2018–2024 年原油指数，未读取黄金 ETF 收益或密封验证。"
        "输入身份见 `artifacts/oil_input_inventory.csv`。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX84 结论\n\n"
        f"机器裁决：`{facts['decision']}`；问题={json.dumps(list(facts['issues']), ensure_ascii=False)}；"
        f"逐年数据量={json.dumps(dict(facts['annual_rows']), sort_keys=True)}。"
        "通过仅允许后继的 2018–2024 境内原油驱动对照，不授予策略或候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s008_domestic_oil_driver_data_gate",
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
        "annual_rows": dict(facts["annual_rows"]),
        "receipt_sha256": result.receipt.sha256,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
