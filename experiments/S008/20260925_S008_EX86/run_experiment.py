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


PREDECESSORS = (
    ("20260924_S008_EX79", "9b523167ec93271e2d2dbf13473cd925db30c0b50a3293d1e79e331679f20547"),
    ("20260925_S008_EX85", "f9563be746df8c62d517a87469b348386117a72f8673088f80dfa9ce14c667c2"),
)


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX86 already has immutable output: {name}")
    predecessors = tuple(
        load_experiment_input(experiment_root.parent / name / "artifacts", expected_receipt_sha256=receipt)
        for name, receipt in PREDECESSORS
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
        resources=ExperimentResources(max_workers=1, random_seed=2026098601),
        predecessors=predecessors,
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX86 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`；前序 EX79、EX85 receipt 均通过锁定校验。"
        "读取 EX48 既有执行日仓位、EX16 因果面板和受管不复权执行价，只限 2024-12-31 以前。"
        "各季度逐项核算，EX48 总体指标复核通过；未读取密封验证、重算策略或生成新规则。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX86 结论\n\n"
        f"机器标签：`{facts['decision']}`；重点上涨季度="
        f"{json.dumps(list(facts['top10_quarters']), ensure_ascii=False)}；"
        f"P02 重点季度错过正收益对数总和={facts['p02_top10_missed_positive_log_return']:.6f}，"
        f"同期避开负收益对数总和={facts['p02_top10_avoided_negative_log_return']:.6f}。"
        "全部季度和 T-1 观察见 `artifacts/`。这是事后失败归因，不证明任何可交易的领先信息，"
        "也不授予新原型、候选或密封验证资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s008_upside_quarter_failure_attribution",
        "strategy_id": "S008",
        "credential_id": "SGC-S008-001",
        "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"],
        "promotion_allowed": False,
        "predecessor_experiment_ids": [item.experiment_id for item in predecessors],
        "predecessor_receipt_sha256": {item.experiment_id: item.receipt_sha256 for item in predecessors},
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment_root)
    print(json.dumps({
        "status": "PASS", "decision": facts["decision"],
        "top10_quarters": list(facts["top10_quarters"]),
        "p02_top10_net_cash_gap": facts["p02_top10_net_cash_gap"],
        "receipt_sha256": result.receipt.sha256,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
