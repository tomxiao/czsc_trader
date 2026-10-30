"""Session-owned US equity preparation, event replay and immutable evidence.

Only the owning session can reuse certification. Persisted artifacts contain
facts, not authority: a reader authenticates the closure and audits it afresh.
"""
from __future__ import annotations

from contextlib import closing
from concurrent.futures import CancelledError
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import inspect
import json
from pathlib import Path

from dataflows import EquityProduct, MarketId, PreparePolicy, TimeInterval
from strategy_runtime.equity import ResearchExecutionSpec, equity_hash
from strategy_runtime.equity_definition import EquityAuxiliaryBinding, EquityInputBinding, EquityStrategyCandidate
from strategy_evaluator.equity_assessment import EquityCertificationScope, certify_equity_ledger

from .equity_evaluation import (EquityArtifact, EquityEvaluationRequest, EquityEvaluationResult,
    _audit_inputs, _data_quality, _fetch_products, _json_value, _records, _runtime_inputs)
from .execution import ExecutionPhase, ResearchExecutionSession
from .account_preparation import PreparedAccountEvaluation, BenchmarkRunIdentity


def _bytes(value):
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _read(content):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate v3 evidence field")
            result[key] = value
        return result
    return json.loads(content, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite v3 evidence")))


@dataclass(frozen=True, slots=True)
class EquityInputSnapshot:
    artifact: EquityArtifact

    def __post_init__(self):
        if type(self.artifact) is not EquityArtifact or self.artifact.kind != "equity_input":
            raise TypeError("input snapshot requires an immutable input artifact")

    @property
    def sha256(self):
        return self.artifact.sha256


class _SessionState:
    def __init__(self):
        from uuid import uuid4
        self.token = uuid4().hex
        self.snapshots = {}
        self.products = {}
        self.replays = {}
        self.prepared = {}
        self.benchmarks = {}
        self.results = {}
        self.replay_statistics = {}
        self.candidate_runs = 0
        self.benchmark_runs = 0
        self.certification = EquityCertificationScope()


def _state(access, execution, experiment_id=None):
    if type(execution) is not ResearchExecutionSession:
        raise TypeError("v3 equity operations require their explicit ResearchExecutionSession")
    execution.require(access, experiment_id)
    state = getattr(execution, "_equity_v3", None)
    if state is None:
        state = _SessionState()
        execution._equity_v3 = state
    return state


def _benchmark_candidate(request):
    from strategy_runtime.equity_definition import EquityStrategyDefinition, equity_source_hash
    from strategy_runtime.equity_features import FeatureGraph
    from strategy_runtime.equity_replay import StrategyStateSchema
    from strategy_runtime.equity_buy_hold_v3 import step
    root = Path(inspect.getsourcefile(step)).parent
    files = ("equity_buy_hold_v3.py",)
    definition = EquityStrategyDefinition(request.candidate.instrument,
        request.candidate.definition.execution_spec, request.candidate.warmup_bars,
        "equity_buy_hold_v3:step", files, equity_source_hash(root, files),
        contract_version=3, feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema())
    # Internal implementation adapter only; the external account owner is BENCHMARK.
    return EquityStrategyCandidate("S000", "C0000", definition, root)


def _query_identity(request, specification):
    ref = request.prepared
    return equity_hash(_json_value({"requests": [asdict(query) for query in request.requests(specification)],
        "prepared": None if ref is None else {"space_id": str(ref.space_id),
            "preparation_id": str(ref.preparation_id), "manifest_sha256": ref.manifest_sha256}}))


def _primary_input_sha256(snapshot):
    value = _read(snapshot.artifact.content)
    return sha256(_bytes({"schema": value["schema"],
        "products": {key: value["products"][key] for key in ("bars", "sessions", "actions", "constraints")},
        "data": {key: value["data"][key] for key in ("bars", "sessions", "actions", "constraints")}})).hexdigest()


def prepare_equity_v3(access, request, *, execution):
    """Fetch/authenticate each exact input selection once in the owning session."""
    if type(request) is not EquityEvaluationRequest or not request.formal or request.candidate.definition.contract_version != 3:
        raise TypeError("v3 preparation requires an explicit v3 strategy request")
    state = _state(access, execution, request.experiment.experiment_id)
    spec = access.execution_spec
    if type(spec) is not ResearchExecutionSpec or spec.market_id is not MarketId.US:
        raise ValueError("v3 replay requires the US equity execution contract")
    spec.require_instrument(request.candidate.instrument)
    if request.candidate.execution_spec_hash != spec.fingerprint or request.experiment.strategy_id != access.strategy_id:
        raise ValueError("v3 request differs from its research context")
    request.candidate.verify()
    definition = request.candidate.definition
    if request.prepared is not None and request.prepared.space_id != access.data.binding.space_id:
        raise ValueError("prepared data belongs to another research space")
    query_identity = _query_identity(request, spec)
    with execution.executor.measure(ExecutionPhase.PREPARE):
        cached = state.snapshots.get(query_identity)
        if cached is None:
            if request.prepared is None:
                data = access.data.prepare(request.requests(spec), policy=PreparePolicy.REUSE)
                if not data.ready:
                    raise ValueError("equity preparation failed: " + "; ".join(str(x.error) for x in data.items if not x.ready))
                request = replace(request, prepared=data.reference)
            products, identities = _fetch_products(access, request)
            artifact = EquityArtifact("equity_input", _bytes({"schema": "equity-input/v1",
                "products": {key: _records(frame) for key, frame in products.items()}, "data": identities}))
            snapshot = EquityInputSnapshot(artifact)
            state.products[snapshot.sha256] = products
            cached = (request.prepared, snapshot, identities)
            state.snapshots[query_identity] = cached
            state.snapshots[_query_identity(request, spec)] = cached
        prepared_ref, snapshot, identities = cached
        request = replace(request, prepared=prepared_ref)
        binding = EquityInputBinding(prepared_ref, request.candidate.instrument, spec.fingerprint,
            tuple((product.name.lower(), identities[product.name.lower()]["content_sha256"]) for product in EquityProduct),
            request.candidate.warmup_bars, auxiliary_inputs=tuple(EquityAuxiliaryBinding(item,
                identities[item.data_key(EquityProduct.BARS)]["content_sha256"],
                identities[item.data_key(EquityProduct.SESSIONS)]["content_sha256"])
                for item in definition.auxiliary_inputs))
        if request.input_binding is not None and request.input_binding != binding:
            raise ValueError("equity input identity differs from prepared assets")
        facts_hash = equity_hash(_audit_inputs(request, spec, state.products[snapshot.sha256]))
        if request.audit_inputs_sha256 is not None and request.audit_inputs_sha256 != facts_hash:
            raise ValueError("equity audit input fingerprint differs")
        request = replace(request, input_binding=binding, audit_inputs_sha256=facts_hash)
        baseline = _benchmark_candidate(request)
        contract = request.identity(spec)
        benchmark = BenchmarkRunIdentity(_bytes({"kind": "BUY_HOLD", "input_snapshot_sha256": _primary_input_sha256(snapshot),
            "instrument": asdict(request.candidate.instrument), "definition": baseline.definition.to_dict(),
            "window": asdict(request.window), "history_start": request.history_start.isoformat(),
            "initial_cash": request.initial_cash, "fee_rate": request.fee_rate,
            "engine_sources": contract["engine_sources"], "python_version": contract["python_version"],
            "pandas_version": contract["pandas_version"]}))
        value = PreparedAccountEvaluation(request, snapshot, benchmark, state.token, _bytes(contract))
        state.prepared[id(value)] = value
        from .parameter_evaluation import validate_parameter_request
        try:
            validate_parameter_request(value, access.data, execution=execution)
        except BaseException:
            state.prepared.pop(id(value), None)
            raise
        return value


def _require_prepared(state, value):
    if (type(value) is not PreparedAccountEvaluation or value.scope_token != state.token
            or state.prepared.get(id(value)) is not value):
        raise ValueError("prepared equity handle was not issued by this execution session")
    if _bytes(value.request.identity(value.candidate.definition.execution_spec)) != value.contract_content:
        raise ValueError("equity engine or request identity changed after preparation")


def _replay(state, prepared, *, benchmark=False):
    from strategy_runtime.equity_replay import PreparedReplay
    candidate = _benchmark_candidate(prepared.request) if benchmark else prepared.candidate
    graph = candidate.definition.feature_graph
    context_key = equity_hash({"auxiliary": [asdict(x) for x in candidate.definition.auxiliary_inputs],
                              "session": candidate.definition.session_context})
    key = (prepared.snapshot.sha256, equity_hash(graph.to_dict()), candidate.definition.execution_spec.data_latency_seconds, context_key)
    if key not in state.replays:
        products = state.products[prepared.snapshot.sha256]
        base = next((value for k, value in state.replays.items() if k[0] == key[0] and k[2:] == key[2:]), None)
        identities = _read(prepared.snapshot.artifact.content)["data"]
        state.replays[key] = (base.with_graph(graph) if base is not None else PreparedReplay.from_frames(
            products["bars"], products["constraints"], graph, latency_seconds=key[2],
            **_runtime_inputs(candidate.definition, products, identities)))
    return candidate, state.replays[key]


@dataclass(frozen=True, slots=True)
class _ReplayAccountRequest:
    """Only execution values cross the worker boundary, never research lineage."""
    window: TimeInterval
    initial_cash: float
    fee_rate: float


def _compute_account(replay, candidate, request, actions, owner):
    """Worker computation only: it cannot certify or publish its own output."""
    from strategy_runtime.equity_replay import run_replay
    from trading_execution_engine.equity import EquityHistoricalExecutor
    executor = EquityHistoricalExecutor(specification=candidate.definition.execution_spec,
        initial_cash=request.initial_cash, fee_rate=request.fee_rate, actions=actions)
    outcome = run_replay(replay, candidate, executor, start=request.window.start,
        end=request.window.end, fee_rate=request.fee_rate, owner=owner)
    account = outcome.execution_result
    run = {"decisions": _records(account.decisions), "orders": _records(account.orders),
        "fills": _records(account.fills), "actions": _records(account.corporate_action_entries),
        "account_points": _records(account.account_points), "trades": _records(account.trades),
        "account_daily": _records(account.account_daily)}
    return run, outcome.statistics


def _account_owner(prepared, *, benchmark):
    candidate = prepared.candidate
    return ("benchmark:" + prepared.benchmark_identity.sha256 if benchmark else
            f"candidate:{candidate.strategy_id}:{candidate.candidate_id}:{candidate.content_identity.content_sha256}")


def _record_timing(state, prepared, benchmark, timing):
    key = ("BENCHMARK" if benchmark else "CANDIDATE", _account_owner(prepared, benchmark=benchmark))
    prior = state.replay_statistics.get(key)
    if prior is not None:
        timing = replace(timing, feature_seconds=prior.feature_seconds + timing.feature_seconds,
            replay_seconds=prior.replay_seconds + timing.replay_seconds,
            rows=prior.rows + timing.rows, decisions=prior.decisions + timing.decisions)
    state.replay_statistics[key] = timing
    if benchmark:
        state.benchmark_runs += 1
    else:
        state.candidate_runs += 1


def _inputs(snapshot, request):
    products = _read(snapshot.artifact.content)["products"]
    return {"bars": products["bars"], "action_facts": products["actions"], "constraints": products["constraints"],
        "specification": _json_value(asdict(request.candidate.definition.execution_spec)),
        "initial_cash": request.initial_cash, "fee_rate": request.fee_rate}


def _certify_run(state, prepared, run, *, benchmark):
    inputs = _inputs(prepared.snapshot, prepared.request)
    ledger = {**inputs, **{name: run[name] for name in
        ("decisions", "orders", "fills", "actions", "account_points", "trades")}}
    with state.certification:
        audit = certify_equity_ledger(ledger)
    run = {**run, "metrics": _json_value(asdict(audit)), "data_quality": _data_quality(inputs["bars"], run)}
    owner = ({"kind": "BENCHMARK", "run_identity": prepared.benchmark_identity.to_dict(),
              "run_sha256": prepared.benchmark_identity.sha256} if benchmark else
             {"kind": "CANDIDATE", "candidate": asdict(prepared.candidate.key),
              "content_sha256": prepared.candidate.content_identity.content_sha256})
    return EquityArtifact("equity_account", _bytes({"schema": "equity-account/v1", "owner": owner,
        "input_sha256": _primary_input_sha256(prepared.snapshot) if benchmark else prepared.snapshot.sha256, "run": run}))


def _result(prepared, candidate, benchmark):
    from .evaluation import EvaluationIdentity
    from strategy_runtime import canonical_sha256
    request = prepared.request
    contract = prepared.identity(request.candidate.definition.execution_spec)
    request_hash = equity_hash(contract)
    identity = EvaluationIdentity(request.candidate.key, request.candidate.content_identity.content_sha256,
        request.prepared.manifest_sha256, request_hash, canonical_sha256(contract["engine_sources"]))
    payload = {"schema": "equity-research/v3", "schema_version": 3, "request": contract,
        "request_hash": request_hash, "evaluation_identity": identity.to_dict(), "evaluation_id": identity.evaluation_id,
        "data": _read(prepared.snapshot.artifact.content)["data"], "input_ref": prepared.snapshot.artifact.reference(),
        "candidate_ref": candidate.reference(), "benchmark_ref": benchmark.reference(),
        "benchmark_identity": prepared.benchmark_identity.to_dict(),
        "limitations": ["BAR_RANGE model; no exact intrabar fill time", "bar observations are not independent samples",
            "research evidence; not frozen release or PTE admission"]}
    return EquityEvaluationResult(request_hash, _bytes(payload), (prepared.snapshot.artifact, candidate, benchmark))


def evaluate_many_equity_v3(access, requests, *, execution):
    """Replay unique accounts, then independently certify in the owning process."""
    from .evaluation_access import EvaluationOutcome, EvaluationStatus, EvaluationError
    state = _state(access, execution)
    if type(requests) is not tuple or not requests:
        raise TypeError("v3 evaluation requires a nonempty tuple of prepared handles")
    for prepared in requests:
        _require_prepared(state, prepared)
        if prepared.experiment.experiment_id != execution.experiment.experiment_id:
            raise ValueError("v3 evaluation belongs to another experiment")
    restored = {}
    if execution.checkpoint is not None:
        for i, prepared in enumerate(requests):
            request_hash = equity_hash(_json_value(prepared.identity(access.execution_spec)))
            cached = execution.checkpoint.load_equity_result(prepared, request_hash)
            if cached is None:
                continue
            with execution.executor.measure(ExecutionPhase.AUTHENTICATE):
                _authenticate_restore(state, prepared, cached)
            restored[i] = cached
            execution.executor.reused_results += 1
    tasks, task_meta, failures = [], {}, {}
    for i, prepared in enumerate(requests):
        if i in restored:
            continue
        for benchmark in (False, True):
            key = ("benchmark", prepared.benchmark_identity.sha256) if benchmark else ("candidate", i)
            if key in task_meta or (benchmark and key[1] in state.benchmarks):
                continue
            task_meta[key] = (prepared, benchmark)
            try:
                with execution.executor.measure(ExecutionPhase.PREPARE):
                    candidate, replay = _replay(state, prepared, benchmark=benchmark)
                owner = _account_owner(prepared, benchmark=benchmark)
                contract = _ReplayAccountRequest(prepared.request.window, prepared.request.initial_cash, prepared.request.fee_rate)
                tasks.append((key, (replay, candidate, contract, state.products[prepared.snapshot.sha256]["actions"], owner)))
            except Exception as exc:
                failures[key] = exc
    completed = {}
    # Drain compute first: COMPUTE wall time does not hide parent certification.
    with closing(execution.executor.run(_compute_account, iter(tasks), phase=ExecutionPhase.COMPUTE, total=len(tasks))) as values:
        for key, value, error in values:
            completed[key] = (value, error)
    accounts = {}
    for key, (value, error) in completed.items():
        if error is not None:
            failures[key] = error
            continue
        prepared, benchmark = task_meta[key]
        _record_timing(state, prepared, benchmark, value[1])
        try:
            with execution.executor.measure(ExecutionPhase.AUTHENTICATE):
                artifact = _certify_run(state, prepared, value[0], benchmark=benchmark)
            accounts[key] = artifact
            if benchmark:
                state.benchmarks[key[1]] = artifact
        except Exception as exc:
            failures[key] = exc
    outcomes = []
    for i, prepared in enumerate(requests):
        request_hash = equity_hash(_json_value(prepared.identity(access.execution_spec)))
        if i in restored:
            outcomes.append(EvaluationOutcome(EvaluationStatus.SUCCEEDED, request_hash, restored[i]))
            continue
        errors = [failures[key] for key in (("candidate", i), ("benchmark", prepared.benchmark_identity.sha256)) if key in failures]
        if errors:
            error = errors[0]
            status = (EvaluationStatus.UNKNOWN if isinstance(error, BrokenProcessPool) else
                      EvaluationStatus.CANCELLED if isinstance(error, (CancelledError, KeyboardInterrupt, SystemExit)) else
                      EvaluationStatus.FAILED)
            outcomes.append(EvaluationOutcome(status, request_hash,
                error=EvaluationError(type(error).__name__, str(error) or type(error).__name__)))
            continue
        try:
            _require_prepared(state, prepared)
            result = _result(prepared, accounts[("candidate", i)], state.benchmarks[prepared.benchmark_identity.sha256])
            with execution.executor.measure(ExecutionPhase.AUTHENTICATE), state.certification:
                build_v3_assessment(result, scope=state.certification)
            state.results[id(result)] = (result, result.result_hash, prepared)
            if execution.checkpoint is not None:
                execution.checkpoint.save_equity_result(request_hash, result)
            outcomes.append(EvaluationOutcome(EvaluationStatus.SUCCEEDED, request_hash, result))
        except Exception as exc:
            outcomes.append(EvaluationOutcome(EvaluationStatus.FAILED, request_hash,
                error=EvaluationError(type(exc).__name__, str(exc) or type(exc).__name__)))
    return tuple(outcomes)


def _authenticate_restore(state, prepared, result):
    expected = _json_value(prepared.identity(prepared.candidate.definition.execution_spec))
    payload = result.payload
    if (payload["request"] != expected or payload["input_ref"] != prepared.snapshot.artifact.reference()
            or payload["benchmark_identity"] != prepared.benchmark_identity.to_dict()):
        raise ValueError("restored v3 result differs from authenticated prepared inputs")
    build_v3_assessment(result, scope=state.certification)
    state.benchmarks[prepared.benchmark_identity.sha256] = next(item for item in result.artifacts
        if item.sha256 == payload["benchmark_ref"]["sha256"])
    state.results[id(result)] = (result, result.result_hash, prepared)


def validate_certified_result(access, prepared, result, *, execution):
    state = _state(access, execution, prepared.experiment.experiment_id)
    _require_prepared(state, prepared)
    expected = state.results.get(id(result))
    if expected is None or expected[0] is not result or expected[1] != result.result_hash or expected[2] is not prepared:
        raise ValueError("result is not the exact certified result issued by this execution session")
    if result.request_hash != equity_hash(_json_value(prepared.identity(access.execution_spec))):
        raise ValueError("certified result request or engine identity changed")


def validate_result_structure(payload, artifacts=()):
    if payload.get("schema_version") != 3 or payload["request"].get("schema") != "equity-research/v3":
        raise ValueError("v3 result schema differs")
    expected = []
    for name, kind in (("input_ref", "equity_input"), ("candidate_ref", "equity_account"), ("benchmark_ref", "equity_account")):
        ref = payload[name]
        if type(ref) is not dict or set(ref) != {"kind", "sha256"} or ref["kind"] != kind:
            raise ValueError("v3 artifact reference schema differs")
        import re
        if type(ref["sha256"]) is not str or re.fullmatch("[a-f0-9]{64}", ref["sha256"]) is None:
            raise ValueError("invalid v3 artifact digest")
        expected.append((ref["kind"], ref["sha256"]))
    if len(set(expected)) != 3:
        raise ValueError("v3 input, candidate and benchmark must be distinct artifacts")
    if artifacts and set(expected) != {(item.kind, item.sha256) for item in artifacts}:
        raise ValueError("v3 result artifact closure differs from references")


@dataclass(frozen=True, slots=True)
class MaterializedEquityV3:
    source_content: bytes
    artifacts: tuple[EquityArtifact, ...]

    def __post_init__(self):
        if (type(self.source_content) is not bytes or type(self.artifacts) is not tuple
                or any(type(item) is not EquityArtifact for item in self.artifacts)):
            raise TypeError("materialized evidence requires immutable source bytes and typed artifacts")
        validate_result_structure(_read(self.source_content), self.artifacts)
        if len(self.artifacts) != 3:
            raise ValueError("materialization requires the complete v3 closure")

    @property
    def source_sha256(self):
        return sha256(self.source_content).hexdigest()

    @property
    def payload(self):
        payload = _read(self.source_content)
        documents = {item.sha256: _read(item.content) for item in self.artifacts}
        inputs = documents[payload["input_ref"]["sha256"]]
        if inputs.get("schema") != "equity-input/v1" or inputs["data"] != payload["data"]:
            raise ValueError("v3 input identity differs")
        runs = {}
        for name, key in (("candidate", "candidate_ref"), ("buy_hold", "benchmark_ref")):
            account = documents[payload[key]["sha256"]]
            expected_input = (payload["input_ref"]["sha256"] if name == "candidate" else
                              payload["benchmark_identity"]["input_snapshot_sha256"])
            if account.get("schema") != "equity-account/v1" or account["input_sha256"] != expected_input:
                raise ValueError("v3 account input identity differs")
            if name == "candidate":
                expected_owner = {"kind": "CANDIDATE", "candidate": payload["evaluation_identity"]["candidate"],
                    "content_sha256": payload["request"]["content_sha256"]}
            else:
                identity = BenchmarkRunIdentity(_bytes(payload["benchmark_identity"]))
                expected_owner = {"kind": "BENCHMARK", "run_identity": identity.to_dict(), "run_sha256": identity.sha256}
                contract = identity.to_dict()
                request = payload["request"]
                primary = EquityInputSnapshot(next(item for item in self.artifacts if item.kind == "equity_input"))
                if (contract["input_snapshot_sha256"] != _primary_input_sha256(primary)
                        or any(contract[name] != request[name] for name in
                            ("instrument", "window", "history_start", "initial_cash", "fee_rate", "engine_sources", "python_version", "pandas_version"))
                        or contract["definition"]["warmup_bars"] != request["warmup_bars"]
                        or contract["definition"]["execution_spec"] != request["specification"]):
                    raise ValueError("v3 benchmark economic identity differs from evaluation")
            if account["owner"] != expected_owner:
                raise ValueError("v3 account owner differs")
            runs[name] = account["run"]
        request = payload["request"]
        products = inputs["products"]
        payload.update(runs=runs, audit_inputs={"bars": products["bars"], "action_facts": products["actions"],
            "constraints": products["constraints"], "specification": request["specification"],
            "initial_cash": request["initial_cash"], "fee_rate": request["fee_rate"]})
        definition = request["candidate_definition"]
        decision_inputs = {}
        if definition.get("session_context"):
            decision_inputs["sessions"] = products["sessions"]
        if definition.get("auxiliary_inputs"):
            decision_inputs["auxiliary"] = {item["name"]: {
                "bars": products[f"auxiliary:{item['name']}:bars"],
                "sessions": products[f"auxiliary:{item['name']}:sessions"]}
                for item in definition["auxiliary_inputs"]}
        if decision_inputs:
            payload["audit_inputs"]["decision_inputs"] = decision_inputs
        return payload


def materialize_v3(value, resolver=None):
    """Resolve an immutable closure; resolver receives a {kind, sha256} reference."""
    if type(value) is EquityEvaluationResult:
        content, artifacts = value.content, value.artifacts
    elif type(value) is dict:
        content, artifacts = _bytes(value), ()
    elif type(value) is bytes:
        content, artifacts = value, ()
    else:
        raise TypeError("v3 materialization requires result, payload or immutable bytes")
    payload = _read(content)
    validate_result_structure(payload, artifacts)
    if not artifacts:
        if not callable(resolver):
            raise TypeError("detached v3 evidence requires an explicit artifact resolver")
        values = []
        for name in ("input_ref", "candidate_ref", "benchmark_ref"):
            ref = payload[name]
            item = EquityArtifact(ref["kind"], resolver(dict(ref)))
            if item.sha256 != ref["sha256"]:
                raise ValueError("v3 artifact content digest differs")
            values.append(item)
        artifacts = tuple(values)
    view = MaterializedEquityV3(content, artifacts)
    view.payload  # Authenticate all owner/input links at the resolver boundary.
    return view


def build_v3_assessment(value, resolver=None, *, scope=None):
    from .equity_assessment import build_equity_assessment_payload
    if scope is None:
        scope = EquityCertificationScope()
    if type(scope) is not EquityCertificationScope:
        raise TypeError("v3 assessment requires an owned certification scope")
    view = value if type(value) is MaterializedEquityV3 else materialize_v3(value, resolver)
    with scope:
        return build_equity_assessment_payload(view)
