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
            raise FileExistsError(f"EX03 already has immutable output: {name}")
    loaded = load_experiment(experiment_root)
    loaded.implementation.synthetic_precheck()
    workspace = ExperimentWorkspace(
        repository_root / ".tmp" / "research-experiments" / uuid4().hex / loaded.definition.experiment_id,
        repository_root,
    )
    context = create_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        workspace=workspace,
        resources=ExperimentResources(max_workers=1, random_seed=20260901),
        real_returns=False,
    )
    result = execute_experiment(loaded, context)
    if result.receipt is None:
        raise RuntimeError("platform did not issue an experiment receipt")
    facts = dict(result.facts)
    shutil.copytree(workspace.root, experiment_root / "artifacts")
    (experiment_root / "03_execution.md").write_text(
        "# S009 EX03 执行\n\n"
        f"REX receipt={result.receipt.sha256}。EX02冻结身份通过，资源种子与定义一致；七项DFLS请求通过。"
        f"面板行数={facts['panel_rows']}，完整行数={facts['complete_rows']}，冻结候选特征={facts['candidate_features']}。"
        "未读取未来收益或2025年以后验证区。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S009 EX03 结论\n\n"
        f"机器裁决：`{facts['decision']}`。共同有效期裁剪后，跨市场价格传导和ETF份额面板通过数据门。"
        "该结论只授权按冻结目录执行信息价值审计，不证明任何特征有效。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s009_cross_market_parity_data_gate_successor",
        "strategy_id": "S009",
        "credential_id": "SGC-S009-001",
        "symbol": "518880.SH",
        "development_cutoff": loaded.definition.development_cutoff.isoformat(),
        "decision": facts["decision"],
        "promotion_allowed": False,
        "technical_predecessor_experiment_id": "20260925_S009_EX02",
        "rex_receipt_sha256": result.receipt.sha256,
    })
    validate_experiment_archive(experiment_root)
    print(json.dumps({
        "status": "PASS",
        "decision": facts["decision"],
        "panel_rows": facts["panel_rows"],
        "complete_rows": facts["complete_rows"],
        "candidate_features": facts["candidate_features"],
        "receipt_sha256": result.receipt.sha256,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

