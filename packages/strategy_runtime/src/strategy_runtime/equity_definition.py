"""Portable, explicitly versioned equity strategy source and decision contracts."""
from dataclasses import asdict, dataclass, replace, field, fields, is_dataclass
from datetime import date, datetime
from enum import StrEnum
import math
from pathlib import Path, PurePosixPath
from hashlib import sha256
from importlib import metadata
import ast
import importlib.abc
import importlib.machinery
import importlib.util
import json
import sys
import types
from types import MappingProxyType
from uuid import uuid4
from functools import lru_cache, cached_property
from typing import Mapping
import pandas as pd

from dataflows import (InstrumentId, MarketId, AssetClass, BarFrequency, PreparedDataRef,
                      SourceRef, EquityProduct, EquityQuery, EquityDataRequest, PriceAdjustment,
                      TradingSession, EquitySession)
from dataflows.equity_contracts import EquityParameters
from .identity import CandidateContentIdentity, ImplementationDependency
from .models import canonical_sha256, ExecutionPolicy
from .dataset_observations import DatasetObservationInput, DatasetObservationBinding
from .market_features import MarketFeature, _parameter_key
from .signal_explanation import SignalExplanationSnapshot, SignalBasisSnapshot
from .equity import (ResearchExecutionSpec, UsEquitySpec, CnEquitySpec, AccountPolicy,
                     CashAvailabilityPolicy, ExecutionModel, EquityPortfolio, DecisionPoint)


def execution_spec_from_dict(value):
    value = dict(value)
    market = value.pop("market")
    if market.get("rule_version") not in {"US_EQUITY_V1", "CN_EQUITY_V1"}:
        raise ValueError("unknown equity market rule version")
    value["market"] = UsEquitySpec(**market) if market["rule_version"] == "US_EQUITY_V1" else CnEquitySpec(**market)
    account = dict(value.pop("account"))
    account["cash_availability"] = CashAvailabilityPolicy(account["cash_availability"])
    value["account"] = AccountPolicy(**account)
    value["decision_clock"] = BarFrequency(value["decision_clock"])
    value["execution"] = ExecutionModel(value["execution"])
    return ResearchExecutionSpec(**value)


def _read_equity_sources(root, files):
    root = Path(root).resolve()
    digest = sha256()
    sources = {}
    for name in sorted(files):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("equity source is absent or escapes source root")
        digest.update(name.encode())
        digest.update(b"\0")
        content = path.read_bytes()
        sources[name] = content
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest(), sources


def equity_source_hash(root, files):
    return _read_equity_sources(root, files)[0]


def _verify_decision_access(tree, filename, definition):
    module, entrypoint = definition.entrypoint.split(':')
    if filename != module.replace('.', '/') + '.py':
        return
    names = {item.name for item in definition.market_features}
    for function in tree.body:
        if type(function) is not ast.FunctionDef or function.name != entrypoint:
            continue
        args = (*function.args.posonlyargs, *function.args.args)
        if not args:
            return
        context = args[0].arg
        for node in ast.walk(function):
            if isinstance(node, ast.Attribute) and node.attr in ('to_frame', 'rows'):
                origin = node.value.value if isinstance(node.value, ast.Subscript) else node.value
                if (isinstance(origin, ast.Attribute) and origin.attr in ('history', 'auxiliary_histories', 'observations')
                        and isinstance(origin.value, ast.Name) and origin.value.id == context):
                    raise ValueError(f'{filename}:{node.lineno}: V4 decisions require a declared market feature for history windows')
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'market_feature'
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == context):
                if len(node.args) != 1 or node.keywords:
                    raise ValueError(f'{filename}:{node.lineno}: V4 decisions require a declared market feature name')
                if isinstance(node.args[0], ast.Constant) and node.args[0].value not in names:
                    raise ValueError(f'{filename}:{node.lineno}: undeclared market feature {node.args[0].value!r}')


@lru_cache(maxsize=128)
def _compiled_equity_source(content: bytes, filename: str):
    """Cache code, never a module or its mutable globals."""
    return compile(content, filename, 'exec')


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


@lru_cache(maxsize=256)
def _immutable_parameters(content):
    """Reuse frozen parameter values without adding mappingproxy to pickle state."""
    return _freeze(json.loads(content))


@lru_cache(maxsize=1)
def _package_distributions():
    return metadata.packages_distributions()


@lru_cache(maxsize=4096)
def _cached_fact_basis(key: str, text: str):
    """Reuse only immutable exact-string facts; preserve constructor validation."""
    return SignalBasisSnapshot(key, text)


def _fact_basis(key, text):
    # String subclasses can customize hashing/equality. They retain the original
    # uncached construction path and must not acquire extra hash operations.
    if type(key) is str and type(text) is str:
        return _cached_fact_basis(key, text)
    return SignalBasisSnapshot(key, text)


@dataclass(frozen=True)
class EquityDecision:
    target: int
    reason: str
    explanation: SignalExplanationSnapshot | None = None

    def __post_init__(self):
        if type(self.target) is not int or self.target not in (0, 1):
            raise ValueError("equity decision requires a binary integer target")
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("equity decision requires a nonblank explanation")
        if self.explanation is not None:
            if type(self.explanation) is not SignalExplanationSnapshot:
                raise TypeError('equity explanation requires SignalExplanationSnapshot')
            if self.explanation.state_key != 'target' or self.explanation.case_key != ('long' if self.target else 'flat'):
                raise ValueError('explanation state differs from actual target')

    @classmethod
    def from_facts(cls, target, reason, *, facts, next_watch):
        """Build the shared typed snapshot from explicit decision-time facts."""
        if type(facts) is not dict or not facts:
            raise ValueError('decision explanations require condition/parameter facts')
        return cls(target, reason, SignalExplanationSnapshot('target', 'long' if target else 'flat', reason,
            tuple(_fact_basis(key, str(value)) for key, value in facts.items()), next_watch, reason))


