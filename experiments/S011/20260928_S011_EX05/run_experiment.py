"""Run S011 EX05 once after preflight and archive complete evidence."""

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
    ExperimentResources, ExperimentWorkspace, load_experiment, load_experiment_input,
)


PREDECESSORS = {
    "20260928_S011_EX02": "5c820f80a763596a80b8faa8340f986372fb252c2684a7c6aed600e0e124c931",
    "20260928_S011_EX03": "fe13686d0a5a4167438ca496716d7a7554b37de875270412d793c8ab39a57e3b",
}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment / name).exists():
            raise FileExistsError(f"EX05 already has immutable output: {name}")
    predecessors = tuple(load_experiment_input(
        experiment.parent / experiment_id / "artifacts", expected_receipt_sha256=receipt,
    ) for experiment_id, receipt in PREDECESSORS.items())
    loaded = load_experiment(experiment)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_experiment_context(
        loaded.definition, repository_root=repository, dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed,
                                      max_evaluations=36),
        real_returns=True, predecessors=predecessors,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue EX05 receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, experiment / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (experiment / "03_execution.md").write_text(
        "# S011 EX05 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。EX02、EX03前序身份已校验；"
        f"同口径BuyHold与{summary['search_budget']}个H02联合参数账户完成。"
        "实际单工作进程；完整trial、订单、成交、交易、权益与输入身份见artifacts。\n",
        encoding="utf-8",
    )
    (experiment / "04_conclusion.md").write_text(
        "# S011 EX05 结论\n\n"
        f"机器状态：`{summary['decision']}`。{summary['search_budget']}个联合点中"
        f"{summary['qualifying_points']}个同时满足收益、回撤和完整样本折算交易频率硬门；"
        f"同订单BuyHold CAGR={summary['baseline']['cagr']:.4%}，"
        f"最大回撤={summary['baseline']['max_drawdown']:.4%}；"
        f"最优trial={summary['best_trial']}，CAGR={summary['best_metrics']['cagr']:.4%}，"
        f"最大回撤={summary['best_metrics']['max_drawdown']:.4%}，"
        f"闭合交易={summary['best_metrics']['closed_per_60']:.2f}笔/60日。"
        "这是开发池已见样本结果，须结合完整trial账本判断，不等于稳健性通过或可交接。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE", "experiment_type": "s011_h02_stage3_joint_search",
        "strategy_id": "S011", "credential_id": "SGC-S011-001", "symbol": "159326.SZ",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": summary["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": list(PREDECESSORS),
        "predecessor_receipt_sha256": dict(PREDECESSORS),
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment)
    print(json.dumps({"status": "PASS", "receipt_sha256": result.receipt.sha256,
                      "decision": summary["decision"],
                      "qualifying_points": summary["qualifying_points"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
