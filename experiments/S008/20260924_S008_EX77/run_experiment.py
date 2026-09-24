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


EX76_RECEIPT = "5f90b6cfa5bab81174bf1d4cb8cbc770b473b4ce91d14b38711943bf1182f1ea"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX77 already has immutable output: {name}")
    predecessor = load_experiment_input(experiment_root.parent / "20260924_S008_EX76" / "artifacts", expected_receipt_sha256=EX76_RECEIPT)
    loaded = load_experiment(experiment_root)
    workspace = ExperimentWorkspace(repository_root / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id, repository_root)
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=2026097701),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX77 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX76 前序 receipt=`{predecessor.receipt_sha256}`。"
        "只复用已归档开发期因果面板和 EX16 控制，全部五条 PMI/CPI 路径入档；"
        "没有读取密封验证、调用新数据源、设计原型、启动搜索或创建候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX77 结论\n\n"
        f"机器裁决：`{facts['decision']}`；审计路径={facts['audited_paths']}。"
        "完整结果见 `artifacts/regime_diagnostic_ledger.csv`。"
        "两个时期均为已见开发证据，本实验只诊断下一研究问题，不授予 Alpha、策略原型或候选资格。"
        "供应商历史修订与精确发布时钟仍未排除。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "tushare_pmi_cpi_regime_diagnosis",
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
    print(json.dumps({"status": "PASS", "decision": facts["decision"], "audited_paths": facts["audited_paths"], "receipt_sha256": result.receipt.sha256}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
