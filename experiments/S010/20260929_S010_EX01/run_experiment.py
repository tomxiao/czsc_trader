"""Run the frozen S010 EX01 survey once and seal its complete result."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment
from research_experiment import ExperimentResources, ExperimentWorkspace, load_experiment


def main() -> None:
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (root / name).exists():
            raise FileExistsError(f"S010 EX01 already has immutable output: {name}")
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
        "# S010 EX01 执行\n\n"
        f"正式实验 receipt：`{result.receipt.sha256}`。源文件通过 schema v3 preflight，"
        f"实际计算人工因子 {summary['manual_factor_count']} 项、tsfresh 因子 {summary['tsfresh_factor_count']} 项；"
        f"可评价 {summary['usable_factor_count']} 项，三种期限共 {summary['scored_comparisons']} 个比较。"
        "具体数据身份、特征矩阵、全部评分与失败覆盖见 `artifacts/`。"
        "未读取验证截止日数据，也未执行账户回放。\n",
        encoding="utf-8",
    )
    (root / "04_conclusion.md").write_text(
        "# S010 EX01 结论\n\n"
        "机器状态：`FACTOR_SURVEY_COMPLETE`，仅表示预注册因子普查运行并归档完成。"
        f"共生成 {summary['factor_count']} 项因子，其中 {summary['usable_factor_count']} 项达到"
        "预定有效日期与唯一值下限。`factor_scores.csv` 保留所有可评价的期限比较；"
        "逐年方向和相对简单价格基线的顺序样本误差均属于开发池诊断。"
        "本轮尚未确认有效组件，尚未形成组件组合、策略或完整账户证据。"
        "下一步按金融职责审查全量分数、冗余与不利证据，再登记新的可证伪组件问题。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(root, {
        "experiment_id": loaded.definition.experiment_id,
        "strategy_id": "S010",
        "credential_id": "SGC-S010-001",
        "status": "COMPLETE",
        "experiment_type": "s010_stage2_factor_survey",
        "symbol": "159326.SZ",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": summary["decision"],
        "promotion_allowed": False,
        "predecessor_experiment_ids": [],
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(root)
    print(json.dumps({"status": "PASS", "receipt_sha256": result.receipt.sha256,
                      "factor_count": summary["factor_count"],
                      "usable_factor_count": summary["usable_factor_count"],
                      "scored_comparisons": summary["scored_comparisons"]},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
