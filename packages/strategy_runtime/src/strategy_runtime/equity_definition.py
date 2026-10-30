"""Portable, explicitly versioned equity strategy source and decision contracts."""
from dataclasses import asdict, dataclass, replace, field
from datetime import datetime
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
                      TradingSession)
from .identity import CandidateContentIdentity, ImplementationDependency
from .models import canonical_sha256
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
    analysis_price: str = 'RAW'

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
        if self.analysis_price != 'RAW':
            raise ValueError('auxiliary inputs require RAW prices')
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
                     EquityQuery(product, start, end, self.frequency, PriceAdjustment.NONE))
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
    """Finer raw execution quotations; never strategy observations."""
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
        return tuple(EquityDataRequest(self.instrument,self.source,EquityQuery(product,start,end,self.frequency))
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


@dataclass(frozen=True)
class EquityInputBinding:
    prepared: PreparedDataRef
    instrument: InstrumentId
    specification_hash: str
    content_identities: tuple[tuple[str, str], ...]
    warmup_bars: int
    auxiliary_inputs: tuple[EquityAuxiliaryBinding, ...] = ()
    execution_input: ExecutionInputBinding | None = None

    def to_dict(self):
        result = asdict(self)
        result['prepared']['space_id'] = str(self.prepared.space_id)
        result['prepared']['preparation_id'] = str(self.prepared.preparation_id)
        if not self.auxiliary_inputs:
            result.pop('auxiliary_inputs')
        if self.execution_input is None:
            result.pop('execution_input')
        return result

    @property
    def expected_identities(self):
        result = dict(self.content_identities)
        for binding in self.auxiliary_inputs:
            result[binding.input.data_key(EquityProduct.BARS)] = binding.bars_sha256
            result[binding.input.data_key(EquityProduct.SESSIONS)] = binding.sessions_sha256
        if self.execution_input is not None:
            for product,fingerprint in ((EquityProduct.BARS,self.execution_input.bars_sha256),(EquityProduct.SESSIONS,self.execution_input.sessions_sha256)):
                result[self.execution_input.input.data_key(product)] = fingerprint
        return MappingProxyType(result)

    def request_key(self, request: EquityDataRequest) -> str:
        if type(request) is not EquityDataRequest:
            raise TypeError('equity binding requires a typed request')
        p = request.parameters
        execution = self.execution_input
        if execution is not None and (execution.input.instrument,execution.input.source,execution.input.frequency)==(p.instrument,p.source,p.query.frequency):
            if p.query.adjustment is not PriceAdjustment.NONE:
                raise ValueError('execution quotations must be RAW')
            return execution.input.data_key(p.query.product)
        matches = [b.input for b in self.auxiliary_inputs if
                   (b.input.instrument, b.input.source, b.input.frequency) ==
                   (p.instrument, p.source, p.query.frequency)]
        if matches:
            if len(matches) != 1 or p.query.adjustment is not PriceAdjustment.NONE:
                raise ValueError('ambiguous or adjusted auxiliary request')
            return matches[0].data_key(p.query.product)
        if p.instrument != self.instrument or p.query.product.name.lower() not in dict(self.content_identities):
            raise ValueError('request is absent from equity input binding')
        return p.query.product.name.lower()

    @classmethod
    def from_dict(cls, value):
        from uuid import UUID
        value = dict(value)
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
        return cls(**value)

    def __post_init__(self):
        if type(self.auxiliary_inputs) is not tuple or any(type(x) is not EquityAuxiliaryBinding for x in self.auxiliary_inputs):
            raise TypeError('typed auxiliary bindings required')
        if self.execution_input is not None and (type(self.execution_input) is not ExecutionInputBinding or self.execution_input.input.instrument!=self.instrument):
            raise ValueError('execution binding differs from traded instrument')
        if self.execution_input is not None and any((x.input.instrument,x.input.source,x.input.frequency)==(self.execution_input.input.instrument,self.execution_input.input.source,self.execution_input.input.frequency) for x in self.auxiliary_inputs):
            raise ValueError('execution binding duplicates an auxiliary role')
        if len({x.input.name for x in self.auxiliary_inputs}) != len(self.auxiliary_inputs):
            raise ValueError('duplicate auxiliary alias')
        products = [(x.input.instrument, x.input.source, x.input.frequency) for x in self.auxiliary_inputs]
        if len(set(products)) != len(products):
            raise ValueError('duplicate auxiliary product request')
        if type(self.prepared) is not PreparedDataRef or type(self.instrument) is not InstrumentId:
            raise TypeError("equity binding requires prepared data and instrument")
        if type(self.warmup_bars) is not int or self.warmup_bars < 1:
            raise ValueError("equity binding requires warmup")
        import re
        if not re.fullmatch("[a-f0-9]{64}", self.specification_hash):
            raise ValueError("invalid execution fingerprint")
        if {k for k, _ in self.content_identities} != {"bars", "sessions", "actions", "constraints"} or len(self.content_identities) != 4:
            raise ValueError("equity binding requires all four product identities")
        if any(not re.fullmatch("[a-f0-9]{64}", v) for _, v in self.content_identities):
            raise ValueError("invalid data content fingerprint")


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
    analysis_price: str = 'RAW'
    explanation_cases: tuple[str, ...] = ('flat', 'long')
    auxiliary_inputs: tuple[EquityAuxiliaryInput, ...] = ()
    session_context: bool = False
    feature_graph: object | None = None
    state_schema: object | None = None
    computation: object | None = None
    execution_input: ExecutionInput | None = None
    initial_account: object | None = None

    def __post_init__(self):
        import re
        if type(self.contract_version) is not int or self.contract_version not in (2, 4) or type(self.execution_spec) is not ResearchExecutionSpec:
            raise ValueError("unsupported equity definition contract")
        if self.contract_version == 4:
            from .equity_features import FeatureGraph
            from .equity_replay import StrategyStateSchema
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
            if any((x.instrument,x.source,x.frequency)==(self.execution_input.instrument,self.execution_input.source,self.execution_input.frequency) for x in self.auxiliary_inputs):
                raise ValueError('execution quotation request duplicates an auxiliary role')
        if self.contract_version!=4 and any(x.instrument.market is not MarketId.US for x in self.auxiliary_inputs):
            raise ValueError('legacy auxiliary input contract supports US only')

        self.execution_spec.require_instrument(self.instrument)
        if type(self.session_context) is not bool:
            raise TypeError('session_context requires bool')
        if type(self.auxiliary_inputs) is not tuple or any(type(x) is not EquityAuxiliaryInput for x in self.auxiliary_inputs):
            raise TypeError('typed auxiliary inputs required')
        if self.contract_version != 4 and (self.auxiliary_inputs or self.session_context) and self.instrument.market is not MarketId.US:
            raise ValueError('auxiliary and session context currently require US market')
        if len({x.name for x in self.auxiliary_inputs}) != len(self.auxiliary_inputs):
            raise ValueError('duplicate auxiliary alias')
        identities = [(x.instrument, x.source, x.frequency) for x in self.auxiliary_inputs]
        if len(set(identities)) != len(identities):
            raise ValueError('duplicate auxiliary product request')
        if any(x.instrument == self.instrument and x.frequency == self.execution_spec.decision_clock for x in self.auxiliary_inputs):
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
        if self.feedback_mode not in {'MARKET_INTENT', 'CONFIRMED_EXECUTION', 'CONFIRMED_CLOSED_CYCLE_V1'} or self.analysis_price != 'RAW':
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

    @cached_property
    def content_identity(self):
        return CandidateContentIdentity(canonical_sha256(self.to_dict()), self.source_sha256,
                                        canonical_sha256([asdict(x) for x in self.dependencies]))

    @property
    def parameters(self):
        return _freeze(json.loads(self.parameters_json))

    def to_dict(self):
        result = {"runtime_kind": "ACCOUNT_REPLAY" if self.contract_version == 4 else "US_EQUITY", **asdict(self)}
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
        value['source_files'] = tuple(value['source_files'])
        value['dependencies'] = tuple(ImplementationDependency(**x) for x in value['dependencies'])
        value['auxiliary_inputs'] = tuple(EquityAuxiliaryInput.from_dict(x) for x in value.get('auxiliary_inputs', ()))
        if value.get('contract_version', 2) == 4:
            from .equity_features import FeatureGraph
            from .equity_replay import StrategyStateSchema
            value['feature_graph'] = FeatureGraph.from_dict(value['feature_graph'])
            value['state_schema'] = StrategyStateSchema.from_dict(value['state_schema'])
        if value.get('execution_input') is not None:
            value['execution_input'] = ExecutionInput.from_dict(value['execution_input'])
        if value.get('initial_account') is not None:
            from .equity_replay import StateRecord
            value['initial_account'] = StateRecord.from_dict(value['initial_account'])
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
        if equity_source_hash(self.source_root, self.definition.source_files) != self.definition.source_sha256:
            raise ValueError('equity source closure changed')
        for dep in self.definition.dependencies:
            if metadata.version(dep.name) != dep.version:
                raise ValueError(f'equity dependency version differs: {dep.name}')
        # Local code must be in the declared closure; external imports need a pinned distribution.
        distributions = _package_distributions()
        pinned = {x.name.replace('_', '-').lower() for x in self.definition.dependencies}
        modules = {n[:-3].replace('/', '.') for n in self.definition.source_files}
        for name in self.definition.source_files:
            for node in ast.walk(ast.parse((self.source_root / name).read_text(encoding='utf-8'))):
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

    def bind_replay(self):
        from .equity_source_runtime import BoundEquityInvocation
        if self.definition.contract_version != 4:
            raise TypeError('bound strategy module scopes require explicit replay definitions')
        return BoundEquityInvocation(self)

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
