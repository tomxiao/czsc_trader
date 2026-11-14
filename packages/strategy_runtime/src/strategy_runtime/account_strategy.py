"""V4 market-neutral strategy decisions and confirmed position feedback."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from collections.abc import Mapping
import math
from enum import StrEnum
from dataflows import TimeInterval, TradingSession
from .signal_explanation import SignalExplanationSnapshot
from .replay_contracts import AccountSnapshot, CycleBudget
from .equity import EquityPortfolio, DecisionPoint
from .equity_replay import StateRecord, StrategyState
from .equity_features import FeatureView, HistoryView
from .dataset_observations import TableHistoryView, TableObservationStatus
from .step_data import StepData


class RecognizedEventKind(StrEnum):
    POSITION_ADJUSTMENT = 'POSITION_ADJUSTMENT'
    SALE_SETTLEMENT = 'SALE_SETTLEMENT'


@dataclass(frozen=True, slots=True)
class RecognizedAccountEvent:
    event_id: str
    kind: RecognizedEventKind
    effective_at: datetime
    quantity_before: int
    quantity_after: int
    cash_delta: float
    receivable_delta: float
    reason: str = 'UNKNOWN'

    def __post_init__(self):
        if type(self.event_id) is not str or not self.event_id or type(self.kind) is not RecognizedEventKind:
            raise TypeError('recognized account event requires identity and typed kind')
        if type(self.effective_at) is not datetime or self.effective_at.tzinfo is None:
            raise TypeError('recognized event requires an aware effective time')
        for name in ('quantity_before','quantity_after'):
            if type(getattr(self,name)) is not int or getattr(self,name)<0:
                raise ValueError('recognized quantities require nonnegative integer units')
        for name in ('cash_delta','receivable_delta'):
            value=getattr(self,name)
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError('recognized event deltas must be finite')
        if self.reason not in {'UNKNOWN', 'TRADE_SETTLEMENT'}:
            raise ValueError('recognized event requires an explicit supported reason')
        if self.kind is RecognizedEventKind.POSITION_ADJUSTMENT and self.reason != 'UNKNOWN':
            raise ValueError('position adjustment cannot infer its cause')


@dataclass(frozen=True, slots=True)
class AccountStrategyState(StrategyState):
    event_cursor: int = 0

    def __post_init__(self):
        StrategyState.__post_init__(self)
        if type(self.event_cursor) is not int or self.event_cursor<0:
            raise ValueError('account event cursor must be a nonnegative integer')

    def to_dict(self):
        return {'revision': self.revision, 'account': self.account.to_dict(),
                'cycle': None if self.cycle is None else {
                    'cycle_id': self.cycle.cycle_id, 'entry_at': self.cycle.entry_at.isoformat(),
                    'values': self.cycle.values.to_dict()},
                'binding': self.binding, 'event_cursor': self.event_cursor}

    @classmethod
    def from_dict(cls, value):
        from .equity_replay import CycleState
        if type(value) is not dict or set(value) != {'revision', 'account', 'cycle', 'binding', 'event_cursor'}:
            raise ValueError('unsupported account strategy state')
        cycle = value['cycle']
        if cycle is not None:
            if type(cycle) is not dict or set(cycle) != {'cycle_id', 'entry_at', 'values'}:
                raise ValueError('unsupported account cycle state')
            cycle = CycleState(cycle['cycle_id'], datetime.fromisoformat(cycle['entry_at']),
                               StateRecord.from_dict(cycle['values']))
        return cls(value['revision'], StateRecord.from_dict(value['account']), cycle,
                   value['binding'], value['event_cursor'])


class SellRemainderPolicy(StrEnum):
    STRICT_STEP = 'STRICT_STEP'
    FULL_LIQUIDATION = 'FULL_LIQUIDATION'


@dataclass(frozen=True, slots=True)
class PositionCycle:
    cycle_id: str
    entry_interval: TimeInterval
    last_fill_interval: TimeInterval
    quantity: int
    buy_cost: float
    sell_income: float
    fees: float
    buy_fills: int
    sell_fills: int

    def __post_init__(self):
        if type(self.cycle_id) is not str or not self.cycle_id:
            raise ValueError('position cycle requires identity')
        if any(type(getattr(self, name)) is not TimeInterval for name in ('entry_interval', 'last_fill_interval')):
            raise TypeError('position cycle requires confirmed intervals')
        if self.entry_interval.start > self.last_fill_interval.start:
            raise ValueError('position fills are out of order')
        for name in ('quantity', 'buy_fills', 'sell_fills'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError('position counts must be nonnegative integers')
        for name in ('buy_cost', 'sell_income', 'fees'):
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError('position amounts must be finite nonnegative numbers')


@dataclass(frozen=True, slots=True)
class PositionFeedback:
    active: PositionCycle | None = None
    latest_closed: PositionCycle | None = None

    def __post_init__(self):
        if any(value is not None and type(value) is not PositionCycle for value in (self.active, self.latest_closed)):
            raise TypeError('position feedback requires typed cycles')
        if self.active is not None and self.active.quantity <= 0:
            raise ValueError('active cycle requires a holding')
        if self.latest_closed is not None and self.latest_closed.quantity != 0:
            raise ValueError('closed cycle must be flat')


@dataclass(frozen=True, slots=True)
class AccountDecision:
    target: float
    explanation: SignalExplanationSnapshot
    def __post_init__(self):
        if type(self.target) not in (float, int) or not math.isfinite(self.target) or not 0 <= self.target <= 1:
            raise ValueError('account target must be finite in [0,1]')
        if type(self.explanation) is not SignalExplanationSnapshot:
            raise TypeError('account decisions require structured explanation')

    @classmethod
    def from_facts(cls, target, reason, *, facts, next_watch):
        from .equity_definition import EquityDecision
        base = EquityDecision.from_facts(int(target > 0), reason, facts=facts, next_watch=next_watch)
        return cls(target, base.explanation)


@dataclass(frozen=True, slots=True)
class AccountStepResult:
    decision: AccountDecision
    account: StateRecord = field(default_factory=StateRecord)
    cycle_values: StateRecord | None = None

    def __post_init__(self):
        if type(self.decision) is not AccountDecision or type(self.account) is not StateRecord:
            raise TypeError('account step requires a typed decision and account state')
        if self.cycle_values is not None and type(self.cycle_values) is not StateRecord:
            raise TypeError('cycle state must be StateRecord')


@dataclass(frozen=True, slots=True)
class DecisionHistory:
    """Only the latest two observed bars and a constant-time count."""

    as_of: datetime
    _recent: tuple
    _count: int

    @classmethod
    def _from_history(cls, value: HistoryView):
        return cls(value.as_of, value._recent, len(value))

    def __len__(self):
        return self._count

    def last(self, offset: int = 0):
        if type(offset) is not int or offset not in (0, 1):
            raise ValueError('decision history exposes offsets zero and one; declare a market feature for a window')
        if offset >= len(self._recent):
            raise IndexError('requested recent observation is unavailable')
        return self._recent[offset]


@dataclass(frozen=True, slots=True)
class DecisionTable:
    """A bounded projection of table observations at the current decision."""

    as_of: datetime
    columns: tuple[str, ...]
    status: TableObservationStatus
    observation_count: int
    session_count: int
    latest_session: date | None
    _latest: tuple

    @classmethod
    def _from_table(cls, value: TableHistoryView):
        return cls(value.as_of, value.columns, value.status, value.observation_count,
                   value.session_count, value.latest_session, value._tail(1))

    def __len__(self):
        return self.observation_count

    def last(self):
        if not self._latest:
            raise IndexError('no visible table observation')
        return self._latest[0]


def _observation_views(values, when):
    from types import MappingProxyType
    if not isinstance(values, Mapping) or any(type(name) is not str or type(view) is not DecisionTable or view.as_of != when
                                            for name, view in values.items()):
        raise ValueError('table observations must belong to current decision')
    return MappingProxyType(dict(values))


class _MarketFeatureInput:
    __slots__ = ()

    def market_feature(self, name: str):
        """Read a named feature declared in the strategy definition."""
        if type(name) is not str or not name:
            raise TypeError('market_feature requires a declared feature name')
        if self._market_feature_provider is None:
            raise ValueError('undeclared market feature: ' + name)
        return self._market_feature_provider(name)


@dataclass(frozen=True, slots=True)
class AccountStepContext:
    point: DecisionPoint
    portfolio: EquityPortfolio
    account: AccountSnapshot
    position: PositionFeedback
    parameters: Mapping
    dfls: StepData
    budget: CycleBudget | None = None
    events: tuple[RecognizedAccountEvent,...] = ()
    session: TradingSession | None = None
    session_available_at: datetime | None = None

    def __post_init__(self):
        from .equity_definition import _freeze
        if type(self.point) is not DecisionPoint or type(self.portfolio) is not EquityPortfolio:
            raise TypeError('account step requires confirmed portfolio and point')
        if type(self.account) is not AccountSnapshot or type(self.position) is not PositionFeedback:
            raise TypeError('account step requires confirmed account and position feedback')
        if (self.account.as_of>self.point.decision_at or self.account.revision!=self.portfolio.revision
                or self.account.quantity!=self.portfolio.quantity):
            raise ValueError('account feedback differs from the confirmed decision point')
        for cycle in (self.position.active,self.position.latest_closed):
            if cycle is not None and cycle.last_fill_interval.end>self.point.decision_at:
                raise ValueError('position feedback contains future fills')

        if self.budget is not None and type(self.budget) is not CycleBudget:
            raise TypeError('budget feedback requires CycleBudget')
        if type(self.events) is not tuple or any(type(event) is not RecognizedAccountEvent for event in self.events):
            raise TypeError('recognized event feedback requires immutable typed events')
        if any(event.effective_at>self.point.decision_at for event in self.events):
            raise ValueError('recognized event feedback contains future facts')

        if type(self.dfls) is not StepData:
            raise TypeError('account step requires a scoped DFLS reader')
        if (self.session is None)!=(self.session_available_at is None):
            raise ValueError('session context requires calendar and availability together')
        if self.session is not None and (type(self.session) is not TradingSession or type(self.session_available_at) is not datetime
                or self.session_available_at.tzinfo is None or self.session_available_at>self.point.decision_at):
            raise ValueError('session context must already be available')
        object.__setattr__(self, 'parameters', _freeze(dict(self.parameters)))


@dataclass(frozen=True, slots=True)
class BatchObservation(_MarketFeatureInput):
    point: DecisionPoint
    features: FeatureView
    history: DecisionHistory
    auxiliary_histories: Mapping = field(default_factory=dict)
    session: TradingSession | None = None
    session_available_at: datetime | None = None
    observations: Mapping[str, DecisionTable] = field(default_factory=dict)
    _market_feature_provider: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'observations', _observation_views(self.observations, self.point.decision_at))
        if type(self.point) is not DecisionPoint or type(self.features) is not FeatureView or type(self.history) is not DecisionHistory:
            raise TypeError('batch observations require typed causal views')
        if self.features.as_of != self.point.decision_at or self.history.as_of != self.point.decision_at:
            raise ValueError('batch observation views differ from decision time')
        from types import MappingProxyType
        if any(type(view) is not DecisionHistory or view.as_of!=self.point.decision_at for view in self.auxiliary_histories.values()):
            raise ValueError('batch auxiliary observations differ from decision time')
        if (self.session is None)!=(self.session_available_at is None):
            raise ValueError('batch session requires declared availability')
        if self.session is not None and (type(self.session) is not TradingSession or type(self.session_available_at) is not datetime
                or self.session_available_at.tzinfo is None or self.session_available_at>self.point.decision_at):
            raise ValueError('batch session is not yet available')
        object.__setattr__(self,'auxiliary_histories',MappingProxyType(dict(self.auxiliary_histories)))



@dataclass(frozen=True, slots=True)
class BatchAccountContext:
    observations: tuple[BatchObservation, ...]
    parameters: Mapping

    def __post_init__(self):
        from .equity_definition import _freeze
        if type(self.observations) is not tuple or any(type(x) is not BatchObservation for x in self.observations):
            raise TypeError('batch context requires an immutable observation sequence')
        if any(a.point.decision_at >= b.point.decision_at for a,b in zip(self.observations,self.observations[1:])):
            raise ValueError('batch observations must be strictly ordered')
        object.__setattr__(self, 'parameters', _freeze(dict(self.parameters)))
