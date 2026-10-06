from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
import json
from math import isfinite
import re
from pathlib import Path

import pandas as pd
from dataflows import Dataflows
from strategy_evaluator import AuditStatus, audit_benchmark_replay, audit_replay

from .benchmarks import MA_BENCHMARK_SLOW_SESSIONS, BenchmarkReplay, replay_benchmarks
from .execution_data import BacktestExecutionData, _prepare_backtest_execution_data
from .audit_adapter import build_benchmark_evidence, build_replay_evidence
from .chart import render_backtest_chart_html
from .chart_context import BacktestChartMetrics, build_backtest_chart_context, build_ma_chart_context
from .evidence import build_manifest
from .metrics import calculate_metrics
from .models import StrategySnapshot
from .result import BacktestResult
from .signal_replay import SignalReplay
from .report import render_report
from .srt_bridge import (
    build_srt_signal_replay,
    describe_snapshot_strategy,
    execution_intraday_frequencies,
    load_srt_strategy,
    replay_srt_account,
    strategy_reference_symbol,
)


@dataclass(frozen=True)
class BacktestRequest:
    symbol: str
    asset_type: str
    start: date
    end: date
    initial_cash: float
    lot_size: int

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or re.fullmatch(r"[A-Z0-9]+\.[A-Z]+", self.symbol) is None:
            raise ValueError("symbol must be a normalized instrument code")
        if self.asset_type not in {"stock", "etf"}:
            raise ValueError("asset_type must be stock or etf")
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValueError("backtest requires ordered date values")
        if isinstance(self.initial_cash, bool) or not isinstance(self.initial_cash, (int, float)) or not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        if type(self.lot_size) is not int:
            raise TypeError("lot_size must be an integer")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


@dataclass(frozen=True)
class BacktestEvaluation:
    """Audited account calculation, with optional reports generated explicitly."""

    snapshot: StrategySnapshot
    request: BacktestRequest
    signals: SignalReplay
    execution_data: BacktestExecutionData
    result: BacktestResult
    benchmarks: BenchmarkReplay
    metrics: dict[str, object]
    manifest: dict[str, object]


def _validate_execution_window(
    request: BacktestRequest,
    execution_data: BacktestExecutionData,
) -> None:
    if request.start > request.end:
        raise ValueError("backtest start must not follow end")
    calendar = execution_data.requests["trading_calendar"]
    if request.end > date.fromisoformat(calendar.end):
        raise ValueError("backtest request exceeds the published cutoff")
    if request.start < date.fromisoformat(calendar.start):
        raise ValueError("backtest request precedes the prepared calendar window")
    sessions = pd.DatetimeIndex(
        pd.to_datetime(execution_data.evaluation_sessions, errors="raise"),
        name="dt",
    ).normalize()
    if sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("execution data evaluation sessions must be non-empty, unique and increasing")
    daily_sessions = pd.DatetimeIndex(
        pd.to_datetime(execution_data.execution_daily["dt"], errors="raise"),
        name="dt",
    ).normalize()
    requested = daily_sessions[
        (daily_sessions >= pd.Timestamp(request.start))
        & (daily_sessions <= pd.Timestamp(request.end))
    ]
    if requested.has_duplicates or not sessions.equals(requested):
        raise ValueError("request window differs from execution data evaluation sessions")


