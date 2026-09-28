"""Execute and archive S011 EX01 after platform preflight passes."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from czsc_trader.research_tools import create_experiment_context, execute_experiment
from dataflows import Dataflows
from research_experiment import ExperimentResources, ExperimentWorkspace, load_experiment


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX01 already has immutable output: {name}")
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
        resources=ExperimentResources(max_workers=4, random_seed=loaded.definition.random_seed),
        real_returns=False,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S011 EX01 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。两项DFLS输入均READY，完整tsfresh设置"
        f"共{summary['parameterizations_per_raw_series']}个原始序列参数组合；"
        f"六个窗口产出{summary['factor_columns']}项因子列。逐列账本与原始面板见artifacts/。"
        "没有读取未来收益、搜索策略参数或创建候选。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX01 结论\n\n"
        f"机器状态：`{summary['decision']}`。覆盖率不少于95%的因子列"
        f"{summary['coverage_95']}项，无定义列{summary['undefined']}项，"
        f"同面板同窗口精确重复列{summary['exact_duplicate_columns']}项。"
        "本实验只盘点日线和30分钟OHLCV尾随时序形态，不证明Alpha或策略收益；"
        "阶段二仍须补充外围因子、冗余和前瞻关系统计后，才评审本轮唯一策略假设。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s011_tsfresh_wide_shape_census",
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
