"""Shared evaluation metadata and explicit historical audit/review adapters.

Ordinary account computation and publication use the V4 session chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from hashlib import sha256
from math import isfinite
from pathlib import Path, PureWindowsPath
import re
from typing import Any

import numpy as np
import pandas as pd
from dataflows import Dataflows
from strategy_evaluator import EvaluationProtocol, MetricObservation, MetricStatus
from strategy_runtime import (
    StrategyCandidate, StrategyRuntime, canonical_sha256, ExecutionPriceBasis, ExecutionPricing,
)
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind
from .parameter_evaluation import ParameterEvaluationBinding
from trading_execution_engine import ExecutionResult, MarketExecutionRules

from ..backtesting.execution_data import (
    BacktestExecutionData,
    _prepare_backtest_execution_data,
)
from ..backtesting.benchmarks import BuyHoldReplay
from ..backtesting.benchmark_contracts import EvaluationBenchmark
from ..backtesting.models import StrategyIdentity, StrategySnapshot
from ..backtesting.signal_replay import SignalReplay
from ..backtesting.srt_bridge import (
    build_srt_signal_replay, execution_intraday_frequencies, load_srt_strategy,
    replay_srt_account,
)

METRIC_SEMANTICS_VERSION = "candidate-srt-txe-v5-market-limits"


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
    dates = pd.DatetimeIndex(pd.to_datetime(pd.DataFrame(execution_data.adjusted_daily, copy=False)["dt"])).normalize()
    execution_dates = pd.DatetimeIndex(
        pd.to_datetime(pd.DataFrame(execution_data.execution_daily, copy=False)["dt"])
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
        prices = pd.DataFrame(execution_data.execution_daily, copy=False)
        prior = prices.loc[prices["dt"] < opening["date"]]
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
                "buyhold_attempts": None if benchmark is None else _frame_hash(benchmark.attempts),
                "buyhold_fills": None if benchmark is None else _frame_hash(benchmark.fills),
                "benchmark": None if benchmark is None else benchmark.benchmark.to_dict(),
                "buyhold_execution": None if benchmark is None or benchmark.execution is None else {
                    name: _frame_hash(getattr(benchmark.execution, name))
                    for name in ("decisions", "orders", "fills", "account_daily", "trades")
                },
            }
        )
    return canonical_sha256({"request_hash": request_hash, "runs": evidence})















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

    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value.get("schema_version") not in (7, 8) or value.get("source_kind") != "published_result":
        raise ValueError("account evaluation evidence requires supported published_result schema")
    request = value["request_identity"]
    if type(request.get("schema_version")) is not int or (value["schema_version"], request.get("schema_version")) not in ((7, 6), (8, 7)):
        raise ValueError("evaluation request and evidence schema versions differ")
    rules = MarketExecutionRules.from_dict(request.get("market_rules"))
    from ..backtesting.execution_data import MarketSecurity

    if rules.suspension_information is not MarketSecurity.select(request["symbol"], request["asset_type"]).suspension_information:
        raise ValueError("evaluation suspension policy differs from market/security type")
    if rules.symbol != request["symbol"]:
        raise ValueError("evaluation market rules differ from request symbol")
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
    if point is not None:
        from strategy_evaluator import ParameterPointBinding, ParameterNeighborhoodBinding
        expected = ParameterPointBinding if value["schema_version"] == 7 else ParameterNeighborhoodBinding
        if type(point) is not expected:
            raise ValueError("parameter binding differs from evidence schema version")
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
        "account_daily": ("date", "signal_date", "valuation_source_date"),
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
        if replay.execution_spec.get("market_rules") != rules.to_dict():
            raise ValueError("evaluation replay market rules differ from request")
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
            attempts=_evidence_frame(benchmark["attempts"]), fills=_evidence_frame(benchmark["fills"]),
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
