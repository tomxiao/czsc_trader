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
    "20260926_S009_EX14": "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f",
    "20260926_S009_EX15": "4d961be51f966963448227ebb281ddfe918f0731944940ca53d06b7a8dac6f4f",
}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment / name).exists():
            raise FileExistsError(f"EX16 already has immutable output: {name}")
    predecessors = tuple(load_experiment_input(
        experiment.parent / experiment_id / "artifacts",
        expected_receipt_sha256=receipt,
    ) for experiment_id, receipt in PREDECESSORS.items())
    loaded = load_experiment(experiment)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_experiment_context(
        loaded.definition, repository_root=repository, dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1,
                                      random_seed=loaded.definition.random_seed,
                                      max_evaluations=118),
        real_returns=True, predecessors=predecessors,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = result.to_dict()["facts"]
    shutil.copytree(workspace.root, experiment / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (experiment / "03_execution.md").write_text(
        "# S009 EX16 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。EX14与EX15前序receipt均已核验。"
        "按预注册设计完成P01单维29点、P02单维25点、P04联合64次建议；"
        "每个原型得分前5个不同点完成30bp压力回放。完整trial和账户证据见artifacts。"
        "2025年及以后封存数据未读取。\n",
        encoding="utf-8",
    )
    (experiment / "04_conclusion.md").write_text(
        "# S009 EX16 结论\n\n"
        f"机器裁决：`{facts['decision']}`。118次建议中"
        f"{facts['distinct_points']}个不同原型-参数点；开发期双硬门通过"
        f"{facts['qualifying_points']}点，各原型分布：{json.dumps(facts['qualified_by_prototype'], ensure_ascii=False)}。"
        "此为已见开发池阈值证据，不构成独立验证或候选资格。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE", "experiment_type": "s009_alternative_threshold_search",
        "strategy_id": "S009", "credential_id": "SGC-S009-001", "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": list(PREDECESSORS),
        "predecessor_receipt_sha256": dict(PREDECESSORS),
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment)
    print(json.dumps({"status": "PASS", **facts, "receipt_sha256": result.receipt.sha256},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
