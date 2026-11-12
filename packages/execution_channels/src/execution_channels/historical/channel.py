"""Historical channel lifecycle over already-prepared execution facts.

No data fetch, strategy callback, or application storage is accepted here.
Adoption records intent/state; advance confirms modeled execution separately.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from bisect import bisect_right

import pandas as pd

from ..contracts import (AccountExecutionPlan, AccountSnapshot, EquityPortfolio,
                         PositionFeedback, RecognizedAccountEvent, CycleBudget)
from ..instruments import InstrumentId
from ..daily_execution import PreviousDailyExecution, daily_execution_outcome
from ..execution_effects import DecisionExecutionEffect, OrderExecutionEffect, decision_execution_effect
from ..state import AccountStrategyState, CycleState, StateRecord
from .portfolio import PortfolioHistoricalExecutor
from .input_facts import normalize_constraint_times


class AdoptionStatus(StrEnum):
    ADOPTED = 'ADOPTED'
    ALREADY_ADOPTED = 'ALREADY_ADOPTED'
    STALE_SNAPSHOT = 'STALE_SNAPSHOT'
    BLOCKED = 'BLOCKED'


@dataclass(frozen=True, slots=True)
class HistoricalDecision:
    plan: AccountExecutionPlan
    expected_state_revision: int
    account_values: StateRecord
    cycle_values: StateRecord | None
    next_event_cursor: int
    state_binding: str

    def __post_init__(self):
        if type(self.plan) is not AccountExecutionPlan or type(self.account_values) is not StateRecord:
            raise TypeError('historical decision requires an execution plan and typed state')
        if self.cycle_values is not None and type(self.cycle_values) is not StateRecord:
            raise TypeError('historical pending cycle must be typed')
        if any(type(value) is not int or value < 0 for value in (self.expected_state_revision,self.next_event_cursor)):
            raise ValueError('historical decision revisions must be nonnegative integers')
        if type(self.state_binding) is not str or not self.state_binding:
            raise ValueError('historical decision requires an owning state binding')


@dataclass(frozen=True, slots=True)
class HistoricalSnapshot:
    account: AccountSnapshot
    portfolio: EquityPortfolio
    position: PositionFeedback
    strategy: AccountStrategyState
    budget: CycleBudget | None
    locked_quantity: int | None
    events: tuple[RecognizedAccountEvent, ...]
    next_event_cursor: int


@dataclass(frozen=True, slots=True)
class HistoricalAdvance:
    processed_through: datetime
    completed_plan: str | None


class HistoricalReplayChannel:
    channel_id = 'historical_replay'

    def __init__(self, *, account_id, instrument, specification, initial_cash, fee_rate,
                 bars, constraints, execution_bars=None, initial_account=None):
        if type(account_id) is not str or not account_id or type(instrument) is not InstrumentId:
            raise TypeError('historical channel requires account and instrument identities')
        specification.require_instrument(instrument)
        if not isinstance(bars, pd.DataFrame) or not isinstance(constraints, pd.DataFrame):
            raise TypeError('historical channel requires prepared execution frames')
        if (not {'BarStart','Date'}.issubset(bars.columns) or 'Date' not in constraints
                or bars.BarStart.duplicated().any() or constraints.Date.duplicated().any()):
            raise ValueError('historical execution facts require unique interval identities')
        self.account_id, self.instrument = account_id, instrument
        self._bars = {row['BarStart']: row for row in bars.to_dict('records')}
        rows = tuple(normalize_constraint_times(row) for row in constraints.to_dict('records'))
        self._constraints = {row['Date']: row for row in rows}
        if len(self._constraints) != len(rows):
            raise ValueError('historical execution constraints contain duplicate normalized dates')
        if set(self._bars) - set(self._constraints):
            raise ValueError('historical execution constraints do not cover bars')
        self._ends = tuple(sorted(row['Date'] for row in self._bars.values()))
        self._end_set = frozenset(self._ends)
        self.executor = PortfolioHistoricalExecutor(specification=specification,
            initial_cash=initial_cash, fee_rate=fee_rate,
            price_basis='HFQ', execution_bars=execution_bars)
        self.state = AccountStrategyState(account=StateRecord() if initial_account is None else initial_account)
        self._pending = None
        self._pending_before_state = None
        self._adopted = {}
        self._clock = None
        self._failed = False

    @classmethod
    def from_executor(cls, executor, *, account_id, instrument, bars, constraints,
                      initial_state=None):
        """Bind prepared execution facts without fetching or creating a second account."""
        if type(executor) is not PortfolioHistoricalExecutor:
            raise TypeError('historical channel requires its own execution account')
        if type(account_id) is not str or not account_id or type(instrument) is not InstrumentId:
            raise TypeError('historical channel requires account and instrument identities')
        executor.spec.require_instrument(instrument)
        value = object.__new__(cls)
        value.account_id, value.instrument, value.executor = account_id, instrument, executor
        value._bars = {row['BarStart']: row for row in bars}
        rows = tuple(normalize_constraint_times(row) for row in constraints)
        value._constraints = {row['Date']: row for row in rows}
        if len(value._bars) != len(bars) or len(value._constraints) != len(constraints):
            raise ValueError('historical inputs contain duplicate interval identities')
        if set(value._bars) - set(value._constraints):
            raise ValueError('historical constraints do not cover execution observations')
        value._ends = tuple(sorted(row['Date'] for row in value._bars.values()))
        value._end_set = frozenset(value._ends)
        value.state = AccountStrategyState() if initial_state is None else initial_state
        if type(value.state) is not AccountStrategyState:
            raise TypeError('historical account requires channel-owned strategy state')
        value._pending, value._clock, value._failed = None, None, False
        value._pending_before_state = None
        value._adopted = {}
        return value

    def _account(self, account_id):
        if account_id != self.account_id:
            raise ValueError('historical account belongs to a different channel instance')

    def advance(self, to: datetime) -> HistoricalAdvance:
        if type(to) is not datetime or to.utcoffset() is None:
            raise TypeError('historical clock requires an aware datetime')
        if self._clock is not None and to < self._clock:
            raise ValueError('historical clock cannot move backwards')
        if self._failed:
            raise RuntimeError('failed historical channel requires an independent run')
        completed = None
        pending = self._pending
        if pending is not None and pending.plan.point.execution_end <= to:
            plan = pending.plan
            try:
                # Modeled fills become confirmed together with their validated
                # interval result. Earlier intervals remain committed.
                with self.executor.transaction():
                    before_revision = self.executor.revision
                    after = self.executor.execute_account_plan(plan, self._bars[plan.point.execution_start],
                        constraint=self._constraints[plan.point.execution_start])
                    if (after.revision != before_revision + 1
                            or self.executor.revision != after.revision):
                        raise ValueError('historical execution must advance revision once')
                    cycle = None
                    if after.quantity:
                        if pending.cycle_values is None:
                            raise ValueError('confirmed holding requires explicit cycle state')
                        cycle = CycleState(self.executor.cycle, after.cycle_entry, pending.cycle_values)
                self.state = AccountStrategyState(self.state.revision, self.state.account, cycle,
                    self.state.binding, self.state.event_cursor)
            except BaseException:
                # This interval did not confirm; restore its strategy adoption
                # while preserving every preceding confirmed interval.
                self.state = self._pending_before_state
                self._adopted.pop(plan.plan_identity)
                self._failed = True
                raise
            completed = plan.plan_identity
            self._pending = None
            self._pending_before_state = None
        self._clock = to
        return HistoricalAdvance(to, completed)

    def decision_execution_effect(self, plan_identity: str, *, valuation_price: Decimal | float,
                                  at: datetime) -> DecisionExecutionEffect:
        """Read current confirmed account/decision facts at the channel clock."""
        if self._clock != at or self._failed:
            raise ValueError('historical execution effect requires its current unfailed clock')
        proposal = self._adopted[plan_identity]
        plan = proposal.plan
        evidence = plan.evidence
        orders = [x for x in self.executor.rows['orders'] if x['decision_id'] == plan_identity]
        effects = []
        if plan_identity not in self.executor.completed:
            instructions = tuple(x.order for x in plan.legs) if plan.legs else plan.orders
            effects = [OrderExecutionEffect(f'{plan_identity}:{i}', order.side.value, order.quantity,
                0, 'PENDING', True) for i, order in enumerate(instructions)]
        else:
            for row in orders:
                filled = row['quantity'] if row['status'] == 'FILLED' else 0
                effects.append(OrderExecutionEffect(row['order_id'], row['side'], row['quantity'], filled,
                    row['status'], False, reason=None if filled else row['reason']))
        return decision_execution_effect(decision_id=plan_identity, at=at,
            target_weight=evidence['target'], planning_result=evidence['planning_result'],
            actual_quantity=self.executor.quantity, cash=self.executor.cash, available_cash=self.executor.cash,
            receivable=self.executor.receivable, valuation_price=valuation_price, orders=tuple(effects))

    def previous_daily_execution(self, account_id: str, *, at: datetime) -> PreviousDailyExecution | None:
        self._account(account_id)
        if self._clock != at or self._pending is not None or self._failed:
            raise ValueError('daily execution history requires the current confirmed channel clock')
        prior = next((row for row in reversed(self.executor.rows['decisions'])
                      if row['signal_status'] == 'EVALUATED'), None)
        if prior is None:
            return None
        filled = 0
        if prior['quantity']:
            for order in reversed(self.executor.rows['orders']):
                if order['decision_id'] != prior['decision_id']:
                    break
                if order['status'] == 'FILLED':
                    filled += order['quantity']
        index = bisect_right(self._ends, at)
        entry_cash = prior['plan']['evidence'].get('entry_cash')
        active = self.executor.position_feedback.active if entry_cash is not None else None
        return PreviousDailyExecution(prior['target'],
            daily_execution_outcome(prior['quantity'], filled, terminal=True),
            index > 0 and prior['execution_end'] == self._ends[index - 1],
            None if entry_cash is None else Decimal(entry_cash),
            Decimal(0) if active is None else Decimal(str(active.buy_cost)))

    def snapshot(self, account_id: str, *, at: datetime,
                 observed_through: datetime | None = None) -> HistoricalSnapshot:
        self._account(account_id)
        if self._failed or self._clock != at or self._pending is not None:
            raise RuntimeError('historical snapshot requires an advanced, unblocked clock')
        if not self._ends or self._ends[0] > at:
            raise ValueError('historical snapshot has no completed reference observation')
        reference = self._ends[bisect_right(self._ends, at) - 1] if observed_through is None else observed_through
        if reference not in self._end_set or reference > at:
            raise ValueError('historical reference must identify a completed observation')
        portfolio = self.executor.snapshot_at(reference, at)
        events, cursor = self.executor.recognized_events_since(self.state.event_cursor, at)
        account = AccountSnapshot(self.instrument, self.instrument.currency, at, self.executor.revision,
            self.executor.cash, self.executor.cash, self.executor.receivable,
            self.executor.quantity, self.executor._sellable(at))
        return HistoricalSnapshot(account, portfolio, self.executor.position_feedback, self.state,
                                  self.executor.cycle_budget, self.executor.locked_quantity, events, cursor)

    def adopt(self, account_id: str, proposal: HistoricalDecision) -> AdoptionStatus:
        self._account(account_id)
        if type(proposal) is not HistoricalDecision:
            raise TypeError('historical adoption requires a typed decision')
        plan = proposal.plan
        previous = self._adopted.get(plan.plan_identity)
        if previous is not None:
            if previous != proposal:
                raise ValueError('historical plan identity was reused with different content')
            return AdoptionStatus.ALREADY_ADOPTED
        if self._failed or self._pending is not None or self._clock != plan.point.decision_at:
            return AdoptionStatus.BLOCKED
        if (plan.expected_revision != self.executor.revision
                or proposal.expected_state_revision != self.state.revision):
            return AdoptionStatus.STALE_SNAPSHOT
        if plan.point.execution_start not in self._bars:
            raise ValueError('historical plan has no prepared execution interval')
        if self._bars[plan.point.execution_start]['Date'] != plan.point.execution_end:
            raise ValueError('historical plan differs from prepared interval')
        if self.state.binding not in (None, proposal.state_binding):
            raise ValueError('historical strategy state belongs to another implementation')
        if proposal.next_event_cursor < self.state.event_cursor:
            raise ValueError('historical event cursor cannot move backwards')
        if (self.executor.quantity or plan.target_quantity) and proposal.cycle_values is None:
            raise ValueError('holding or entry requires pending cycle state')
        cycle = None if self.state.cycle is None else CycleState(
            self.state.cycle.cycle_id, self.state.cycle.entry_at, proposal.cycle_values)
        state = AccountStrategyState(self.state.revision+1, proposal.account_values, cycle,
            proposal.state_binding, proposal.next_event_cursor)
        self._adopted[plan.plan_identity] = proposal
        self._pending_before_state = self.state
        self.state, self._pending = state, proposal
        return AdoptionStatus.ADOPTED

    def finish(self):
        if self._failed or self._pending is not None:
            raise RuntimeError('historical channel cannot finalize unresolved execution')
        return self.executor.finish()
