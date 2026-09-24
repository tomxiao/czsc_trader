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


EX73_RECEIPT = "eacee397d9e54726fb0dc17956d6451edf42729239bd3a0a574ecfaf403698d1"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX74 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX73" / "artifacts",
        expected_receipt_sha256=EX73_RECEIPT,
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
        resources=ExperimentResources(max_workers=1, random_seed=2026097401),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    ledger = (workspace.root / "information_path_ledger.csv").read_text(encoding="utf-8")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX74 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`，EX73 前序 receipt=`{predecessor.receipt_sha256}`。"
        "先核查 DFLS CPI、EX16 因果特征和 ETF 执行价格的身份，再读取开发期收益。"
        "以一次发布为一次独立观察；未读取密封验证、没有创建原型或候选。\n\n"
        f"完整 6 条信息路径见 `artifacts/information_path_ledger.csv`；字节数={len(ledger.encode('utf-8'))}。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX74 结论\n\n"
        f"机器裁决：`{facts['decision']}`。CPI 发布事件={facts['event_count']}，"
        f"审计路径={facts['path_count']}，主周期通过路径="
        f"`{json.dumps(facts['supported_primary_features'], ensure_ascii=False)}`。\n\n"
        "本次信息审计只决定是否进入职责复核；不证明可交易收益，也不授予候选资格。"
        "样本是月度发布事件，需谨慎解释统计稳定性。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "us_cpi_event_information_audit",
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
