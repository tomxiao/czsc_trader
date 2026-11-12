"""Independent EC planning/account tests: no SRT or DFLS fixture dependency."""
from datetime import timedelta
from dataclasses import replace

import pandas as pd
import pytest

from execution_channels.contracts import SellRemainderPolicy
from execution_channels.daily_execution import DAILY_TARGET_TRIGGER, DailyExecutionOutcome
from execution_channels.instruments import MarketId
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import DecisionExplanation, TradeIntent
from execution_channels.policy import ExecutionPolicy
from execution_channels.historical.channel import HistoricalReplayChannel, HistoricalDecision, AdoptionStatus
from execution_channels.state import StateRecord
from execution_channels.serialization import to_record, from_record


from ec_facts import fixture


# Independent risk: EC10; responsibility-level assertions.


# Independent risk: EC01; responsibility-level assertions.


# Independent risk: EC12; responsibility-level assertions.


# Independent risk: EC12; responsibility-level assertions.


# Independent risk: EC01; responsibility-level assertions.


# Independent risk: EC10; responsibility-level assertions.
@pytest.mark.parametrize('stale', [False,True], ids=['EC10-C01','EC10-C03'])
def test_historical_channel_adoption_preserves_confirmed_account_and_idempotency(stale):
    market = MarketId.US
    instrument, spec, point, row, constraint = fixture(market)
    prior = {**row, 'BarStart': row['BarStart']-timedelta(days=1), 'Date': point.observed_through}
    prior_constraint = {**constraint, 'Date': prior['BarStart'], 'AvailableDate': prior['BarStart'],
                        'BuySellableAt': prior['BarStart'], 'SettlementAt': prior['Date']}
    channel = HistoricalReplayChannel(account_id='account', instrument=instrument, specification=spec,
        initial_cash=10000., fee_rate=.001, bars=pd.DataFrame([prior,row]),
        constraints=pd.DataFrame([prior_constraint,constraint]),)
    channel.advance(point.decision_at)
    before = channel.snapshot('account', at=point.decision_at)
    plan = plan_account_decision(TradeIntent(1., DecisionExplanation({'reason':'entry'})), point,
        before.account, 10., spec, owner='account', implementation='a'*64, fee_rate=.001,
        execution_policy=ExecutionPolicy("TARGET_POSITION", {}), sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION)
    decision = HistoricalDecision(plan, before.strategy.revision, StateRecord((('seen',1),)),
                                  StateRecord(), before.next_event_cursor, 'owner-binding')
    if stale:
        channel.adopt('account', decision)
        channel.advance(point.execution_end)
        confirmed = channel.snapshot('account', at=point.execution_end)
        stale_point = replace(point, decision_at=point.execution_end, execution_start=point.execution_end,
                              execution_end=point.execution_end+timedelta(hours=6))
        from execution_channels.contracts import AccountExecutionPlan
        stale_plan = from_record(AccountExecutionPlan, {**to_record(plan),
            'plan_identity':'b'*64,'point':to_record(stale_point)})
        assert channel.adopt('account', replace(decision,plan=stale_plan)) is AdoptionStatus.STALE_SNAPSHOT
        assert channel.snapshot('account', at=point.execution_end) == confirmed
        return
    assert channel.adopt('account', decision) is AdoptionStatus.ADOPTED
    assert channel.executor.quantity == 0
    assert channel.state.account.get('seen') == 1
    assert channel.state.cycle is None
    assert channel.adopt('account', decision) is AdoptionStatus.ALREADY_ADOPTED
    with pytest.raises(RuntimeError, match='unresolved'):
        channel.finish()
    advanced = channel.advance(point.execution_end)
    assert advanced.completed_plan == plan.plan_identity
    after = channel.snapshot('account', at=point.execution_end)
    assert after.account.quantity == plan.target_quantity
    assert after.position.active.quantity == plan.target_quantity
    assert after.strategy.cycle is not None
    assert after.strategy.revision == 1
    assert channel.adopt('account', decision) is AdoptionStatus.ALREADY_ADOPTED
    assert channel.advance(point.execution_end).completed_plan is None
    with pytest.raises(ValueError,match='different content'):
        channel.adopt('account', replace(decision,account_values=StateRecord((('seen',2),))))


def test_daily_historical_target_retries_across_weekend_then_holds():
    instrument, spec, point, row, constraint = fixture(MarketId.US)
    offsets = (-4, -3, 0, 1)
    bars = [{**row, 'BarStart': row['BarStart'] + timedelta(days=i), 'Date': row['Date'] + timedelta(days=i)}
            for i in offsets]
    constraints = [{**constraint, 'Date': bar['BarStart'], 'AvailableDate': bar['BarStart'],
                    'BuySellableAt': bar['BarStart'], 'SettlementAt': bar['Date']} for bar in bars]
    channel = HistoricalReplayChannel(account_id='account', instrument=instrument, specification=spec,
        initial_cash=10000., fee_rate=.001, bars=pd.DataFrame(bars), constraints=pd.DataFrame(constraints))
    policy = ExecutionPolicy('TARGET_POSITION', {'execution_trigger': DAILY_TARGET_TRIGGER})
    target = TradeIntent(1., DecisionExplanation({'reason': 'long'}))

    for index, reference, trigger in ((1, 8., 'INITIAL_TARGET'), (2, 10., 'PREVIOUS_ZERO_FILL'),
                                       (3, 9., 'UNCHANGED_TARGET')):
        start, end = bars[index]['BarStart'], bars[index]['Date']
        current = replace(point, observed_through=bars[index - 1]['Date'], decision_at=start,
                          execution_start=start, execution_end=end, session_id=start.date().isoformat())
        channel.advance(start)
        snapshot = channel.snapshot('account', at=start)
        prior = channel.previous_daily_execution('account', at=start)
        if index > 1:
            assert prior.previous_session
            assert prior.outcome is (DailyExecutionOutcome.ZERO_FILL if index == 2 else DailyExecutionOutcome.FULL_FILL)
        plan = plan_account_decision(target, current, snapshot.account, reference, spec, owner='account',
            implementation='a'*64, fee_rate=.001, execution_policy=policy, previous_daily_execution=prior,
            sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION)
        assert plan.evidence['execution_trigger'] == trigger
        assert bool(plan.orders) == (index < 3)
        assert channel.adopt('account', HistoricalDecision(plan, snapshot.strategy.revision,
            StateRecord(), StateRecord(), snapshot.next_event_cursor, 'owner-binding')) is AdoptionStatus.ADOPTED
        channel.advance(end)