@dataclass(frozen=True)
class EquityDecisionContext:
    history: object
    portfolio: EquityPortfolio
    point: DecisionPoint
    parameters: object
    auxiliary_histories: Mapping[str, pd.DataFrame] = field(default_factory=lambda: MappingProxyType({}))
    session: TradingSession | None = None
    session_available_at: datetime | None = None

    def __post_init__(self):
        if not isinstance(self.auxiliary_histories, Mapping) or any(
                type(name) is not str or not isinstance(frame, pd.DataFrame)
                for name, frame in self.auxiliary_histories.items()):
            raise TypeError('auxiliary histories require named DataFrames')
        object.__setattr__(self, 'auxiliary_histories', MappingProxyType(
            {name: frame.copy(deep=True) for name, frame in self.auxiliary_histories.items()}))


@dataclass(frozen=True)
class EquityAuxiliaryInput:
    name: str
    instrument: InstrumentId
    source: SourceRef
    frequency: BarFrequency
    warmup_bars: int
    max_age_seconds: float
    analysis_price: str = 'HFQ'

    def __post_init__(self):
        import re
        if type(self.name) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', self.name):
            raise ValueError('auxiliary input requires a stable alias')
        if type(self.instrument) is not InstrumentId or type(self.source) is not SourceRef:
            raise TypeError('auxiliary input requires typed instrument and source')
        if self.instrument.market not in (MarketId.CN,MarketId.US) or self.instrument.asset_class not in (AssetClass.STOCK, AssetClass.ETF):
            raise ValueError('auxiliary inputs require supported equity instruments')
        if type(self.frequency) is not BarFrequency or self.frequency not in (BarFrequency.M30, BarFrequency.DAILY):
            raise ValueError('auxiliary frequency must be M30 or DAILY')
        if type(self.analysis_price) is not str or self.analysis_price not in {'RAW', 'HFQ'}:
            raise ValueError('auxiliary input requires a declared RAW or HFQ price basis')
        if type(self.warmup_bars) is not int or self.warmup_bars < 1:
            raise ValueError('auxiliary warmup must be positive')
        if type(self.max_age_seconds) not in (int, float) or not math.isfinite(self.max_age_seconds) or self.max_age_seconds < 0:
            raise ValueError('auxiliary maximum age must be finite and nonnegative')

    def data_key(self, product: EquityProduct) -> str:
        if type(product) is not EquityProduct or product not in (EquityProduct.BARS, EquityProduct.SESSIONS):
            raise ValueError('auxiliary inputs bind bars and sessions only')
        return f'auxiliary:{self.name}:{product.name.lower()}'

    def requests(self, start, end):
        return tuple(EquityDataRequest(self.instrument, self.source,
                     EquityQuery(product, start, end, self.frequency,
                         PriceAdjustment.BACKWARD if product is EquityProduct.BARS and self.analysis_price == 'HFQ'
                         else PriceAdjustment.NONE))
                     for product in (EquityProduct.BARS, EquityProduct.SESSIONS))

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        instrument = dict(value['instrument'])
        instrument['market'] = MarketId(instrument['market'])
        instrument['asset_class'] = AssetClass(instrument['asset_class'])
        value['instrument'] = InstrumentId(**instrument)
        value['source'] = SourceRef(**value['source'])
        value['frequency'] = BarFrequency(value['frequency'])
        return cls(**value)


@dataclass(frozen=True)
class ExecutionInput:
    """Finer HFQ historical execution quotations; never strategy observations."""
    instrument: InstrumentId
    source: SourceRef
    frequency: BarFrequency

    def __post_init__(self):
        if type(self.instrument) is not InstrumentId or type(self.source) is not SourceRef:
            raise TypeError('execution input requires typed instrument/source')
        if self.instrument.market not in (MarketId.CN,MarketId.US) or self.instrument.asset_class not in (AssetClass.STOCK,AssetClass.ETF):
            raise ValueError('execution input requires supported equity instrument')
        if self.frequency is not BarFrequency.M30:
            raise ValueError('execution checkpoints require actual M30 quotations')

    def data_key(self, product):
        if type(product) is not EquityProduct or product not in (EquityProduct.BARS,EquityProduct.SESSIONS):
            raise ValueError('execution input binds bars and sessions only')
        return f'execution:{product.name.lower()}'

    def requests(self,start,end):
        return tuple(EquityDataRequest(self.instrument,self.source,EquityQuery(product,start,end,self.frequency, PriceAdjustment.BACKWARD if product is EquityProduct.BARS else PriceAdjustment.NONE))
            for product in (EquityProduct.BARS,EquityProduct.SESSIONS))

    @classmethod
    def from_dict(cls,value):
        value=dict(value)
        instrument=dict(value['instrument'])
        instrument['market']=MarketId(instrument['market'])
        instrument['asset_class']=AssetClass(instrument['asset_class'])
        return cls(InstrumentId(**instrument),SourceRef(**value['source']),BarFrequency(value['frequency']))


@dataclass(frozen=True)
class ExecutionInputBinding:
    input: ExecutionInput
    bars_sha256: str
    sessions_sha256: str

    def __post_init__(self):
        import re
        if type(self.input) is not ExecutionInput:
            raise TypeError('execution binding requires ExecutionInput')
        if any(type(v) is not str or not re.fullmatch('[a-f0-9]{64}',v) for v in (self.bars_sha256,self.sessions_sha256)):
            raise ValueError('execution binding requires exact content fingerprints')

    @classmethod
    def from_dict(cls,value):
        return cls(ExecutionInput.from_dict(value['input']),value['bars_sha256'],value['sessions_sha256'])


@dataclass(frozen=True)
class EquityAuxiliaryBinding:
    input: EquityAuxiliaryInput
    bars_sha256: str
    sessions_sha256: str

    def __post_init__(self):
        import re
        if type(self.input) is not EquityAuxiliaryInput:
            raise TypeError('auxiliary binding requires a typed input')
        if any(type(x) is not str or not re.fullmatch('[a-f0-9]{64}', x)
               for x in (self.bars_sha256, self.sessions_sha256)):
            raise ValueError('invalid auxiliary content fingerprint')

    @classmethod
    def from_dict(cls, value):
        return cls(EquityAuxiliaryInput.from_dict(value['input']), value['bars_sha256'], value['sessions_sha256'])


class InputBindingScope(StrEnum):
    OBSERVATION = 'OBSERVATION'
    EXECUTION = 'EXECUTION'


