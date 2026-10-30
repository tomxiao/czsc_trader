"""V3 public replay ownership, state transactions and exact economic transitions."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import pickle

import pandas as pd
import pytest

from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, SourceRef, TradingSession, TimeInterval
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, EquityStrategyCandidate, EquityAuxiliaryInput,
    EquityStrategyDefinition, EquityPortfolio, ResearchExecutionSpec, StrategyRuntime, UsEquitySpec, equity_source_hash)
from strategy_runtime.equity_features import BarField, FeatureGraph, RawField
from strategy_runtime.equity_replay import (PreparedReplay, ReplayFailure, StateField, StateRecord,
    StateValueType, StrategyStateSchema, run_replay)
from trading_execution_engine.equity import EquityHistoricalExecutor


SOURCE = '''from strategy_runtime import EquityDecision
from strategy_runtime.equity_replay import StateRecord, StepResult
counter = 0
def step(ctx, state):
    global counter
    counter += 1
    if counter != 1:
        raise ValueError("namespace state leaked")
    close = ctx.features.get("close").value
    if state.cycle is None:
        held, latched = 0, False
        target = int(close >= 10.)
    else:
        held = state.cycle.values.get("held") + 1
        latched = state.cycle.values.get("latched") or close < 9.
        target = int(not latched)
    return StepResult(EquityDecision.from_facts(target, "numbered test", facts={"held":held,"latched":latched},
        next_watch="next complete bar"), StateRecord(), StateRecord((("held",held),("latched",latched))))
'''


def candidate(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'strategy.py').write_text(SOURCE, encoding='utf-8')
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    graph = FeatureGraph((RawField('close', BarField.CLOSE),), ('close',))
    schema = StrategyStateSchema(cycle_fields=(StateField('held', StateValueType.INT),
                                             StateField('latched', StateValueType.BOOL)))
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'),
        spec, 1, 'strategy:step', ('strategy.py',), equity_source_hash(root, ('strategy.py',)), '{}',
        contract_version=3, feature_graph=graph, state_schema=schema)
    return EquityStrategyCandidate('S999', 'C0001', definition, root)


def inputs(value, count=7):
    starts = pd.date_range('2024-03-01 14:30', periods=count, freq='30min', tz='UTC')
    bars = pd.DataFrame({'BarStart': starts, 'Date': starts + pd.Timedelta(minutes=30),
        'AvailableDate': starts + pd.Timedelta(minutes=30), 'Open': 10., 'High': 11.,
        'Low': 9., 'Close': 10., 'Volume': 100000., 'Amount': 1000000.,
        'BarStatus': 'OBSERVED', 'ExecutionBlocked': False})
    constraints = pd.DataFrame({'Date': starts, 'AvailableDate': starts,
                                'QuantityStep': 1, 'PriceTick': .01, 'Tradable': True})
    actions = pd.DataFrame([{'Date': starts[0], 'AvailableDate': starts[0],
        'EventId': 'none', 'Kind': 'NONE', 'Ratio': 1., 'CashPerShare': 0., 'PayAt': None}])
    executor = EquityHistoricalExecutor(specification=value.definition.execution_spec,
        initial_cash=1000., fee_rate=.001, actions=actions)
    return bars, constraints, executor


def test_actual_fill_starts_cycle_expired_buy_does_not_sell_latch_survives(tmp_path):
    value = candidate(tmp_path)
    bars, constraints, executor = inputs(value)
    bars.loc[1, ['Open', 'High', 'Low', 'Close']] = [13., 14., 12., 13.]
    bars.loc[2, ['Open', 'High', 'Low', 'Close']] = [10., 11., 7., 8.]
    bars.loc[3, 'ExecutionBlocked'] = True
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph)
    outcome = run_replay(prepared, value, executor, start=bars.BarStart.iloc[1].to_pydatetime(),
        end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)
    result = outcome.execution_result
    assert result.orders.iloc[0].status == 'EXPIRED'
    assert result.orders.iloc[1].status == 'FILLED'
    assert result.orders.iloc[2].reason == 'KNOWN_INTERRUPTION'
    assert result.orders.iloc[3].side == 'SELL' and result.orders.iloc[3].status == 'FILLED'
    facts = [{item['key']: item['text'] for item in explanation['basis']}
             for explanation in result.decisions.explanation]
    assert facts[0]['held'] == facts[1]['held'] == '0'
    assert facts[2] == {'held': '1', 'latched': 'True'}
    assert facts[3] == {'held': '2', 'latched': 'True'}
    assert facts[4]['held'] == '0'  # New entry after actual complete sale.
    assert outcome.state.revision == len(result.decisions)
    assert outcome.statistics.rows == 6
    assert outcome.statistics.replay_seconds >= outcome.statistics.feature_seconds >= 0
    assert pickle.loads(pickle.dumps(outcome.state)) == outcome.state


def test_transaction_rejects_post_execute_revision_and_restores_all_account_state(tmp_path, monkeypatch):
    value = candidate(tmp_path)
    bars, constraints, executor = inputs(value, 3)
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph)
    execute = executor.execute

    def incorrect_revision(*args, **kwargs):
        actual = execute(*args, **kwargs)
        return replace(actual, revision=actual.revision + 1)

    monkeypatch.setattr(executor, 'execute', incorrect_revision)
    with pytest.raises(ReplayFailure, match='exactly one') as failed:
        run_replay(prepared, value, executor, start=bars.BarStart.iloc[1].to_pydatetime(),
            end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)
    assert executor.cash == 1000. and executor.quantity == executor.revision == 0
    assert not executor.completed and all(not rows for rows in executor.rows.values())
    assert executor.cycle is None
    assert failed.value.committed_state.revision == 0
    assert isinstance(failed.value.cause, ValueError)
    monkeypatch.setattr(executor, 'execute', execute)
    result = run_replay(prepared, value, executor, start=bars.BarStart.iloc[1].to_pydatetime(),
        end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)
    assert result.state.cycle is not None


def test_strong_schema_definition_roundtrip_and_prepared_pickle(tmp_path):
    value = candidate(tmp_path)
    assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(value.definition.to_dict()))) == value.definition
    schema = value.definition.state_schema
    with pytest.raises(TypeError):
        schema.validate_record(StateRecord((('held', True), ('latched', False))), scope='cycle')
    with pytest.raises(ValueError):
        schema.validate_record(StateRecord((('held', 1),)), scope='cycle')
    with pytest.raises(ValueError):
        StateRecord((('bad', float('nan')),))
    with pytest.raises(ValueError):
        StateRecord((('bad', datetime(2024, 1, 1)),))
    bars, constraints, _ = inputs(value)
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph)
    clone = pickle.loads(pickle.dumps(prepared))
    assert clone.graph == prepared.graph
    assert clone._data.starts == prepared._data.starts


def test_owner_is_explicit_and_future_suffix_does_not_change_earlier_tables(tmp_path):
    value = candidate(tmp_path)
    bars, constraints, executor = inputs(value)
    end = bars.Date.iloc[3].to_pydatetime()
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph)
    first = run_replay(prepared, value, executor, start=bars.BarStart.iloc[1].to_pydatetime(),
                       end=end, fee_rate=.001, owner='benchmark:independent')
    altered, _, second_executor = inputs(value)
    altered.loc[4:, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 5
    second = run_replay(PreparedReplay.from_frames(altered, constraints, value.definition.feature_graph),
        value, second_executor, start=bars.BarStart.iloc[1].to_pydatetime(), end=end,
        fee_rate=.001, owner='benchmark:independent')
    for name in ('decisions', 'orders', 'fills', 'corporate_action_entries', 'account_points', 'account_daily', 'trades'):
        pd.testing.assert_frame_equal(getattr(first.execution_result, name), getattr(second.execution_result, name), check_exact=True)
    assert (first.state.revision, first.state.account, first.state.cycle) == (
        second.state.revision, second.state.account, second.state.cycle)
    assert first.state.binding != second.state.binding  # Distinct prepared-data ownership.
    _, _, third_executor = inputs(value)
    third = run_replay(prepared, value, third_executor, start=bars.BarStart.iloc[1].to_pydatetime(),
                      end=end, fee_rate=.001, owner='benchmark:another')
    assert first.execution_result.decisions.decision_id.iloc[0] != third.execution_result.decisions.decision_id.iloc[0]


def test_invalid_latency_and_unsupported_market_contracts_reject(tmp_path):
    value = candidate(tmp_path)
    bars, constraints, executor = inputs(value)
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph, latency_seconds=1)
    with pytest.raises(ValueError, match='visibility'):
        run_replay(prepared, value, executor, start=datetime(2024, 3, 1, 15, tzinfo=timezone.utc),
                   end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)


def test_v3_rejects_stateless_plan_used_by_production_advice(tmp_path):
    value = candidate(tmp_path)
    bars, _, _ = inputs(value)
    instance = StrategyRuntime(execution_spec=value.definition.execution_spec).create(value)
    interval = TimeInterval(bars.BarStart.iloc[1].to_pydatetime(), bars.Date.iloc[1].to_pydatetime())
    with pytest.raises(ValueError, match='historical research only'):
        instance.plan(bars.iloc[:1], interval, EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)


def with_context(value, bars, *, max_age=1800.):
    declaration = EquityAuxiliaryInput('market', InstrumentId(MarketId.US, AssetClass.ETF, 'SPY'),
        SourceRef('synthetic', 'v3'), BarFrequency.M30, 1, max_age)
    value = replace(value, definition=replace(value.definition, auxiliary_inputs=(declaration,), session_context=True))
    session = TradingSession(bars.BarStart.iloc[0].date(), 'America/New_York',
        (TimeInterval(bars.BarStart.iloc[0].to_pydatetime(), bars.Date.iloc[-1].to_pydatetime()),))
    sessions = pd.DataFrame({'Date': [bars.BarStart.iloc[0]], 'AvailableDate': [bars.BarStart.iloc[0]],
                             'SessionDate': [session.session_date.isoformat()]})
    return value, sessions, (session,)


def test_auxiliary_and_session_asof_views_and_late_availability(tmp_path):
    value = candidate(tmp_path)
    bars, constraints, executor = inputs(value)
    source = SOURCE.replace('"held":held,"latched":latched',
        '"held":held,"latched":latched,"aux_rows":len(ctx.auxiliary_histories["market"]),'
        '"session":ctx.session.session_date.isoformat()')
    (tmp_path / 'strategy.py').write_text(source, encoding='utf-8')
    value = replace(value, definition=replace(value.definition, source_sha256=equity_source_hash(tmp_path, ('strategy.py',))))
    value, sessions, calendar = with_context(value, bars)
    auxiliary = bars.copy()
    auxiliary.loc[1, 'AvailableDate'] = bars.Date.iloc[3]
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph,
        auxiliary_histories={'market': auxiliary}, sessions=sessions, trading_sessions=calendar)
    restored = pickle.loads(pickle.dumps(prepared))
    result = run_replay(restored, value, executor, start=bars.BarStart.iloc[1].to_pydatetime(),
        end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001).execution_result
    facts = [{item['key']: item['text'] for item in value['basis']} for value in result.decisions.explanation]
    assert [item['aux_rows'] for item in facts[:4]] == ['1', '1', '2', '4']
    assert all(item['session'] == '2024-03-01' for item in facts)


def test_auxiliary_staleness_and_unavailable_session_reject_without_executing(tmp_path):
    value = candidate(tmp_path)
    bars, constraints, executor = inputs(value)
    value, sessions, calendar = with_context(value, bars, max_age=0.)
    auxiliary = bars.copy()
    auxiliary.loc[1, 'AvailableDate'] = bars.Date.iloc[3]
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph,
        auxiliary_histories={'market': auxiliary}, sessions=sessions, trading_sessions=calendar)
    with pytest.raises(ReplayFailure, match='STALE') as failed:
        run_replay(prepared, value, executor, start=bars.BarStart.iloc[1].to_pydatetime(),
            end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)
    assert failed.value.committed_state.revision == executor.revision == 1
    assert len(executor.rows['decisions']) == 1
    bars, constraints, executor = inputs(value)
    sessions.loc[0, 'AvailableDate'] = bars.BarStart.iloc[2]
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph,
        auxiliary_histories={'market': bars}, sessions=sessions, trading_sessions=calendar)
    with pytest.raises(ReplayFailure, match='session is not yet available'):
        run_replay(prepared, value, executor, start=bars.BarStart.iloc[1].to_pydatetime(),
            end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)
    assert executor.revision == 0 and executor.quantity == 0


def test_failure_exposes_exact_committed_state_and_same_binding_retry(tmp_path, monkeypatch):
    value = candidate(tmp_path)
    bars, constraints, executor = inputs(value)
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph)
    execute = executor.execute

    def fail_third(*args, **kwargs):
        actual = execute(*args, **kwargs)
        if actual.revision == 3:
            raise RuntimeError('synthetic failure after third execution')
        return actual

    monkeypatch.setattr(executor, 'execute', fail_third)
    with pytest.raises(ReplayFailure, match='synthetic failure') as failed:
        run_replay(prepared, value, executor, start=bars.BarStart.iloc[1].to_pydatetime(),
            end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)
    assert failed.value.committed_state.revision == executor.revision == 2
    monkeypatch.setattr(executor, 'execute', execute)
    changed = bars.copy()
    changed.loc[0, 'Volume'] *= 2
    other_data = PreparedReplay.from_frames(changed, constraints, value.definition.feature_graph)
    with pytest.raises(ValueError, match='different replay owner'):
        run_replay(other_data, value, executor, start=failed.value.next_execution_start,
            end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001,
            initial_state=failed.value.committed_state)
    outcome = run_replay(prepared, value, executor, start=failed.value.next_execution_start,
        end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001, initial_state=failed.value.committed_state)
    _, _, untouched = inputs(value)
    serial = run_replay(prepared, value, untouched, start=bars.BarStart.iloc[1].to_pydatetime(),
        end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)
    assert outcome.state == serial.state
    pd.testing.assert_frame_equal(outcome.execution_result.decisions, serial.execution_result.decisions, check_exact=True)
