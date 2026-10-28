"""Typed BAR_RANGE research routed through the batch evaluation capability."""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace, field
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
from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityInputBinding
from trading_execution_engine.equity import EquityHistoricalExecutor
from trading_execution_engine.fills import resolve_fill
from strategy_evaluator.equity import audit_equity_account

from .context import ExperimentRef
from ..backtesting.benchmark_contracts import EvaluationBenchmark, EquityBuyHold

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
    candidate: EquityCandidate | EquityStrategyCandidate
    window: TimeInterval
    history_start: date
    sources: EquitySources
    initial_cash: float
    fee_rate: float
    prepared: PreparedDataRef | None = None
    benchmark: EvaluationBenchmark | None = field(default=None, kw_only=True)
    window_id: str = field(default="FULL", kw_only=True)
    scenario_id: str = field(default="STANDARD", kw_only=True)
    measurement_tier: str = field(default="FORMAL", kw_only=True)
    drawdown_basis: str | None = field(default=None, kw_only=True)
    concentration_basis: str | None = field(default=None, kw_only=True)
    frequency_window_days: int = field(default=60, kw_only=True)
    lineage: object | None = field(default=None, kw_only=True)
    input_binding: EquityInputBinding | None = field(default=None, kw_only=True)
    audit_inputs_sha256: str | None = field(default=None, kw_only=True)

    def __post_init__(self):
        import math
        for value, expected in ((self.experiment, ExperimentRef),
                                (self.window, TimeInterval), (self.sources, EquitySources), (self.history_start, date)):
            if type(value) is not expected:
                raise TypeError(f"equity evaluation requires {expected.__name__}")
        if type(self.candidate) not in (EquityCandidate, EquityStrategyCandidate):
            raise TypeError("equity evaluation requires an explicit equity candidate")
        from .evaluation import EvaluationCost, EvaluationLineage
        EvaluationCost(self.scenario_id, self.fee_rate, self.measurement_tier)
        if type(self.window_id) is not str or not self.window_id.strip():
            raise ValueError("equity window_id must be nonblank")
        if type(self.frequency_window_days) is not int or self.frequency_window_days != 60:
            raise ValueError("equity frequency currently requires 60 trading sessions")
        if self.lineage is not None and type(self.lineage) is not EvaluationLineage:
            raise TypeError("equity lineage requires EvaluationLineage")
        if self.formal:
            if type(self.benchmark) is not EvaluationBenchmark or type(self.benchmark.execution) is not EquityBuyHold:
                raise TypeError("formal equity evaluation requires an explicit EquityBuyHold benchmark")
            if self.benchmark.execution.execution_spec.fingerprint != self.candidate.execution_spec_hash:
                raise ValueError("equity benchmark and candidate execution contracts differ")
            if self.drawdown_basis not in {"SESSION_CLOSE", "BAR_CLOSE"} or self.concentration_basis not in {"TOP_DECILE", "MAX_SINGLE"}:
                raise ValueError("formal equity evaluation requires explicit drawdown and concentration bases")
        elif any(x is not None for x in (self.benchmark, self.lineage, self.input_binding, self.drawdown_basis, self.concentration_basis, self.audit_inputs_sha256)):
            raise ValueError("legacy equity requests cannot claim formal v2 contracts")
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
        if self.input_binding is not None and (type(self.input_binding) is not EquityInputBinding or self.input_binding.prepared != self.prepared):
            raise ValueError("equity input binding differs from prepared data")

    @property
    def formal(self):
        return type(self.candidate) is EquityStrategyCandidate

    def requests(self, specification):
        end = pd.Timestamp(self.window.end).tz_convert(self.candidate.instrument.timezone).date()
        return tuple(EquityDataRequest(self.candidate.instrument, getattr(self.sources, product.name.lower()),
                                      EquityQuery(product, self.history_start, end, specification.decision_clock))
                     for product in EquityProduct)

    def identity(self, specification):
        candidate = self.candidate
        engine_sources = {item.__module__: sha256(Path(inspect.getsourcefile(item)).read_bytes()).hexdigest()
                          for item in (EquityEvaluationRequest, StrategyRuntime, EquityStrategyInstance, EquityHistoricalExecutor, resolve_fill, audit_equity_account)}
        if self.formal:
            engine_sources[EquityStrategyCandidate.__module__] = sha256(Path(inspect.getsourcefile(EquityStrategyCandidate)).read_bytes()).hexdigest()
            from strategy_runtime.equity_buy_hold import decide as hold_decision
            engine_sources[hold_decision.__module__] = sha256(Path(inspect.getsourcefile(hold_decision)).read_bytes()).hexdigest()
        contract = {"schema": "equity-research/v2" if self.formal else "equity-research/v1", "experiment": asdict(self.experiment),
                "candidate_id": candidate.candidate_id, "instrument": asdict(candidate.instrument),
                "implementation_hash": candidate.implementation_hash, "warmup_bars": candidate.warmup_bars,
                "specification": asdict(specification), "specification_hash": specification.fingerprint,
                "window": asdict(self.window), "history_start": self.history_start.isoformat(),
                "sources": asdict(self.sources), "initial_cash": self.initial_cash, "fee_rate": self.fee_rate,
                "engine_sources": engine_sources, "python_version": platform.python_version(),
                "pandas_version": pd.__version__,
                "data_manifest": self.prepared.manifest_sha256 if self.prepared is not None else None}
        if self.formal:
            identity = self.candidate.content_identity
            contract.update(candidate_identity=asdict(identity), content_sha256=identity.content_sha256,
                            candidate_definition=self.candidate.definition.to_dict(),
                            benchmark=self.benchmark.to_dict(), benchmark_sha256=self.benchmark.fingerprint,
                            window_id=self.window_id, scenario_id=self.scenario_id,
                            measurement_tier=self.measurement_tier, drawdown_basis=self.drawdown_basis,
                            concentration_basis=self.concentration_basis, frequency_window_days=self.frequency_window_days,
                            input_binding=None if self.input_binding is None else self.input_binding.to_dict(),
                            audit_inputs_sha256=self.audit_inputs_sha256,
                            lineage=None if self.lineage is None else {
                                "derivation": self.lineage.derivation.to_dict(),
                                "parameter_binding": None if self.lineage.parameter_binding is None else self.lineage.parameter_binding.to_dict()})
        return contract


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
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate equity JSON field: {key}")
                result[key] = value
            return result
        def constant(value):
            raise ValueError(f"nonfinite equity JSON constant: {value}")
        return json.loads(self.content, object_pairs_hook=unique, parse_constant=constant)

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
    if request.formal:
        request.candidate.verify()
    elif request.candidate.implementation_hash != equity_implementation_hash(request.candidate.decide):
        raise ValueError("candidate source changed")
    if request.prepared is not None:
        if request.prepared.space_id != access.data.binding.space_id:
            raise ValueError("prepared data belongs to another research space")
        identities, products = [], {}
        for query in request.requests(specification):
            result = access.data.fetch(query, prepared=request.prepared)
            if not result.ready:
                raise ValueError(f"pinned equity data unavailable: {result.error}")
            identities.append((query.parameters.query.product.name.lower(), result.identity.content_sha256))
            products[query.parameters.query.product.name.lower()] = result.dataframe
        if request.formal:
            binding = EquityInputBinding(request.prepared, request.candidate.instrument, specification.fingerprint,
                                         tuple(identities), request.candidate.warmup_bars)
            if request.input_binding is not None and request.input_binding != binding:
                raise ValueError("equity input identity differs from prepared assets")
            facts_hash = equity_hash({"bars": _records(products["bars"]), "action_facts": _records(products["actions"]),
                                      "constraints": _records(products["constraints"]), "specification": asdict(specification),
                                      "initial_cash": request.initial_cash, "fee_rate": request.fee_rate})
            if request.audit_inputs_sha256 is not None and request.audit_inputs_sha256 != facts_hash:
                raise ValueError("equity audit facts differ from prepared request")
            bound = replace(request, input_binding=binding, audit_inputs_sha256=facts_hash)
            from .parameter_evaluation import validate_parameter_request
            validate_parameter_request(bound, access.data)
            return bound
        return request
    prepared = access.data.prepare(request.requests(specification), policy=PreparePolicy.REUSE)
    if not prepared.ready:
        errors = [str(item.error) for item in prepared.items if not item.ready]
        raise ValueError("equity preparation failed: " + "; ".join(errors))
    return prepare_equity(access, replace(request, prepared=prepared.reference))


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
                                     ("decisions", "orders", "fills", "actions", "account_points", "trades")},
                                     decision_contract="FORMAL_V2" if request.formal else None)
        if _json_value(asdict(audit)) != run["metrics"]:
            raise ValueError("published equity metrics differ from independent audit")
    if request.formal:
        expected_inputs = {"bars": facts["bars"], "action_facts": facts["actions"], "constraints": facts["constraints"],
                           "specification": asdict(access.execution_spec), "initial_cash": request.initial_cash,
                           "fee_rate": request.fee_rate}
        if payload.get("audit_inputs") != _json_value(expected_inputs):
            raise ValueError("formal equity audit input differs from authenticated data")
        from .equity_assessment import build_equity_assessment_payload
        build_equity_assessment_payload(payload)


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
    baseline = EquityCandidate(prepared.candidate.strategy_id, prepared.candidate.candidate_id + ":hold",
                               prepared.candidate.instrument, specification.fingerprint,
                               equity_implementation_hash(_hold), prepared.candidate.warmup_bars, _hold)
    if prepared.formal:
        from strategy_runtime.equity_definition import EquityStrategyDefinition, equity_source_hash
        from strategy_runtime.equity_buy_hold import decide as hold_decision
        source_root = Path(inspect.getsourcefile(hold_decision)).parent
        source_files = ("equity_buy_hold.py",)
        definition = EquityStrategyDefinition(prepared.candidate.instrument, specification,
            prepared.candidate.warmup_bars, "equity_buy_hold:decide", source_files,
            equity_source_hash(source_root, source_files))
        baseline = EquityStrategyCandidate(prepared.candidate.strategy_id, prepared.candidate.candidate_id,
                                           definition, source_root)
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
                                     constraints=_records(products["constraints"]), fee_rate=prepared.fee_rate, **evidence,
                                     decision_contract="FORMAL_V2" if prepared.formal else None)
        runs[name] = {**evidence, "account_daily": _records(account.account_daily), "metrics": asdict(audit)}
    contract = prepared.identity(specification)
    # Normalize timestamps before hashing so JSON readback has the same identity.
    def encode(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        raise TypeError(f"unserializable equity evidence: {type(value)}")
    contract = json.loads(json.dumps(contract, default=encode))
    request_hash = equity_hash(contract)
    payload = {"schema": contract["schema"], "request_hash": request_hash, "request": contract,
               "data": identities, "runs": runs,
               "limitations": ["BAR_RANGE model; no exact intrabar fill time", "bar observations are not independent samples",
                               "research evidence; not frozen release or PTE admission"]}
    if prepared.formal:
        from .evaluation import EvaluationIdentity
        from strategy_runtime import canonical_sha256
        identity = EvaluationIdentity(prepared.candidate.key, prepared.candidate.content_identity.content_sha256,
                                      prepared.prepared.manifest_sha256, request_hash,
                                      canonical_sha256(contract["engine_sources"]))
        payload.update(schema_version=2, evaluation_identity=identity.to_dict(), evaluation_id=identity.evaluation_id,
                       audit_inputs={"bars": _records(bars), "action_facts": _records(products["actions"]),
                                     "constraints": _records(products["constraints"]), "specification": asdict(specification),
                                     "initial_cash": prepared.initial_cash, "fee_rate": prepared.fee_rate})
        prepared.candidate.verify()
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False, default=encode).encode()
    return EquityEvaluationResult(request_hash, content)
