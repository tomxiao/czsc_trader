"""Typed BAR_RANGE research routed through the batch evaluation capability."""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from datetime import date
import json
from typing import TYPE_CHECKING
import inspect
from pathlib import Path
from hashlib import sha256
import platform

import pandas as pd
from dataflows import (EquityDataRequest, EquityProduct, EquityQuery, MarketId,
                       PreparePolicy, PreparedDataRef, SourceRef, TimeInterval)
from strategy_runtime.equity import (EquityCandidate, EquityStrategyInstance,
                                    ResearchExecutionSpec, equity_hash, equity_implementation_hash)
from strategy_runtime.runtime import StrategyRuntime
from trading_execution_engine.equity import EquityHistoricalExecutor
from trading_execution_engine.fills import resolve_fill
from strategy_evaluator.equity import audit_equity_account

from .context import ExperimentRef

if TYPE_CHECKING:
    from .evaluation_access import EvaluationStatus, EvaluationError


@dataclass(frozen=True, slots=True)
class EquitySources:
    bars: SourceRef
    sessions: SourceRef
    actions: SourceRef
    constraints: SourceRef

    def __post_init__(self):
        if any(type(value) is not SourceRef for value in (self.bars, self.sessions, self.actions, self.constraints)):
            raise TypeError("each equity product requires an explicit versioned source")


@dataclass(frozen=True, slots=True)
class EquityEvaluationRequest:
    experiment: ExperimentRef
    candidate: EquityCandidate
    window: TimeInterval
    history_start: date
    sources: EquitySources
    initial_cash: float
    fee_rate: float
    prepared: PreparedDataRef | None = None

    def __post_init__(self):
        import math
        for value, expected in ((self.experiment, ExperimentRef), (self.candidate, EquityCandidate),
                                (self.window, TimeInterval), (self.sources, EquitySources), (self.history_start, date)):
            if type(value) is not expected:
                raise TypeError(f"equity evaluation requires {expected.__name__}")
        if self.experiment.strategy_id != self.candidate.strategy_id:
            raise ValueError("candidate belongs to another experiment batch")
        if self.history_start > self.window.start.date():
            raise ValueError("history must precede the evaluation window")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (self.initial_cash, self.fee_rate)):
            raise ValueError("account values must be finite")
        if self.initial_cash <= 0 or not 0 <= self.fee_rate < 1:
            raise ValueError("invalid cash or fee rate")
        if self.prepared is not None and type(self.prepared) is not PreparedDataRef:
            raise TypeError("prepared requires PreparedDataRef")

    def requests(self, specification):
        end = pd.Timestamp(self.window.end).tz_convert(self.candidate.instrument.timezone).date()
        return tuple(EquityDataRequest(self.candidate.instrument, getattr(self.sources, product.name.lower()),
                                      EquityQuery(product, self.history_start, end, specification.decision_clock))
                     for product in EquityProduct)

    def identity(self, specification):
        candidate = self.candidate
        engine_sources = {item.__module__: sha256(Path(inspect.getsourcefile(item)).read_bytes()).hexdigest()
                          for item in (EquityEvaluationRequest, StrategyRuntime, EquityStrategyInstance, EquityHistoricalExecutor, resolve_fill, audit_equity_account)}
        return {"schema": "equity-research/v1", "experiment": asdict(self.experiment),
                "candidate_id": candidate.candidate_id, "instrument": asdict(candidate.instrument),
                "implementation_hash": candidate.implementation_hash, "warmup_bars": candidate.warmup_bars,
                "specification": asdict(specification), "specification_hash": specification.fingerprint,
                "window": asdict(self.window), "history_start": self.history_start.isoformat(),
                "sources": asdict(self.sources), "initial_cash": self.initial_cash, "fee_rate": self.fee_rate,
                "engine_sources": engine_sources, "python_version": platform.python_version(),
                "pandas_version": pd.__version__,
                "data_manifest": self.prepared.manifest_sha256 if self.prepared is not None else None}


