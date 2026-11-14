"""Research host orchestration: SRT proposals and EC-owned historical accounts."""
from dataclasses import replace
from time import perf_counter
from datetime import datetime
import math

from dataflows import TimeInterval
from strategy_runtime import AccountDecisionEngine, AccountStrategyState, StateRecord, STEP_DATA_CONTRACT
from strategy_runtime.equity_replay import PreparedObservations, ReplayOutcome, ReplayStatistics, ReplayFailure
from strategy_runtime.equity import equity_hash
from strategy_runtime.strategy_performance import (StrategyPerformanceBudget, StrategyPerformanceExceeded,
                                                    _StrategyPerformanceProbe)
from execution_channels.historical import HistoricalReplayChannel, HistoricalDecision, AdoptionStatus
from execution_channels.daily_execution import INTERVAL_TARGET_TRIGGER, TARGET_TRIGGERS
from execution_channels.execution_intervals import execution_intervals
from execution_channels.instruments import TimeInterval as ChannelInterval
from execution_channels.historical.input_facts import normalize_constraint_times
from execution_channels.state import AccountStrategyState as ChannelStrategyState, StateRecord as ChannelStateRecord
from .ec_boundary import (execution_instrument, execution_plan, strategy_budget, strategy_events,
                          strategy_feedback, strategy_portfolio, strategy_snapshot)


