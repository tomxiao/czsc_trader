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


EX68_RECEIPT = "a9c683cb0d64e94fa8930c753e2bfd9626949d1e864b00b8152b9953b0aceb01"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX79 already has immutable output: {name}")
    predecessor = load_experiment_input(experiment_root.parent / "20260924_S008_EX68" / "artifacts", expected_receipt_sha256=EX68_RECEIPT)
    loaded = load_experiment(experiment_root)
    workspace = ExperimentWorkspace(repository_root / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id, repository_root)
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=2026097801),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX79 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX68 机器前序 receipt=`{predecessor.receipt_sha256}`。"
        "EX78 技术失败与源码由哈希锚定，唯一修复为两处字段名。只读取已有 EX42、EX48、EX16 开发期归档。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX79 结论\n\n"
        f"机器裁决：`{facts['decision']}`；Oracle 状态段={facts['oracle_segments']}，"
        f"转换={facts['oracle_transitions']}，持仓日={facts['oracle_long_sessions']}/{facts['common_sessions']}。"
        "完整机会地图与 T-1/T-21 可观测值见 `artifacts/`。Oracle 是事后上界；"
        "转换样本不足以学习或验证规则，本实验不授予原型或候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s008_opportunity_topology_and_observability",
        "strategy_id": "S008",
        "credential_id": "SGC-S008-001",
        "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"],
        "promotion_allowed": False,
        "technical_predecessor_experiment_id": "20260924_S008_EX78",
        "technical_predecessor_manifest_sha256": "23f02aa3cf3483888cc825cb8742a65175c6281e9f1bb656c6b97b406bac755a",
        "predecessor_experiment_id": predecessor.experiment_id,
        "predecessor_receipt_sha256": predecessor.receipt_sha256,
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment_root)
    print(json.dumps({"status": "PASS", "decision": facts["decision"], "oracle_segments": facts["oracle_segments"], "oracle_transitions": facts["oracle_transitions"], "receipt_sha256": result.receipt.sha256}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