@dataclass(frozen=True, slots=True)
class EquityEvaluationResult:
    """Canonical immutable evidence bytes; views returned by payload are detached."""
    request_hash: str
    content: bytes

    def __post_init__(self):
        if type(self.content) is not bytes or not self.content:
            raise TypeError("equity result requires nonempty immutable bytes")
        payload = self.payload
        if payload["request_hash"] != self.request_hash or equity_hash(payload["request"]) != self.request_hash:
            raise ValueError("equity result request identity differs")

    @property
    def payload(self):
        return json.loads(self.content)

    @property
    def result_hash(self):
        from hashlib import sha256
        return sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class EquityEvaluationOutcome:
    status: EvaluationStatus
    result: EquityEvaluationResult | None = None
    error: EvaluationError | None = None

    def __post_init__(self):
        from .evaluation_access import EvaluationStatus, EvaluationError
        if type(self.status) is not EvaluationStatus or self.status not in {EvaluationStatus.SUCCEEDED, EvaluationStatus.FAILED}:
            raise ValueError("unknown equity evaluation status")
        if (self.status == "SUCCEEDED") != (type(self.result) is EquityEvaluationResult and self.error is None):
            raise ValueError("equity outcome status differs from result")
        if self.status == "FAILED" and (self.result is not None or type(self.error) is not EvaluationError):
            raise ValueError("failed equity outcome requires an error")


def prepare_equity(access, request):
    specification = access.execution_spec
    if type(specification) is not ResearchExecutionSpec:
        raise ValueError("equity evaluation requires an explicit context execution specification")
    if specification.market_id is not MarketId.US:
        raise ValueError("UNSUPPORTED_EXECUTION_COMBINATION: BAR_RANGE currently admits US only")
    specification.require_instrument(request.candidate.instrument)
    if request.candidate.execution_spec_hash != specification.fingerprint:
        raise ValueError("MARKET_CONTRACT_MISMATCH: candidate and context")
    if request.experiment.strategy_id != access.strategy_id:
        raise ValueError("equity request belongs to another research batch")
    if request.candidate.implementation_hash != equity_implementation_hash(request.candidate.decide):
        raise ValueError("candidate source changed")
    if request.prepared is not None:
        if request.prepared.space_id != access.data.binding.space_id:
            raise ValueError("prepared data belongs to another research space")
        for query in request.requests(specification):
            result = access.data.fetch(query, prepared=request.prepared)
            if not result.ready:
                raise ValueError(f"pinned equity data unavailable: {result.error}")
        return request
    prepared = access.data.prepare(request.requests(specification), policy=PreparePolicy.REUSE)
    if not prepared.ready:
        errors = [str(item.error) for item in prepared.items if not item.ready]
        raise ValueError("equity preparation failed: " + "; ".join(errors))
    return replace(request, prepared=prepared.reference)


def _hold(history, portfolio):
    return 1


def _records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso", date_unit="us"))


def _json_value(value):
    def encode(item):
        if hasattr(item, "isoformat"):
            return item.isoformat()
        raise TypeError(f"unserializable equity evidence: {type(item)}")
    return json.loads(json.dumps(value, default=encode, allow_nan=False))


def validate_equity_result(access, request, result):
    if type(result) is not EquityEvaluationResult or request.prepared is None:
        raise TypeError("equity publication requires a prepared request and immutable result")
    expected = _json_value(request.identity(access.execution_spec))
    payload = result.payload
    if expected != payload["request"] or equity_hash(expected) != result.request_hash:
        raise ValueError("published equity request differs from evaluated request")
    facts = {}
    for query in request.requests(access.execution_spec):
        fetched = access.data.fetch(query, prepared=request.prepared)
        name = query.parameters.query.product.name.lower()
        if not fetched.ready or fetched.identity.content_sha256 != payload["data"][name]["content_sha256"]:
            raise ValueError("published equity data identity differs")
        facts[name] = _records(fetched.dataframe)
    if set(payload["runs"]) != {"candidate", "buy_hold"}:
        raise ValueError("equity evidence requires candidate and benchmark")
    for run in payload["runs"].values():
        expected_times = [row["Date"] for row in facts["bars"]
                          if pd.Timestamp(row["BarStart"]) >= request.window.start and pd.Timestamp(row["Date"]) <= request.window.end]
        if [row["time"] for row in run["account_points"]] != expected_times:
            raise ValueError("published account does not cover its evaluation window")
        daily = {}
        for row in run["account_points"]:
            daily[row["session"]] = row
        if list(daily.values()) != run["account_daily"]:
            raise ValueError("published daily account differs from bar observations")
        audit = audit_equity_account(initial_cash=request.initial_cash, specification=asdict(access.execution_spec),
                                     bars=facts["bars"], action_facts=facts["actions"], constraints=facts["constraints"],
                                     fee_rate=request.fee_rate, **{key: run[key] for key in
                                     ("decisions", "orders", "fills", "actions", "account_points", "trades")})
        if _json_value(asdict(audit)) != run["metrics"]:
            raise ValueError("published equity metrics differ from independent audit")


