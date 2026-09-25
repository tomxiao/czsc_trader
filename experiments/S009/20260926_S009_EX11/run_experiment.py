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


PREDECESSOR = "20260926_S009_EX10"
PREDECESSOR_RECEIPT = "5e283dd9cddfb894103507f9b991762df7b7f63eecb75642eb4fdb339896abeb"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX11 already has immutable output: {name}")
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
        "# S009 EX11 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX10前序receipt=`{predecessor.receipt_sha256}`。"
        "固化四个低自由度原型与统一执行契约，并以完整布尔真值表验证规则分离。"
        "未读取真实收益、未搜索参数、未选择优胜者、未创建候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S009 EX11 结论\n\n"
        f"机器裁决：`{facts['decision']}`；原型数={facts['prototype_count']}；"
        f"机制数={facts['mechanism_count']}；学习参数数={facts['learned_parameter_count']}。"
        "下一步仅验证同一SRT实现能否在合成行情上表达全部规则并闭合TXE执行；"
        "本实验不构成Alpha、候选或硬目标达成证据。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s009_low_freedom_prototype_freeze",
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