@dataclass(frozen=True)
class EquityInputBinding:
    prepared: PreparedDataRef
    instrument: InstrumentId
    specification_hash: str
    content_identities: tuple[tuple[str, str], ...]
    warmup_bars: int
    auxiliary_inputs: tuple[EquityAuxiliaryBinding, ...] = ()
    execution_input: ExecutionInputBinding | None = None
    request_bindings: tuple[tuple[str, EquityParameters], ...] = ()
    observation_bindings: tuple[DatasetObservationBinding, ...] = ()
    scope: InputBindingScope = InputBindingScope.EXECUTION

    def to_dict(self):
        result = asdict(self)
        if self.scope is InputBindingScope.EXECUTION:
            result.pop('scope')
        else:
            result['scope'] = self.scope.value
        if self.observation_bindings:
            result['observation_bindings'] = [item.to_dict() for item in self.observation_bindings]
        else:
            result.pop('observation_bindings')
        result['prepared']['space_id'] = str(self.prepared.space_id)
        result['prepared']['preparation_id'] = str(self.prepared.preparation_id)
        if not self.auxiliary_inputs:
            result.pop('auxiliary_inputs')
        if self.execution_input is None:
            result.pop('execution_input')
        if not self.request_bindings:
            result.pop('request_bindings')
        else:
            for _, parameters in result['request_bindings']:
                parameters['query']['start'] = parameters['query']['start'].isoformat()
                parameters['query']['end'] = parameters['query']['end'].isoformat()
                cutoff = parameters['query'].pop('completed_through')
                if cutoff is not None:
                    parameters['query']['completed_through'] = cutoff.isoformat()
        return result

    def for_observations(self):
        """Explicitly project a research selection into strategy-only inputs."""
        if not self.request_bindings:
            raise ValueError('observation projection requires explicit source bindings')
        primary = {'bars', 'sessions'}
        keep = primary | {item.input.data_key(product) for item in self.auxiliary_inputs
                          for product in (EquityProduct.BARS, EquityProduct.SESSIONS)}
        return replace(self, scope=InputBindingScope.OBSERVATION,
            content_identities=tuple((role, value) for role, value in self.content_identities if role in primary),
            request_bindings=tuple((role, query) for role, query in self.request_bindings if role in keep),
            execution_input=None)

    @property
    def expected_identities(self):
        result = dict(self.content_identities)
        result.update((item.input.data_key(), item.content_sha256) for item in self.observation_bindings if item.request is not None)
        for binding in self.auxiliary_inputs:
            result[binding.input.data_key(EquityProduct.BARS)] = binding.bars_sha256
            result[binding.input.data_key(EquityProduct.SESSIONS)] = binding.sessions_sha256
        if self.execution_input is not None:
            for product,fingerprint in ((EquityProduct.BARS,self.execution_input.bars_sha256),(EquityProduct.SESSIONS,self.execution_input.sessions_sha256)):
                result[self.execution_input.input.data_key(product)] = fingerprint
        return MappingProxyType(result)

    def request_key(self, request: EquityDataRequest) -> str:
        matches = [item.input.data_key() for item in self.observation_bindings if item.request == request]
        if matches:
            if len(matches) != 1:
                raise ValueError('request has shared observation roles; bind the complete request set')
            return matches[0]
        if type(request) is not EquityDataRequest:
            raise TypeError('equity binding requires a typed request')
        p = request.parameters
        if self.request_bindings:
            matches = [key for key, parameters in self.request_bindings if parameters == p]
            if len(matches) != 1:
                raise ValueError('request has absent or shared roles; bind the complete request set')
            return matches[0]
        execution = self.execution_input
        if execution is not None and (execution.input.instrument,execution.input.source,execution.input.frequency)==(p.instrument,p.source,p.query.frequency):
            if p.query.adjustment is not (PriceAdjustment.BACKWARD if p.query.product is EquityProduct.BARS else PriceAdjustment.NONE):
                raise ValueError('historical execution quotations must be HFQ')
            return execution.input.data_key(p.query.product)
        matches = [b.input for b in self.auxiliary_inputs if
                   (b.input.instrument, b.input.source, b.input.frequency) ==
                   (p.instrument, p.source, p.query.frequency)]
        if matches:
            if len(matches) != 1 or p.query.adjustment is not (PriceAdjustment.BACKWARD if p.query.product is EquityProduct.BARS else PriceAdjustment.NONE):
                raise ValueError('ambiguous or non-HFQ auxiliary request')
            return matches[0].data_key(p.query.product)
        if p.instrument != self.instrument or p.query.product.name.lower() not in dict(self.content_identities):
            raise ValueError('request is absent from equity input binding')
        if p.query.adjustment is not (PriceAdjustment.NONE if p.query.product is EquityProduct.SESSIONS else PriceAdjustment.BACKWARD):
            raise ValueError('primary input requires HFQ prices')
        return p.query.product.name.lower()

    def bind_requests(self, requests: tuple[EquityDataRequest, ...]) -> tuple[tuple[str, EquityDataRequest], ...]:
        """Resolve logical roles, allowing one physical calendar to serve multiple roles."""
        if self.observation_bindings:
            from dataflows import DataRequest
            if type(requests) is not tuple or any(not isinstance(x, DataRequest) for x in requests):
                raise TypeError('binding requires typed product requests')
            observation_requests = tuple(item.request for item in self.observation_bindings if item.request is not None)
            if any(request not in requests for request in observation_requests):
                raise ValueError('requests omit declared observations')
            equity_requests = tuple(item for item in requests if item not in observation_requests)
            base = replace(self, observation_bindings=()).bind_requests(equity_requests)
            return base + tuple((item.input.data_key(), item.request) for item in self.observation_bindings if item.request is not None)
        if type(requests) is not tuple or any(type(x) is not EquityDataRequest for x in requests):
            raise TypeError('binding requires typed product requests')
        if not self.request_bindings:
            return tuple((self.request_key(request), request) for request in requests)
        physical = {request.parameters: request for request in requests}
        if set(physical) != {parameters for _, parameters in self.request_bindings}:
            raise ValueError('requests differ from bound product selection')
        return tuple((key, physical[parameters]) for key, parameters in self.request_bindings)

    @classmethod
    def from_dict(cls, value):
        from uuid import UUID
        value = dict(value)
        value['scope'] = InputBindingScope(value.get('scope', InputBindingScope.EXECUTION))
        prepared = dict(value['prepared'])
        prepared['space_id'] = UUID(prepared['space_id'])
        prepared['preparation_id'] = UUID(prepared['preparation_id'])
        value['prepared'] = PreparedDataRef(**prepared)
        instrument = dict(value['instrument'])
        instrument['market'] = MarketId(instrument['market'])
        instrument['asset_class'] = AssetClass(instrument['asset_class'])
        value['instrument'] = InstrumentId(**instrument)
        value['content_identities'] = tuple(tuple(x) for x in value['content_identities'])
        value['auxiliary_inputs'] = tuple(EquityAuxiliaryBinding.from_dict(x) for x in value.get('auxiliary_inputs', ()))
        if value.get('execution_input') is not None:
            value['execution_input'] = ExecutionInputBinding.from_dict(value['execution_input'])
        bindings = []
        for key, parameters in value.get('request_bindings', ()):
            instrument = dict(parameters['instrument'])
            instrument['market'] = MarketId(instrument['market'])
            instrument['asset_class'] = AssetClass(instrument['asset_class'])
            query = dict(parameters['query'])
            for field_name, enum in (('product', EquityProduct), ('frequency', BarFrequency),
                                     ('adjustment', PriceAdjustment), ('session', EquitySession)):
                query[field_name] = enum(query[field_name])
            for field_name in ('start', 'end'):
                query[field_name] = date.fromisoformat(query[field_name])
            if 'completed_through' in query:
                from datetime import datetime
                query['completed_through'] = datetime.fromisoformat(query['completed_through'])
            bindings.append((key, EquityParameters(InstrumentId(**instrument),
                SourceRef(**parameters['source']), EquityQuery(**query))))
        value['request_bindings'] = tuple(bindings)
        value['observation_bindings'] = tuple(DatasetObservationBinding.from_dict(x) for x in value.get('observation_bindings', ()))
        return cls(**value)

    def __post_init__(self):
        if type(self.scope) is not InputBindingScope:
            raise TypeError('input binding requires an explicit scope')
        if self.scope is InputBindingScope.OBSERVATION and self.execution_input is not None:
            raise ValueError('strategy observations cannot bind execution-only quotations')
        if type(self.observation_bindings) is not tuple or any(type(x) is not DatasetObservationBinding for x in self.observation_bindings):
            raise TypeError('observation bindings require typed entries')
        if len({x.input.name for x in self.observation_bindings}) != len(self.observation_bindings):
            raise ValueError('duplicate observation alias')
        observation_identities = {}
        for item in self.observation_bindings:
            if item.request is None:
                continue
            previous = observation_identities.setdefault(item.request, item.content_sha256)
            if previous != item.content_sha256:
                raise ValueError('shared observation request has inconsistent content identities')
        if type(self.auxiliary_inputs) is not tuple or any(type(x) is not EquityAuxiliaryBinding for x in self.auxiliary_inputs):
            raise TypeError('typed auxiliary bindings required')
        if self.execution_input is not None and (type(self.execution_input) is not ExecutionInputBinding or self.execution_input.input.instrument!=self.instrument):
            raise ValueError('execution binding differs from traded instrument')
        if self.execution_input is not None and any(x.input.analysis_price == 'RAW' and (x.input.instrument,x.input.source,x.input.frequency)==(self.execution_input.input.instrument,self.execution_input.input.source,self.execution_input.input.frequency) for x in self.auxiliary_inputs):
            raise ValueError('execution binding duplicates an auxiliary role')
        if len({x.input.name for x in self.auxiliary_inputs}) != len(self.auxiliary_inputs):
            raise ValueError('duplicate auxiliary alias')
        products = [(x.input.instrument, x.input.source, x.input.frequency, x.input.analysis_price) for x in self.auxiliary_inputs]
        if len(set(products)) != len(products):
            raise ValueError('duplicate auxiliary product request')
        if type(self.prepared) is not PreparedDataRef or type(self.instrument) is not InstrumentId:
            raise TypeError("equity binding requires prepared data and instrument")
        if type(self.warmup_bars) is not int or self.warmup_bars < 1:
            raise ValueError("equity binding requires warmup")
        import re
        if not re.fullmatch("[a-f0-9]{64}", self.specification_hash):
            raise ValueError("invalid execution fingerprint")
        required = ({'bars', 'sessions'} if self.scope is InputBindingScope.OBSERVATION else
                    {'bars', 'sessions', 'trading_facts'})
        if {k for k, _ in self.content_identities} != required or len(self.content_identities) != len(required):
            raise ValueError("equity binding products differ from the declared input scope")
        if any(not re.fullmatch("[a-f0-9]{64}", v) for _, v in self.content_identities):
            raise ValueError("invalid data content fingerprint")
        if type(self.request_bindings) is not tuple or any(type(item) is not tuple or len(item) != 2
                or type(item[0]) is not str or type(item[1]) is not EquityParameters for item in self.request_bindings):
            raise TypeError('request bindings require typed role and equity parameters')
        if any(x.input.analysis_price != 'RAW' for x in self.auxiliary_inputs) and not self.request_bindings:
            raise ValueError('adjusted observations require explicit request bindings')
        if self.request_bindings:
            roles = dict(self.request_bindings)
            identities = {key: value for key, value in self.expected_identities.items() if not key.startswith('observation:')}
            primary_roles = dict(self.content_identities)
            if len(roles) != len(self.request_bindings) or set(roles) != set(identities):
                raise ValueError('request bindings must cover exact product roles')
            for key, parameters in self.request_bindings:
                query = parameters.query
                if key in primary_roles:
                    if (parameters.instrument != self.instrument or query.product.name.lower() != key
                            or query.adjustment is not (PriceAdjustment.NONE if query.product is EquityProduct.SESSIONS else PriceAdjustment.BACKWARD)):
                        raise ValueError('primary request binding must use traded HFQ products')
                else:
                    declaration = (self.execution_input.input if key.startswith('execution:') else
                        next(x.input for x in self.auxiliary_inputs if key.startswith(f'auxiliary:{x.input.name}:')))
                    expected = {r.parameters for r in declaration.requests(query.start, query.end)
                        if declaration.data_key(r.parameters.query.product) == key}
                    if parameters not in expected:
                        raise ValueError('request binding differs from declared observation or execution input')
            by_request = {}
            for key, parameters in self.request_bindings:
                fingerprint = identities[key]
                if parameters in by_request and by_request[parameters] != fingerprint:
                    raise ValueError('shared physical product has inconsistent content identities')
                by_request[parameters] = fingerprint