def evaluate_equity(access, prepared):
    specification = access.execution_spec
    products = {}
    identities = {}
    calendar = None
    for query in prepared.requests(specification):
        result = access.data.fetch(query, prepared=prepared.prepared)
        if not result.ready:
            raise ValueError(f"pinned equity product unavailable: {result.error}")
        name = query.parameters.query.product.name.lower()
        products[name] = result.dataframe
        identities[name] = {"content_sha256": result.identity.content_sha256,
                            "metadata": dict(result.identity.metadata)}
        declared = result.identity.metadata["sessions"]
        if calendar is not None and calendar != declared:
            raise ValueError("independent equity products disagree on the trading calendar")
        calendar = declared
    bars = products["bars"]
    eligible = bars.loc[(bars.BarStart >= prepared.window.start) & (bars.Date <= prepared.window.end)]
    if eligible.empty or eligible.BarStart.iloc[0] != prepared.window.start or eligible.Date.iloc[-1] != prepared.window.end:
        raise ValueError("evaluation window must align with observed session bars")
    # An independent account always starts flat. Both candidate and hold benchmark
    # use the same history, start, costs, events and execution specification.
    baseline = replace(prepared.candidate, candidate_id=prepared.candidate.candidate_id + ":hold",
                       decide=_hold, implementation_hash=equity_implementation_hash(_hold))
    runs = {}
    for name, candidate in (("candidate", prepared.candidate), ("buy_hold", baseline)):
        executor = EquityHistoricalExecutor(specification=specification, initial_cash=prepared.initial_cash,
                                            fee_rate=prepared.fee_rate, actions=products["actions"])
        account = StrategyRuntime(execution_spec=specification).create(candidate).run_window(
            bars, products["constraints"], executor, start=prepared.window.start,
            end=prepared.window.end, fee_rate=prepared.fee_rate)
        evidence = {"decisions": _records(account.decisions), "orders": _records(account.orders),
                    "fills": _records(account.fills), "actions": _records(account.corporate_action_entries),
                    "account_points": _records(account.account_points), "trades": _records(account.trades)}
        audit = audit_equity_account(initial_cash=prepared.initial_cash, specification=asdict(specification),
                                     bars=_records(bars), action_facts=_records(products["actions"]),
                                     constraints=_records(products["constraints"]), fee_rate=prepared.fee_rate, **evidence)
        runs[name] = {**evidence, "account_daily": _records(account.account_daily), "metrics": asdict(audit)}
    contract = prepared.identity(specification)
    # Normalize timestamps before hashing so JSON readback has the same identity.
    def encode(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        raise TypeError(f"unserializable equity evidence: {type(value)}")
    contract = json.loads(json.dumps(contract, default=encode))
    request_hash = equity_hash(contract)
    payload = {"schema": "equity-research/v1", "request_hash": request_hash, "request": contract,
               "data": identities, "runs": runs,
               "limitations": ["BAR_RANGE model; no exact intrabar fill time", "bar observations are not independent samples",
                               "research evidence; not frozen release or PTE admission"]}
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False, default=encode).encode()
    return EquityEvaluationResult(request_hash, content)
