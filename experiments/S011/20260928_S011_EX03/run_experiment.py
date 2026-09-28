"""Execute and archive S011 EX03 after platform preflight passes."""

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
    "20260928_S011_EX01": "b086702fda537d0129a437d9013e75dd2b5e942ea7aef1d9d5fb4be1013da4e8",
    "20260928_S011_EX02": "5c820f80a763596a80b8faa8340f986372fb252c2684a7c6aed600e0e124c931",
}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX03 already has immutable output: {name}")
    predecessors = tuple(
        load_experiment_input(
            experiment_root.parent / experiment_id / "artifacts",
            expected_receipt_sha256=receipt,
        ) for experiment_id, receipt in PREDECESSORS.items()
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
        predecessors=predecessors,
        real_returns=True,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S011 EX03 执行\n\n"
        f"前序EX01/EX02 receipt均通过身份校验；EX03 receipt=`{result.receipt.sha256}`。"
        f"质量筛后因子列{summary['quality_filtered_factor_columns']}项，"
        f"四个收益期限共{summary['factor_horizon_tests']}项因子-期限检验。"
        "完整逐项账本、收益代理、简单价格基准和输入身份见artifacts/；"
        "没有实施订单、成本或完整账户回测。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX03 结论\n\n"
        f"机器状态：`{summary['decision']}`。同时具备至少250个全样本、"
        f"各半段至少100个配对观测的检验{summary['valid_test_rows']}项；"
        f"其中前后半段秩相关同号{summary['split_half_same_sign_rows']}项。"
        "这些是大规模、重叠收益窗口的开发池探索统计；同号或高相关并不证明可交易Alpha，"
        "沪深300差额也只控制宽基市场的一个代理。阶段二还须检查统计结果的金融逻辑、"
        "自身价格基准增量、筛选偏差和执行后剩余收益，再逐轮评审唯一假设。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s011_broad_factor_forward_relation_census",
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
