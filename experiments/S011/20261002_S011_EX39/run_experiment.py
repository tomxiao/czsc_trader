"""Source-bound one-shot managed evaluation and immutable local evidence archive."""

from datetime import timedelta
import json
from pathlib import Path
import shutil
import traceback

from dataflows import Dataflows, LocalCacheConfig, DataRequest, Dataset
from research_experiment import (
    load_experiment,
    load_experiment_input,
    experiment_source_sha256,
    ExperimentResources,
    ExperimentWorkspace,
)
from czsc_trader.research_tools import (
    preflight_experiment,
    create_formal_experiment_context,
    execute_experiment,
)
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    assert not (ROOT / "artifacts").exists(), "A prior execution must not be overwritten"
    inputs = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))
    names = ("experiment.py", "run_experiment.py", "inputs.json", "01_goal.md", "02_design.md")
    binding = dict(
        schema_version=3,
        module="experiment",
        qualname="Experiment",
        source_files=list(names),
        source_sha256=experiment_source_sha256(ROOT, names),
        dependencies=inputs["dependencies"],
    )
    if (ROOT / "experiment_binding.json").exists():
        assert json.loads((ROOT / "experiment_binding.json").read_text(encoding="utf-8")) == binding
    else:
        write(ROOT / "experiment_binding.json", binding)
    loaded = load_experiment(ROOT)
    predecessors = tuple(
        load_experiment_input(ROOT.parent / ex / "artifacts", expected_receipt_sha256=digest)
        for ex, digest in inputs["predecessors"].items()
    )
    resources = ExperimentResources(1, 39, native_threads_per_worker=4)
    cache = LocalCacheConfig(
        REPO / ".tmp/s011-regeneration/cache", "S011-20260928-regeneration-v1", timedelta(days=1)
    )
    flows = Dataflows(env_file=REPO / ".env", cache=cache)
    requests = tuple(
        DataRequest(dataset, symbol, start, "2026-09-28", "2026-09-28", frequency)
        for dataset, symbol, start, frequency in (
            (Dataset.ETF_OHLCV, "159326.SZ", "2024-12-26", "daily"),
            (Dataset.ETF_OHLCV, "159326.SZ", "2024-12-26", "30m"),
            (Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ", "2024-12-26", "daily"),
            (Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, "000300.SH", "2024-12-26", "daily"),
            (Dataset.GLOBAL_INDEX_DAILY, "SPX", "2024-12-16", "daily"),
            (Dataset.TRADING_CALENDAR, "SSE", "2025-02-06", "daily"),
        )
    )
    report = preflight_experiment(
        loaded,
        resources=resources,
        predecessors=predecessors,
        dataflows=flows,
        data_requests=requests,
    )
    write(ROOT / "preflight.json", report.to_dict())
    print(json.dumps(report.to_dict(), ensure_ascii=False), flush=True)
    report.require_pass()
    workspace = ExperimentWorkspace(REPO / ".tmp/s011-c0621-evaluation/EX39", REPO)
    context = create_formal_experiment_context(
        loaded.definition,
        repository_root=REPO,
        resources=resources,
        workspace=workspace,
        predecessors=predecessors,
        cache=cache,
    )
    failure = None
    try:
        result = execute_experiment(loaded, context)
    except Exception:
        failure = traceback.format_exc()
        workspace.path("technical_failure.txt").write_text(failure, encoding="utf-8", newline="\n")
    shutil.copytree(workspace.root, ROOT / "artifacts")
    if failure:
        status = "TECHNICAL_FAILURE"
        execution = "技术执行失败，证据见 artifacts/technical_failure.txt；不原地重试。"
        conclusion = execution
    else:
        status = "COMPLETE"
        summary = json.loads(workspace.path("evaluation_summary.json").read_text(encoding="utf-8"))
        write(ROOT / "evaluation_summary.json", summary)
        write(
            ROOT / "evaluation_record.json",
            json.loads(workspace.path("evaluation_record.json").read_text(encoding="utf-8")),
        )
        execution = f"受管评价完成；回执 `{result.receipt.sha256}`。一个候选、一个窗口、一个标准成本场景，未搜索参数。基准为显式 LimitBuyHold。平台通用回测图因默认附加基准而暂缓。"
        m = summary["strategy_metrics"]
        b = summary["benchmark_metrics"]
        conclusion = (
            f"固定候选 `S011-C0621`，内容身份 `{summary['content_sha256']}`。已见开发池 2025-02-06 至 2026-09-28，共 {summary['sessions']} 个交易日。\n\n"
            f"| 指标 | 策略 | 正式限价 BuyHold |\n| --- | ---: | ---: |\n"
            f"| 收益率 | {m['return']:.4%} | {b['return']:.4%} |\n"
            f"| 最大回撤 | {m['max_drawdown']:.4%} | {b['max_drawdown']:.4%} |\n"
            f"| 闭合交易数 | {m['closed_trades']} | {b['closed_trades']} |\n"
            f"| 卡玛比率 | {m['calmar']:.4f} | {b['calmar']:.4f} |\n"
            f"| 盈亏比 | {m['win_loss_ratio']:.4f} | 不适用（未闭合持仓） |\n"
            f"| 交易胜率 | {m['win_rate']:.4%} | 不适用（未闭合持仓） |\n\n"
            f"CAGR：策略 {summary['strategy_cagr']:.4%}，限价基准 {summary['benchmark_cagr']:.4%}；60 日折算闭合交易频率 {summary['closed_trades_per_60_sessions']:.4f}。"
            f"已确认目标全部满足：`{summary['all_targets_met']}`；逐项结果见 [评价摘要](evaluation_summary.json)。\n\n"
            "基准为显式 LimitBuyHold，lot_size=100、溢价0.3%、每侧成本10bp、初始资金100万元。"
            "TDR 通用图表自带 NextOpenBuyHold，未采用本次研究基准；图表输出暂缓，待平台显式基准接口调整。\n\n"
            "这次执行只建立当前候选身份下的评价证据，未重做邻域、压力或全部阶段交付。已见开发池不构成独立验证；历史选择偏差继续存在。阶段五、冻结和部署均未授权。"
        )
    (ROOT / "03_execution.md").write_text(
        "# EX39 执行\n\n" + execution + "\n", encoding="utf-8", newline="\n"
    )
    (ROOT / "04_conclusion.md").write_text(
        "# EX39 C0621 基准回测与评价\n\n" + conclusion + "\n", encoding="utf-8", newline="\n"
    )
    build_experiment_manifest(
        ROOT,
        dict(
            experiment_id=ROOT.name,
            strategy_id="S011",
            symbol="159326.SZ",
            status=status,
            development_cutoff="2026-09-28",
        ),
    )
    validate_experiment_archive(ROOT)
    print(json.dumps({"status": status, "experiment": ROOT.name}), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
