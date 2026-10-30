"""Formal equity identity and causal decision behavior through public APIs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import pickle

import pandas as pd
import pytest
from dataflows import InstrumentId, MarketId, AssetClass, BarFrequency, TimeInterval
from strategy_runtime import (EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash,
    ResearchExecutionSpec, UsEquitySpec, AccountPolicy, CashAvailabilityPolicy, EquityPortfolio, StrategyRuntime,
    EquityClosedCycle, EquityClosedCycleFeedback, EquityDecisionContext, DecisionPoint)


def candidate(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'rules.py').write_text('THRESHOLD = 10\n', encoding='utf-8')
    (root / 'strategy.py').write_text('from .rules import THRESHOLD\nfrom strategy_runtime import EquityDecision\n'
        'counter = 0\ndef decide(ctx):\n global counter\n counter += 1\n'
        ' return EquityDecision.from_facts(int(ctx.history.Close.iloc[-1] >= ctx.parameters["threshold"] and counter == 1), '
        '"threshold decision", facts={"close": ctx.history.Close.iloc[-1], "threshold": ctx.parameters["threshold"]}, next_watch="next bar")\n', encoding='utf-8')
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    files = ('rules.py', 'strategy.py')
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'), spec, 1,
        'strategy:decide', files, equity_source_hash(root, files), '{"threshold":10}')
    return EquityStrategyCandidate('S999', 'C0001', definition, root)


def test_formal_equity_portable_identity_and_stateless_decisions(tmp_path):
    original = candidate(tmp_path / 'original')
    relocated = candidate(tmp_path / 'relocated')
    assert original.content_identity == relocated.content_identity
    assert pickle.loads(pickle.dumps(original)) == original
    assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(original.definition.to_dict()))) == original.definition
    changed = replace(original, definition=replace(original.definition, parameters_json='{"threshold":11}'))
    assert changed.content_identity != original.content_identity
    with pytest.raises(ValueError, match='parameter type differs'):
        replace(original.definition, parameters_json='{"threshold":true}')
    runtime = StrategyRuntime(execution_spec=original.definition.execution_spec)
    assert runtime.identify(original, dependencies=()) == original.content_identity
    instance = runtime.create(original)
    end = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    history = pd.DataFrame({'Date': [end], 'AvailableDate': [end], 'Close': [10.]})
    interval = TimeInterval(end, end + timedelta(minutes=30))
    first = instance.plan(history, interval, EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)
    second = instance.plan(history, interval, EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)
    assert first == second and first.target == 1
    assert first.explanation['basis'][1] == {'key': 'threshold', 'text': '10'}
    assert runtime.create(changed).plan(history, interval, EquityPortfolio(1000., 0, 0., 0), fee_rate=.001).target == 0
    (original.source_root / 'rules.py').write_text('THRESHOLD = 11\n', encoding='utf-8')
    with pytest.raises(ValueError, match='closure changed'):
        original.verify()


def test_formal_equity_rejects_undeclared_import_and_future_history(tmp_path):
    value = candidate(tmp_path)
    future = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
    history = pd.DataFrame({'Date': [future], 'AvailableDate': [future], 'Close': [10.]})
    with pytest.raises(ValueError, match='CAUSAL_TIME'):
        StrategyRuntime(execution_spec=value.definition.execution_spec).create(value).plan(history,
            TimeInterval(future - timedelta(minutes=30), future), EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)
    (tmp_path / 'rules.py').write_text('import unlisted_dependency\n', encoding='utf-8')
    with pytest.raises(ValueError, match='undeclared equity dependency'):
        replace(value, definition=replace(value.definition,
            source_sha256=equity_source_hash(tmp_path, value.definition.source_files)))


def test_formal_decision_observes_split_before_planning(tmp_path):
    from trading_execution_engine.frozen_equity import _FrozenEquityExecutor
    value = candidate(tmp_path)
    value = replace(value, definition=replace(value.definition, parameters_json='{"threshold":1}'))
    start = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    starts = [start + timedelta(minutes=30 * i) for i in range(3)]
    ends = [x + timedelta(minutes=30) for x in starts]
    bars = pd.DataFrame({'BarStart': starts, 'Date': ends, 'AvailableDate': ends,
                         'Open': [10., 10., 5.], 'High': [10., 10., 5.],
                         'Low': [10., 10., 5.], 'Close': [10., 10., 5.], 'Volume': 10000.})
    constraints = pd.DataFrame({'Date': starts, 'AvailableDate': starts, 'QuantityStep': 1,
                                'PriceTick': .01, 'Tradable': True})
    actions = pd.DataFrame([{'Date': starts[2], 'AvailableDate': starts[2], 'EventId': 'split',
                             'Kind': 'SPLIT', 'Ratio': 2., 'CashPerShare': 0., 'PayAt': None}])
    executor = _FrozenEquityExecutor(specification=value.definition.execution_spec,
                                         initial_cash=1000., fee_rate=.001, actions=actions)
    result = StrategyRuntime(execution_spec=value.definition.execution_spec).create(value).run_window(
        bars, constraints, executor, start=starts[1], end=ends[-1], fee_rate=.001)
    assert result.account_points.iloc[-1].quantity == 196
    assert result.decisions.iloc[-1].reference_price == 5.
    assert result.decisions.iloc[-1].side == 'HOLD'


def closed_cycle():
    entry = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    return EquityClosedCycle('cycle-1', TimeInterval(entry, entry + timedelta(minutes=30)),
        TimeInterval(entry + timedelta(hours=1), entry + timedelta(hours=1, minutes=30)),
        10, 100.1, entry + timedelta(hours=1))


@pytest.mark.parametrize(('field', 'value'), [
    ('cycle_id', ''), ('cycle_id', ' cycle '),
    ('entry_quantity', True), ('entry_quantity', 0), ('entry_quantity', 1.5),
    ('entry_cost', True), ('entry_cost', float('nan')), ('entry_cost', float('inf')), ('entry_cost', 0.),
    ('entry_interval', {}), ('exit_interval', {}),
    ('exit_observed_through', datetime(2026, 10, 1, 15)),
    ('exit_observed_through', datetime(2026, 10, 1, 14, 29, tzinfo=timezone.utc)),
    ('exit_observed_through', datetime(2026, 10, 1, 15, 1, tzinfo=timezone.utc)),
])
def test_closed_cycle_rejects_invalid_execution_facts(field, value):
    with pytest.raises((ValueError, TypeError)):
        replace(closed_cycle(), **{field: value})


def test_closed_cycle_feedback_typed_states_and_portable_boundary():
    closed = closed_cycle()
    boundary = replace(closed, exit_observed_through=closed.entry_interval.end)
    assert boundary.exit_observed_through == closed.entry_interval.end
    local = replace(closed, exit_observed_through=closed.exit_observed_through.astimezone(
        timezone(timedelta(hours=8))))
    assert local == closed
    feedback = EquityClosedCycleFeedback(closed)
    portfolio = EquityPortfolio(110., 0, 0., 2, closed_cycle_feedback=feedback)
    assert pickle.loads(pickle.dumps(portfolio)) == portfolio
    assert EquityClosedCycleFeedback().latest is None
    assert EquityPortfolio(100., 0, 0., 0).closed_cycle_feedback is None
    with pytest.raises(TypeError, match='typed latest'):
        EquityClosedCycleFeedback({'cycle_id': 'not-a-cycle'})
    with pytest.raises(TypeError, match='typed closed'):
        replace(portfolio, closed_cycle_feedback={})


def feedback_candidate(root, mode):
    value = candidate(root)
    (root / 'strategy.py').write_text(
        'from strategy_runtime import EquityDecision\n'
        'def decide(ctx):\n'
        '    p = ctx.portfolio\n'
        '    f = None if p is None else p.closed_cycle_feedback\n'
        '    state = "market" if p is None else "unavailable" if f is None else '
        '"empty" if f.latest is None else f.latest.cycle_id\n'
        '    return EquityDecision.from_facts(0, state, facts={"state":state}, next_watch="next bar")\n',
        encoding='utf-8')
    return replace(value, definition=replace(value.definition, feedback_mode=mode,
        source_sha256=equity_source_hash(root, value.definition.source_files)))


def test_closed_cycle_mode_requires_capability_and_preserves_old_input_contract(tmp_path):
    value = feedback_candidate(tmp_path, 'CONFIRMED_CLOSED_CYCLE_V1')
    assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(value.definition.to_dict()))) == value.definition
    old = replace(value, definition=replace(value.definition, feedback_mode='CONFIRMED_EXECUTION'))
    market = replace(value, definition=replace(value.definition, feedback_mode='MARKET_INTENT'))
    assert len({x.content_identity.content_sha256 for x in (value, old, market)}) == 3
    closed = closed_cycle()
    end = closed.exit_interval.end
    point = DecisionPoint(end, end, TimeInterval(end, end + timedelta(minutes=30)))
    history = pd.DataFrame({'Date':[end], 'AvailableDate':[end], 'Close':[10.]})
    unavailable = EquityPortfolio(100., 0, 0., 2)
    context = EquityDecisionContext(history, unavailable, point, value.definition.parameters)
    with pytest.raises(ValueError, match='CLOSED_CYCLE_FEEDBACK_UNAVAILABLE'):
        value.decide(context)
    runtime = StrategyRuntime(execution_spec=value.definition.execution_spec)
    with pytest.raises(ValueError, match='CLOSED_CYCLE_FEEDBACK_UNAVAILABLE'):
        runtime.create(value).plan(history, point.execution_interval, unavailable, fee_rate=.001)
    empty = replace(unavailable, closed_cycle_feedback=EquityClosedCycleFeedback())
    assert value.decide(replace(context, portfolio=empty)).reason == 'empty'
    full = replace(unavailable, closed_cycle_feedback=EquityClosedCycleFeedback(closed))
    assert value.decide(replace(context, portfolio=full)).reason == 'cycle-1'
    assert old.decide(replace(context, portfolio=full)).reason == 'unavailable'
    assert market.decide(replace(context, portfolio=full)).reason == 'market'
    assert runtime.create(value).plan(history, point.execution_interval, full, fee_rate=.001).explanation['judgment'] == 'cycle-1'


@pytest.mark.parametrize('violation', ['exit-in-future', 'observation-in-future', 'overlapping-current-cycle'])
def test_closed_cycle_mode_rejects_noncausal_feedback(tmp_path, violation):
    value = feedback_candidate(tmp_path, 'CONFIRMED_CLOSED_CYCLE_V1')
    closed = closed_cycle()
    now = closed.exit_interval.end
    observed = now
    portfolio = EquityPortfolio(100., 0, 0., 2, closed_cycle_feedback=EquityClosedCycleFeedback(closed))
    if violation == 'exit-in-future':
        now -= timedelta(minutes=1)
        observed = now
    elif violation == 'observation-in-future':
        observed = closed.exit_observed_through - timedelta(minutes=1)
    else:
        portfolio = replace(portfolio, quantity=1, cycle_entry=closed.exit_interval.start, cycle_cost=10.)
    point = DecisionPoint(observed, now, TimeInterval(now, now + timedelta(minutes=30)))
    context = EquityDecisionContext(pd.DataFrame(), portfolio, point, value.definition.parameters)
    with pytest.raises(ValueError, match='CAUSAL_TIME_VIOLATION'):
        value.decide(context)
