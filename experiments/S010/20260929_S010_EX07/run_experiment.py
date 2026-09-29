"""Run and seal the frozen S010 EX07 cross-source survey."""

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
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
    "20260929_S010_EX06": "a5ae3eb4633f97d0b4c1aa815fc5fc6992eff7d4adc0e0a2afb009c331b02276",
}


def main() -> None:
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (root / name).exists():
            raise FileExistsError(f"S010 EX07 already has immutable output: {name}")
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
        "# S010 EX07 执行\n\n"
        f"正式实验 receipt：`{result.receipt.sha256}`。EX01—EX06 前序身份已核验。"
        f"四类受管数据形成 {summary['factor_count']} 项候选及"
        f" {summary['comparison_count']} 个预定比较；数据身份与全量结果见 `artifacts/`。\n",
        encoding="utf-8",
    )
    (root / "04_conclusion.md").write_text(
        "# S010 EX07 结论\n\n"
        "机器状态：`CROSS_SOURCE_SURVEY_COMPLETE`，表示预注册跨来源普查完成。"
        "风险、确认和退出职责须依据逐段方向、不利价格路径及冗余竞争解释另行评议；"
        "本实验不形成订单、完整账户或候选。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(root, {
        "experiment_id": loaded.definition.experiment_id, "strategy_id": "S010",
        "credential_id": "SGC-S010-001", "status": "COMPLETE",
        "experiment_type": "s010_stage2_cross_source_adverse_survey",
        "symbol": "159326.SZ", "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": summary["decision"], "promotion_allowed": False,
        "predecessor_experiment_ids": list(RECEIPTS),
        "predecessor_receipt_sha256": RECEIPTS,
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(root)
    print(json.dumps({"status": "PASS", "receipt_sha256": result.receipt.sha256,
                      "factor_count": summary["factor_count"],
                      "comparison_count": summary["comparison_count"]},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
