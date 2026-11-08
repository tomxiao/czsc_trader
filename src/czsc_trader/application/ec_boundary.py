"""Explicit research application projections; no execution arithmetic."""
from dataflows import TimeInterval
from strategy_runtime import EquityPortfolio, PositionFeedback, PositionCycle, AccountSnapshot
from strategy_runtime.account_strategy import RecognizedAccountEvent, RecognizedEventKind
from strategy_runtime.replay_contracts import CycleBudget
from strategy_runtime.entry_cycle import EntryCyclePhase
from execution_channels.serialization import from_record, to_record
from execution_channels import contracts as ec
from execution_channels.instruments import InstrumentId
from execution_channels.policy import ResearchExecutionSpec, ExecutionPolicy
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import TradeIntent


def execution_spec(spec):
    return from_record(ResearchExecutionSpec, to_record(spec))


def execution_instrument(instrument):
    return from_record(InstrumentId, to_record(instrument))


def session_execution_plan(proposal, portfolio, state):
    from execution_channels.planning.session import SessionProposal, plan_session_decision
    fields = {key: to_record(getattr(proposal, key)) for key in (
        'strategy', 'point', 'signal_date', 'signal_identity', 'references',
        'input_identities', 'price_identities', 'execution_policy')}
    fields.update(target_position=proposal.signal.target_position,
        cycle_target=to_record(proposal.signal.cycle_target), evidence=to_record(proposal.signal.evidence))
    return plan_session_decision(from_record(SessionProposal, fields), portfolio, state)


def strategy_portfolio(value):
    fields = to_record(value)
    if fields.get('closed_cycle_feedback') is not None:
        from strategy_runtime import EquityClosedCycle, EquityClosedCycleFeedback
        record = fields['closed_cycle_feedback']
        latest = record['latest']
        if latest is not None:
            for key in ('entry_interval', 'exit_interval'):
                latest[key] = TimeInterval(**latest[key])
            record['latest'] = EquityClosedCycle(**latest)
        fields['closed_cycle_feedback'] = EquityClosedCycleFeedback(**record)
    return EquityPortfolio(**fields)


def strategy_snapshot(value, instrument):
    fields = to_record(value)
    fields['instrument'] = instrument
    return AccountSnapshot(**fields)


def strategy_position(value):
    if value is None:
        return None
    fields = to_record(value)
    for key in ('entry_interval', 'last_fill_interval'):
        fields[key] = TimeInterval(**fields[key])
    return PositionCycle(**fields)


def strategy_feedback(value):
    return PositionFeedback(strategy_position(value.active), strategy_position(value.latest_closed))


def strategy_budget(value):
    if value is None:
        return None
    fields = to_record(value)
    fields['phase'] = EntryCyclePhase(fields['phase'])
    return CycleBudget(**fields)


def strategy_events(values):
    return tuple(RecognizedAccountEvent(**{**to_record(value), 'kind': RecognizedEventKind(value.kind.value)}) for value in values)


def execution_plan(result, snapshot, specification, *, owner, implementation, fee_rate, sell_remainder_policy, reference_price, execution_policy, cycle_budget=None, locked_quantity=None):
    record = to_record(result.proposal.decision)
    record['explanation'] = {'facts': result.proposal.decision.explanation.to_dict()}
    return plan_account_decision(from_record(TradeIntent, record),
        from_record(ec.ReplayPoint, to_record(result.point)),
        from_record(ec.AccountSnapshot, to_record(snapshot)), reference_price,
        execution_spec(specification), owner=owner, implementation=implementation,
        fee_rate=fee_rate, sell_remainder_policy=ec.SellRemainderPolicy(sell_remainder_policy),
        execution_policy=from_record(ExecutionPolicy, to_record(execution_policy)),
        cycle_budget=from_record(ec.CycleBudget, to_record(cycle_budget)) if cycle_budget is not None else None,
        locked_quantity=locked_quantity, suppressed=result.suppressed)
