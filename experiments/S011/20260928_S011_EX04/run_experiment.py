"""Execute and archive S011 EX04 after platform preflight passes."""

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
    "20260928_S011_EX02": "5c820f80a763596a80b8faa8340f986372fb252c2684a7c6aed600e0e124c931",
    "20260928_S011_EX03": "fe13686d0a5a4167438ca496716d7a7554b37de875270412d793c8ab39a57e3b",
}


def main() -> None:
    sys.dont_write_bytecode = True
    experiment_root = Path(__file__).resolve().parent
    repository_root = experiment_root.parents[2]
    for name in ("artifacts", "03_execution.md", "04_conclusion.md", "experiment_manifest.json"):
        if (experiment_root / name).exists():
            raise FileExistsError(f"EX04 already has immutable output: {name}")
    predecessors = tuple(
        load_experiment_input(
            experiment_root.parent / experiment_id / "artifacts", expected_receipt_sha256=receipt,
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
        "# S011 EX04 执行\n\n"
        f"EX02与EX03的前序receipt及档案通过校验；EX04 receipt=`{result.receipt.sha256}`。"
        f"固定完整样本{summary['complete_case_days']}个交易日；使用自然零分界、"
        "预定5/10/20日结果、20日连续区块和2000次抽样。逐组、分层及完整日期面板见artifacts/。"
        "没有模拟限价成交、真实账户或参数搜索。\n",
        encoding="utf-8",
    )
    (experiment_root / "04_conclusion.md").write_text(
        "# S011 EX04 结论\n\n"
        f"机器状态：`{summary['decision']}`。10日ETF毛收益的走强减非走强均值差"
        f"`{summary['primary_etf_spread_h10']:.6f}`；减沪深300同窗收益后的差"
        f"`{summary['primary_market_difference_spread_h10']:.6f}`；控制既有价格和市场变量后的"
        f"差额收益状态系数`{summary['conditional_market_difference_coefficient_h10']:.6f}`。"
        f"走强状态关闭次数折算`{summary['state_closes_per_60_days']:.2f}`次/60日。"
        "区块区间、分半与分层及20 bp成本代理见artifacts/。"
        "这些仍是看过EX03筛选结果后的开发池诊断，不证明可执行Alpha；"
        "是否进入阶段三须结合完整证据另行判断。\n",
        encoding="utf-8",
    )
    build_experiment_manifest(experiment_root, {
        "experiment_id": loaded.definition.experiment_id,
        "status": "COMPLETE",
        "experiment_type": "s011_targeted_fx_hypothesis_diagnostic",
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
