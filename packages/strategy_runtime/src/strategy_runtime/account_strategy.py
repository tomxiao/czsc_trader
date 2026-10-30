"""V4 market-neutral strategy decisions and confirmed position feedback."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Mapping
import math
from enum import StrEnum
from dataflows import TimeInterval, TradingSession
from .signal_explanation import SignalExplanationSnapshot
from .replay_contracts import AccountSnapshot, ReplayOrder, ReplayLeg, CycleBudget
from .equity import EquityPortfolio, DecisionPoint
from .equity_replay import StateRecord, StrategyState
from .equity_features import FeatureView, HistoryView


class RecognizedEventKind(StrEnum):
    SPLIT = 'SPLIT'
    CASH_DIVIDEND = 'CASH_DIVIDEND'
    DIVIDEND_PAYMENT = 'DIVIDEND_PAYMENT'
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
    ratio: float | None = None

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
        if self.kind is RecognizedEventKind.SPLIT:
            if type(self.ratio) not in (int,float) or not math.isfinite(self.ratio) or self.ratio<=0:
                raise ValueError('recognized split requires its confirmed ratio')
        elif self.ratio is not None:
            raise ValueError('only recognized splits declare a unit ratio')


@dataclass(frozen=True, slots=True)
class AccountStrategyState(StrategyState):
    event_cursor: int = 0

    def __post_init__(self):
        StrategyState.__post_init__(self)
        if type(self.event_cursor) is not int or self.event_cursor<0:
            raise ValueError('account event cursor must be a nonnegative integer')


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
    orders: tuple[ReplayOrder, ...] = ()
    legs: tuple[ReplayLeg, ...] = ()
    capital_mode: str = 'target_equity_fraction'
    cycle_before: CycleBudget | None = None
    cycle_after: CycleBudget | None = None

    def __post_init__(self):
        if type(self.target) not in (float, int) or not math.isfinite(self.target) or not 0 <= self.target <= 1:
            raise ValueError('account target must be finite in [0,1]')
        if type(self.explanation) is not SignalExplanationSnapshot:
            raise TypeError('account decisions require structured explanation')
        if type(self.orders) is not tuple or any(type(x) is not ReplayOrder for x in self.orders):
            raise TypeError('account orders require ReplayOrder tuple')
        if type(self.legs) is not tuple or any(type(x) is not ReplayLeg for x in self.legs):
            raise TypeError('account legs require ReplayLeg tuple')
        if self.orders and self.legs:
            raise ValueError('orders and dependency legs are mutually exclusive')
        if self.capital_mode not in ('target_equity_fraction', 'signal_cash_fraction', 'full_available_cash'):
            raise ValueError('unsupported account capital mode')
        if any(x is not None and type(x) is not CycleBudget for x in (self.cycle_before, self.cycle_after)):
            raise TypeError('account cycle budgets require CycleBudget')
        if self.capital_mode != 'signal_cash_fraction' and any(x is not None for x in (self.cycle_before,self.cycle_after)):
            raise ValueError('cycle budgets require signal_cash_fraction')

    @classmethod
    def from_facts(cls, target, reason, *, facts, next_watch, **kwargs):
        from .equity_definition import EquityDecision
        base = EquityDecision.from_facts(int(target > 0), reason, facts=facts, next_watch=next_watch)
        return cls(target, base.explanation, **kwargs)


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
class AccountStepContext:
    point: DecisionPoint
    portfolio: EquityPortfolio
    account: AccountSnapshot
    position: PositionFeedback
    parameters: Mapping
    features: FeatureView
    history: HistoryView
    budget: CycleBudget | None = None
    events: tuple[RecognizedAccountEvent,...] = ()
    auxiliary_histories: Mapping = field(default_factory=dict)
    session: TradingSession | None = None
    session_available_at: datetime | None = None

    def __post_init__(self):
        from .equity_definition import _freeze
        from types import MappingProxyType
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

        if type(self.features) is not FeatureView or type(self.history) is not HistoryView:
            raise TypeError('account step requires immutable visible inputs')
        if self.features.as_of != self.point.decision_at or self.history.as_of != self.point.decision_at:
            raise ValueError('account views differ from decision time')
        if any(type(view) is not HistoryView or view.as_of!=self.point.decision_at for view in self.auxiliary_histories.values()):
            raise ValueError('auxiliary observations must belong to the current decision')
        if (self.session is None)!=(self.session_available_at is None):
            raise ValueError('session context requires calendar and availability together')
        if self.session is not None and (type(self.session) is not TradingSession or type(self.session_available_at) is not datetime
                or self.session_available_at.tzinfo is None or self.session_available_at>self.point.decision_at):
            raise ValueError('session context must already be available')
        object.__setattr__(self, 'parameters', _freeze(dict(self.parameters)))
        object.__setattr__(self, 'auxiliary_histories', MappingProxyType(dict(self.auxiliary_histories)))


@dataclass(frozen=True, slots=True)
class BatchObservation:
    point: DecisionPoint
    features: FeatureView
    history: HistoryView
    auxiliary_histories: Mapping = field(default_factory=dict)
    session: TradingSession | None = None
    session_available_at: datetime | None = None

    def __post_init__(self):
        if type(self.point) is not DecisionPoint or type(self.features) is not FeatureView or type(self.history) is not HistoryView:
            raise TypeError('batch observations require typed causal views')
        if self.features.as_of != self.point.decision_at or self.history.as_of != self.point.decision_at:
            raise ValueError('batch observation views differ from decision time')
        from types import MappingProxyType
        if any(type(view) is not HistoryView or view.as_of!=self.point.decision_at for view in self.auxiliary_histories.values()):
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
