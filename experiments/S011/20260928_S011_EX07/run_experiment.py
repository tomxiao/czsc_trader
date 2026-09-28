"""Run and archive the focused S011 H02 return-first successor after preflight."""

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


PREDECESSOR = "20260928_S011_EX06"
PREDECESSOR_RECEIPT = "91e356e5647a96224bfd670ba9c5fe5f1acd40d4beac5d500b6bb81456d90483"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment / name).exists():
            raise FileExistsError(f"EX07 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment.parent / PREDECESSOR / "artifacts", expected_receipt_sha256=PREDECESSOR_RECEIPT,
    )
    loaded = load_experiment(experiment)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_experiment_context(
        loaded.definition, repository_root=repository, dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed,
                                      max_evaluations=64),
        real_returns=True, predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue EX07 receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, experiment / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (experiment / "03_execution.md").write_text(
        "# S011 EX07 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。EX06前序receipt及档案已核验，"
        "20/3/10锚点完整权益曲线与EX06相同；"
        f"同口径BuyHold与{summary['search_budget']}个H02联合参数账户完成。"
        "实际单工作进程；完整trial、订单、成交、交易、权益与输入身份见artifacts。\n",
        encoding="utf-8",
    )
    best = summary["highest_return_metrics"]
    (experiment / "04_conclusion.md").write_text(
        "# S011 EX07 结论\n\n"
        f"机器状态：`{summary['decision']}`。{summary['search_budget']}组中，"
        f"{summary['return_qualifying_points']}组达到收益门，"
        f"{summary['all_goals_qualifying_points']}组同时达到全部三项目标。"
        f"同订单BuyHold CAGR={summary['baseline']['cagr']:.4%}；"
        f"收益最高trial={summary['highest_return_trial']}，CAGR={best['cagr']:.4%}，"
        f"回撤={best['max_drawdown']:.4%}，闭合交易={best['closed_per_60']:.2f}笔/60日。"
        "只按收益排序；回撤和频率照实记录。此为已见开发池证据，不构成独立验证。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE", "experiment_type": "s011_h02_focused_return_search",
        "strategy_id": "S011", "credential_id": "SGC-S011-001", "symbol": "159326.SZ",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": summary["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": [PREDECESSOR],
        "predecessor_receipt_sha256": {PREDECESSOR: PREDECESSOR_RECEIPT},
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment)
    print(json.dumps({"status": "PASS", "receipt_sha256": result.receipt.sha256,
                      "decision": summary["decision"],
                      "return_qualifying_points": summary["return_qualifying_points"],
                      "all_goals_qualifying_points": summary["all_goals_qualifying_points"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
