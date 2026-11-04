"""Synthetic historical evidence for explicit inspection/freeze tests only.

This fixture calls SRT/TXE directly. It does not restore retired research APIs,
checkpoints or production publication paths. All callers use pytest tmp_path.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark
from strategy_evaluator import MetricObservation
from typing import Mapping
from types import MappingProxyType
from types import SimpleNamespace
import json
from math import isfinite

import pandas as pd
from strategy_manager import CandidateKey
from strategy_runtime import (StrategyRuntime, StrategyInputBinding, canonical_sha256,
    StrategyCandidate, ImplementationDependency, ExecutionPriceBasis)
from strategy_evaluator import (AccountPoint, AssessmentCandidate, AssessmentEvidence,
    EvaluationScenarioContext, AssessmentFill, ClosedCycle, FillSide,
    LedgerComparisonMode, LedgerComparisonRequest, compare_ledgers)
from czsc_trader.research_tools.evaluation import (
    METRIC_SEMANTICS_VERSION, EvaluationRun, EvaluationWindow, EvaluationCost, EvaluationLineage,
    EvaluationIdentity, _observation, _evaluation_result_hash, _execute_candidate_replay)
from czsc_trader.backtesting.models import StrategyIdentity, StrategySnapshot
from czsc_trader.backtesting.srt_bridge import prepare_srt_input_binding, build_srt_signal_replay
from czsc_trader.backtesting.benchmarks import replay_buyhold
from czsc_trader.backtesting.audit_adapter import build_replay_evidence
from czsc_trader.backtesting.metrics import calculate_metrics


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
    frequency_window_days: int = 60
    execution_mode: str = "FULL"
    lineage: EvaluationLineage | None = None
    dependencies: tuple[ImplementationDependency, ...] = ()
    input_bindings: Mapping[str, StrategyInputBinding] = field(default_factory=dict)
    price_basis: ExecutionPriceBasis = ExecutionPriceBasis.HFQ_RESEARCH

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


def _validate_costs(costs: tuple[EvaluationCost, ...]) -> None:
    if not isinstance(costs, tuple) or not costs or any(
        not isinstance(item, EvaluationCost) for item in costs
    ):
        raise TypeError("evaluation costs require a non-empty tuple of EvaluationCost")
    if len({item.scenario_id for item in costs}) != len(costs):
        raise ValueError("evaluation cost scenario identities must be unique")


def snapshot(request):
    return StrategySnapshot(StrategyIdentity('CANDIDATE', request.strategy.reference_id, 'historical_test'),
        request.strategy.runtime_identity_sha256, canonical_sha256(request.strategy.payload),
        dict(request.strategy.payload), runtime_root=request.strategy.source_root)


def prepare_historical(context, request):
    assert request.execution_data is not None, 'historical fixture requires explicit synthetic inputs'
    return replace(request, input_bindings={window.window_id: prepare_srt_input_binding(
        snapshot=snapshot(request), execution_data=request.execution_data,
        start=pd.Timestamp(window.start), end=pd.Timestamp(window.end),
        repository_root=request.repository_root, dataflows=context.data) for window in request.windows})


def evaluate_historical(context, request):
    content = StrategyRuntime().identify(request.strategy, dependencies=request.dependencies).content_sha256
    binding = canonical_sha256(request.runtime_binding)
    contract = _request_identity_payload(request, content, binding)
    request_hash = canonical_sha256(contract)
    runs = []
    for window in request.windows:
        prepared = build_srt_signal_replay(snapshot=snapshot(request), execution_data=request.execution_data,
            start=pd.Timestamp(window.start), end=pd.Timestamp(window.end), repository_root=request.repository_root,
            dataflows=context.data, input_binding=request.input_bindings[window.window_id])
        for cost in request.costs:
            run_context = SimpleNamespace(init_cash=request.initial_cash, _dataflows=context.data,
                frequency_window_days=request.frequency_window_days)
            signals, execution = _execute_candidate_replay(run_context,
                SimpleNamespace(execution_data=request.execution_data), prepared, cost.one_way_cost)
            observation = _observation(run_context, request.strategy.candidate_id, window.window_id,
                cost.measurement_tier, cost.scenario_id, execution, request.execution_data)
            benchmark = replay_buyhold(signals, request.execution_data, request.initial_cash,
                benchmark=request.benchmark)
            identity = EvaluationIdentity(CandidateKey(request.strategy.strategy_family_id, request.strategy.candidate_id),
                content, canonical_sha256({'fixture_inputs': request.execution_data.fingerprint, 'window': window.window_id}),
                canonical_sha256({'fixture_window': window.window_id, 'cost': cost.one_way_cost}),
                canonical_sha256({'fixture': 'explicit-historical-inspection'}))
            runs.append(EvaluationRun(request.strategy.candidate_id, window.window_id, cost.scenario_id,
                signals, execution, observation, benchmark, identity))
    runs = tuple(runs)
    return EvaluationResult(runs, request_hash, request.strategy.runtime_identity_sha256, binding,
        request.execution_data.fingerprint, _evaluation_result_hash(request_hash, runs),
        request.execution_mode, request.execution_data)


def _assessment_with_replays(request, result):
    assert request.lineage is None, 'historical fixture has no research parameter searches'
    for run in result.runs:
        account = tuple(AccountPoint(pd.Timestamp(row.date).date().isoformat(), float(row.cash),
            int(row.quantity), float(row.close), float(row.equity)) for row in run.execution.account_daily.itertuples())
        fills = tuple(AssessmentFill(str(row.cycle_id), pd.Timestamp(row.fill_time).date().isoformat(),
            FillSide(row.side), int(row.quantity), float(row.price), float(row.fees))
            for row in run.execution.fills.itertuples())
        closed = tuple(ClosedCycle(str(row.cycle_id), pd.Timestamp(row.exit_date).date().isoformat())
            for row in run.execution.trades.itertuples() if row.status == 'CLOSED')
        replay = build_replay_evidence(run.signals, request.execution_data, run.execution,
            request.initial_cash, calculate_metrics(run.execution, request.initial_cash))
        compared = compare_ledgers(LedgerComparisonRequest(replay, replay, LedgerComparisonMode.ECONOMIC, 0.0))
        common = canonical_sha256({'data': request.execution_data.fingerprint, 'symbol': request.symbol,
            'sessions': [x.session for x in account], 'initial_cash': request.initial_cash,
            'benchmark': request.benchmark.fingerprint, 'execution_mode': request.execution_mode,
            'frequency_window_days': request.frequency_window_days, 'metric_version': METRIC_SEMANTICS_VERSION})
        opening = run.execution.account_daily.iloc[0]
        cost = next(x for x in request.costs if x.scenario_id == run.scenario_id)
        yield AssessmentEvidence(AssessmentCandidate(request.strategy.reference_id, run.identity.content_sha256),
            request.experiment_id, result.result_hash[:32], run.identity.evaluation_id, result.request_hash,
            result.result_hash, common, run.window_id, run.scenario_id, METRIC_SEMANTICS_VERSION,
            EvaluationScenarioContext(float(cost.one_way_cost), cost.measurement_tier, request.benchmark.benchmark_id,
                request.benchmark.kind, request.benchmark.fingerprint), float(request.initial_cash),
            float(opening['cash_before']), int(opening['quantity_before']), request.frequency_window_days,
            account, fills, closed, tuple(float(x) for x in run.buyhold.account_daily['equity']),
            None, None, compared.economic_sha256, None), replay


def historical_assessment(request, result):
    return tuple(item for item, _ in _assessment_with_replays(request, result))


def publish_historical(context, request, result):
    from hashlib import sha256
    from czsc_trader.research_tools import EvidenceRef, ExperimentRef
    content = json.dumps(serialize_evaluation_evidence(request, result), ensure_ascii=False,
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    digest = sha256(content).hexdigest()
    reference = EvidenceRef(ExperimentRef(context.strategy_id, request.experiment_id), digest+'.json',
        digest, 'application/json', 'historical-baseline', 'account_evaluation', 8)
    path = context.repository.root / reference.repository_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return reference


def _request_identity_payload(
    request: EvaluationRequest, content_sha256: str, binding_hash: str,
) -> dict[str, object]:
    """Project already authenticated request values without loading mutable source files."""
    return {
        "schema_version": 7,
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
        "market_rules": None if request.execution_data is None else request.execution_data.market_rules.to_dict(),
        "benchmark": request.benchmark.to_dict(),
        "frequency_window_days": request.frequency_window_days,
        "execution_mode": request.execution_mode,
        "metric_semantics_version": METRIC_SEMANTICS_VERSION,
    }


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
                "attempts": frame(run.buyhold.attempts),
                "fills": frame(run.buyhold.fills),
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
            "schema_version": 8,
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
