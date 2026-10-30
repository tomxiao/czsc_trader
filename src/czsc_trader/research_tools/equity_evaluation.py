"""Equity request/result contracts, shared inputs and historical evidence validation.

New account computation lives exclusively in equity_replay_v3.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import date
import json
import inspect
from pathlib import Path
from hashlib import sha256
import platform

import pandas as pd
from dataflows import (EquityDataRequest, EquityProduct, EquityQuery, PreparedDataRef, SourceRef, TimeInterval)
from strategy_runtime.equity import (EquityCandidate, EquityStrategyInstance,
                                    equity_hash)
from strategy_runtime.runtime import StrategyRuntime
from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityInputBinding
from dataflows.equity_data import sessions_from_metadata
from trading_execution_engine.equity import EquityHistoricalExecutor
from trading_execution_engine.fills import resolve_fill
from strategy_evaluator.equity import audit_equity_account

from .context import ExperimentRef
from ..backtesting.benchmark_contracts import EvaluationBenchmark, EquityBuyHold


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
        return tuple(query for _, query in self.request_items(specification))

    def request_items(self, specification):
        """Stable product keys; auxiliary products never replace the traded asset."""
        end = pd.Timestamp(self.window.end).tz_convert(self.candidate.instrument.timezone).date()
        primary = tuple((product.name.lower(), EquityDataRequest(
            self.candidate.instrument, getattr(self.sources, product.name.lower()),
            EquityQuery(product, self.history_start, end, specification.decision_clock))) for product in EquityProduct)
        auxiliary = (() if not self.formal else tuple(
            (item.data_key(query.parameters.query.product), query)
            for item in self.candidate.definition.auxiliary_inputs
            for query in item.requests(self.history_start, end)))
        return primary + auxiliary

    def identity(self, specification):
        candidate = self.candidate
        engine_sources = {item.__module__: sha256(Path(inspect.getsourcefile(item)).read_bytes()).hexdigest()
                          for item in (EquityEvaluationRequest, StrategyRuntime, EquityStrategyInstance, EquityHistoricalExecutor, resolve_fill, audit_equity_account)}
        if self.formal:
            engine_sources[EquityStrategyCandidate.__module__] = sha256(Path(inspect.getsourcefile(EquityStrategyCandidate)).read_bytes()).hexdigest()
            from strategy_runtime.equity_buy_hold import decide as hold_decision
            engine_sources[hold_decision.__module__] = sha256(Path(inspect.getsourcefile(hold_decision)).read_bytes()).hexdigest()
            if candidate.definition.auxiliary_inputs or candidate.definition.session_context:
                from strategy_runtime.equity_context import build_equity_decision_context
                engine_sources[build_equity_decision_context.__module__] = sha256(
                    Path(inspect.getsourcefile(build_equity_decision_context)).read_bytes()).hexdigest()
            if candidate.definition.contract_version == 3:
                from strategy_runtime import (equity_features, equity_replay, equity_buy_hold_v3,
                                              equity_context, equity_source_runtime, replay_kernel, replay_contracts, replay_adapters)
                from strategy_evaluator import equity_assessment as se_equity_assessment
                from . import equity_replay_v3, equity_assessment, parameter_evaluation, account_preparation
                from trading_execution_engine import accounting, replay as execution_replay
                for module in (equity_features, equity_replay, equity_buy_hold_v3, equity_replay_v3,
                               equity_context, equity_source_runtime, equity_assessment, se_equity_assessment,
                               parameter_evaluation, account_preparation, replay_kernel, replay_contracts, replay_adapters, accounting, execution_replay):
                    engine_sources[module.__name__] = sha256(Path(module.__file__).read_bytes()).hexdigest()
        version = 3 if self.formal and candidate.definition.contract_version == 3 else 2 if self.formal else 1
        contract = {"schema": f"equity-research/v{version}", "experiment": asdict(self.experiment),
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
class EquityArtifact:
    """An immutable, content addressed member of a v3 evidence closure."""
    kind: str
    content: bytes

    def __post_init__(self):
        if self.kind not in {"equity_input", "equity_account"}:
            raise ValueError("unknown equity artifact kind")
        if type(self.content) is not bytes or not self.content:
            raise TypeError("equity artifact requires immutable bytes")

    @property
    def sha256(self):
        return sha256(self.content).hexdigest()

    def reference(self):
        return {"kind": self.kind, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class EquityEvaluationResult:
    """Canonical immutable evidence bytes; views returned by payload are detached."""
    request_hash: str
    content: bytes
    artifacts: tuple[EquityArtifact, ...] = ()

    def __post_init__(self):
        if type(self.content) is not bytes or not self.content:
            raise TypeError("equity result requires nonempty immutable bytes")
        payload = self.payload
        if payload["request_hash"] != self.request_hash or equity_hash(payload["request"]) != self.request_hash:
            raise ValueError("equity result request identity differs")
        if type(self.artifacts) is not tuple or any(type(item) is not EquityArtifact for item in self.artifacts):
            raise TypeError("equity result artifacts require an immutable typed tuple")
        if len({item.sha256 for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate equity artifact")
        if payload.get("schema") == "equity-research/v3":
            from .equity_replay_v3 import validate_result_structure
            validate_result_structure(payload, self.artifacts)
        elif self.artifacts:
            raise ValueError("only v3 results carry detached artifacts")

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


def _fetch_products(access, request):
    products, identities, calendars = {}, {}, {}
    for name, query in request.request_items(access.execution_spec):
        result = access.data.fetch(query, prepared=request.prepared)
        if not result.ready:
            raise ValueError(f"pinned equity product unavailable ({name}): {result.error}")
        products[name] = result.dataframe
        identities[name] = {"content_sha256": result.identity.content_sha256,
                            "metadata": dict(result.identity.metadata)}
        # Each observation instrument owns its calendar. A daily auxiliary may
        # have a different set of sessions from the traded instrument.
        group = name.rsplit(":", 1)[0] if name.startswith("auxiliary:") else "primary"
        declared = result.identity.metadata["sessions"]
        if group in calendars and calendars[group] != declared:
            raise ValueError(f"independent equity products disagree on the trading calendar: {group}")
        calendars[group] = declared
    return products, identities


def _audit_inputs(request, specification, products):
    inputs = {"bars": _records(products["bars"]), "action_facts": _records(products["actions"]),
              "constraints": _records(products["constraints"]), "specification": asdict(specification),
              "initial_cash": request.initial_cash, "fee_rate": request.fee_rate}
    if request.formal:
        definition = request.candidate.definition
        decision_inputs = {}
        if definition.session_context:
            decision_inputs["sessions"] = _records(products["sessions"])
        if definition.auxiliary_inputs:
            decision_inputs["auxiliary"] = {item.name: {
                "bars": _records(products[item.data_key(EquityProduct.BARS)]),
                "sessions": _records(products[item.data_key(EquityProduct.SESSIONS)])}
                for item in definition.auxiliary_inputs}
        if decision_inputs:
            inputs["decision_inputs"] = decision_inputs
    return inputs


def _runtime_inputs(definition, products, identities):
    kwargs = {}
    if definition.auxiliary_inputs:
        kwargs["auxiliary_histories"] = {item.name: products[item.data_key(EquityProduct.BARS)]
                                         for item in definition.auxiliary_inputs}
    if definition.session_context:
        kwargs["sessions"] = products["sessions"]
        kwargs["trading_sessions"] = sessions_from_metadata(identities["sessions"]["metadata"])
    return kwargs


def _records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso", date_unit="us"))


def _data_quality(bars, run):
    """Report execution limitations from source facts and audited account entries."""
    ends = {row["time"] for row in run["account_points"]}
    selected = [row for row in bars if row["Date"] in ends]
    def summary(rows):
        affected = [row for row in rows if row.get("BarStatus", "OBSERVED") != "OBSERVED"
                    or row.get("ExecutionBlocked", False)]
        return {
            "missing_bars": sum(row.get("BarStatus") == "MISSING" for row in rows),
            "zero_volume_bars": sum(row.get("BarStatus") == "ZERO_VOLUME" for row in rows),
            "known_blocked_bars": sum(bool(row.get("ExecutionBlocked", False)) for row in rows),
            "affected_sessions": sorted({pd.Timestamp(row["BarStart"]).tz_convert("America/New_York").date().isoformat()
                                         for row in affected}),
            "intervals": [{"start": row["BarStart"], "end": row["Date"],
                           "bar_status": row.get("BarStatus", "OBSERVED"),
                           "execution_blocked": row.get("ExecutionBlocked", False)} for row in affected],
        }
    return {
        "basis": "MISSING_OR_ZERO_VOLUME_UNTRADABLE_RESEARCH_ASSUMPTION" if any("BarStatus" in row for row in bars)
                 else "STRICT_COMPLETE_BARS",
        "prepared_history": summary(bars), "evaluation_window": summary(selected),
        "stale_valuations": sum(row.get("valuation_stale", False) for row in run["account_points"]),
        "suppressed_signals": sum(row.get("signal_status") == "SUPPRESSED_UNOBSERVED_BAR" for row in run["decisions"]),
        "affected_orders": [{"order_id": row["order_id"], "reason": row["reason"],
                             "start": row["valid_start"], "end": row["valid_end"]}
                            for row in run["orders"] if row["reason"] in {"MISSING_BAR", "ZERO_VOLUME", "KNOWN_INTERRUPTION"}],
    }


def _json_value(value):
    def encode(item):
        if hasattr(item, "isoformat"):
            return item.isoformat()
        raise TypeError(f"unserializable equity evidence: {type(item)}")
    return json.loads(json.dumps(value, default=encode, allow_nan=False))


def validate_equity_result(access, request, result, *, execution=None):
    from .equity_replay_v3 import PreparedAccountEvaluation, validate_certified_result
    if type(request) is PreparedAccountEvaluation:
        return validate_certified_result(access, request, result, execution=execution)
    if type(result) is not EquityEvaluationResult or request.prepared is None:
        raise TypeError("equity publication requires a prepared request and immutable result")
    expected = _json_value(request.identity(access.execution_spec))
    payload = result.payload
    if expected != payload["request"] or equity_hash(expected) != result.request_hash:
        raise ValueError("published equity request differs from evaluated request")
    products, identities = _fetch_products(access, request)
    if _json_value(identities) != payload["data"]:
        raise ValueError("published equity data identity differs")
    facts = {name: _records(frame) for name, frame in products.items()}
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
        if run.get("data_quality") != _data_quality(facts["bars"], run):
            raise ValueError("published equity data quality differs from source and execution facts")
    if request.formal:
        expected_inputs = _audit_inputs(request, access.execution_spec, products)
        if payload.get("audit_inputs") != _json_value(expected_inputs):
            raise ValueError("formal equity audit input differs from authenticated data")
        from .equity_assessment import build_equity_assessment_payload
        build_equity_assessment_payload(payload)
