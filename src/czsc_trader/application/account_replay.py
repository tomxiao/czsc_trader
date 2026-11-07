"""Research host orchestration: SRT proposals and EC-owned historical accounts."""
from dataclasses import replace
from time import perf_counter
from datetime import datetime
import math

from dataflows import TimeInterval
from strategy_runtime import AccountDecisionEngine, AccountStrategyState, StateRecord
from strategy_runtime.equity_replay import PreparedObservations, ReplayOutcome, ReplayStatistics, ReplayFailure
from strategy_runtime.equity import equity_hash
from execution_channels.historical import HistoricalReplayChannel, HistoricalDecision, AdoptionStatus
from execution_channels.historical.input_facts import normalize_constraint_times
from execution_channels.state import AccountStrategyState as ChannelStrategyState, StateRecord as ChannelStateRecord
from .ec_boundary import (execution_instrument, execution_plan, strategy_budget, strategy_events,
                          strategy_feedback, strategy_portfolio, strategy_snapshot)


def run_replay(prepared, candidate, executor, *, constraints, start, end, fee_rate, initial_state=None, owner=None):
    """Execute a supplied historical window with exactly the online strategy entry."""
    if type(prepared) is not PreparedObservations or candidate.definition.contract_version != 4:
        raise TypeError('historical account requires prepared V4 observations')
    if any(type(t) is not datetime or t.utcoffset() is None for t in (start, end)) or start >= end:
        raise ValueError('historical window requires aware positive bounds')
    definition = candidate.definition
    if executor.spec.fingerprint != definition.execution_spec.fingerprint or executor.fee_rate != fee_rate:
        raise ValueError('execution contract differs from declared research policy')
    owner = candidate.candidate_id if owner is None else owner
    state = initial_state or AccountStrategyState(account=definition.initial_account or StateRecord())
    constraint_rows = constraints.to_dict('records') if hasattr(constraints, 'to_dict') else constraints
    constraint_rows = tuple(sorted((normalize_constraint_times(row) for row in constraint_rows),
                                   key=lambda row: row['Date']))
    by_start = {row['Date']: row for row in constraint_rows}
    if len(by_start) != len(constraint_rows):
        raise ValueError('duplicate execution constraints')
    constraint_identity = equity_hash([
        {key: None if isinstance(value, float) and math.isnan(value) else value
         for key, value in row.items()} for row in constraint_rows])
    binding = equity_hash({'owner': owner, 'implementation': candidate.implementation_hash,
        'prepared': prepared.identity, 'execution_constraints': constraint_identity,
        'specification': definition.execution_spec.fingerprint, 'fee_rate': fee_rate})
    if state.binding not in (None, binding) or (state.revision and state.binding is None):
        raise ValueError('strategy state belongs to another account')
    data = prepared._data
    ticks = tuple((i, a, b) for i, (a, b) in enumerate(zip(data.starts, data.ends)) if a >= start and b <= end)
    expected = tuple((a, b) for (a, b), _ in prepared._calendar_intervals if a >= start and b <= end)
    if not ticks or ticks[0][1] != start or ticks[-1][2] != end or tuple((a,b) for _,a,b in ticks) != expected:
        raise ValueError('account window must cover its complete execution calendar')
    channel = HistoricalReplayChannel.from_executor(executor, account_id=owner,
        instrument=execution_instrument(candidate.instrument), bars=data.rows, constraints=constraint_rows,
        initial_state=ChannelStrategyState.from_dict(state.to_dict()))
    engine = AccountDecisionEngine(candidate, prepared)
    decisions = 0
    started = perf_counter()
    with candidate.bind_replay() as scope:
        for i, a, b in ticks:
            prior = state
            try:
                constraint = by_start.get(a)
                if constraint is None or constraint['AvailableDate'] > a:
                    raise ValueError('trading constraint unavailable at decision')
                observation = engine.observation(TimeInterval(a,b))
                channel.advance(a)
                snapshot = channel.snapshot(owner, at=a, observed_through=observation[0].observed_through)
                state = AccountStrategyState.from_dict(snapshot.strategy.to_dict())
                account = strategy_snapshot(snapshot.account, candidate.instrument)
                result = engine.propose(TimeInterval(a,b), strategy_portfolio(snapshot.portfolio), account, state,
                    strategy_feedback(snapshot.position), owner=owner, fee_rate=fee_rate,
                    budget=strategy_budget(snapshot.budget), events=strategy_events(snapshot.events),
                    next_event_cursor=snapshot.next_event_cursor, binding=binding)
                definition.state_schema.validate_record(result.proposal.account, scope='account')
                if result.proposal.cycle_values is not None:
                    definition.state_schema.validate_record(result.proposal.cycle_values, scope='cycle')
                plan = execution_plan(result, account, definition.execution_spec, owner=owner,
                    implementation=candidate.implementation_hash, fee_rate=fee_rate,
                    sell_remainder_policy=constraint['SellRemainderPolicy'])
                proposal = HistoricalDecision(plan, snapshot.strategy.revision,
                    ChannelStateRecord.from_dict(result.proposal.account.to_dict()),
                    None if result.proposal.cycle_values is None else ChannelStateRecord.from_dict(result.proposal.cycle_values.to_dict()),
                    result.next_event_cursor, binding)
                adopted = channel.adopt(owner, proposal)
                if adopted is not AdoptionStatus.ADOPTED:
                    raise ValueError('historical decision was not adopted: ' + adopted.value)
                channel.advance(b)
                state = AccountStrategyState.from_dict(channel.state.to_dict())
                decisions += not result.suppressed
            except Exception as exc:
                # An accepted decision or preceding confirmed fill cannot be
                # erased merely because a later execution operation failed.
                committed = AccountStrategyState.from_dict(channel.state.to_dict()) if channel.state.revision > prior.revision else prior
                raise ReplayFailure(committed, a, exc) from exc
        account_result = channel.finish()
    stats = ReplayStatistics(0., perf_counter()-started, len(ticks), decisions)
    stats = replace(stats, source_checks=scope.checks, source_bytes_read=scope.bytes_read, module_loads=scope.loads)
    return ReplayOutcome(account_result, state, stats)
