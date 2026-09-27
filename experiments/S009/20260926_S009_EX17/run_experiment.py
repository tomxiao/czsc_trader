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
    "20260926_S009_EX16": "4809e0fae5957d0e3e9dc3cba1d3dbfdd475b6a59f250798762cb9d26289c8ac",
}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment / name).exists():
            raise FileExistsError(f"EX17 already has immutable output: {name}")
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
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        real_returns=True, predecessors=predecessors,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = result.to_dict()["facts"]
    shutil.copytree(workspace.root, experiment / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (experiment / "03_execution.md").write_text(
        "# S009 EX17 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。前序 EX14–EX16 收据和不可变归档均已核验。"
        "仅读取已归档的开发期完整账户，合成 preflight 与逐日恒等式检查通过；未读取 2025 年及以后数据。"
        "逐日和年度归因、已见最优点及摘要见 artifacts。\n", encoding="utf-8",
    )
    (experiment / "04_conclusion.md").write_text(
        "# S009 EX17 结论\n\n"
        "本实验仅作事后差距归因，`POST_HOC_GAP_ATTRIBUTION_ONLY`。"
        "空仓漏涨、避损、持仓及进出场对数收益分项逐日与最终账户比值闭合。"
        "不得把空仓日的已实现行情当作决策时可得信号，也不授予任何新原型或候选资格。"
        "各账户数值见 `artifacts/attribution_summary.csv`；下一轮应依据该差距回到机会信息门。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment, {
        "experiment_id": loaded.definition.experiment_id, "status": "COMPLETE",
        "experiment_type": "s009_posthoc_gain_gap_attribution", "strategy_id": "S009",
        "credential_id": "SGC-S009-001", "symbol": "518880.SH",
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
