"""Market-neutral, session-owned preparation handles for account evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .equity_evaluation import EquityEvaluationRequest
    from .equity_replay import EquityInputSnapshot


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


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PreparedAccountEvaluation:
    request: EquityEvaluationRequest
    snapshot: EquityInputSnapshot
    benchmark_identity: BenchmarkRunIdentity | None
    scope_token: str
    contract_content: bytes

    def __post_init__(self):
        from .equity_evaluation import EquityEvaluationRequest
        from .equity_replay import EquityInputSnapshot, _bytes, _read
        if type(self.request) is not EquityEvaluationRequest:
            raise TypeError('prepared account requires an EquityEvaluationRequest')
        from strategy_runtime import STEP_DATA_CONTRACT
        if (self.request.candidate.definition.contract_version != STEP_DATA_CONTRACT
                or self.request.prepared is None or self.request.input_binding is None
                or type(self.snapshot) is not EquityInputSnapshot):
            raise TypeError('prepared equity evaluation requires a bound V4 request')
        expected_type = type(None) if self.request.benchmark is None else BenchmarkRunIdentity
        if type(self.benchmark_identity) is not expected_type:
            raise TypeError('prepared benchmark identity differs from the request')
        if type(self.scope_token) is not str or not self.scope_token:
            raise TypeError('prepared evaluation requires an owner token')
        if type(self.contract_content) is not bytes or _bytes(_read(self.contract_content)) != self.contract_content:
            raise TypeError('prepared evaluation requires canonical immutable contract bytes')

    @property
    def experiment(self):
        return self.request.experiment

    @property
    def candidate(self):
        return self.request.candidate

    @property
    def formal(self):
        return True

    def identity(self, specification):
        contract = _read(self.contract_content)
        if specification.fingerprint != contract['specification_hash']:
            raise ValueError('prepared evaluation execution contract differs')
        return contract


def require_account(access, value, execution):
    from .execution import ResearchExecutionSession
    if type(value) is not PreparedAccountEvaluation:
        raise TypeError('account evaluation requires a session-owned PreparedAccountEvaluation')
    if type(execution) is not ResearchExecutionSession:
        raise TypeError('account evaluation requires an explicit ResearchExecutionSession')
    execution.require(access, value.experiment.experiment_id)
    from .equity_replay import _require_prepared, _state
    _require_prepared(_state(access, execution), value)
    return value.request
