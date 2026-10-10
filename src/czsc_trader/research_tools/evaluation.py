"""Shared research-evaluation Harness driven by SRT, TXE and SE contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from hashlib import sha256
from math import isfinite
from pathlib import Path, PureWindowsPath
import platform
from importlib import metadata
import re
import json
from typing import Any, Mapping
from types import MappingProxyType

import numpy as np
import pandas as pd
from dataflows import Dataflows
from strategy_evaluator import EvaluationProtocol, MetricObservation, MetricStatus
from strategy_runtime import (
    StrategyCandidate, StrategyRuntime, StrategyInputBinding,
    canonical_sha256, ImplementationDependency,
    ExecutionPriceBasis, ExecutionPricing,
)
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind
from .parameter_evaluation import ParameterEvaluationBinding
from strategy_runtime.implementation_identity import implementation_sha256
from trading_execution_engine import ExecutionResult

from ..backtesting.execution_data import (
    BacktestExecutionData,
    _prepare_backtest_execution_data,
    _require_execution_frequencies,
)
from ..backtesting.benchmarks import BuyHoldReplay, replay_buyhold
from ..backtesting.benchmark_contracts import EvaluationBenchmark, LimitBuyHold
from ..backtesting.models import StrategyIdentity, StrategySnapshot
from ..backtesting.signal_replay import SignalReplay
from ..backtesting.srt_bridge import (
    build_srt_signal_replay, execution_intraday_frequencies, load_srt_strategy,
    replay_srt_account, prepare_srt_input_binding,
)

METRIC_SEMANTICS_VERSION = "candidate-srt-txe-v4-explicit-benchmark"


@dataclass(frozen=True)
class _CandidateEvaluationContext:
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
    _dataflows: Dataflows = field(kw_only=True, repr=False, compare=False)


@dataclass(frozen=True)
class _EvaluationWorkspace:
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
        if (not isinstance(self.scenario_id, str) or not self.scenario_id.strip()
                or self.scenario_id in {".", ".."}
                or any(char in self.scenario_id for char in '/\\:<>"|?*')
                or any(ord(char) < 32 for char in self.scenario_id)
                or self.scenario_id.endswith((".", " "))
                or PureWindowsPath(self.scenario_id).is_reserved()):
            raise ValueError("evaluation scenario_id must be a nonblank safe path component")
        if isinstance(self.one_way_cost, bool) or not isfinite(self.one_way_cost) or not 0 <= self.one_way_cost < 1:
            raise ValueError("evaluation cost must be finite and in [0, 1)")
        if self.measurement_tier not in {"SCREENING", "FORMAL", "STRESS"}:
            raise ValueError("invalid evaluation measurement tier")


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
    execution_data: BacktestExecutionData | None = None
    benchmark: EvaluationBenchmark = field(kw_only=True)
    workers: int = 1
    frequency_window_days: int = 60
    execution_mode: str = "FULL"
    lineage: EvaluationLineage | None = None
    dependencies: tuple[ImplementationDependency, ...] = ()
    input_bindings: Mapping[str, StrategyInputBinding] = field(default_factory=dict)
    price_basis: ExecutionPriceBasis = ExecutionPriceBasis.UNADJUSTED

    def __post_init__(self):
        if not isinstance(self.price_basis, ExecutionPriceBasis):
            raise TypeError("price_basis requires ExecutionPriceBasis")
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
        if not isinstance(self.input_bindings, Mapping) or any(
            not isinstance(name, str) or not isinstance(binding, StrategyInputBinding)
            for name, binding in self.input_bindings.items()
        ):
            raise TypeError("input_bindings must map window IDs to StrategyInputBinding")
        if self.input_bindings and set(self.input_bindings) != {item.window_id for item in self.windows}:
            raise ValueError("input_bindings must cover every evaluation window")
        object.__setattr__(self, "input_bindings", MappingProxyType(dict(self.input_bindings)))
        _validate_costs(self.costs)


@dataclass(frozen=True, slots=True)
class EvaluationLineage:
    derivation: CandidateDerivation
    parameter_binding: ParameterEvaluationBinding | None = None

    def __post_init__(self):
        if not isinstance(self.derivation, CandidateDerivation):
            raise TypeError("lineage requires CandidateDerivation")
        if self.parameter_binding is not None and type(self.parameter_binding) is not ParameterEvaluationBinding:
            raise TypeError("lineage requires ParameterEvaluationBinding")
        if self.parameter_binding is not None and self.derivation.kind is not CandidateDerivationKind.PARAMETERS:
            raise ValueError("parameter point binding requires PARAMETERS derivation")


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
    execution_data: BacktestExecutionData | None = field(default=None, repr=False, compare=False)

    @property
    def observations(self) -> tuple[MetricObservation, ...]:
        return tuple(item.observation for item in self.runs)


def _prepare_evaluation_workspace(
    context: _CandidateEvaluationContext, protocol: EvaluationProtocol, *,
    intraday_frequencies: tuple[str, ...] = (),
) -> _EvaluationWorkspace:
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
        if "5m" in intraday_frequencies and execution_data.execution_five_minute is None:
            raise ValueError("review dataset has no required five-minute execution prices")
        if "30m" in intraday_frequencies and execution_data.execution_intraday.empty:
            raise ValueError("review dataset has no required thirty-minute execution prices")
    else:
        if context.review_data_hash is not None:
            raise ValueError("review dataset hash requires a snapshot directory")
        first_start = min(start for _, (start, _) in context.periods)
        execution_data = _prepare_backtest_execution_data(
            repository_root=Path(context.repository.root),
            symbol=context.symbol,
            asset_type=context.asset_type,
            start=first_start.date(),
            end=pd.Timestamp(protocol.development_cutoff).date(),
            intraday_frequencies=intraday_frequencies,
            dataflows=context._dataflows,
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
    common_start = max(dates[0], execution_dates[0])
    if not dates[dates >= common_start].equals(execution_dates[execution_dates >= common_start]):
        raise ValueError("research and execution session calendars differ")
    periods = dict(context.periods)
    if not periods or len(periods) != len(context.periods):
        raise ValueError("evaluation windows must be non-empty and unique")
    for name, (start, end) in periods.items():
        if start != start.normalize() or end != end.normalize() or start > end:
            raise ValueError(f"invalid evaluation window: {name}")
        if start not in dates or end not in dates or start not in execution_dates or end not in execution_dates:
            raise ValueError(f"evaluation window {name} is not bounded by trading sessions")
        if end > cutoff:
            raise ValueError(f"evaluation window {name} exceeds development cutoff")
        if not (dates < start).any() or not (execution_dates < start).any():
            raise ValueError(f"evaluation window {name} has no prior signal session")
    return _EvaluationWorkspace(execution_data, periods)


def _snapshot(context: _CandidateEvaluationContext, item: dict[str, object]):
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


def _prepare_candidate_replays(context, protocol, payloads, candidate_ids):
    """Load complete SRT identities, publications and window decisions once per call."""
    by_id = {str(item["candidate_id"]): item for item in payloads}
    if len(by_id) != len(payloads) or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("duplicate candidate identities")
    if missing := set(candidate_ids) - set(by_id):
        raise ValueError(f"candidate payloads missing: {sorted(missing)}")
    loaded = {key: _snapshot(context, by_id[key]) for key in candidate_ids}
    workspace = _prepare_evaluation_workspace(
        context, protocol,
        intraday_frequencies=tuple(sorted({frequency for _, strategy in loaded.values()
                                          for frequency in execution_intraday_frequencies(strategy)})),
    )
    flows = context._dataflows
    replays = {}
    for key, (snapshot, _) in loaded.items():
        replays[key] = {
            name: build_srt_signal_replay(
                snapshot=snapshot,
                execution_data=workspace.execution_data,
                start=start,
                end=end,
                repository_root=context.repository.root,
                dataflows=flows,
            )
            for name, (start, end) in workspace.periods.items()
        }
    return workspace, replays


def _execute_candidate_replay(context, workspace, prepared, fee_rate):
    """Return the ledger and its effective-cost evidence without editing SRT."""
    strategy, signals = prepared
    result = replay_srt_account(
        strategy=strategy,
        signals=signals,
        execution_data=workspace.execution_data,
        initial_cash=context.init_cash, fee_rate_override=fee_rate,
        dataflows=context._dataflows,
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
        signals, execution = _execute_candidate_replay(context, workspace, prepared, fee)
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


def _evaluate_runs(context, protocol, candidates, candidate_ids, costs):
    if type(context.workers) is not int or context.workers < 1:
        raise ValueError("evaluation workers must be a positive integer")
    _validate_costs(costs)
    workspace, replays = _prepare_candidate_replays(context, protocol, candidates, candidate_ids)
    runs = _evaluate_prepared(
        context, workspace, replays, candidate_ids,
        {item.scenario_id: (item.one_way_cost, item.measurement_tier) for item in costs},
        include_buyhold=False,
    )
    return EvaluationResult(runs)


def _validate_costs(costs: tuple[EvaluationCost, ...]) -> None:
    if not isinstance(costs, tuple) or not costs or any(
        not isinstance(item, EvaluationCost) for item in costs
    ):
        raise TypeError("evaluation costs require a non-empty tuple of EvaluationCost")
    if len({item.scenario_id for item in costs}) != len(costs):
        raise ValueError("evaluation cost scenario identities must be unique")


def _request_contract(request: EvaluationRequest, *, require_execution: bool = True) -> tuple[dict[str, object], str]:
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
    if data is None and require_execution:
        raise ValueError("evaluation requires prepared BacktestExecutionData")
    if data is not None:
        if not isinstance(data, BacktestExecutionData):
            raise ValueError("evaluation requires prepared BacktestExecutionData")
        if data.pricing.basis is not request.price_basis:
            raise ValueError("execution data price and quantity units differ from request")
        if data.pricing.anchor_date is not None and any(data.pricing.anchor_date >= w.start for w in request.windows):
            raise ValueError("HFQ anchor must precede every evaluation window")
        required_frequencies = set(execution_intraday_frequencies(StrategyRuntime().describe(candidate)))
        if isinstance(request.benchmark.execution, LimitBuyHold):
            required_frequencies.add("30m")
        _require_execution_frequencies(data, tuple(sorted(required_frequencies)))
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
            or execution_sessions.empty
            or execution_sessions.has_duplicates
            or not execution_sessions.is_monotonic_increasing
        ):
            raise ValueError("adjusted and execution market calendars differ")
        common_start = max(adjusted_sessions[0], execution_sessions[0])
        if not adjusted_sessions[adjusted_sessions >= common_start].equals(
            execution_sessions[execution_sessions >= common_start]
        ):
            raise ValueError("adjusted and execution market calendars differ")
        requested_sessions = pd.DatetimeIndex(data.evaluation_sessions).normalize()
        if (
            requested_sessions.empty
            or requested_sessions.has_duplicates
            or not requested_sessions.is_monotonic_increasing
            or requested_sessions[-1].date() != request.data_cutoff
            or not requested_sessions.isin(execution_sessions).all()
            or not requested_sessions.isin(adjusted_sessions).all()
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
    if any(item.end > request.data_cutoff for item in request.windows):
        raise ValueError("evaluation window violates cutoff")
    if data is not None:
        sessions = pd.DatetimeIndex(pd.to_datetime(data.execution_daily["dt"])).normalize()
        for item in request.windows:
            start, end = pd.Timestamp(item.start), pd.Timestamp(item.end)
            if start > end or start not in sessions or end not in sessions:
                raise ValueError(f"evaluation window is not bounded by trading sessions: {item.window_id}")
            if end.date() > request.data_cutoff or not (sessions < start).any():
                raise ValueError(f"evaluation window violates cutoff or warmup: {item.window_id}")

    _validate_costs(request.costs)

    return _request_identity_payload(request, identity.content_sha256, binding_hash), binding_hash


def _request_identity_payload(
    request: EvaluationRequest, content_sha256: str, binding_hash: str,
) -> dict[str, object]:
    """Project already authenticated request values without loading mutable source files."""
    return {
        "schema_version": 5,
        "content_sha256": content_sha256,
        "lineage": None if request.lineage is None else request.lineage.derivation.to_dict(),
        "parameter_binding": None if request.lineage is None or request.lineage.parameter_binding is None
        else request.lineage.parameter_binding.to_dict(),
        "input_bindings": {name: item.to_dict() for name, item in request.input_bindings.items()},
        "nonparameter_context_sha256": canonical_sha256({
            "payload": {key: value for key, value in request.strategy.payload.items() if key != "parameters"},
            "runtime_binding": {key: value for key, value in request.runtime_binding.items() if key != "candidate_id"},
            "dependencies": [{"name": item.name, "version": item.version} for item in sorted(request.dependencies)],
            "symbol": request.symbol, "asset_type": request.asset_type.lower(),
            "windows": [{"id": x.window_id, "start": x.start.isoformat(), "end": x.end.isoformat()}
                        for x in request.windows],
            "cutoff": request.data_cutoff.isoformat(), "cash": request.initial_cash,
            "costs": [{"id": x.scenario_id, "cost": x.one_way_cost, "tier": x.measurement_tier}
                      for x in request.costs],
            "data": None if request.execution_data is None else request.execution_data.fingerprint,
            "price_basis": request.price_basis.value, "benchmark": request.benchmark.to_dict(),
            "frequency_window_days": request.frequency_window_days, "mode": request.execution_mode,
            "metric_version": METRIC_SEMANTICS_VERSION,
        }),
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
        "data_identity": None if request.execution_data is None else request.execution_data.fingerprint,
        "price_basis": request.price_basis.value,
        "pricing": None if request.execution_data is None else request.execution_data.pricing.to_dict(),
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
                "signal_support": {name: value for name, value in run.signals.support_data.items()
                                   if name != "input_binding"},
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


def _prepare_evaluation_inputs(request: EvaluationRequest, *, dataflows: Dataflows) -> EvaluationRequest:
    """Resolve all window inputs in the owning process before worker dispatch."""
    return _bind_evaluation_inputs(request, dataflows=dataflows)


def _bind_evaluation_inputs(request: EvaluationRequest, *, dataflows) -> EvaluationRequest:
    _request_contract(request, require_execution=False)
    if request.input_bindings:
        if request.execution_data is None:
            raise ValueError("bound evaluation requires its original execution data")
        return request
    if not isinstance(dataflows, Dataflows):
        raise TypeError("evaluation requires host-supplied Dataflows")
    if request.execution_data is None:
        definition = StrategyRuntime().describe(request.strategy)
        frequencies = set(execution_intraday_frequencies(definition))
        if isinstance(request.benchmark.execution, LimitBuyHold):
            frequencies.add("30m")
        request = replace(request, execution_data=_prepare_backtest_execution_data(
            repository_root=Path(request.repository_root), symbol=request.symbol,
            asset_type=request.asset_type, start=min(item.start for item in request.windows),
            end=request.data_cutoff, intraday_frequencies=tuple(sorted(frequencies)),
            dataflows=dataflows,
            price_basis=request.price_basis,
        ))
    _request_contract(request)
    snapshot = StrategySnapshot(
        StrategyIdentity("CANDIDATE", request.strategy.reference_id, "research_evaluation"),
        request.strategy.runtime_identity_sha256,
        canonical_sha256(request.strategy.payload), dict(request.strategy.payload),
        runtime_root=request.strategy.source_root,
    )
    bindings = {
        window.window_id: prepare_srt_input_binding(
            snapshot=snapshot, execution_data=request.execution_data,
            start=pd.Timestamp(window.start), end=pd.Timestamp(window.end),
            repository_root=Path(request.repository_root).resolve(), dataflows=dataflows,
        )
        for window in request.windows
    }
    return replace(request, input_bindings=bindings)


def _evaluate_strategy(request: EvaluationRequest, *, dataflows: Dataflows) -> EvaluationResult:
    """Evaluate one strategy without candidate admission, ranking or governance writes."""

    request = _prepare_evaluation_inputs(request, dataflows=dataflows)
    contract, binding_hash = _request_contract(request)
    request_hash = canonical_sha256(contract)
    periods = tuple(
        (
            item.window_id,
            (pd.Timestamp(item.start), pd.Timestamp(item.end)),
        )
        for item in request.windows
    )
    context = _CandidateEvaluationContext(
        repository=type(
            "EvaluationRepository",
            (),
            {"root": Path(request.repository_root).resolve()},
        )(),
        symbol=request.symbol,
        asset_type=request.asset_type,
        periods=periods,
        fee_rate=request.costs[0].one_way_cost,
        init_cash=request.initial_cash,
        workers=request.workers,
        frequency_window_days=request.frequency_window_days,
        family_id=request.strategy.strategy_family_id,
        _dataflows=dataflows,
    )
    snapshot = StrategySnapshot(
        StrategyIdentity("CANDIDATE", request.strategy.reference_id, "research_evaluation"),
        request.strategy.runtime_identity_sha256,
        canonical_sha256(request.strategy.payload),
        dict(request.strategy.payload),
        runtime_root=request.strategy.source_root,
    )
    workspace = _EvaluationWorkspace(request.execution_data, dict(periods))
    replays = {
        request.strategy.candidate_id: {
            name: build_srt_signal_replay(
                snapshot=snapshot,
                execution_data=request.execution_data,
                start=start,
                end=end,
                repository_root=Path(request.repository_root).resolve(),
                dataflows=context._dataflows,
                input_binding=request.input_bindings[name],
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
            "pricing": request.execution_data.pricing.to_dict(),
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
        execution_data=request.execution_data,
    )


def _evaluate_candidate_payloads(context, protocol, candidates, candidate_ids, costs):
    """Produce candidate observations for internal review and audit workflows."""
    return _evaluate_runs(context, protocol, candidates, candidate_ids, costs).observations


def _signal_table(value):
    table = json.loads(
        value.to_json(orient="table", date_format="iso", date_unit="ns", index=False)
    )
    # pandas JSON limits doubles to 15 digits. Keep Python float values so the
    # enclosing JSON writer preserves the full binary64 round-trip precision.
    for encoded, original in zip(table["data"], value.to_dict(orient="records")):
        for name, cell in original.items():
            if isinstance(cell, float) and isfinite(cell):
                encoded[name] = cell
    return table



def serialize_evaluation_evidence(request: EvaluationRequest, result: EvaluationResult) -> dict:
    """Project authenticated account facts only when their retention is requested."""
    from .assessment import _assessment_with_replays

    if type(request) is not EvaluationRequest or type(result) is not EvaluationResult:
        raise TypeError("evidence requires EvaluationRequest and EvaluationResult")
    if request.execution_data is None:
        request = replace(request, execution_data=result.execution_data)
    if not request.input_bindings:
        bindings = {
            run.window_id: StrategyInputBinding.from_mapping(run.signals.support_data["input_binding"])
            for run in result.runs
        }
        request = replace(request, input_bindings=bindings)
    evaluated = _assessment_with_replays(
        request, result,
    )

    def frame(value):
        table = _signal_table(value)
        table["dtypes"] = {name: str(dtype) for name, dtype in value.dtypes.items()}
        return table

    runs = []
    assessment = []
    for run, (evidence, replay) in zip(result.runs, evaluated, strict=True):
        assessment.append(evidence)
        item = {
            "identity": run.identity.to_dict(),
            "replay_evidence": replay.to_dict(),
            "window_id": run.window_id,
            "scenario_id": run.scenario_id,
            "candidate_id": run.candidate_id,
            "signals": _signal_table(run.signals.decisions),
            "signal_dtypes": {
                name: str(dtype) for name, dtype in run.signals.decisions.dtypes.items()
            },
            "signal_data_identity": run.signals.data_identity,
            "signal_support": run.signals.support_data,
            "signal_window": {
                "calculation_start": run.signals.calculation_start.isoformat(),
                "evaluation_start": run.signals.evaluation_start.isoformat(),
                "evaluation_end": run.signals.evaluation_end.isoformat(),
            },
            "observation": run.observation.to_dict(),
            "ledgers": {
                name: frame(getattr(run.execution, name))
                for name in ("decisions", "orders", "fills", "account_daily", "trades")
            },
            "buyhold": None
            if run.buyhold is None
            else {
                "account_daily": frame(run.buyhold.account_daily),
                "orders": frame(run.buyhold.orders),
                "metrics": run.buyhold.metrics,
                "benchmark": run.buyhold.benchmark.to_dict(),
                "execution": None if run.buyhold.execution is None else {
                    name: frame(getattr(run.buyhold.execution, name))
                    for name in ("decisions", "orders", "fills", "account_daily", "trades")
                },
            },
        }
        runs.append(item)
    return {
            "schema_version": 6,
            "source_kind": "published_result",
            "request_identity": _request_identity_payload(
                request, result.runs[0].identity.content_sha256, result.runtime_binding_hash
            ),
            "request_hash": result.request_hash,
            "strategy_identity": result.strategy_identity,
            "runtime_binding_hash": result.runtime_binding_hash,
            "data_identity": result.data_identity,
            "execution_mode": result.execution_mode,
            "input_bindings": {name: binding.to_dict() for name, binding in request.input_bindings.items()},
            "result_hash": result.result_hash,
            "runs": runs,
            "assessment_evidence": [item.to_dict() for item in assessment],
    }


def _evidence_frame(value: dict, *, dtypes: dict | None = None) -> pd.DataFrame:
    columns = [field["name"] for field in value["schema"]["fields"]]
    types = value["dtypes"] if dtypes is None else dtypes
    return pd.DataFrame({
        name: pd.Series([row[name] for row in value["data"]], dtype=types[name])
        for name in columns
    })


def validate_evaluation_evidence(value: dict) -> None:
    """Authenticate a published result and its numeric projections without rerunning it."""
    from types import SimpleNamespace
    from strategy_evaluator import AssessmentEvidence, ReplayEvidence, audit_replay, AuditStatus
    from ..backtesting.audit_adapter import _records

    if not isinstance(value, dict) or value.get("schema_version") != 6 or value.get("source_kind") != "published_result":
        raise ValueError("account evaluation evidence requires schema 6 published_result")
    request = value["request_identity"]
    if request.get("schema_version") != 5:
        raise ValueError("evaluation request requires schema 5 parameter identities")
    pricing = ExecutionPricing.from_dict(request["pricing"])
    if pricing.basis.value != request["price_basis"]:
        raise ValueError("evaluation pricing differs from requested units")
    if pricing.anchor_date is not None and pricing.anchor_date >= min(
        date.fromisoformat(w["start"]) for w in request["windows"]
    ):
        raise ValueError("evaluation HFQ anchor must precede every window")
    if canonical_sha256(request) != value["request_hash"]:
        raise ValueError("evaluation request identity differs")
    if any(value[name] != request[name] for name in ("strategy_identity", "runtime_binding_hash", "data_identity", "execution_mode")):
        raise ValueError("evaluation metadata differs from request")
    projected = tuple(AssessmentEvidence.from_dict(item) for item in value["assessment_evidence"])
    if request["input_bindings"] != value["input_bindings"]:
        raise ValueError("saved input bindings differ from authenticated request")
    parameter_binding = request["parameter_binding"]
    point = None if parameter_binding is None else ParameterEvaluationBinding.from_dict(parameter_binding).point
    if any(item.parameter_point != point for item in projected):
        raise ValueError("assessment parameter point differs from authenticated request")
    if not projected or len(projected) != len(value["runs"]):
        raise ValueError("evaluation assessment coordinates differ")
    runs = []
    coordinates = []
    def record(payload):
        return SimpleNamespace(to_dict=lambda: payload)
    date_columns = {
        "decisions": ("signal_date", "valid_session"),
        "orders": ("signal_date", "execution_date"),
        "fills": ("signal_date", "fill_time"),
        "account_daily": ("date", "signal_date"),
        "trades": ("entry_date", "exit_date"),
    }
    for item, assessment in zip(value["runs"], projected, strict=True):
        if item["signal_support"]["input_binding"] != request["input_bindings"][item["window_id"]]:
            raise ValueError("run input binding differs from authenticated request")
        identity = item["identity"]
        if (assessment.request_sha256 != value["request_hash"]
            or assessment.result_sha256 != value["result_hash"]
            or assessment.attempt_id != value["result_hash"][:32]
            or assessment.candidate.candidate_id != request["strategy_reference"]
            or assessment.candidate.content_sha256 != request["content_sha256"]
            or assessment.experiment_id != request["experiment_id"]
            or assessment.evaluation_id != canonical_sha256(identity)
            or (assessment.window_id, assessment.scenario_id) != (item["window_id"], item["scenario_id"])):
            raise ValueError("evaluation assessment identity differs")
        if identity["content_sha256"] != request["content_sha256"] or (
            identity["candidate"]["strategy_id"] + "-" + identity["candidate"]["candidate_id"]
        ) != request["strategy_reference"]:
            raise ValueError("evaluation candidate identity differs")
        ledgers = {name: _evidence_frame(table) for name, table in item["ledgers"].items()}
        replay = ReplayEvidence.from_dict(item["replay_evidence"])
        if replay.execution_spec.get("pricing") != request["pricing"]:
            raise ValueError("evaluation replay pricing differs from request")
        if pricing.basis is ExecutionPriceBasis.UNADJUSTED and any(
            row.get("price_scale") != 1 for row in replay.execution_daily
        ):
            raise ValueError("unadjusted replay requires unit price scales")
        if audit_replay(replay).status is not AuditStatus.PASS:
            raise ValueError("evaluation account audit failed")
        for name, columns in date_columns.items():
            # JSON numbers use the same binary64 values after table decoding.
            expected = _records(ledgers[name], columns)
            actual = getattr(replay, name)
            if canonical_sha256(expected) != canonical_sha256(actual):
                raise ValueError(f"evaluation replay {name} differs from account ledgers")
        account = tuple((pd.Timestamp(row.date).date().isoformat(), float(row.cash),
                         int(row.quantity), float(row.close), float(row.equity))
                        for row in ledgers["account_daily"].itertuples())
        if account != tuple((x.session, x.cash, x.quantity, x.close, x.equity) for x in assessment.account):
            raise ValueError("evaluation assessment account differs")
        fills = tuple((str(row.cycle_id), pd.Timestamp(row.fill_time).date().isoformat(),
                       str(row.side), int(row.quantity), float(row.price), float(row.fees))
                      for row in ledgers["fills"].itertuples())
        if fills != tuple((x.cycle_id, x.session, x.side.value, x.quantity, x.price, x.fees) for x in assessment.fills):
            raise ValueError("evaluation assessment fills differ")
        closed = tuple((str(row.cycle_id), pd.Timestamp(row.exit_date).date().isoformat())
                       for row in ledgers["trades"].itertuples() if row.status == "CLOSED")
        if closed != tuple((x.cycle_id, x.exit_session) for x in assessment.closed_cycles):
            raise ValueError("evaluation assessment closed cycles differ")
        benchmark_contract = EvaluationBenchmark.from_dict(request["benchmark"])
        common_context = canonical_sha256({
            "data": request["data_identity"], "symbol": request["symbol"],
            "sessions": [x[0] for x in account], "initial_cash": request["initial_cash"],
            "benchmark": benchmark_contract.fingerprint, "execution_mode": request["execution_mode"],
            "frequency_window_days": request["frequency_window_days"], "metric_version": METRIC_SEMANTICS_VERSION,
        })
        opening = ledgers["account_daily"].iloc[0]
        cost = next(x for x in request["costs"] if x["scenario_id"] == item["scenario_id"])
        if (assessment.context_sha256 != common_context
            or assessment.initial_cash != request["initial_cash"]
            or assessment.opening_cash != float(opening["cash_before"])
            or assessment.opening_quantity != int(opening["quantity_before"])
            or assessment.frequency_window_days != request["frequency_window_days"]
            or assessment.metric_version != METRIC_SEMANTICS_VERSION
            or assessment.scenario_context.one_way_cost != cost["one_way_cost"]
            or assessment.scenario_context.measurement_tier != cost["measurement_tier"]
            or assessment.scenario_context.benchmark_contract_sha256 != benchmark_contract.fingerprint):
            raise ValueError("evaluation assessment protocol differs")
        execution = SimpleNamespace(**ledgers, equity=pd.Series(
            ledgers["account_daily"]["equity"].to_numpy(),
            index=pd.DatetimeIndex(ledgers["account_daily"]["date"]),
        ))
        prices = pd.DataFrame(replay.execution_daily).rename(columns={"date": "dt"})
        prices["dt"] = pd.to_datetime(prices["dt"])
        observation = _observation(SimpleNamespace(init_cash=request["initial_cash"],
            frequency_window_days=request["frequency_window_days"]), item["candidate_id"],
            item["window_id"], cost["measurement_tier"], item["scenario_id"], execution,
            SimpleNamespace(execution_daily=prices))
        if canonical_sha256(observation.to_dict()) != canonical_sha256(item["observation"]):
            raise ValueError("evaluation metrics differ from account ledgers")
        signals = SimpleNamespace(
            decisions=_evidence_frame(item["signals"], dtypes=item["signal_dtypes"]),
            data_identity=item["signal_data_identity"], support_data=item["signal_support"],
            **{key: pd.Timestamp(date) for key, date in item["signal_window"].items()},
        )
        benchmark = item["buyhold"]
        buyhold = None if benchmark is None else SimpleNamespace(
            account_daily=_evidence_frame(benchmark["account_daily"]),
            orders=_evidence_frame(benchmark["orders"]), metrics=benchmark["metrics"],
            benchmark=record(benchmark["benchmark"]),
            execution=None if benchmark["execution"] is None else SimpleNamespace(
                **{name: _evidence_frame(table) for name, table in benchmark["execution"].items()}),
        )
        if buyhold is None or benchmark_contract.to_dict() != benchmark["benchmark"] or (
            assessment.benchmark_equity != tuple(float(x) for x in buyhold.account_daily["equity"])
        ):
            raise ValueError("evaluation assessment benchmark differs")
        runs.append(SimpleNamespace(candidate_id=item["candidate_id"],window_id=item["window_id"],
            scenario_id=item["scenario_id"], identity=record(identity), signals=signals,
            execution=SimpleNamespace(**ledgers), observation=record(item["observation"]), buyhold=buyhold))
        coordinates.append((item["window_id"], item["scenario_id"]))
    expected = {(w["window_id"], c["scenario_id"]) for w in request["windows"] for c in request["costs"]}
    if len(coordinates) != len(expected) or set(coordinates) != expected:
        raise ValueError("evaluation coordinates differ")
    if _evaluation_result_hash(value["request_hash"], tuple(runs)) != value["result_hash"]:
        raise ValueError("evaluation result hash differs")
