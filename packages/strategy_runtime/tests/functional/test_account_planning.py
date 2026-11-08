"""Durable single-step planning shares causal decisions with V4 research."""
from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json

import pandas as pd
import pytest

from dataflows import BarFrequency, MarketId, TimeInterval
from strategy_runtime import (AccountDecisionEngine, AccountStrategyState, CycleState,
    ExecutionPrecision, PositionFeedback, ReplayPoint, StateRecord, StrategyComputation,
    PreparedObservations, RecognizedAccountEvent, RecognizedEventKind)
from czsc_trader.application.account_replay import run_replay
from czsc_trader.application.ec_boundary import (execution_spec, execution_instrument, execution_plan, strategy_portfolio, strategy_snapshot, strategy_feedback, strategy_budget, strategy_events)
from execution_channels.serialization import from_record, to_record
from execution_channels.contracts import ReplayPoint as ExecutionPoint
from execution_channels.historical import PortfolioHistoricalExecutor
from test_account_v4 import setup


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('frequency', [BarFrequency.DAILY, BarFrequency.M30])
@pytest.mark.parametrize('computation', [StrategyComputation.BATCH_HISTORY, StrategyComputation.STATEFUL_STEP])
def test_independent_single_steps_match_research_with_state_restart(tmp_path, market, frequency, computation):
    candidate, prepared, baseline, bars, constraints, _, _ = setup(tmp_path, market, frequency, computation)
    expected = run_replay(prepared, candidate, baseline, constraints=constraints,
        start=bars.BarStart.iloc[1].to_pydatetime(), end=bars.Date.iloc[-1].to_pydatetime(),
        fee_rate=.001).execution_result
    executor = PortfolioHistoricalExecutor(specification=execution_spec(candidate.definition.execution_spec),
        initial_cash=100000., fee_rate=.001, price_basis='HFQ')
    state = AccountStrategyState()
    for index in range(1, len(bars)):
        # New planner and decoded state emulate independent durable calls/restarts.
        engine = AccountDecisionEngine(candidate, prepared)
        state = AccountStrategyState.from_dict(json.loads(json.dumps(state.to_dict())))
        start, end = prepared._data.starts[index], prepared._data.ends[index]
        point = ReplayPoint(prepared._data.ends[index-1], start, start, end,
                            start.astimezone(ZoneInfo(candidate.instrument.timezone)).date().isoformat(), ExecutionPrecision.BAR_INTERVAL)
        with executor.transaction():
            portfolio = strategy_portfolio(executor.snapshot_at(point.observed_through, start))
            account = strategy_snapshot(executor.account_snapshot(from_record(ExecutionPoint, to_record(point)), execution_instrument(candidate.instrument)), candidate.instrument)
            events, cursor = executor.recognized_events_since(state.event_cursor, start)
            result = engine.propose(TimeInterval(start, end), portfolio, account, state,
                strategy_feedback(executor.position_feedback), owner='durable-account', fee_rate=.001,
                budget=strategy_budget(executor.cycle_budget), events=strategy_events(events), next_event_cursor=cursor)
            prior = state.to_dict()
            after = executor.execute_account_plan(execution_plan(result, account, candidate.definition.execution_spec, owner="durable-account", implementation=candidate.implementation_hash, fee_rate=.001, sell_remainder_policy=constraints.iloc[index].SellRemainderPolicy, reference_price=float(bars.Close.iloc[index-1]), execution_policy=candidate.definition.execution_policy, cycle_budget=executor.cycle_budget, locked_quantity=executor.locked_quantity), prepared._data.rows[index], constraint=constraints.iloc[index].to_dict())
            assert state.to_dict() == prior  # Planning and execution never mutate caller-owned strategy state.
            cycle = None if not after.quantity else CycleState(executor.cycle, after.cycle_entry, result.proposal.cycle_values)
            state = AccountStrategyState(after.revision, result.proposal.account, cycle,
                                         engine.state_binding('durable-account', .001), result.next_event_cursor)
    actual = executor.finish()
    for frame, columns in [('account_points', ['cash', 'quantity', 'equity']),
                           ('fills', ['side', 'quantity', 'price', 'fees'])]:
        pd.testing.assert_frame_equal(getattr(actual, frame)[columns], getattr(expected, frame)[columns])


