"""Shared research-evaluation Harness driven by SRT, TXE and SE contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
from math import isfinite
from pathlib import Path
import platform
from importlib import metadata
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd
from dataflows import Dataflows
from strategy_evaluator import EvaluationProtocol, MetricObservation, MetricStatus
from strategy_runtime import StrategyCandidate, StrategyRuntime, canonical_sha256, ImplementationDependency
from strategy_manager import CandidateKey, CandidateDerivation
from research_experiment import ExperimentArtifact
from strategy_runtime.implementation_identity import implementation_sha256
from trading_execution_engine import ExecutionResult

from ..backtesting.execution_data import (
    BacktestExecutionData,
    prepare_backtest_execution_data,
)
from ..backtesting.benchmarks import BuyHoldReplay, replay_buyhold
from ..backtesting.benchmark_contracts import EvaluationBenchmark
from ..backtesting.models import StrategyIdentity, StrategySnapshot
from ..backtesting.signal_replay import SignalReplay
from ..backtesting.srt_bridge import (
    build_srt_signal_replay, execution_intraday_frequencies, load_srt_strategy,
    replay_srt_account,
)

METRIC_SEMANTICS_VERSION = "candidate-srt-txe-v4-explicit-benchmark"


@dataclass(frozen=True)
class CandidateEvaluationContext:
    repository: Any
    symbol: str
    asset_type: str
    periods: tuple[tuple[str, tuple[pd.Timestamp, pd.Timestamp]], ...]
    fee_rate: float = 0.0005
    init_cash: float = 1_000_000.0
    workers: int = 1
    frequency_window_days: int = 60
    family_id: str = ""
    review_data_root: Path | None = None
    review_data_hash: str | None = None
    candidate_runtime_roots: dict[str, Path] | None = None
    dataflows: Dataflows | None = None


@dataclass(frozen=True)
class EvaluationWorkspace:
    execution_data: BacktestExecutionData
    periods: dict[str, tuple[pd.Timestamp, pd.Timestamp]]


@dataclass(frozen=True)
class EvaluationWindow:
    window_id: str
    start: date
    end: date

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValueError("evaluation window requires ordered date values")


@dataclass(frozen=True)
class EvaluationCost:
    scenario_id: str
    one_way_cost: float
    measurement_tier: str = "FORMAL"

    def __post_init__(self):
        if isinstance(self.one_way_cost, bool) or not isfinite(self.one_way_cost) or not 0 <= self.one_way_cost < 1:
            raise ValueError("evaluation cost must be finite and in [0, 1)")


@dataclass(frozen=True)
class EvaluationRequest:
    """Complete researcher-owned input contract for one executable strategy."""

    repository_root: Path
    experiment_id: str
    strategy: StrategyCandidate
    runtime_binding: Mapping[str, object]
    symbol: str
    asset_type: str
    windows: tuple[EvaluationWindow, ...]
    data_cutoff: date
    initial_cash: float
    costs: tuple[EvaluationCost, ...]
    execution_data: BacktestExecutionData
    benchmark: EvaluationBenchmark
    workers: int = 1
    frequency_window_days: int = 60
    execution_mode: str = "FULL"
    lineage: EvaluationLineage | None = None
    dependencies: tuple[ImplementationDependency, ...] = ()

    def __post_init__(self):
        if type(self.data_cutoff) is not date:
            raise TypeError("data_cutoff must be a date")
        if not isinstance(self.strategy, StrategyCandidate):
            raise TypeError("strategy must be StrategyCandidate")
        if not isinstance(self.runtime_binding, Mapping):
            raise TypeError("runtime_binding must be a mapping")
        if not isinstance(self.windows, tuple) or not all(isinstance(item, EvaluationWindow) for item in self.windows):
            raise TypeError("windows must be a tuple of EvaluationWindow")
        if not isinstance(self.costs, tuple) or not all(isinstance(item, EvaluationCost) for item in self.costs):
            raise TypeError("costs must be a tuple of EvaluationCost")
        if type(self.workers) is not int or self.workers < 1:
            raise ValueError("workers must be a positive integer")
        if isinstance(self.initial_cash, bool) or not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        if not isinstance(self.dependencies, tuple) or not all(isinstance(item, ImplementationDependency) for item in self.dependencies):
            raise TypeError("dependencies must contain ImplementationDependency")
        if self.lineage is not None and not isinstance(self.lineage, EvaluationLineage):
            raise TypeError("lineage must be EvaluationLineage")


@dataclass(frozen=True, slots=True)
class EvaluationLineage:
    derivation: CandidateDerivation

    def __post_init__(self):
        if not isinstance(self.derivation, CandidateDerivation):
            raise TypeError("lineage requires CandidateDerivation")


@dataclass(frozen=True, slots=True)
class EvaluationIdentity:
    candidate: CandidateKey
    content_sha256: str
    input_sha256: str
    protocol_sha256: str
    environment_sha256: str

    def __post_init__(self):
        if not isinstance(self.candidate, CandidateKey):
            raise TypeError("evaluation identity requires CandidateKey")
        for value in (self.content_sha256, self.input_sha256, self.protocol_sha256, self.environment_sha256):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("evaluation identities must be lowercase SHA-256")

    def to_dict(self):
        return {
            "candidate": self.candidate.to_dict(), "content_sha256": self.content_sha256,
            "input_sha256": self.input_sha256, "protocol_sha256": self.protocol_sha256,
            "environment_sha256": self.environment_sha256,
        }

    @property
    def evaluation_id(self):
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True)
class EvaluationRun:
    """SRT and TXE facts plus the SE observation for one evaluation coordinate."""

    candidate_id: str
    window_id: str
    scenario_id: str
    signals: SignalReplay
    execution: ExecutionResult
    observation: MetricObservation
    buyhold: BuyHoldReplay | None = None
    identity: EvaluationIdentity | None = None


@dataclass(frozen=True)
class EvaluationResult:
    """Complete, non-governance result returned by the research Harness."""

    runs: tuple[EvaluationRun, ...]
    request_hash: str = ""
    strategy_identity: str = ""
    runtime_binding_hash: str = ""
    data_identity: str = ""
    result_hash: str = ""
    execution_mode: str = "FULL"
    attempt_id: str | None = None
    record: ExperimentArtifact | None = None

    @property
    def observations(self) -> tuple[MetricObservation, ...]:
        return tuple(item.observation for item in self.runs)


def _scenario_settings(scenario: str, base_fee_rate: float) -> tuple[float, int]:
    if scenario == "standard":
        fee, slippage = base_fee_rate, 0
    elif scenario.startswith("fee_x"):
        fee, slippage = base_fee_rate * float(scenario.removeprefix("fee_x")), 0
    elif scenario.startswith("total_cost_") and scenario.endswith("bp"):
        fee, slippage = float(scenario.removeprefix("total_cost_").removesuffix("bp")) / 10_000, 0
    elif scenario.startswith("slippage_") and scenario.endswith("bp"):
        fee, slippage = base_fee_rate, int(scenario.removeprefix("slippage_").removesuffix("bp"))
    else:
        raise ValueError(f"unsupported stress scenario: {scenario}")
    if not isfinite(fee) or not 0 <= fee < 1 or slippage < 0:
        raise ValueError(f"invalid cost scenario: {scenario}")
    return fee, slippage


def prepare_evaluation_workspace(
    context: CandidateEvaluationContext, protocol: EvaluationProtocol, *,
    include_five_minute: bool = False,
) -> EvaluationWorkspace:
    options = {"include_five_minute": True} if include_five_minute else {}
    if context.review_data_root is not None:
        from ..application.review_data import load_review_dataset
        if context.review_data_hash is None:
            raise ValueError("review execution requires the sealed dataset hash")
        execution_data = load_review_dataset(
            context.review_data_root, context.review_data_hash
        )
        if (
            execution_data.symbol,
            execution_data.asset_type,
            execution_data.cutoff,
        ) != (
            context.symbol, context.asset_type, pd.Timestamp(protocol.development_cutoff).date(),
        ):
            raise ValueError("review dataset identity differs from evaluation request")
        if include_five_minute and execution_data.execution_five_minute is None:
            raise ValueError("review dataset has no required five-minute execution prices")
    else:
        if context.review_data_hash is not None:
            raise ValueError("review dataset hash requires a snapshot directory")
        first_start = min(start for _, (start, _) in context.periods)
        execution_data = prepare_backtest_execution_data(
            srt_data_root=getattr(
                context.repository,
                "tdr_srt_root",
                Path(context.repository.root) / "data" / "backtest",
            ),
            symbol=context.symbol,
            asset_type=context.asset_type,
            start=first_start.date(),
            end=pd.Timestamp(protocol.development_cutoff).date(),
            env_file=context.repository.root / ".env" if context.dataflows is None else None,
            include_five_minute=bool(options),
            dataflows=context.dataflows,
        )
    cutoff = pd.Timestamp(protocol.development_cutoff).normalize()
    dates = pd.DatetimeIndex(pd.to_datetime(execution_data.adjusted_daily["dt"])).normalize()
    execution_dates = pd.DatetimeIndex(
        pd.to_datetime(execution_data.execution_daily["dt"])
    ).normalize()
    for label, index in (("research market", dates), ("execution", execution_dates)):
        if index.empty or index.max() != cutoff:
            actual = None if index.empty else index.max().date().isoformat()
            raise ValueError(f"{label} data does not reach development cutoff: requested={cutoff.date()}, actual={actual}")
        if index.has_duplicates or not index.is_monotonic_increasing:
            raise ValueError(f"{label} sessions must be unique and increasing")
    if not dates.equals(execution_dates):
        raise ValueError("research and execution session calendars differ")
    periods = dict(context.periods)
    if not periods or len(periods) != len(context.periods):
        raise ValueError("evaluation windows must be non-empty and unique")
    for name, (start, end) in periods.items():
        if start != start.normalize() or end != end.normalize() or start > end:
            raise ValueError(f"invalid evaluation window: {name}")
        if start not in dates or end not in dates:
            raise ValueError(f"evaluation window {name} is not bounded by trading sessions")
        if end > cutoff:
            raise ValueError(f"evaluation window {name} exceeds development cutoff")
        if not (dates < start).any():
            raise ValueError(f"evaluation window {name} has no prior signal session")
    return EvaluationWorkspace(execution_data, periods)


def _snapshot(context: CandidateEvaluationContext, item: dict[str, object]):
    payload = item.get("strategy_payload")
    if not isinstance(payload, dict):
        raise ValueError(f"candidate {item['candidate_id']} has no complete strategy_payload")
    reference = str(item["candidate_id"])
    registered = bool(item.get("is_incumbent") and "-v" in reference)
    if registered:
        release, strategy = load_srt_strategy(context.repository.root, reference, deployment_symbol=context.symbol)
        if canonical_sha256(payload) != canonical_sha256(release.payload):
            raise ValueError("incumbent manifest payload differs from the frozen release")
        identity, source_hash = StrategyIdentity("REGISTERED", reference, "evaluation"), release.release_hash
    else:
        family = str(item.get("strategy_id", context.family_id))
        candidate_id = reference.removeprefix(family + "-") if family else reference
        roots = context.candidate_runtime_roots or {}
        runtime_root = roots.get(reference) or roots.get(candidate_id)
        candidate = StrategyCandidate(family, candidate_id, payload, runtime_root)
        strategy = StrategyRuntime().describe(candidate)
        identity = StrategyIdentity("CANDIDATE", candidate.reference_id, "evaluation")
        source_hash = candidate.runtime_identity_sha256
    return StrategySnapshot(
        identity, source_hash, canonical_sha256(payload), payload,
        runtime_root=runtime_root if not registered else None,
    ), strategy


def prepare_candidate_replays(context, protocol, payloads, candidate_ids):
    """Load complete SRT identities, publications and window decisions once per call."""
    by_id = {str(item["candidate_id"]): item for item in payloads}
    if len(by_id) != len(payloads) or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("duplicate candidate identities")
    if missing := set(candidate_ids) - set(by_id):
        raise ValueError(f"candidate payloads missing: {sorted(missing)}")
    loaded = {key: _snapshot(context, by_id[key]) for key in candidate_ids}
    workspace = prepare_evaluation_workspace(
        context, protocol,
        include_five_minute=any(execution_intraday_frequencies(strategy) for _, strategy in loaded.values()),
    )
    replays = {}
    for key, (snapshot, _) in loaded.items():
        replays[key] = {
            name: build_srt_signal_replay(
                snapshot=snapshot,
                execution_data=workspace.execution_data,
                start=start,
                end=end,
                repository_root=context.repository.root,
                dataflows=context.dataflows,
            )
            for name, (start, end) in workspace.periods.items()
        }
    return workspace, replays


def execute_candidate_replay(context, workspace, prepared, fee_rate):
    """Return the ledger and its effective-cost evidence without editing SRT."""
    strategy, signals = prepared
    result = replay_srt_account(
        strategy=strategy,
        signals=signals,
        execution_data=workspace.execution_data,
        initial_cash=context.init_cash, fee_rate_override=fee_rate,
        dataflows=context.dataflows,
    )
    support = dict(signals.support_data)
    policy = support["execution_policy"]
    settings = dict(policy["settings"])
    if policy["policy_type"] == "FROZEN_RULE":
        settings["capital"] = {**settings["capital"], "fee_rate": fee_rate}
    else:
        settings["one_way_cost"] = fee_rate
    support["execution_policy"] = {**policy, "settings": settings}
    support["evaluation_fee_rate"] = fee_rate
    return replace(signals, support_data=support), result


def _observation(context, candidate_id, window, tier, scenario, result, execution_data=None):
    equity = result.equity
    total = float(equity.iloc[-1] / context.init_cash - 1)
    cagr = float((1 + total) ** (252 / len(equity)) - 1)
    drawdown = float(equity.div(equity.cummax().clip(lower=context.init_cash)).sub(1).min())
    calmar = cagr / abs(drawdown) if abs(drawdown) > 1e-12 else None
    closed = result.trades.loc[result.trades["status"].eq("CLOSED")]
    returns = closed["net_return"].astype(float)
    wins, losses = returns[returns > 0], returns[returns < 0]
    pf = None
    win_loss_ratio = None
    if closed.empty:
        status = MetricStatus.NO_CLOSED_TRADES
    elif wins.empty:
        status = MetricStatus.NO_WINS
    elif losses.empty:
        status = MetricStatus.NO_LOSSES
    else:
        pf = float(wins.sum() / abs(losses.sum()))
        win_loss_ratio = float(wins.mean() / abs(losses.mean()))
        status = MetricStatus.LOW_SAMPLE if len(closed) < 10 else MetricStatus.VALID
    fills = result.fills
    turnover = float((fills["quantity"] * fills["price"]).sum() / context.init_cash) if not fills.empty else 0.0
    cost = float(fills["fees"].sum() / context.init_cash) if not fills.empty else 0.0
    # Overlay core establishment is represented by opening account state, not an event fill.
    opening = result.account_daily.iloc[0]
    if int(opening["quantity_before"]) > 0:
        if execution_data is None:
            raise ValueError("opening holdings require an execution-price ledger")
        prior = execution_data.execution_daily.loc[
            execution_data.execution_daily["dt"] < opening["date"]
        ]
        if prior.empty:
            raise ValueError("opening holdings have no pre-window execution price")
        gross = int(opening["quantity_before"]) * float(prior.iloc[-1]["close"])
        turnover += gross / context.init_cash
        cost += (context.init_cash - float(opening["cash_before"]) - gross) / context.init_cash
    count_days = context.frequency_window_days
    if type(count_days) is not int or count_days <= 0:
        raise ValueError("frequency window must be a positive integer")
    sessions = pd.DatetimeIndex(equity.index).normalize()
    exits = pd.DatetimeIndex(pd.to_datetime(closed["exit_date"])).normalize()
    counts = [float(((exits >= sessions[i-count_days+1]) & (exits <= sessions[i])).sum()) for i in range(count_days-1, len(sessions))]
    median, p10 = (float(np.median(counts)), float(np.quantile(counts, .1))) if counts else (None, None)
    return MetricObservation(
        candidate_id, window, scenario, tier, cagr, total, drawdown, calmar,
        MetricStatus.VALID if calmar is not None and isfinite(calmar) else MetricStatus.UNAVAILABLE,
        pf, status, len(closed), turnover, cost,
        (("net_cagr", cagr), ("total_return", total), (f"{window}_return", total)),
        count_days, median, p10,
        win_loss_ratio, status,
    )


def _frame_hash(frame: pd.DataFrame) -> str:
    payload = frame.to_json(
        orient="table",
        date_format="iso",
        date_unit="ns",
        double_precision=15,
        index=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _validate_execution_result(
    result: ExecutionResult,
    execution_data: BacktestExecutionData,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    account = result.account_daily
    required = {
        "date", "cash_before", "quantity_before", "cash", "quantity", "close", "equity",
    }
    if not required.issubset(account.columns) or account.empty:
        raise ValueError("TXE account ledger is incomplete")
    dates = pd.DatetimeIndex(pd.to_datetime(account["date"])).normalize()
    expected = pd.DatetimeIndex(
        pd.to_datetime(
            execution_data.execution_daily.loc[
                execution_data.execution_daily["dt"].between(start, end), "dt"
            ]
        )
    ).normalize()
    if dates.has_duplicates or not dates.is_monotonic_increasing or not dates.equals(expected):
        raise ValueError("TXE account ledger does not cover the evaluation sessions exactly")
    numeric = account[["cash_before", "quantity_before", "cash", "quantity", "close", "equity"]].astype(float)
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("TXE account ledger contains non-finite values")
    recomputed = numeric["cash"] + numeric["quantity"] * numeric["close"]
    if not np.allclose(recomputed, numeric["equity"], rtol=0.0, atol=1e-8):
        raise ValueError("TXE account equity does not reconcile to cash and holdings")
    if len(account) > 1:
        if not np.allclose(
            numeric["cash_before"].iloc[1:], numeric["cash"].iloc[:-1],
            rtol=0.0, atol=1e-8,
        ):
            raise ValueError("TXE cash ledger is not continuous")
        if not np.array_equal(
            numeric["quantity_before"].iloc[1:].to_numpy(),
            numeric["quantity"].iloc[:-1].to_numpy(),
        ):
            raise ValueError("TXE holdings ledger is not continuous")
    orders = result.orders
    if not orders.empty:
        if orders["order_id"].duplicated().any():
            raise ValueError("TXE order ledger contains duplicate identities")
        signal_dates = pd.to_datetime(orders["signal_date"]).dt.normalize()
        execution_dates = pd.to_datetime(orders["execution_date"]).dt.normalize()
        if execution_dates.lt(signal_dates).any():
            raise ValueError("TXE order precedes its strategy signal")
    fills = result.fills
    if not fills.empty:
        if fills["fill_id"].duplicated().any():
            raise ValueError("TXE fill ledger contains duplicate identities")
        if (fills["fees"].astype(float) < 0).any():
            raise ValueError("TXE fill ledger contains negative fees")
        if not set(fills["order_id"]).issubset(set(orders["order_id"])):
            raise ValueError("TXE fills reference unknown orders")


def _validate_buyhold(
    benchmark: BuyHoldReplay,
    execution_data: BacktestExecutionData,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    account = benchmark.account_daily
    if account.empty or not {"date", "equity"}.issubset(account.columns):
        raise ValueError("BuyHold account ledger is incomplete")
    dates = pd.DatetimeIndex(pd.to_datetime(account["date"])).normalize()
    expected = pd.DatetimeIndex(
        pd.to_datetime(
            execution_data.execution_daily.loc[
                execution_data.execution_daily["dt"].between(start, end), "dt"
            ]
        )
    ).normalize()
    if not dates.equals(expected):
        raise ValueError("BuyHold ledger does not use the strategy evaluation sessions")
    if not np.isfinite(account["equity"].astype(float).to_numpy()).all():
        raise ValueError("BuyHold ledger contains non-finite equity")
    if benchmark.execution is not None:
        _validate_execution_result(benchmark.execution, execution_data, start, end)


def _evaluate_prepared(
    context,
    workspace,
    replays,
    candidate_ids,
    costs,
    *,
    include_buyhold,
    benchmark=None,
):
    tasks = tuple(
        (key, window, scenario, prepared, fee, measurement_tier)
        for key in candidate_ids
        for scenario, (fee, measurement_tier) in costs.items()
        for window, prepared in replays[key].items()
    )

    def compute(task):
        key, window, scenario, prepared, fee, measurement_tier = task
        signals, execution = execute_candidate_replay(context, workspace, prepared, fee)
        _validate_execution_result(
            execution,
            workspace.execution_data,
            signals.evaluation_start,
            signals.evaluation_end,
        )
        observation = _observation(
            context,
            key,
            window,
            measurement_tier,
            scenario,
            execution,
            workspace.execution_data,
        )
        buyhold = (
            replay_buyhold(
                signals, workspace.execution_data, context.init_cash,
                benchmark=benchmark,
            )
            if include_buyhold
            else None
        )
        if buyhold is not None:
            _validate_buyhold(
                buyhold,
                workspace.execution_data,
                signals.evaluation_start,
                signals.evaluation_end,
            )
        return EvaluationRun(
            key, window, scenario, signals, execution, observation, buyhold
        )

    if context.workers == 1 or len(tasks) < 2:
        return tuple(map(compute, tasks))
    with ThreadPoolExecutor(max_workers=min(context.workers, len(tasks))) as executor:
        return tuple(executor.map(compute, tasks))


def _evaluate_runs(
    context,
    protocol,
    candidates,
    candidate_ids,
    tier,
    scenarios,
    *,
    include_buyhold=False,
):
    if type(context.workers) is not int or context.workers < 1:
        raise ValueError("evaluation workers must be a positive integer")
    if tier not in {"SCREENING", "FORMAL", "STRESS"}:
        raise ValueError(f"unsupported evaluation tier: {tier}")
    if not scenarios or len(set(scenarios)) != len(scenarios):
        raise ValueError("cost scenarios must be non-empty and unique")
    costs = {}
    for scenario in scenarios:
        if scenario != "standard" and tier != "STRESS":
            raise ValueError("non-standard scenarios require STRESS tier")
        fee, slippage = _scenario_settings(scenario, context.fee_rate)
        if slippage or scenario.startswith("slippage_"):
            raise ValueError("TXE evaluation does not support price-slippage scenarios; declare an explicit total-cost scenario")
        costs[scenario] = (fee, tier)
    workspace, replays = prepare_candidate_replays(context, protocol, candidates, candidate_ids)
    runs = _evaluate_prepared(
        context,
        workspace,
        replays,
        candidate_ids,
        costs,
        include_buyhold=include_buyhold,
    )
    return EvaluationResult(runs)


def _request_contract(request: EvaluationRequest) -> tuple[dict[str, object], str]:
    if not isinstance(request, EvaluationRequest):
        raise TypeError("research evaluation requires an EvaluationRequest")
    root = Path(request.repository_root).resolve()
    if not root.is_dir():
        raise ValueError("evaluation repository root is unavailable")
    if not request.experiment_id or Path(request.experiment_id).name != request.experiment_id:
        raise ValueError("evaluation experiment_id must be one path component")
    candidate = request.strategy
    if not isinstance(candidate, StrategyCandidate) or candidate.source_root is None:
        raise ValueError("evaluation requires a sourced StrategyCandidate")
    try:
        candidate.source_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("strategy runtime root must stay inside the repository") from exc
    binding = request.runtime_binding
    required_binding = {"candidate_id", "source_files", "implementation_sha256"}
    if not isinstance(binding, Mapping) or not required_binding.issubset(binding):
        raise ValueError("runtime binding is incomplete")
    if binding["candidate_id"] != candidate.reference_id:
        raise ValueError("runtime binding belongs to another strategy candidate")
    source_files = binding["source_files"]
    if (
        not isinstance(source_files, list | tuple)
        or not source_files
        or any(not isinstance(item, str) or not item for item in source_files)
        or len(source_files) != len(set(source_files))
    ):
        raise ValueError("runtime binding source_files are invalid")
    descriptor = candidate.payload.get("runtime")
    if not isinstance(descriptor, Mapping):
        raise ValueError("strategy payload has no runtime descriptor")
    if tuple(descriptor.get("source_files", ())) != tuple(source_files):
        raise ValueError("strategy payload and runtime binding source files differ")
    actual_source_hash = implementation_sha256(
        tuple(source_files), source_root=candidate.source_root
    )
    if (
        binding["implementation_sha256"] != actual_source_hash
        or descriptor.get("source_sha256") != actual_source_hash
    ):
        raise ValueError("strategy source closure differs from the runtime binding")
    binding_hash = canonical_sha256(binding)
    identity = StrategyRuntime().identify(candidate, dependencies=request.dependencies)

    symbol = request.symbol.upper()
    asset_type = request.asset_type.lower()
    if request.symbol != symbol or asset_type not in {"stock", "etf"}:
        raise ValueError("evaluation symbol or asset_type is not normalized")
    data = request.execution_data
    if not isinstance(data, BacktestExecutionData):
        raise ValueError("evaluation requires prepared BacktestExecutionData")
    if (data.symbol, data.asset_type, data.cutoff) != (
        symbol,
        asset_type,
        request.data_cutoff,
    ):
        raise ValueError("execution data identity differs from the evaluation contract")
    if re.fullmatch(r"[0-9a-f]{64}", data.fingerprint) is None:
        raise ValueError("execution data fingerprint must be lowercase SHA-256")
    adjusted_sessions = pd.DatetimeIndex(
        pd.to_datetime(data.adjusted_daily["dt"])
    ).normalize()
    execution_sessions = pd.DatetimeIndex(
        pd.to_datetime(data.execution_daily["dt"])
    ).normalize()
    if (
        adjusted_sessions.empty
        or adjusted_sessions.has_duplicates
        or not adjusted_sessions.is_monotonic_increasing
        or not adjusted_sessions.equals(execution_sessions)
    ):
        raise ValueError("adjusted and execution market calendars differ")
    requested_sessions = pd.DatetimeIndex(data.evaluation_sessions).normalize()
    if (
        requested_sessions.empty
        or requested_sessions.has_duplicates
        or not requested_sessions.is_monotonic_increasing
        or requested_sessions[-1].date() != request.data_cutoff
        or not requested_sessions.isin(execution_sessions).all()
    ):
        raise ValueError("execution evaluation sessions are incomplete")
    if not np.isfinite(float(request.initial_cash)) or request.initial_cash <= 0:
        raise ValueError("evaluation initial_cash must be positive and finite")
    if request.execution_mode != "FULL":
        raise ValueError("only FULL execution is allowed until equivalence is validated")
    if type(request.workers) is not int or request.workers < 1:
        raise ValueError("evaluation workers must be a positive integer")
    if type(request.frequency_window_days) is not int or request.frequency_window_days < 1:
        raise ValueError("frequency_window_days must be a positive integer")
    if type(request.benchmark) is not EvaluationBenchmark:
        raise TypeError("evaluation requires an explicit EvaluationBenchmark")

    if not request.windows:
        raise ValueError("evaluation windows must not be empty")
    window_ids = [item.window_id for item in request.windows]
    if (
        any(not name or Path(name).name != name or "/" in name or "\\" in name for name in window_ids)
        or len(window_ids) != len(set(window_ids))
    ):
        raise ValueError("evaluation window identities must be nonblank and unique")
    sessions = pd.DatetimeIndex(pd.to_datetime(data.execution_daily["dt"])).normalize()
    for item in request.windows:
        start, end = pd.Timestamp(item.start), pd.Timestamp(item.end)
        if start > end or start not in sessions or end not in sessions:
            raise ValueError(f"evaluation window is not bounded by trading sessions: {item.window_id}")
        if end.date() > request.data_cutoff or not (sessions < start).any():
            raise ValueError(f"evaluation window violates cutoff or warmup: {item.window_id}")

    if not request.costs:
        raise ValueError("evaluation costs must not be empty")
    scenario_ids = [item.scenario_id for item in request.costs]
    if (
        "standard" not in scenario_ids
        or any(
            not name or Path(name).name != name or "/" in name or "\\" in name
            for name in scenario_ids
        )
        or len(scenario_ids) != len(set(scenario_ids))
    ):
        raise ValueError("evaluation costs require one unique standard scenario")
    standard_cost = next(
        item.one_way_cost for item in request.costs if item.scenario_id == "standard"
    )
    for item in request.costs:
        if not item.scenario_id or not isfinite(item.one_way_cost) or not 0 <= item.one_way_cost < 1:
            raise ValueError(f"invalid evaluation cost: {item.scenario_id}")
        if item.measurement_tier not in {"SCREENING", "FORMAL", "STRESS"}:
            raise ValueError(f"invalid measurement tier: {item.scenario_id}")
        if item.scenario_id == "standard" and item.measurement_tier == "STRESS":
            raise ValueError("standard cost cannot use the STRESS measurement tier")
        if item.scenario_id != "standard" and (
            item.measurement_tier != "STRESS" or item.one_way_cost <= standard_cost
        ):
            raise ValueError("pressure costs must exceed standard cost and use STRESS tier")

    return _request_identity_payload(request, identity.content_sha256, binding_hash), binding_hash


def _request_identity_payload(
    request: EvaluationRequest, content_sha256: str, binding_hash: str,
) -> dict[str, object]:
    """Project already authenticated request values without loading mutable source files."""
    return {
        "schema_version": 3,
        "content_sha256": content_sha256,
        "lineage": None if request.lineage is None else request.lineage.derivation.to_dict(),
        "experiment_id": request.experiment_id,
        "strategy_reference": request.strategy.reference_id,
        "strategy_identity": request.strategy.runtime_identity_sha256,
        "runtime_binding_hash": binding_hash,
        "symbol": request.symbol,
        "asset_type": request.asset_type.lower(),
        "windows": [
            {"window_id": x.window_id, "start": x.start.isoformat(), "end": x.end.isoformat()}
            for x in request.windows
        ],
        "data_cutoff": request.data_cutoff.isoformat(),
        "initial_cash": request.initial_cash,
        "costs": [
            {"scenario_id": x.scenario_id, "one_way_cost": x.one_way_cost,
             "measurement_tier": x.measurement_tier}
            for x in request.costs
        ],
        "data_identity": request.execution_data.fingerprint,
        "benchmark": request.benchmark.to_dict(),
        "frequency_window_days": request.frequency_window_days,
        "execution_mode": request.execution_mode,
        "metric_semantics_version": METRIC_SEMANTICS_VERSION,
    }


def _evaluation_result_hash(request_hash: str, runs: tuple[EvaluationRun, ...]) -> str:
    evidence = []
    for run in runs:
        benchmark = run.buyhold
        evidence.append(
            {
                "candidate_id": run.candidate_id,
                "window_id": run.window_id,
                "scenario_id": run.scenario_id,
                "identity": None if run.identity is None else run.identity.to_dict(),
                "signal_data_identity": run.signals.data_identity,
                "signal_support": run.signals.support_data,
                "signal_window": {
                    "calculation_start": run.signals.calculation_start.isoformat(),
                    "evaluation_start": run.signals.evaluation_start.isoformat(),
                    "evaluation_end": run.signals.evaluation_end.isoformat(),
                },
                "signals": _frame_hash(run.signals.decisions),
                "decisions": _frame_hash(run.execution.decisions),
                "orders": _frame_hash(run.execution.orders),
                "fills": _frame_hash(run.execution.fills),
                "account_daily": _frame_hash(run.execution.account_daily),
                "trades": _frame_hash(run.execution.trades),
                "observation": run.observation.to_dict(),
                "buyhold_account_daily": None
                if benchmark is None
                else _frame_hash(benchmark.account_daily),
                "buyhold_orders": None
                if benchmark is None
                else _frame_hash(benchmark.orders),
                "buyhold_metrics": None if benchmark is None else benchmark.metrics,
                "benchmark": None if benchmark is None else benchmark.benchmark.to_dict(),
                "buyhold_execution": None if benchmark is None or benchmark.execution is None else {
                    name: _frame_hash(getattr(benchmark.execution, name))
                    for name in ("decisions", "orders", "fills", "account_daily", "trades")
                },
            }
        )
    return canonical_sha256({"request_hash": request_hash, "runs": evidence})


def evaluate_strategy(
    request: EvaluationRequest, *, dataflows: Dataflows | None = None,
) -> EvaluationResult:
    """Evaluate one strategy without candidate admission, ranking or governance writes."""

    contract, binding_hash = _request_contract(request)
    request_hash = canonical_sha256(contract)
    periods = tuple(
        (
            item.window_id,
            (pd.Timestamp(item.start), pd.Timestamp(item.end)),
        )
        for item in request.windows
    )
    context = CandidateEvaluationContext(
        repository=type(
            "EvaluationRepository",
            (),
            {"root": Path(request.repository_root).resolve()},
        )(),
        symbol=request.symbol,
        asset_type=request.asset_type,
        periods=periods,
        fee_rate=next(
            item.one_way_cost for item in request.costs if item.scenario_id == "standard"
        ),
        init_cash=request.initial_cash,
        workers=request.workers,
        frequency_window_days=request.frequency_window_days,
        family_id=request.strategy.strategy_family_id,
        dataflows=dataflows if dataflows is not None else Dataflows(
            env_file=Path(request.repository_root) / ".env",
        ),
    )
    snapshot = StrategySnapshot(
        StrategyIdentity("CANDIDATE", request.strategy.reference_id, "research_evaluation"),
        request.strategy.runtime_identity_sha256,
        canonical_sha256(request.strategy.payload),
        dict(request.strategy.payload),
        runtime_root=request.strategy.source_root,
    )
    workspace = EvaluationWorkspace(request.execution_data, dict(periods))
    replays = {
        request.strategy.candidate_id: {
            name: build_srt_signal_replay(
                snapshot=snapshot,
                execution_data=request.execution_data,
                start=start,
                end=end,
                repository_root=Path(request.repository_root).resolve(),
                dataflows=context.dataflows,
            )
            for name, (start, end) in periods
        }
    }
    runs = _evaluate_prepared(
        context,
        workspace,
        replays,
        (request.strategy.candidate_id,),
        {
            item.scenario_id: (item.one_way_cost, item.measurement_tier)
            for item in request.costs
        },
        include_buyhold=True,
        benchmark=request.benchmark,
    )
    environment = canonical_sha256({
        "python": platform.python_version(), "platform": platform.platform(),
        "numpy": np.__version__, "pandas": pd.__version__,
        "implementation": implementation_sha256(("models.py", "runtime.py", "identity.py", "loader.py"), source_root=Path(__import__("strategy_runtime").__file__).parent),
        "evaluator": sha256(Path(__file__).read_bytes()).hexdigest(),
        "benchmark_source": {
            name: sha256((Path(__file__).parents[1] / "backtesting" / name).read_bytes()).hexdigest()
            for name in ("benchmark_contracts.py", "benchmarks.py", "_limit_buyhold.py")
        },
        "srt_execution_source": {
            name: sha256((Path(__import__("strategy_runtime").__file__).parent / name).read_bytes()).hexdigest()
            for name in ("execution_planner.py", "execution_rules.py", "contracts.py")
        },
        "packages": {
            name: metadata.version(name) for name in (
                "czsc-dataflows", "czsc-strategy-runtime", "czsc-strategy-evaluator",
                "czsc-trading-execution-engine", "threadpoolctl",
            )
        },
        "txe_source": {
            path.relative_to(Path(__import__("trading_execution_engine").__file__).parent).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(__import__("trading_execution_engine").__file__).parent.rglob("*.py"))
        },
    })
    windows_by_id = {item.window_id: item for item in request.windows}
    costs_by_id = {item.scenario_id: item for item in request.costs}
    identified = []
    for run in runs:
        window = windows_by_id[run.window_id]
        cost = costs_by_id[run.scenario_id]
        protocol_hash = canonical_sha256({
            "window_id": run.window_id, "scenario_id": run.scenario_id,
            "start": window.start.isoformat(), "end": window.end.isoformat(),
            "initial_cash": request.initial_cash, "cost": cost.one_way_cost,
            "tier": cost.measurement_tier, "benchmark": request.benchmark.to_dict(),
            "frequency_window_days": request.frequency_window_days,
            "metric_version": METRIC_SEMANTICS_VERSION, "execution_mode": request.execution_mode,
        })
        identity = EvaluationIdentity(
            CandidateKey(request.strategy.strategy_family_id, request.strategy.candidate_id),
            contract["content_sha256"],
            canonical_sha256({"execution": request.execution_data.fingerprint, "signal": run.signals.data_identity}),
            protocol_hash, environment,
        )
        identified.append(replace(run, identity=identity))
    runs = tuple(identified)
    result_hash = _evaluation_result_hash(request_hash, runs)
    return EvaluationResult(
        runs=runs,
        request_hash=request_hash,
        strategy_identity=request.strategy.runtime_identity_sha256,
        runtime_binding_hash=binding_hash,
        data_identity=request.execution_data.fingerprint,
        result_hash=result_hash,
        execution_mode=request.execution_mode,
    )


def evaluate_candidate_payloads(
    context, protocol, candidates, candidate_ids, tier, scenarios=("standard",)
):
    """Compatibility batch adapter used by TDR candidate evaluation."""

    return _evaluate_runs(
        context, protocol, candidates, candidate_ids, tier, scenarios
    ).observations
