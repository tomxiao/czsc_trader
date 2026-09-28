from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.experiment_archive import (
    build_experiment_manifest,
    validate_experiment_archive,
)
from czsc_trader.research_tools import create_experiment_context, execute_experiment
from dataflows import Dataflows
from research_experiment import (
    ExperimentResources,
    ExperimentWorkspace,
    load_experiment,
)


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in (
        "artifacts",
        "03_execution.md",
        "04_conclusion.md",
        "experiment_manifest.json",
    ):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX01 already has immutable output: {name}")
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
        resources=ExperimentResources(max_workers=1, random_seed=2026092801),
        real_returns=False,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(
        workspace.root,
        experiment_root / "artifacts",
        ignore=shutil.ignore_patterns("scratch"),
    )
    (experiment_root / "03_execution.md").write_text(
        "# S011 EX01 执行\n\n"
        f"REX receipt=`{result.receipt.sha256}`。schema v3 合成预检通过；"
        f"历史成分并集={summary['historical_member_union']}，可比较修订="
        f"{summary['comparable_rows']}，覆盖成分={summary['revised_members']}。"
        "全部材料经 DFLS 读取；没有读取 ETF 价格、未来收益、账户结果或密封验证数据。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX01 结论\n\n"
        f"机器裁决：`{facts['decision']}`。有效温度交易日="
        f"{summary['temperature']['sessions']}，变化交易日="
        f"{summary['temperature']['changed_sessions']}，诊断闭合状态="
        f"{summary['diagnostic_behavior']['closed_episodes']}。"
        "本实验只裁决机构预期机制是否取得一次固定收益信息增量检验资格；"
        "不证明 Alpha、交易策略或候选资格。Tushare 历史版本不可得、指数快照精确发布时间"
        "未核实，均继续作为开发证据限制。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        experiment_root,
        {
            "experiment_id": loaded.definition.experiment_id,
            "status": "COMPLETE",
            "experiment_type": "s011_sell_side_expectation_mechanism_gate",
            "strategy_id": "S011",
            "credential_id": "SGC-S011-001",
            "symbol": "159326.SZ",
            "development_cutoff": loaded.definition.development_cutoff.isoformat(),
            "decision": facts["decision"],
            "promotion_allowed": False,
            "reads_real_returns": False,
            "rex_receipt_sha256": result.receipt.sha256,
        },
    )
    validate_experiment_archive(experiment_root)
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "outcome": result.outcome.value,
                "decision": facts["decision"],
                "comparable_rows": facts["comparable_rows"],
                "revised_members": facts["revised_members"],
                "temperature_sessions": facts["temperature_sessions"],
                "closed_diagnostic_episodes": facts["closed_diagnostic_episodes"],
                "receipt_sha256": result.receipt.sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
