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
    "20260926_S009_EX14": "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f",
    "20260926_S009_EX17": "db25093229cc1931ba601009a1bc8f8cbaea74d1ee10732d9d50643c12b01637",
}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment / name).exists():
            raise FileExistsError(f"EX18 already has immutable output: {name}")
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
    shutil.copytree(workspace.root, experiment / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (experiment / "03_execution.md").write_text(
        "# S009 EX18 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。前序 EX14/EX17 收据与归档均核验；"
        "合成 preflight 通过，只用已归档开发期账户，不读取 2025 年及以后数据。\n", encoding="utf-8",
    )
    (experiment / "04_conclusion.md").write_text(
        "# S009 EX18 结论\n\n"
        "本实验裁决仅为 `DURATION_DIAGNOSTIC_ONLY`。负状态持续天数与次日 BuyHold 收益的条件关系"
        "保存在 `artifacts/duration_summary.csv` 与 `artifacts/annual_duration.csv`。"
        "这些分组含留存选择，只能帮助决定是否值得设计新原型；不构成可执行收益或候选证据。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment, {
        "experiment_id": loaded.definition.experiment_id, "status": "COMPLETE",
        "experiment_type": "s009_negative_state_duration_diagnostic", "strategy_id": "S009",
        "credential_id": "SGC-S009-001", "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": list(PREDECESSORS),
        "predecessor_receipt_sha256": dict(PREDECESSORS), "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment)
    print(json.dumps({"status": "PASS", **facts, "receipt_sha256": result.receipt.sha256},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
