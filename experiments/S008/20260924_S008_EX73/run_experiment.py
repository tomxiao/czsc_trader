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


EX72_RECEIPT = "c3e57d8b354c93bfc9c4c26456344cb2d8ac41bfc4be2219fa663469d50034ee"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX73 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / "20260924_S008_EX72" / "artifacts",
        expected_receipt_sha256=EX72_RECEIPT,
    )
    loaded = load_experiment(experiment_root)
    workspace = ExperimentWorkspace(
        repository_root
        / ".tmp"
        / "research-experiments"
        / uuid4().hex
        / loaded.definition.experiment_id,
        repository_root,
    )
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=2026097301),
        predecessors=(predecessor,),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S008 EX73 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。先验证 EX72 receipt，再通过 DFLS 正式请求"
        "2013-07-29 至 2024-12-31 的美国 CPI 发布事件，并以 ALFRED 截至 2024-12-31 的"
        "历史版本校准。供应商原始值未入档，密钥未入档；没有读取 ETF 收益或密封验证区。\n\n"
        f"DFLS 状态=`{facts['dfls_status']}`，记录数={facts.get('dfls_rows', 0)}，"
        f"ALFRED 版本数={facts.get('alfred_vintage_count', 0)}。\n",
        encoding="utf-8",
    )
    decision = str(facts["decision"])
    interpretation = (
        "只取得正式信息价值审计资格；尚无 CPI 对黄金上涨捕获有增量的证据。"
        if decision == "PROCEED_US_CPI_INFORMATION_VALUE_AUDIT"
        else "数据或因果门未通过，不得用于 S008 正式收益检验。"
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S008 EX73 结论\n\n"
        f"机器裁决：`{decision}`。"
        f"开发期 CPI 发布事件={facts.get('dfls_rows', 0)}；"
        f"当时版本同比容差内={facts.get('point_in_time_yoy_within_0_05pp', 0)}。"
        f"{interpretation}\n\n"
        "本轮仅重现此前已见的数据质量探索结论；不代表独立收益、原型或候选证据。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "us_cpi_release_data_and_causality_gate",
            "strategy_id": "S008",
            "credential_id": "SGC-S008-001",
            "symbol": "518880.SH",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": decision,
            "promotion_allowed": False,
            "predecessor_experiment_ids": [predecessor.experiment_id],
            "predecessor_receipt_sha256": {predecessor.experiment_id: predecessor.receipt_sha256},
            "rex_receipt_sha256": result.receipt.sha256,
        },
    )
    validate_experiment_archive(experiment_root)
    print(
        json.dumps(
            {
                "status": "PASS",
                "decision": decision,
                "dfls_rows": facts.get("dfls_rows", 0),
                "point_in_time_yoy_within_0_05pp": facts.get(
                    "point_in_time_yoy_within_0_05pp", 0
                ),
                "receipt_sha256": result.receipt.sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