@dataclass(frozen=True)
class EquityStrategyDefinition:
    instrument: InstrumentId
    execution_spec: ResearchExecutionSpec
    warmup_bars: int
    entrypoint: str
    source_files: tuple[str, ...]
    source_sha256: str
    parameters_json: str = "{}"
    dependencies: tuple[ImplementationDependency, ...] = ()
    contract_version: int = 2
    parameter_schema_json: str | None = None
    feedback_mode: str = 'CONFIRMED_EXECUTION'
    analysis_price: str = 'HFQ'
    explanation_cases: tuple[str, ...] = ('flat', 'long')
    auxiliary_inputs: tuple[EquityAuxiliaryInput, ...] = ()
    session_context: bool = False
    feature_graph: object | None = None
    state_schema: object | None = None
    computation: object | None = None
    execution_input: ExecutionInput | None = None
    initial_account: object | None = None
    observation_inputs: tuple[DatasetObservationInput, ...] = ()
    execution_policy: ExecutionPolicy | None = None
    market_features: tuple[MarketFeature, ...] = ()

    def __post_init__(self):
        import re
        if type(self.observation_inputs) is not tuple or any(type(x) is not DatasetObservationInput for x in self.observation_inputs):
            raise TypeError('definition requires typed observation inputs')
        if len({x.name for x in self.observation_inputs}) != len(self.observation_inputs):
            raise ValueError('duplicate observation alias')
        from .models import ExecutionPolicy
        if self.contract_version == 4 and type(self.execution_policy) is not ExecutionPolicy:
            raise TypeError('V4 requires an explicit execution policy')
        if self.contract_version == 4 and self.execution_policy.policy_type not in {
                'TARGET_POSITION', 'FROZEN_RULE', 'INTRADAY_OVERLAY'}:
            raise ValueError('V4 requires a supported channel execution policy')
        if self.contract_version != 4 and (self.observation_inputs or self.execution_policy is not None):
            raise ValueError('dataset observations and execution policy require V4')
        self.frozen_assets
        if type(self.contract_version) is not int or self.contract_version not in (2, 4) or type(self.execution_spec) is not ResearchExecutionSpec:
            raise ValueError("unsupported equity definition contract")
        if self.contract_version == 4:
            from .equity_features import FeatureGraph
            from .equity_replay import StrategyStateSchema
            if (self.execution_policy.settings.get('execution_trigger') == 'daily_target_change_or_zero_fill'
                    and self.execution_spec.decision_clock.value != 'daily'):
                raise ValueError('daily target execution requires a daily decision clock')
            if type(self.feature_graph) is not FeatureGraph or type(self.state_schema) is not StrategyStateSchema:
                raise TypeError('account replay requires a typed feature graph and state schema')
            if self.feedback_mode != 'CONFIRMED_EXECUTION':
                raise ValueError('account replay requires CONFIRMED_EXECUTION feedback')
        elif self.feature_graph is not None or self.state_schema is not None:
            raise ValueError('equity V2 cannot declare account replay features or state')
        from .replay_contracts import StrategyComputation
        from dataflows import BarFrequency
        if self.contract_version == 4:
            if type(self.computation) is not StrategyComputation:
                raise TypeError('V4 requires explicit strategy computation')
            if self.execution_spec.decision_clock not in (BarFrequency.DAILY, BarFrequency.M30):
                raise ValueError('V4 requires D1 or M30 decision clock')
            if self.computation is StrategyComputation.BATCH_HISTORY and (self.state_schema.account_fields or self.state_schema.cycle_fields):
                raise ValueError('batch computation cannot declare account-dependent state fields')
            from .equity_replay import StateRecord
            if self.initial_account is not None and type(self.initial_account) is not StateRecord:
                raise TypeError('initial account state requires StateRecord')
            self.state_schema.validate_record(self.initial_account if self.initial_account is not None else StateRecord(),scope='account')

        elif self.computation is not None or self.initial_account is not None:
            raise ValueError('legacy definitions cannot declare V4 computation or state')
        if self.execution_input is not None:
            if self.contract_version!=4 or type(self.execution_input) is not ExecutionInput:
                raise TypeError('execution input requires V4 and ExecutionInput')
            if self.execution_input.instrument!=self.instrument or self.execution_spec.decision_clock is not BarFrequency.DAILY:
                raise ValueError('finer execution input requires same instrument DAILY strategy')
            if any(x.analysis_price == 'RAW' and (x.instrument,x.source,x.frequency)==(self.execution_input.instrument,self.execution_input.source,self.execution_input.frequency) for x in self.auxiliary_inputs):
                raise ValueError('execution quotation request duplicates an auxiliary role')
        if self.contract_version!=4 and any(x.instrument.market is not MarketId.US for x in self.auxiliary_inputs):
            raise ValueError('legacy auxiliary input contract supports US only')
        if self.contract_version == 4 and any(x.analysis_price != 'HFQ' for x in self.auxiliary_inputs):
            raise ValueError('V4 auxiliary inputs require HFQ prices')
        if self.contract_version != 4 and any(x.analysis_price != 'RAW' for x in self.auxiliary_inputs):
            raise ValueError('adjusted observations require V4')

        self.execution_spec.require_instrument(self.instrument)
        if type(self.session_context) is not bool:
            raise TypeError('session_context requires bool')
        if type(self.auxiliary_inputs) is not tuple or any(type(x) is not EquityAuxiliaryInput for x in self.auxiliary_inputs):
            raise TypeError('typed auxiliary inputs required')
        if self.contract_version != 4 and (self.auxiliary_inputs or self.session_context) and self.instrument.market is not MarketId.US:
            raise ValueError('auxiliary and session context currently require US market')
        if len({x.name for x in self.auxiliary_inputs}) != len(self.auxiliary_inputs):
            raise ValueError('duplicate auxiliary alias')
        identities = [(x.instrument, x.source, x.frequency, x.analysis_price) for x in self.auxiliary_inputs]
        if len(set(identities)) != len(identities):
            raise ValueError('duplicate auxiliary product request')
        if any(x.analysis_price == 'RAW' and x.instrument == self.instrument and x.frequency == self.execution_spec.decision_clock for x in self.auxiliary_inputs):
            raise ValueError('auxiliary request duplicates the primary instrument frequency')
        if type(self.warmup_bars) is not int or self.warmup_bars < 1:
            raise ValueError("positive warmup required")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", self.entrypoint):
            raise ValueError("entrypoint must be module:function")
        if type(self.source_files) is not tuple or not self.source_files or len(set(self.source_files)) != len(self.source_files):
            raise ValueError("unique source manifest required")
        for name in self.source_files:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name or ':' in name or path.suffix != '.py':
                raise ValueError("source manifest must contain relative Python paths")
        if self.entrypoint.split(':')[0].replace('.', '/') + '.py' not in self.source_files:
            raise ValueError("entrypoint absent from source manifest")
        if not re.fullmatch('[a-f0-9]{64}', self.source_sha256):
            raise ValueError("invalid source hash")
        params = json.loads(self.parameters_json, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if type(params) is not dict:
            raise TypeError("parameters require a JSON object")
        object.__setattr__(self, 'parameters_json', json.dumps(params, sort_keys=True, separators=(',', ':'), allow_nan=False))
        names = {int: 'integer', float: 'number', bool: 'boolean', str: 'string', list: 'array', dict: 'object', type(None): 'null'}
        schema = ({key: {'type': names[type(v)]} for key, v in params.items()}
                  if self.parameter_schema_json is None else json.loads(self.parameter_schema_json))
        if type(schema) is not dict or set(schema) != set(params):
            raise ValueError('parameter schema must cover exactly all effective parameters')
        for key, value in params.items():
            rule = schema[key]
            if type(rule) is not dict or set(rule) - {'type', 'minimum', 'maximum', 'enum'}:
                raise ValueError('unsupported parameter schema')
            kind = rule.get('type')
            if kind != names[type(value)] and not (kind == 'number' and type(value) is int):
                raise ValueError(f'parameter type differs: {key}')
            for bound in ('minimum', 'maximum'):
                if bound in rule:
                    if type(value) not in (int, float) or type(rule[bound]) not in (int, float):
                        raise ValueError('parameter bounds require numeric values')
                    if (bound == 'minimum' and value < rule[bound]) or (bound == 'maximum' and value > rule[bound]):
                        raise ValueError(f'parameter outside legal domain: {key}')
            if 'enum' in rule and (type(rule['enum']) is not list or value not in rule['enum']):
                raise ValueError(f'parameter outside declared choices: {key}')
        object.__setattr__(self, 'parameter_schema_json', json.dumps(schema, sort_keys=True, separators=(',', ':'), allow_nan=False))
        if self.feedback_mode not in {'MARKET_INTENT', 'CONFIRMED_EXECUTION', 'CONFIRMED_CLOSED_CYCLE_V1'} or self.analysis_price != ('HFQ' if self.contract_version == 4 else 'RAW'):
            raise ValueError('unsupported equity feedback or analysis price contract')
        if tuple(self.explanation_cases) != ('flat', 'long'):
            raise ValueError('equity explanations must declare both target branches')
        object.__setattr__(self, 'explanation_cases', tuple(self.explanation_cases))
        if type(self.dependencies) is not tuple or any(type(x) is not ImplementationDependency for x in self.dependencies):
            raise TypeError("typed dependencies required")
        if len({x.name for x in self.dependencies}) != len(self.dependencies):
            raise ValueError("duplicate dependency")
        object.__setattr__(self, 'dependencies', tuple(sorted(self.dependencies)))
        object.__setattr__(self, 'source_files', tuple(sorted(self.source_files)))
        self._validate_market_features()

    def _validate_market_features(self):
        features = self.market_features
        if type(features) is not tuple or any(type(item) is not MarketFeature for item in features):
            raise TypeError('market_features requires a tuple of MarketFeature declarations')
        if not features:
            return
        if self.contract_version != 4 or len({item.name for item in features}) != len(features):
            raise ValueError('declared market features require V4 and unique names')
        bar_depth = {None: self.warmup_bars, **{item.name: item.warmup_bars for item in self.auxiliary_inputs}}
        tables = {item.name for item in self.observation_inputs}
        for feature in features:
            module = feature.entrypoint.split(':')[0].replace('.', '/')
            if module + '.py' not in self.source_files and module + '/__init__.py' not in self.source_files:
                raise ValueError('market feature entrypoint is outside declared source: ' + feature.name)
            if feature.session_date and not self.session_context:
                raise ValueError('market feature session_date requires declared session context')
            for name in feature.parameters:
                if name not in self.parameters:
                    raise ValueError('market feature uses an undeclared parameter: ' + name)
                _parameter_key(self.parameters[name])
            for window in feature.windows:
                if window.table:
                    if window.source not in tables:
                        raise ValueError('market feature uses an undeclared observation table: ' + str(window.source))
                elif window.rows > bar_depth.get(window.source, 0):
                    raise ValueError('market feature window exceeds declared bar warmup: ' + str(window.source))

    @cached_property
    def content_identity(self):
        return CandidateContentIdentity(canonical_sha256(self.to_dict()), self.source_sha256,
                                        canonical_sha256([asdict(x) for x in self.dependencies]))

    @property
    def frozen_assets(self):
        assets = {}
        paths = {}
        for item in self.observation_inputs:
            if item.asset is None:
                continue
            previous_path = paths.setdefault(item.asset.relative_path.casefold(), item.asset.relative_path)
            if previous_path != item.asset.relative_path:
                raise ValueError('frozen asset paths conflict on case-insensitive filesystems')
            existing = assets.setdefault(item.asset.relative_path, item.asset)
            if existing != item.asset:
                raise ValueError('frozen asset path has conflicting identities')
        return tuple(assets[key] for key in sorted(assets))

    @property
    def parameters(self):
        return _immutable_parameters(self.parameters_json)

    def to_dict(self):
        # Policy settings are immutable mappings; dataclasses.asdict cannot
        # deepcopy mappingproxy. Serialize that owned contract explicitly.
        def record(value):
            if is_dataclass(value):
                return {item.name: record(getattr(value, item.name)) for item in fields(value)}
            if isinstance(value, Mapping):
                return {key: record(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return type(value)(record(item) for item in value)
            return value
        result = {"runtime_kind": "ACCOUNT_REPLAY" if self.contract_version == 4 else "US_EQUITY", **record(self)}
        if self.observation_inputs:
            result['observation_inputs'] = [item.to_dict() for item in self.observation_inputs]
        else:
            result.pop('observation_inputs')
        if self.execution_policy is None:
            result.pop('execution_policy')
        if self.contract_version != 4:
            result.pop("computation")
        else:
            result["computation"] = self.computation.value
        if not self.auxiliary_inputs:
            result.pop('auxiliary_inputs')
        if not self.session_context:
            result.pop('session_context')
        if self.execution_input is None:
            result.pop('execution_input')
        if self.initial_account is None:
            result.pop('initial_account')
        else:
            result['initial_account'] = self.initial_account.to_dict()
        if not self.market_features:
            result.pop('market_features')
        if self.contract_version == 2:
            result.pop('feature_graph')
            result.pop('state_schema')
        else:
            result['feature_graph'] = self.feature_graph.to_dict()
            result['state_schema'] = self.state_schema.to_dict()
        return result

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        if value.pop('runtime_kind') != ('ACCOUNT_REPLAY' if value.get('contract_version') == 4 else 'US_EQUITY'):
            raise ValueError('wrong runtime kind')
        instrument = dict(value['instrument'])
        instrument['market'] = MarketId(instrument['market'])
        instrument['asset_class'] = AssetClass(instrument['asset_class'])
        value['instrument'] = InstrumentId(**instrument)
        value['execution_spec'] = execution_spec_from_dict(value['execution_spec'])
        if value.get('execution_policy') is not None:
            from .models import ExecutionPolicy
            value['execution_policy'] = ExecutionPolicy(**value['execution_policy'])
        value['source_files'] = tuple(value['source_files'])
        value['dependencies'] = tuple(ImplementationDependency(**x) for x in value['dependencies'])
        value['auxiliary_inputs'] = tuple(EquityAuxiliaryInput.from_dict(x) for x in value.get('auxiliary_inputs', ()))
        value['observation_inputs'] = tuple(DatasetObservationInput.from_dict(x) for x in value.get('observation_inputs', ()))
        value['market_features'] = tuple(MarketFeature.from_dict(x) for x in value.get('market_features', ()))
        if value.get('contract_version', 2) == 4:
            from .equity_features import FeatureGraph
            from .equity_replay import StrategyStateSchema
            value['feature_graph'] = FeatureGraph.from_dict(value['feature_graph'])
            value['state_schema'] = StrategyStateSchema.from_dict(value['state_schema'])
        if value.get('execution_input') is not None:
            value['execution_input'] = ExecutionInput.from_dict(value['execution_input'])
        if value.get('initial_account') is not None:
            from .equity_replay import StateRecord
            # Frozen releases use immutable mappings/tuples for JSON containers.
            # Restore only that representation at the definition boundary; the
            # standalone StateRecord JSON decoder remains strict.
            def json_containers(item):
                if isinstance(item, Mapping):
                    return {key: json_containers(val) for key, val in item.items()}
                if isinstance(item, (tuple, list)):
                    return [json_containers(val) for val in item]
                return item
            value['initial_account'] = StateRecord.from_dict(json_containers(value['initial_account']))
        if value.get('contract_version') == 4:
            from .replay_contracts import StrategyComputation
            value['computation'] = StrategyComputation(value['computation'])
        return cls(**value)


@dataclass(frozen=True)
class EquityStrategyCandidate:
    strategy_id: str
    candidate_id: str
    definition: EquityStrategyDefinition
    source_root: Path

    def __post_init__(self):
        from strategy_manager import CandidateKey
        CandidateKey(self.strategy_id, self.candidate_id)
        if type(self.definition) is not EquityStrategyDefinition:
            raise TypeError('typed equity definition required')
        object.__setattr__(self, 'source_root', Path(self.source_root).resolve())
        self.verify()

    @property
    def key(self):
        from strategy_manager import CandidateKey
        return CandidateKey(self.strategy_id, self.candidate_id)

    @property
    def strategy_family_id(self):
        return self.strategy_id

    @property
    def instrument(self):
        return self.definition.instrument

    @property
    def execution_spec_hash(self):
        return self.definition.execution_spec.fingerprint

    @property
    def warmup_bars(self):
        return self.definition.warmup_bars

    @property
    def implementation_hash(self):
        return self.content_identity.content_sha256

    @property
    def content_identity(self):
        return self.definition.content_identity

    @property
    def payload(self):
        return {'runtime': {'kind': 'ACCOUNT_REPLAY' if self.definition.contract_version == 4 else 'US_EQUITY', 'contract_version': self.definition.contract_version,
                            'source_files': self.definition.source_files, 'source_sha256': self.definition.source_sha256},
                'equity_definition': self.definition.to_dict()}

    def verify(self):
        for asset in self.definition.frozen_assets:
            asset.resolve(self.source_root)
        digest, sources = _read_equity_sources(self.source_root, self.definition.source_files)
        if digest != self.definition.source_sha256:
            raise ValueError('equity source closure changed')
        for dep in self.definition.dependencies:
            if metadata.version(dep.name) != dep.version:
                raise ValueError(f'equity dependency version differs: {dep.name}')
        # Local code must be in the declared closure; external imports need a pinned distribution.
        distributions = _package_distributions()
        pinned = {x.name.replace('_', '-').lower() for x in self.definition.dependencies}
        modules = {n[:-3].replace('/', '.') for n in self.definition.source_files}
        functions = {}
        for name, content in sources.items():
            tree = ast.parse(content.decode('utf-8'), filename=name)
            if self.definition.contract_version == 4:
                _verify_decision_access(tree, name, self.definition)
            if self.definition.market_features:
                functions[name] = {node.name for node in tree.body if type(node) is ast.FunctionDef}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [x.name for x in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        package = name[:-3].replace('/', '.').split('.')[:-1]
                        base = package[:len(package) - node.level + 1]
                        module = '.'.join([*base, *([node.module] if node.module else [])])
                        imports = [module] if node.module else [module + '.' + x.name for x in node.names]
                        if any(x not in modules and x + '.__init__' not in modules for x in imports):
                            raise ValueError('relative import absent from equity source closure')
                        continue
                    imports = [node.module or '']
                else:
                    continue
                for module in imports:
                    top = module.split('.')[0]
                    if top in sys.stdlib_module_names or top == 'strategy_runtime':
                        continue
                    if top in {m.split('.')[0] for m in modules}:
                        raise ValueError('local imports must be relative for isolated loading')
                    if not any(x.replace('_', '-').lower() in pinned for x in distributions.get(top, ())):
                        raise ValueError(f'undeclared equity dependency: {top}')
        for feature in self.definition.market_features:
            module, function = feature.entrypoint.split(':')
            path = module.replace('.', '/')
            filename = path + '/__init__.py' if path + '/__init__.py' in sources else path + '.py'
            if function not in functions[filename]:
                raise ValueError('market feature is not a declared top-level function: ' + feature.entrypoint)

    def decide(self, context):
        if self.definition.contract_version != 2:
            raise ValueError('account replay requires the historical account step contract')
        if type(context) is not EquityDecisionContext or type(context.point) is not DecisionPoint:
            raise TypeError('equity decision requires a typed context and decision point')
        mode = self.definition.feedback_mode
        if mode == 'MARKET_INTENT':
            context = replace(context, portfolio=None)
        else:
            portfolio = context.portfolio
            if type(portfolio) is not EquityPortfolio:
                raise TypeError('confirmed execution requires a typed equity portfolio')
            if mode == 'CONFIRMED_CLOSED_CYCLE_V1':
                feedback = portfolio.closed_cycle_feedback
                if feedback is None:
                    raise ValueError('CLOSED_CYCLE_FEEDBACK_UNAVAILABLE')
                closed = feedback.latest
                if closed is not None:
                    if (closed.exit_interval.end > context.point.decision_at
                            or closed.exit_observed_through > context.point.observed_through):
                        raise ValueError('CAUSAL_TIME_VIOLATION: closed cycle is not yet available')
                    if (portfolio.quantity > 0 and portfolio.cycle_entry is not None
                            and closed.exit_interval.end > portfolio.cycle_entry):
                        raise ValueError('CAUSAL_TIME_VIOLATION: closed cycle overlaps current holding')
            elif portfolio.closed_cycle_feedback is not None:
                # Old definitions do not acquire new execution inputs implicitly.
                context = replace(context, portfolio=replace(portfolio, closed_cycle_feedback=None))
        if self.definition.auxiliary_inputs or self.definition.session_context:
            from .equity_context import validate_equity_decision_context
            context = validate_equity_decision_context(self.definition, context)
        else:
            context = replace(context, auxiliary_histories=MappingProxyType({}),
                              session=None, session_available_at=None)
        return self._invoke(context)

    def account_step(self, context, state):
        from .account_strategy import AccountStepContext, AccountStepResult, AccountStrategyState
        from .replay_contracts import StrategyComputation
        if (self.definition.contract_version != 4 or self.definition.computation is not StrategyComputation.STATEFUL_STEP
                or type(context) is not AccountStepContext or type(state) is not AccountStrategyState):
            raise TypeError('V4 stateful implementation requires typed context and state')
        from .equity_source_runtime import active_invocation
        bound = active_invocation(self)
        if bound is None:
            raise RuntimeError('account strategy requires its loaded replay scope')
        result = bound.invoke(context, state)
        if type(result) is not AccountStepResult:
            raise TypeError('account strategy must return AccountStepResult')
        self.definition.state_schema.validate_record(result.account, scope='account')
        if result.cycle_values is not None:
            self.definition.state_schema.validate_record(result.cycle_values, scope='cycle')
        return result

    def calculate_account_batch(self, context):
        from .account_strategy import BatchAccountContext, AccountDecision
        from .replay_contracts import StrategyComputation
        if (self.definition.contract_version != 4 or self.definition.computation is not StrategyComputation.BATCH_HISTORY
                or type(context) is not BatchAccountContext):
            raise TypeError('V4 batch implementation requires typed observations')
        from .equity_source_runtime import active_invocation
        bound = active_invocation(self)
        if bound is None:
            raise RuntimeError('batch strategy requires its loaded replay scope')
        result = bound.invoke(context)
        if (type(result) is not tuple or len(result) != len(context.observations)
                or any(type(item) is not AccountDecision for item in result)):
            raise TypeError('batch strategy must return one AccountDecision per observation')
        return result

    def bind_replay(self, *, performance=None):
        from .equity_source_runtime import BoundEquityInvocation
        if self.definition.contract_version != 4:
            raise TypeError('bound strategy module scopes require explicit replay definitions')
        return BoundEquityInvocation(self, performance=performance)

    def _invoke(self, context):
        actual, sources = _read_equity_sources(self.source_root, self.definition.source_files)
        if actual != self.definition.source_sha256:
            raise ValueError('equity source closure changed during execution')
        namespace = '_equity_' + uuid4().hex
        package = types.ModuleType(namespace)
        package.__path__ = [str(self.source_root)]
        sys.modules[namespace] = package
        module_name, function = self.definition.entrypoint.split(':')
        root, manifest = self.source_root, self.definition.source_files

        class SourceLoader(importlib.machinery.SourceFileLoader):
            def get_code(self, fullname):
                name = Path(self.path).relative_to(root).as_posix()
                return _compiled_equity_source(sources[name], self.path)

        class SourceFinder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if not fullname.startswith(namespace + '.'):
                    return None
                relative = fullname[len(namespace) + 1:].replace('.', '/')
                package_name = relative + '/__init__.py'
                name = package_name if package_name in manifest else relative + '.py'
                if name not in manifest:
                    raise ImportError('import absent from equity source manifest')
                return importlib.util.spec_from_file_location(fullname, root / name,
                    loader=SourceLoader(fullname, str(root / name)),
                    submodule_search_locations=[str(root / relative)] if name == package_name else None)

        finder = SourceFinder()
        sys.meta_path.insert(0, finder)
        try:
            module = importlib.import_module(namespace + '.' + module_name)
            decision = getattr(module, function)(context)
            if type(decision) is not EquityDecision:
                raise TypeError('equity implementation must return EquityDecision')
            if decision.explanation is None:
                raise ValueError('formal equity decision requires a structured explanation snapshot')
            return decision
        finally:
            sys.meta_path.remove(finder)
            for name in tuple(sys.modules):
                if name == namespace or name.startswith(namespace + '.'):
                    del sys.modules[name]