def run_replay(prepared, candidate, executor, *, constraints, start, end, fee_rate, initial_state=None, owner=None,
               step_data_load=None, performance_budget: StrategyPerformanceBudget | None = None):
    """Execute a supplied historical window with exactly the online strategy entry."""
    if type(prepared) is not PreparedObservations or candidate.definition.contract_version != STEP_DATA_CONTRACT:
        raise TypeError('historical account requires the V5 DFLS step contract')
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
    implementation = candidate.implementation_hash
    binding = equity_hash({'owner': owner, 'implementation': implementation,
        'prepared': prepared.identity, 'execution_constraints': constraint_identity,
        'specification': definition.execution_spec.fingerprint, 'fee_rate': fee_rate})
    if state.binding not in (None, binding) or (state.revision and state.binding is None):
        raise ValueError('strategy state belongs to another account')
    data = prepared._data
    ticks = tuple((a, b) for a, b in zip(data.starts, data.ends) if a >= start and b <= end)
    expected = tuple((a, b) for (a, b), _ in prepared._calendar_intervals if a >= start and b <= end)
    if not ticks or ticks[0][0] != start or ticks[-1][1] != end or ticks != expected:
        raise ValueError('account window must cover its complete execution calendar')
    channel = HistoricalReplayChannel.from_executor(executor, account_id=owner,
        instrument=execution_instrument(candidate.instrument), bars=data.rows, constraints=constraint_rows,
        initial_state=ChannelStrategyState.from_dict(state.to_dict()))
    if performance_budget is not None and type(performance_budget) is not StrategyPerformanceBudget:
        raise TypeError('replay performance requires StrategyPerformanceBudget')
    performance = None if performance_budget is None else _StrategyPerformanceProbe(performance_budget, len(ticks))
    engine = AccountDecisionEngine(candidate, prepared, step_data_load=step_data_load, performance=performance)
    trigger = definition.execution_policy.settings.get('execution_trigger')
    target_trigger = trigger in TARGET_TRIGGERS
    cycles = {(cycle.window.start, cycle.window.end): cycle for cycle in execution_intervals(
        ChannelInterval(a, b) for (a, b), _ in prepared._calendar_intervals)} if target_trigger else {}
    interval_policy = trigger == INTERVAL_TARGET_TRIGGER
    if interval_policy:
        calendar_availability = {(a, b): prepared._sessions[index][1]
                                 for (a, b), index in prepared._calendar_intervals}
        bar_ready = dict(zip(data.ends, data.ready_at, strict=True))
    projected_channel_state = None
    decisions = 0
    data_reads = []
    started = perf_counter()
    with candidate.bind_replay(performance=performance) as scope:
        for a, b in ticks:
            prior = state
            try:
                constraint = by_start.get(a)
                if constraint is None or constraint['AvailableDate'] > a:
                    raise ValueError('trading constraint unavailable at decision')
                interval = TimeInterval(a, b)
                cycle = cycles.get((a, b))
                decision_at = a
                if interval_policy and cycle.previous_window is not None:
                    decision_at = max(cycle.start, constraint['AvailableDate'], calendar_availability[a, b],
                                      bar_ready[cycle.previous_window.end])
                    if decision_at > a:
                        raise ValueError('completed decision input unavailable at submission start')
                observation = engine.observation(interval, decision_at=decision_at)
                channel.advance(decision_at)
                snapshot = channel.snapshot(owner, at=decision_at, observed_through=observation[0].observed_through)
                # A completed interval already supplied the confirmed strategy
                # state for the next decision. Moving the clock and taking a
                # snapshot can settle cash but leave that strategy state intact.
                if snapshot.strategy is not projected_channel_state:
                    state = AccountStrategyState.from_dict(snapshot.strategy.to_dict())
                account = strategy_snapshot(snapshot.account, candidate.instrument)
                result = engine.propose(interval, strategy_portfolio(snapshot.portfolio), account, state,
                    strategy_feedback(snapshot.position), owner=owner, fee_rate=fee_rate,
                    budget=strategy_budget(snapshot.budget), events=strategy_events(snapshot.events),
                    next_event_cursor=snapshot.next_event_cursor, binding=binding, decision_at=decision_at)
                previous_execution = None
                if target_trigger:
                    previous_window = cycle.previous_window
                    previous_execution = channel.previous_execution(owner, at=decision_at,
                        previous_end=None if previous_window is None else previous_window.end)
                plan = execution_plan(result, account, definition.execution_spec, owner=owner,
                    implementation=implementation, fee_rate=fee_rate,
                    sell_remainder_policy=constraint['SellRemainderPolicy'],
                    reference_price=observation[1],
                    execution_policy=definition.execution_policy, cycle_budget=snapshot.budget,
                    locked_quantity=snapshot.locked_quantity,
                    previous_daily_execution=previous_execution, execution_interval=cycle)
                proposal = HistoricalDecision(plan, snapshot.strategy.revision,
                    ChannelStateRecord.from_dict(result.proposal.account.to_dict()),
                    None if result.proposal.cycle_values is None else ChannelStateRecord.from_dict(result.proposal.cycle_values.to_dict()),
                    result.next_event_cursor, binding)
                adopted = channel.adopt(owner, proposal)
                if adopted is not AdoptionStatus.ADOPTED:
                    raise ValueError('historical decision was not adopted: ' + adopted.value)
                if definition.step_data_inputs:
                    data_reads.append({'decision_at': decision_at.isoformat(), 'decision_id': plan.plan_identity,
                                       'reads': [read.to_dict() for read in result.data_reads]})
                channel.advance(b)
                projected_channel_state = channel.state
                state = AccountStrategyState.from_dict(projected_channel_state.to_dict())
                decisions += not result.suppressed
            except StrategyPerformanceExceeded:
                raise
            except Exception as exc:
                # An accepted decision or preceding confirmed fill cannot be
                # erased merely because a later execution operation failed.
                committed = AccountStrategyState.from_dict(channel.state.to_dict()) if channel.state.revision > prior.revision else prior
                raise ReplayFailure(committed, a, exc) from exc
        profile = None if performance is None else performance.finish()
        account_result = channel.finish()
    stats = ReplayStatistics(0., perf_counter()-started, len(ticks), decisions, strategy_performance=profile)
    stats = replace(stats, source_checks=scope.checks, source_bytes_read=scope.bytes_read, module_loads=scope.loads)
    return ReplayOutcome(account_result, state, stats, tuple(data_reads))
