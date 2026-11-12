"""Explicit research application projections; no execution arithmetic."""
from dataclasses import dataclass
from functools import lru_cache

from dataflows import TimeInterval, InstrumentId as DataInstrumentId
from strategy_runtime import (EquityPortfolio, EquityClosedCycle, EquityClosedCycleFeedback,
                              PositionFeedback, PositionCycle, AccountSnapshot)
from strategy_runtime.account_strategy import RecognizedAccountEvent, RecognizedEventKind
from strategy_runtime.account_planning import AccountDecisionProposal
from strategy_runtime.replay_contracts import CycleBudget
from strategy_runtime.entry_cycle import EntryCyclePhase
from strategy_runtime.equity import ResearchExecutionSpec as StrategyExecutionSpec
from strategy_runtime.models import ExecutionPolicy as StrategyExecutionPolicy
from execution_channels.serialization import from_record, to_record
from execution_channels import contracts as ec
from execution_channels.instruments import InstrumentId
from execution_channels.policy import ResearchExecutionSpec, ExecutionPolicy
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import TradeIntent, DecisionExplanation


@dataclass(frozen=True, slots=True, eq=False)
class _IdentityKey:
    """Bounded cache key for immutable contracts; retain exact numeric spelling."""
    value: object

    def __hash__(self):
        return id(self.value)

    def __eq__(self, other):
        return type(other) is _IdentityKey and self.value is other.value


@lru_cache(maxsize=128)
def _execution_spec(key):
    return from_record(ResearchExecutionSpec, to_record(key.value))


@lru_cache(maxsize=128)
def _execution_instrument(key):
    return from_record(InstrumentId, to_record(key.value))


@lru_cache(maxsize=128)
def _execution_policy(key):
    if type(key.value) is not StrategyExecutionPolicy:
        raise TypeError('execution projection requires the strategy execution policy')
    return from_record(ExecutionPolicy, to_record(key.value))


def execution_spec(spec):
    if type(spec) is not StrategyExecutionSpec:
        raise TypeError('execution projection requires the strategy execution specification')
    return _execution_spec(_IdentityKey(spec))


def execution_instrument(instrument):
    if type(instrument) is not DataInstrumentId:
        raise TypeError('execution projection requires a data instrument')
    return _execution_instrument(_IdentityKey(instrument))


def session_execution_plan(proposal, portfolio, state):
    from execution_channels.planning.session import SessionProposal, plan_session_decision
    fields = {key: to_record(getattr(proposal, key)) for key in (
        'strategy', 'point', 'signal_date', 'signal_identity', 'references',
        'input_identities', 'price_identities', 'execution_policy')}
    fields.update(target_position=proposal.signal.target_position,
        cycle_target=to_record(proposal.signal.cycle_target), evidence=to_record(proposal.signal.evidence))
    return plan_session_decision(from_record(SessionProposal, fields), portfolio, state)


def strategy_portfolio(value):
    if type(value) is not ec.EquityPortfolio:
        raise TypeError('strategy projection requires an execution portfolio')
    feedback = value.closed_cycle_feedback
    if feedback is not None:
        latest = feedback.latest
        if latest is not None:
            latest = EquityClosedCycle(latest.cycle_id,
                TimeInterval(latest.entry_interval.start, latest.entry_interval.end),
                TimeInterval(latest.exit_interval.start, latest.exit_interval.end),
                latest.entry_quantity, latest.entry_cost, latest.exit_observed_through)
        feedback = EquityClosedCycleFeedback(latest)
    return EquityPortfolio(value.cash, value.quantity, value.receivable, value.revision,
        value.cycle_entry, value.cycle_cost, value.feedback_source, feedback)


def strategy_snapshot(value, instrument):
    if type(value) is not ec.AccountSnapshot:
        raise TypeError('strategy projection requires an execution account snapshot')
    return AccountSnapshot(instrument, value.currency, value.as_of, value.revision,
        value.cash, value.available_cash, value.receivable, value.quantity, value.sellable_quantity)


def strategy_position(value):
    if value is None:
        return None
    if type(value) is not ec.PositionCycle:
        raise TypeError('strategy projection requires an execution position')
    return PositionCycle(value.cycle_id,
        TimeInterval(value.entry_interval.start, value.entry_interval.end),
        TimeInterval(value.last_fill_interval.start, value.last_fill_interval.end),
        value.quantity, value.buy_cost, value.sell_income, value.fees, value.buy_fills, value.sell_fills)


def strategy_feedback(value):
    if type(value) is not ec.PositionFeedback:
        raise TypeError('strategy projection requires execution position feedback')
    return PositionFeedback(strategy_position(value.active), strategy_position(value.latest_closed))


def strategy_budget(value):
    if value is None:
        return None
    if type(value) is not ec.CycleBudget:
        raise TypeError('strategy projection requires an execution cycle budget')
    return CycleBudget(value.cycle_id, value.target_quantity, value.allocation_fraction,
        value.cash_budget, value.buy_cost_including_fees, EntryCyclePhase(value.phase.value))


def strategy_events(values):
    if type(values) is not tuple or any(type(value) is not ec.RecognizedAccountEvent for value in values):
        raise TypeError('strategy projection requires execution account events')
    return tuple(RecognizedAccountEvent(value.event_id, RecognizedEventKind(value.kind.value),
        value.effective_at, value.quantity_before, value.quantity_after,
        value.cash_delta, value.receivable_delta, value.reason) for value in values)


def execution_plan(result, snapshot, specification, *, owner, implementation, fee_rate, sell_remainder_policy, reference_price, execution_policy, cycle_budget=None, locked_quantity=None, previous_daily_execution=None, execution_interval=None):
    if type(result) is not AccountDecisionProposal or type(snapshot) is not AccountSnapshot:
        raise TypeError('execution projection requires a typed strategy proposal and account snapshot')
    if cycle_budget is not None and type(cycle_budget) not in (ec.CycleBudget, CycleBudget):
        raise TypeError('execution projection requires a typed cycle budget')
    decision, point = result.proposal.decision, result.point
    intent = TradeIntent(decision.target, DecisionExplanation(decision.explanation.to_dict()))
    execution_point = ec.ReplayPoint(point.observed_through, point.decision_at,
        point.execution_start, point.execution_end, point.session_id, ec.ExecutionPrecision(point.precision.value))
    account = ec.AccountSnapshot(execution_instrument(snapshot.instrument), snapshot.currency,
        snapshot.as_of, snapshot.revision, snapshot.cash, snapshot.available_cash,
        snapshot.receivable, snapshot.quantity, snapshot.sellable_quantity)
    # Historical snapshots already carry the EC-owned immutable budget.
    if cycle_budget is not None and type(cycle_budget) is not ec.CycleBudget:
        cycle_budget = ec.CycleBudget(cycle_budget.cycle_id, cycle_budget.target_quantity,
            cycle_budget.allocation_fraction, cycle_budget.cash_budget,
            cycle_budget.buy_cost_including_fees, ec.EntryCyclePhase(cycle_budget.phase.value))
    return plan_account_decision(intent, execution_point, account, reference_price,
        execution_spec(specification), owner=owner, implementation=implementation,
        fee_rate=fee_rate, sell_remainder_policy=ec.SellRemainderPolicy(sell_remainder_policy),
        execution_policy=_execution_policy(_IdentityKey(execution_policy)),
        cycle_budget=cycle_budget,
        locked_quantity=locked_quantity, suppressed=result.suppressed,
        previous_daily_execution=previous_daily_execution, execution_interval=execution_interval)
