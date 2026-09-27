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


PREDECESSORS = {
    "20260925_S009_EX04": "f920ee1275018fbd5672f29fe4dabff31371636215b85570c50bcfcc6a4c0f38",
    "20260926_S009_EX10": "5e283dd9cddfb894103507f9b991762df7b7f63eecb75642eb4fdb339896abeb",
    "20260926_S009_EX14": "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f",
}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment / name).exists():
            raise FileExistsError(f"EX19 already has immutable output: {name}")
    predecessors = tuple(load_experiment_input(
        experiment.parent / experiment_id / "artifacts", expected_receipt_sha256=receipt,
    ) for experiment_id, receipt in PREDECESSORS.items())
    loaded = load_experiment(experiment)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_experiment_context(
        loaded.definition, repository_root=repository, dataflows=Dataflows(), workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        real_returns=True, predecessors=predecessors,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = result.to_dict()["facts"]
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, experiment / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (experiment / "03_execution.md").write_text(
        "# S009 EX19 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。EX04/EX10/EX14 收据核验，S008 EX16/EX18 完整归档与 manifest 身份核验。"
        "schema v3 preflight 合成预检通过；仅读取已见开发池至 2024-12-31；没有封存期读取或账户回放。\n",
        encoding="utf-8",
    )
    (experiment / "04_conclusion.md").write_text(
        "# S009 EX19 结论\n\n"
        f"机器裁决：`{facts['decision']}`。P03 已持仓日={summary['held_days']}，汇率非正持仓日={summary['weak_fx_held_days']}；"
        f"汇率非正组未来 5 日开盘收益均值={summary['weak_fx_mean_5d_return']:.6f}，95% 区间="
        f"[{summary['weak_fx_mean_ci95'][0]:.6f}, {summary['weak_fx_mean_ci95'][1]:.6f}]；"
        f"弱汇率组收益低于 -20bp 的年度={summary['negative_weak_fx_years']}/6。"
        "本实验重复使用已见开发池，结果仅用于确定是否进入新原型实现门；不是完整账户、独立验证或候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment, {
        "experiment_id": loaded.definition.experiment_id, "status": "COMPLETE",
        "experiment_type": "s009_s008_fx_held_exit_information", "strategy_id": "S009",
        "credential_id": "SGC-S009-001", "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": list(PREDECESSORS),
        "predecessor_receipt_sha256": dict(PREDECESSORS),
        "cross_strategy_s008_manifest_sha256": summary["cross_strategy_s008_manifest_sha256"],
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment)
    print(json.dumps({"status": "PASS", **facts, "receipt_sha256": result.receipt.sha256},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
