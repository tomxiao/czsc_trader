"""Explicit application projections between strategy and execution domains.

No order sizing, market rule or account arithmetic belongs in this module.
"""
from dataclasses import asdict
import json

from dataflows import TimeInterval
from strategy_runtime.account_strategy import PositionCycle, RecognizedAccountEvent, RecognizedEventKind
from strategy_runtime.equity_replay import StateRecord

from execution_channels.serialization import from_record, to_record
from execution_channels.state import StateRecord as ExecutionStateRecord
from execution_channels.contracts import AccountSnapshot, ReplayPoint, SellRemainderPolicy
from execution_channels.policy import ResearchExecutionSpec, ExecutionPolicy
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import TradeIntent
from execution_channels.futu.equity_contracts import EquityAccountRules
from execution_channels.futu.inspection import InspectionAccountPermit


def execution_rules(instrument, specification):
    return EquityAccountRules.from_dict({'schema_version': 1,
        'instrument': to_record(instrument), 'execution': to_record(specification)})


def execution_permit(permit):
    """Project a host-validated isolation permission, keeping all scope fields."""
    if permit is None:
        return None
    return InspectionAccountPermit(**asdict(permit))


def initial_account_record(definition):
    return ExecutionStateRecord.from_dict((definition.initial_account or StateRecord()).to_dict())


def strategy_position(value):
    if value is None:
        return None
    fields = to_record(value)
    for key in ('entry_interval', 'last_fill_interval'):
        fields[key] = TimeInterval(**fields[key])
    return PositionCycle(**fields)


def strategy_events(values):
    result = []
    for value in values:
        fields = to_record(value)
        fields['kind'] = RecognizedEventKind(fields['kind'])
        result.append(RecognizedAccountEvent(**fields))
    return tuple(result)


def execution_plan(result, snapshot, specification, *, reference, execution_policy, cycle_budget, locked_quantity, owner, implementation, fee_rate, sell_remainder_policy):
    record = to_record(result.proposal.decision)
    record['explanation'] = {'facts': result.proposal.decision.explanation.to_dict()}
    return plan_account_decision(from_record(TradeIntent, record),
        from_record(ReplayPoint, to_record(result.point)),
        from_record(AccountSnapshot, to_record(snapshot)), reference,
        from_record(ResearchExecutionSpec, to_record(specification)), owner=owner,
        implementation=implementation, fee_rate=fee_rate,
        sell_remainder_policy=SellRemainderPolicy(sell_remainder_policy),
        execution_policy=from_record(ExecutionPolicy, to_record(execution_policy)),
        cycle_budget=cycle_budget, locked_quantity=locked_quantity, suppressed=result.suppressed)


def session_execution_plan(proposal, portfolio, state):
    """Project a legacy session signal to the same EC planning ownership."""
    from execution_channels.planning.session import SessionProposal, plan_session_decision
    from execution_channels.session_contracts import PortfolioSnapshot, ExecutionState
    fields = {key: to_record(getattr(proposal, key)) for key in (
        "strategy", "point", "signal_date", "signal_identity", "references",
        "input_identities", "price_identities", "execution_policy")}
    fields.update(target_position=proposal.signal.target_position,
        cycle_target=to_record(proposal.signal.cycle_target), evidence=to_record(proposal.signal.evidence))
    return plan_session_decision(from_record(SessionProposal, fields),
        from_record(PortfolioSnapshot, to_record(portfolio)),
        from_record(ExecutionState, to_record(state)))


def execution_admission(plan, snapshot, document, proposal, *, state_binding,
                        next_event_cursor, prepared, rules):
    from execution_channels.futu.v4_admission import (V4AccountProposal, V4ExecutionContext,
        prepare_v4_adoption)
    transition = V4AccountProposal(ExecutionStateRecord.from_dict(proposal.account.to_dict()),
        None if proposal.cycle_values is None else ExecutionStateRecord.from_dict(proposal.cycle_values.to_dict()),
        state_binding, next_event_cursor)
    context = from_record(V4ExecutionContext, {
        "interval": to_record(prepared.interval), "as_of": prepared.as_of,
        "buy_sellable_at": prepared.buy_sellable_at,
        "v4_constraint": {key: prepared.v4_constraint[key] for key in
            ("SellRemainderPolicy", "PriceLimitPolicy", "PriceLimitLower", "PriceLimitUpper")},
        "data_identity": prepared.data_identity,
        "fee_rate": prepared.fee_rate})
    return prepare_v4_adoption(plan, from_record(AccountSnapshot, to_record(snapshot)),
        document, transition, context, rules)


def strategy_account_snapshot(account, document, rules, at, available_cash, instrument):
    from execution_channels.futu.v4_admission import decision_snapshot
    from strategy_runtime.replay_contracts import AccountSnapshot as StrategySnapshot
    value = decision_snapshot(account, document, rules, at, available_cash)
    fields = to_record(value)
    fields["instrument"] = instrument
    return StrategySnapshot(**fields)


def account_input_identity(inputs):
    """Project a PTE-validated recipe; EC does not parse the host schema."""
    from execution_channels.futu.input_identity import AccountInputIdentity
    from execution_channels.instruments import InstrumentId

    return AccountInputIdentity(inputs.release_hash,
        from_record(InstrumentId, to_record(inputs.binding.instrument)),
        inputs.binding.specification_hash, inputs.fee_rate,
        json.dumps(inputs.to_dict(), sort_keys=True, allow_nan=False).encode())
