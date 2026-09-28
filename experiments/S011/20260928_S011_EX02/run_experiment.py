"""Execute and archive S011 EX02 after platform preflight passes."""

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


PREDECESSOR_RECEIPT = "b086702fda537d0129a437d9013e75dd2b5e942ea7aef1d9d5fb4be1013da4e8"


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX02 already has immutable output: {name}")
    predecessor = load_experiment_input(
        experiment_root.parent / "20260928_S011_EX01" / "artifacts",
        expected_receipt_sha256=PREDECESSOR_RECEIPT,
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
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        predecessors=(predecessor,),
        real_returns=False,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S011 EX02 执行\n\n"
        f"EX01 receipt=`{PREDECESSOR_RECEIPT}`；EX02 receipt=`{result.receipt.sha256}`。"
        f"六项DFLS输入均READY，人工与外围tsfresh四个面板共{summary['factor_columns']}项因子列。"
        "逐列账本、原始面板和输入身份见artifacts/。没有读取未来收益、搜索策略参数或创建候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX02 结论\n\n"
        f"机器状态：`{summary['decision']}`。覆盖率不少于95%的因子列{summary['coverage_95']}项，"
        f"全无定义列{summary['undefined']}项，常数列{summary['constant']}项，"
        f"同面板同窗口精确重复列{summary['exact_duplicate_columns']}项；各项有重叠，不可相加。"
        "本实验只扩展了因果可得的基础量价、日内和外围状态因子，尚未判断其与未来收益的关系。"
        "下一步在阶段二进行全量前瞻统计、市场与自身价格基准增量检验，披露多重筛选后再选择"
        "本轮唯一待评审策略假设。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s011_base_and_peripheral_factor_census",
        "strategy_id": "S011",
        "credential_id": "SGC-S011-001",
        "symbol": "159326.SZ",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": summary["decision"],
        "promotion_allowed": False,
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment_root)
    print(json.dumps({"status": "PASS", "receipt": result.receipt.sha256, **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