def _run_backtest(
    *,
    snapshot: StrategySnapshot,
    request: BacktestRequest,
    repository_root: Path | None = None,
    execution_data: BacktestExecutionData | None = None,
    dataflows: Dataflows,
) -> BacktestEvaluation:
    """Calculate and audit accounts without retaining reports or process records."""
    request = replace(request, symbol=request.symbol.upper())
    if repository_root is None:
        raise ValueError("SRT backtest requires a repository root")
    _, definition = describe_snapshot_strategy(
        repository_root,
        snapshot,
        deployment_symbol=request.symbol,
    )
    settings = definition.execution.settings
    policy_type = definition.execution.policy_type
    if policy_type == "FROZEN_RULE":
        policy_lot_size = settings["instrument"]["lot_size"]
    elif policy_type == "INTRADAY_OVERLAY":
        policy_lot_size = settings["lot_size"]
    else:
        raise ValueError(f"unsupported execution policy: {policy_type}")
    if type(policy_lot_size) is not int or request.lot_size != policy_lot_size:
        raise ValueError("request lot_size differs from strategy execution contract")
    if not isinstance(dataflows, Dataflows):
        raise TypeError("backtest requires host-supplied Dataflows")
    flows = dataflows
    if execution_data is None:
        execution_data = _prepare_backtest_execution_data(
            repository_root=repository_root,
            symbol=request.symbol,
            asset_type=request.asset_type,
            start=request.start,
            end=request.end,
            intraday_frequencies=execution_intraday_frequencies(definition),
            prior_sessions=MA_BENCHMARK_SLOW_SESSIONS,
            dataflows=flows,
        )
    if execution_data.symbol != request.symbol:
        raise ValueError("request symbol differs from TDR execution data")
    if execution_data.asset_type != request.asset_type:
        raise ValueError("request asset type differs from TDR execution data")
    _validate_execution_window(request, execution_data)
    strategy, signals = build_srt_signal_replay(
        snapshot=snapshot,
        execution_data=execution_data,
        start=execution_data.evaluation_start,
        end=execution_data.evaluation_end,
        repository_root=repository_root,
        dataflows=flows,
    )
    reference_symbol = strategy_reference_symbol(strategy)
    if snapshot.identity.kind == "REGISTERED":
        # The calculation runtime may be rebound; preserve the native symbol in reports.
        _, native_strategy = load_srt_strategy(repository_root, snapshot.identity.reference)
        reference_symbol = strategy_reference_symbol(native_strategy)
    application = {
        "mode": "native_symbol" if reference_symbol == request.symbol else "cross_symbol_generalization",
        "strategy_reference_symbol": reference_symbol,
        "backtest_symbol": request.symbol,
        "runtime_engine": "srt",
        "chart_renderer": "TDR",
        "chart_contract": "tdr_backtest_chart.v1",
    }
    result = replay_srt_account(
        strategy=strategy, signals=signals, execution_data=execution_data,
        initial_cash=request.initial_cash,
        dataflows=flows,
    )
    strategy_metrics = calculate_metrics(result, request.initial_cash)
    evidence = build_replay_evidence(
        signals, execution_data, result, request.initial_cash, strategy_metrics
    )
    audited = audit_replay(evidence)
    if audited.status is not AuditStatus.PASS:
        raise ValueError(f"SE replay audit failed: {', '.join(audited.reason_codes)}")
    audit = audited.to_dict()
    benchmarks = replay_benchmarks(
        signals, execution_data, request.initial_cash, lot_size=request.lot_size,
    )
    benchmark_audits = {
        name: audit_benchmark_replay(evidence)
        for name, evidence in build_benchmark_evidence(
            benchmarks, signals, execution_data, request.initial_cash, lot_size=request.lot_size,
        ).items()
    }
    failures = {
        name: result.reason_codes
        for name, result in benchmark_audits.items()
        if result.status is not AuditStatus.PASS
    }
    if failures:
        raise ValueError(f"SE benchmark audit failed: {failures}")
    audit["benchmarks"] = {
        name: result.to_dict() for name, result in benchmark_audits.items()
    }
    metrics = {
        "strategy": {
            "reference": snapshot.identity.reference,
            "metrics": strategy_metrics,
        },
        "benchmarks": benchmarks.metrics,
    }
    manifest = build_manifest(
        request=request,
        snapshot=snapshot,
        data=execution_data,
        signals=signals,
        metrics=metrics,
        audit=audit,
        application=application,
    )
    return BacktestEvaluation(snapshot, request, signals, execution_data, result, benchmarks, metrics, manifest)


def _backtest_report_files(evaluation: BacktestEvaluation) -> dict[str, bytes]:
    """Render requested report payloads; callers publish them via the evidence API."""
    if not isinstance(evaluation, BacktestEvaluation):
        raise TypeError("backtest reports require BacktestEvaluation")
    snapshot, request, signals = evaluation.snapshot, evaluation.request, evaluation.signals
    execution_data, result, benchmarks = evaluation.execution_data, evaluation.result, evaluation.benchmarks
    metrics, manifest = evaluation.metrics, evaluation.manifest
    application = manifest["application"]
    strategy_metrics = metrics["strategy"]["metrics"]
    def document(value):
        return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    files = {
        name: frame.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")
        for name, frame in (
            ("decisions.csv", result.decisions), ("orders.csv", result.orders),
            ("fills.csv", result.fills), ("account_daily.csv", result.account_daily),
            ("trades.csv", result.trades), ("buyhold_account_daily.csv", benchmarks.buyhold_account_daily),
            ("ma_signals.csv", benchmarks.ma_signals), ("ma_orders.csv", benchmarks.ma_orders),
            ("ma_account_daily.csv", benchmarks.ma_account_daily), ("ma_trades.csv", benchmarks.ma_trades),
        )
    }
    files.update({"metrics.json": document(metrics), "audit.json": document(manifest["audit"]),
                  "manifest.json": document(manifest),
                  "observations.json": document([item.to_dict() for item in result.observations])})
    chart_context = build_backtest_chart_context(
        signals, execution_data, result, request.initial_cash,
        metrics=BacktestChartMetrics(total_return=strategy_metrics["return"],
            max_drawdown=strategy_metrics["max_drawdown"], closed_trades=strategy_metrics["closed_trades"],
            calmar=strategy_metrics["calmar"], win_loss_ratio=strategy_metrics["win_loss_ratio"],
            win_rate=strategy_metrics["win_rate"]),
        benchmark_accounts=(("BuyHold", benchmarks.buyhold_account_daily), ("MA5/MA20", benchmarks.ma_account_daily)),
    )
    files["chart.html"] = render_backtest_chart_html(chart_context).encode("utf-8")
    files["ma_chart.html"] = render_backtest_chart_html(build_ma_chart_context(chart_context, benchmarks)).encode("utf-8")
    report = render_report(snapshot, metrics,
        strategy_reference_symbol=application["strategy_reference_symbol"], backtest_symbol=application["backtest_symbol"],
        application_mode=application["mode"], research_start=snapshot.research_start, research_end=snapshot.research_end,
        calculation_start=signals.calculation_start.date(), calculation_end=signals.calculation_end.date(),
        evaluation_start=signals.evaluation_start.date(), evaluation_end=signals.evaluation_end.date(),
        trading_days=len(result.account_daily), lot_size=request.lot_size)
    # Evidence filenames are content identities, so links remain valid after publication.
    for name in ("chart.html", "ma_chart.html"):
        report = report.replace(f"({name})", f"({sha256(files[name]).hexdigest()}.html)")
    files["report.md"] = report.encode("utf-8")
    return files