def test_binding_survives_new_prepared_history_but_rejects_other_account(tmp_path):
    c, p, e, bars, constraints, sessions, session_frame = setup(
        tmp_path, MarketId.US, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP)
    shorter = PreparedObservations.from_frames(bars.iloc[:3], c.definition.feature_graph,
        frequency=BarFrequency.DAILY, timezone=c.instrument.timezone,
        sessions=session_frame.iloc[:3], trading_sessions=sessions[:3])
    first, second = AccountDecisionEngine(c, shorter), AccountDecisionEngine(c, p)
    assert shorter.identity != p.identity
    assert first.state_binding('account', .001) == second.state_binding('account', .001)
    interval = TimeInterval(p._data.starts[1], p._data.ends[1])
    point = ReplayPoint(p._data.ends[0], interval.start, interval.start, interval.end,
                        sessions[1].session_date.isoformat(), ExecutionPrecision.BAR_INTERVAL)
    portfolio = strategy_portfolio(e.snapshot_at(point.observed_through, point.decision_at))
    account = strategy_snapshot(e.account_snapshot(from_record(ExecutionPoint, to_record(point)), execution_instrument(c.instrument)), c.instrument)
    state = AccountStrategyState(binding=first.state_binding('another-account', .001))
    with pytest.raises(ValueError, match='another account'):
        second.propose(interval, portfolio, account, state, PositionFeedback(), owner='account', fee_rate=.001)


def test_future_event_and_backward_observation_are_rejected(tmp_path):
    c, p, e, _, _, sessions, _ = setup(tmp_path, MarketId.US, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP)
    engine = AccountDecisionEngine(c, p)
    interval = TimeInterval(p._data.starts[2], p._data.ends[2])
    point = ReplayPoint(p._data.ends[1], interval.start, interval.start, interval.end,
                        sessions[2].session_date.isoformat(), ExecutionPrecision.BAR_INTERVAL)
    portfolio = strategy_portfolio(e.snapshot_at(point.observed_through, point.decision_at))
    account = strategy_snapshot(e.account_snapshot(from_record(ExecutionPoint, to_record(point)), execution_instrument(c.instrument)), c.instrument)
    event = RecognizedAccountEvent('future', RecognizedEventKind.POSITION_ADJUSTMENT,
                                  interval.end, 0, 0, 1., 0.)
    with pytest.raises(ValueError, match='future facts'):
        engine.propose(interval, portfolio, account, AccountStrategyState(), PositionFeedback(),
                    owner='account', fee_rate=.001, events=(event,))
    with pytest.raises(ValueError, match='causal time order'):
        engine.observation(TimeInterval(p._data.starts[1], p._data.ends[1]))
    with pytest.raises(ValueError, match='cursor'):
        AccountDecisionEngine(c, p).propose(interval, portfolio, account,
            AccountStrategyState(event_cursor=2), PositionFeedback(), owner='account',
            fee_rate=.001, next_event_cursor=1)


def test_state_round_trip_preserves_types_and_rejects_missing_cursor():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state = AccountStrategyState(3, StateRecord((('flag', False), ('anchor', stamp))),
        CycleState('cycle', stamp, StateRecord((('entry', 12.),))), 'identity', 7)
    value = json.loads(json.dumps(state.to_dict()))
    assert AccountStrategyState.from_dict(value) == state
    del value['event_cursor']
    with pytest.raises(ValueError, match='unsupported account strategy state'):
        AccountStrategyState.from_dict(value)


@pytest.mark.parametrize('cross_observation', [False, True])
def test_explicit_batch_inspection_detects_cross_observation_dependency(tmp_path, cross_observation):
    from strategy_runtime import check_account_batch_consistency, equity_source_hash
    c, p, _, bars, constraints, _, _ = setup(tmp_path, MarketId.US, BarFrequency.M30, StrategyComputation.BATCH_HISTORY)
    if cross_observation:
        (tmp_path / 'strategy.py').write_text('''from strategy_runtime import AccountDecision
def calculate(ctx):
    return tuple(AccountDecision.from_facts(float(index % 2), 'sequence-dependent',
        facts={'index': index}, next_watch='next point') for index, row in enumerate(ctx.observations))
''', encoding='utf-8')
        c = replace(c, definition=replace(c.definition, source_sha256=equity_source_hash(tmp_path, ('strategy.py',))))
    result = check_account_batch_consistency(c, p,
        start=bars.BarStart.iloc[1].to_pydatetime(), end=bars.Date.iloc[-1].to_pydatetime())
    assert result.checked_points == len(bars) - 1
    assert result.consistent is (not cross_observation)
    if cross_observation:
        assert result.differing_points == tuple(stamp.to_pydatetime() for stamp in bars.BarStart.iloc[2:])
