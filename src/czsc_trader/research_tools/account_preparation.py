"""Market-neutral, session-owned preparation handles for account evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .evaluation import EvaluationRequest
    from .equity_evaluation import EquityEvaluationRequest
    from .equity_replay_v3 import EquityInputSnapshot


def _read(content):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate preparation field: {key}')
            result[key] = value
        return result
    def reject(value):
        raise ValueError(f'nonfinite preparation value: {value}')
    return json.loads(content, object_pairs_hook=unique, parse_constant=reject)


def _bytes(value):
    from datetime import date, datetime
    def encode(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f'invalid preparation identity value: {type(item)}')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=encode).encode()


@dataclass(frozen=True, slots=True)
class BenchmarkRunIdentity:
    """An immutable execution identity independent of candidate registration."""
    content: bytes

    def __post_init__(self):
        if type(self.content) is not bytes:
            raise TypeError('benchmark identity requires immutable canonical bytes')
        value = _read(self.content)
        if value.get('kind') not in {'BUY_HOLD', 'ACCOUNT_BENCHMARKS'} or _bytes(value) != self.content:
            raise ValueError('invalid benchmark identity')

    @property
    def sha256(self):
        return sha256(self.content).hexdigest()

    def to_dict(self):
        return _read(self.content)


@dataclass(frozen=True, slots=True)
class AccountInputSnapshot:
    """Immutable identities for pinned business inputs; never mutable account state."""
    content: bytes

    def __post_init__(self):
        if type(self.content) is not bytes or not self.content:
            raise TypeError('input snapshot requires immutable nonempty bytes')
        _read(self.content)

    @property
    def sha256(self):
        return sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedAccountEvaluation:
    request: EvaluationRequest | EquityEvaluationRequest
    snapshot: AccountInputSnapshot | EquityInputSnapshot
    benchmark_identity: BenchmarkRunIdentity
    scope_token: str
    contract_content: bytes

    def __post_init__(self):
        from .evaluation import EvaluationRequest
        from .equity_evaluation import EquityEvaluationRequest
        from .equity_replay_v3 import EquityInputSnapshot, _bytes, _read
        if type(self.request) is EvaluationRequest:
            if (type(self.snapshot) is not AccountInputSnapshot or not self.request.input_bindings
                    or self.request.execution_data is None):
                raise TypeError('prepared evaluation requires pinned account inputs')
        elif type(self.request) is EquityEvaluationRequest:
            if (not self.request.formal or self.request.candidate.definition.contract_version not in (3, 4)
                    or self.request.prepared is None or self.request.input_binding is None
                    or type(self.snapshot) is not EquityInputSnapshot):
                raise TypeError('prepared v3 evaluation requires a bound v3 request')
        else:
            raise TypeError('prepared account requires an explicit evaluation request')
        if type(self.benchmark_identity) is not BenchmarkRunIdentity:
            raise TypeError('prepared evaluation requires typed benchmark identity')
        if type(self.scope_token) is not str or not self.scope_token:
            raise TypeError('prepared evaluation requires an owner token')
        if type(self.contract_content) is not bytes or _bytes(_read(self.contract_content)) != self.contract_content:
            raise TypeError('prepared evaluation requires canonical immutable contract bytes')

    @property
    def experiment(self):
        from .evaluation import EvaluationRequest
        from .context import ExperimentRef
        if type(self.request) is EvaluationRequest:
            return ExperimentRef(self.request.strategy.strategy_family_id, self.request.experiment_id)
        return self.request.experiment

    @property
    def candidate(self):
        from .evaluation import EvaluationRequest
        return self.request.strategy if type(self.request) is EvaluationRequest else self.request.candidate

    @property
    def formal(self):
        return True

    def identity(self, specification):
        from .evaluation import EvaluationRequest
        contract = _read(self.contract_content)
        if type(self.request) is not EvaluationRequest:
            if specification.fingerprint != contract['specification_hash']:
                raise ValueError('prepared evaluation execution contract differs')
        elif specification is not None:
            raise ValueError('prepared account execution contract differs')
        return contract


def _prepare_account(access, request, execution):
    """Authenticate input selection once, independently of account cash/costs."""
    from uuid import uuid4
    from dataclasses import replace
    from .execution import ResearchExecutionSession
    from .evaluation import EvaluationRequest, _request_contract, _request_identity_payload
    if type(request) is not EvaluationRequest:
        raise TypeError('account preparation requires EvaluationRequest')
    if type(execution) is not ResearchExecutionSession:
        raise TypeError('account preparation requires an explicit ResearchExecutionSession')
    execution.require(access, request.experiment_id)
    if not hasattr(execution, '_accounts'):
        execution._accounts = ({}, {}, uuid4().hex)
        execution._account_input_selections = {}
        execution._account_private_requests = {}
    handles, inputs, token = execution._accounts
    authenticated = _request_contract(request, require_execution=False)[0]
    selection = dict(authenticated)
    for name in ('nonparameter_context_sha256', 'lineage', 'parameter_binding', 'initial_cash',
                 'costs', 'benchmark', 'frequency_window_days', 'metric_semantics_version'):
        selection.pop(name, None)
    selection['repository'] = str(request.repository_root.resolve())
    selection['source_root'] = str(request.strategy.source_root.resolve())
    ref = None if request.execution_data is None else request.execution_data.prepared
    selection['execution_locator'] = None if ref is None else {
        'space_id': str(ref.space_id), 'preparation_id': str(ref.preparation_id), 'manifest_sha256': ref.manifest_sha256}
    binding = None if request.lineage is None else request.lineage.parameter_binding
    selection['parameter_plan'] = None if binding is None else binding.plan.to_dict()
    key = sha256(_bytes(selection)).hexdigest()
    cached = execution._account_input_selections.get(key)
    if cached is None:
        bound = access._bind_inputs(request)
        from .parameter_evaluation import prepare_parameter_facts
        facts = prepare_parameter_facts(bound, access.data)
        data = _bytes({'execution': bound.execution_data.fingerprint,
                      'bindings': {name: item.to_dict() for name, item in bound.input_bindings.items()},
                      'parameter_facts': facts})
        digest = sha256(data).hexdigest()
        snapshot = inputs.setdefault(digest, AccountInputSnapshot(data))
        from dataclasses import fields
        import pandas as pd
        original = bound.execution_data
        copies = {}
        for item in fields(original):
            current = getattr(original, item.name)
            if isinstance(current, pd.DataFrame):
                # Certified provenance lives in the pinned binding/snapshot.
                # Detach numerical blocks without deep-copying quality attrs.
                copies[item.name] = pd.DataFrame(current, copy=True)
            elif isinstance(current, pd.Series):
                copies[item.name] = pd.Series(current, copy=True)
            elif isinstance(current, pd.Index):
                copies[item.name] = current.copy(deep=True)
            elif isinstance(current, dict):
                copies[item.name] = dict(current)
        private_data = replace(original, **copies)
        execution._account_input_selections[key] = (bound, snapshot, private_data)
    else:
        original, snapshot, private_data = cached
        bound = replace(request, execution_data=original.execution_data, input_bindings=original.input_bindings)
    contract = _request_identity_payload(bound, authenticated['content_sha256'], authenticated['runtime_binding_hash'])
    content = _bytes(contract)
    benchmark = BenchmarkRunIdentity(_bytes({'kind': 'ACCOUNT_BENCHMARKS',
        'input': bound.execution_data.fingerprint,
        'windows': sorted({(item.start.isoformat(), item.end.isoformat()) for item in bound.windows}),
        'cash': bound.initial_cash, 'costs': sorted({item.one_way_cost for item in bound.costs}),
        'benchmark': bound.benchmark.to_dict()}))
    value = PreparedAccountEvaluation(bound, snapshot, benchmark, token, content)
    handles[id(value)] = value
    execution._account_private_requests[id(value)] = replace(bound, execution_data=private_data)
    from .parameter_evaluation import validate_parameter_request
    try:
        validate_parameter_request(value, access.data, execution=execution)
    except BaseException:
        handles.pop(id(value), None)
        execution._account_private_requests.pop(id(value), None)
        raise
    return value


def require_account(access, value, execution):
    from .execution import ResearchExecutionSession
    from .evaluation import EvaluationRequest, _request_identity_payload
    if type(value) is not PreparedAccountEvaluation:
        raise TypeError('account evaluation requires a session-owned PreparedAccountEvaluation')
    if type(execution) is not ResearchExecutionSession:
        raise TypeError('account evaluation requires an explicit ResearchExecutionSession')
    execution.require(access, value.experiment.experiment_id)
    if type(value.request) is not EvaluationRequest:
        from .equity_replay_v3 import _require_prepared, _state
        _require_prepared(_state(access, execution), value)
        return value.request
    handles, _, token = getattr(execution, '_accounts', ({}, {}, None))
    if handles.get(id(value)) is not value or value.scope_token != token:
        raise ValueError('prepared account handle was not issued by this execution session')
    contract = _read(value.contract_content)
    current = _request_identity_payload(value.request, contract["content_sha256"], contract["runtime_binding_hash"])
    if _bytes(current) != value.contract_content:
        raise ValueError('account request identity changed after preparation')
    return execution._account_private_requests[id(value)]


def account_benchmark_seeds(execution, value, *, request):
    """Compute each exact baseline once, during evaluation, never preparation."""
    from ..backtesting.benchmarks import BenchmarkReplayScope, BenchmarkWindow
    from .execution import ExecutionPhase
    import pandas as pd
    if not hasattr(execution, '_account_benchmarks'):
        execution._account_benchmarks = BenchmarkReplayScope()
    # evaluate_many authenticated the handle before entering its busy operation.
    # The task generator runs inside that operation; it must not re-enter it.
    if (not execution._active
            or execution._account_private_requests.get(id(value)) is not request
            or execution._accounts[0].get(id(value)) is not value):
        raise ValueError('benchmark requires the exact authenticated account request')
    bound = request
    with execution.executor.measure(ExecutionPhase.BENCHMARK):
        return tuple(execution._account_benchmarks.prepare(bound.execution_data,
            BenchmarkWindow(pd.Timestamp(window.start), pd.Timestamp(window.end), cost.one_way_cost),
            bound.initial_cash, benchmark=bound.benchmark)
            for window in bound.windows for cost in bound.costs)


def prepare_account(access, request, execution):
    from .execution import ResearchExecutionSession, ExecutionPhase
    if type(execution) is not ResearchExecutionSession:
        raise TypeError('account preparation requires an explicit ResearchExecutionSession')
    with execution.executor.measure(ExecutionPhase.PREPARE):
        return _prepare_account(access, request, execution)
