"""Run and seal the frozen S010 EX03 intraday review."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from czsc_trader.research_tools import create_formal_experiment_context, execute_experiment
from research_experiment import (
    ExperimentResources, ExperimentWorkspace, load_experiment, load_experiment_input,
)


RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
}


def main() -> None:
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (root / name).exists():
            raise FileExistsError(f"S010 EX03 already has immutable output: {name}")
    predecessors = tuple(
        load_experiment_input(root.parent / name / "artifacts", expected_receipt_sha256=receipt)
        for name, receipt in RECEIPTS.items()
    )
    loaded = load_experiment(root)
    workspace = ExperimentWorkspace(
        repository / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository,
    )
    context = create_formal_experiment_context(
        loaded.definition, repository_root=repository, workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=loaded.definition.random_seed),
        predecessors=predecessors,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("experiment platform did not issue a receipt")
    summary = json.loads(workspace.path("summary.json").read_text(encoding="utf-8"))
    shutil.copytree(workspace.root, root / "artifacts", ignore=shutil.ignore_patterns("scratch"))
    (root / "03_execution.md").write_text(
        "# S010 EX03 执行\n\n"
        f"正式实验 receipt：`{result.receipt.sha256}`。EX01/EX02 前序收据及档案身份已核验。"
        f"计算 {summary['intraday_factor_count']} 个预定日内因子、{summary['comparison_count']} 个期限/基线比较；"
        f"首根 30 分钟线开盘价与日线不同的交易日有 {summary['open_discrepancy_days']} 个，"
        "这些开盘价未进入因子。数据身份与逐段结果见 `artifacts/`。\n",
        encoding="utf-8",
    )
    (root / "04_conclusion.md").write_text(
        "# S010 EX03 结论\n\n"
        "机器状态：`INTRADAY_REVIEW_COMPLETE`，表示预注册日内审查完成。"
        f"历史振幅高状态 {summary['range_high_days']} 个测试日，低状态 {summary['range_low_days']} 个测试日；"
        "未来五日开盘价格及 20bp 往返成本代理仅用于信息审查，连续测试日的标签可能重叠。"
        "组件职责与有效性须结合逐段误差、方向、块区间及金融竞争解释判断；"
        "本实验不形成订单、完整账户或候选。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(root, {
        "experiment_id": loaded.definition.experiment_id, "strategy_id": "S010",
        "credential_id": "SGC-S010-001", "status": "COMPLETE",
        "experiment_type": "s010_stage2_intraday_mechanism_review",
        "symbol": "159326.SZ", "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": summary["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": list(RECEIPTS),
        "predecessor_receipt_sha256": RECEIPTS,
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(root)
    print(json.dumps({"status": "PASS", "receipt_sha256": result.receipt.sha256,
                      "factor_count": summary["intraday_factor_count"],
                      "comparison_count": summary["comparison_count"],
                      "open_discrepancy_days": summary["open_discrepancy_days"]},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
