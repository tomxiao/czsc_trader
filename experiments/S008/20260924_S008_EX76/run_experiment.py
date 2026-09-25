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


EX75_RECEIPT = "b9960087006c4861efa7e595398fe6ff40b96b3f1808f6816d1c4088a2b0fe40"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX76 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX75" / "artifacts",
        expected_receipt_sha256=EX75_RECEIPT,
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
        resources=ExperimentResources(max_workers=1, random_seed=2026097601),
        predecessors=(predecessor,),
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX76 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；EX75 前序 receipt=`{predecessor.receipt_sha256}`。"
        "先复核六项 DFLS 内容身份、EX16 控制面板及执行价清单，再读取截止 2024-12-31 的开发期收益。"
        "完整月度面板和 24 条路径入档；没有读取密封验证、设计原型、启动搜索或创建候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX76 结论\n\n"
        f"机器裁决：`{facts['decision']}`；月度决策={facts['monthly_decisions']}；"
        f"信息路径={facts['audited_paths']}。完整结果见 `artifacts/information_path_ledger.csv`。\n\n"
        "此前探索已查看两段开发期的 20 日收益差，本实验的发现/确认分段都不能视为未见验证。"
        "股债相关性使用收益率变动构造的债价代理，不是论文的债券总回报。"
        "本实验不授予策略原型或候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "tushare_five_factor_information_audit",
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
    print(json.dumps({
        "status": "PASS", "decision": facts["decision"],
        "monthly_decisions": facts["monthly_decisions"],
        "audited_paths": facts["audited_paths"],
        "receipt_sha256": result.receipt.sha256,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
