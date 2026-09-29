"""Run frozen S011 EX08 once and preserve its machine evidence."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment
from research_experiment import ExperimentResources, ExperimentWorkspace, load_experiment


def main() -> None:
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (root / name).exists():
            raise FileExistsError(f"S011 EX08 already has immutable output: {name}")
    loaded = load_experiment(root)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_formal_experiment_context(
        loaded.definition, repository_root=repository, workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("experiment platform did not issue a receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, root / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (root / "03_execution.md").write_text(
        "# S011 EX08 执行\n\n"
        f"正式 receipt：`{result.receipt.sha256}`。"
        f"ETF {summary['etf_sessions']} 日；{summary['factor_count']} 个风险偏好与利率因素，"
        f"{summary['comparison_count']} 项固定比较；顺序段可评价 "
        f"{summary['evaluated_folds']} 个、不足 {summary['insufficient_folds']} 个。"
        "数据身份、跨市场源日期及全部结果见 `artifacts/`。\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "receipt_sha256": result.receipt.sha256,
                      "decision": summary["decision"],
                      "evaluated_folds": summary["evaluated_folds"]},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
