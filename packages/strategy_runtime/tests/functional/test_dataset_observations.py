"""Causal table inputs and opt-in planning facts on the shared V4 engine."""
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import pickle

import pandas as pd
import pytest
from dataflows import (DataIdentity, Dataset, MarketId, BarFrequency, TimeInterval,
                      DataCoverageRequirement)
from strategy_runtime import (DatasetObservationInput, DatasetObservationBinding,
    FrozenDataAsset, ObservationAvailability, PreparedObservationTable, PreparedReplay,
    EquityStrategyDefinition, AccountDecisionEngine, AccountStrategyState,
    StrategyComputation, ReplayPoint, ExecutionPrecision, PositionFeedback,
    equity_source_hash)
from test_account_v4 import setup


def identity(dataset=Dataset.INDEX_CONSTITUENT_WEIGHT, symbol='000905.SH', *, available='AvailableDate'):
    return DataIdentity(dataset.value, 'fixture', symbol, '2026-01-01', '2026-01-03', 'a' * 64,
        dict(source_time_field='Date', availability_time_field=available,
             source_calendar='SSE', available_at='EXPLICIT', request_range_policy='EXACT',
             primary_key=['Date', 'ConstituentSymbol'] if dataset is Dataset.INDEX_CONSTITUENT_WEIGHT else ['Date']))


def test_panel_visibility_keeps_same_day_rows_and_delayed_publication():
    frame = pd.DataFrame({'Date': pd.to_datetime(['2026-01-01', '2026-01-01', '2026-01-02'], utc=True),
        'AvailableDate': pd.to_datetime(['2026-01-02', '2026-01-03', '2026-01-02'], utc=True),
        'ConstituentSymbol': ['A', 'B', 'A'], 'Weight': [1., 2., 3.]})
    table = PreparedObservationTable.from_frame(frame, identity())
    table = pickle.loads(pickle.dumps(table))
    view = table.view(datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert [(row['ConstituentSymbol'], row['Weight']) for row in view.rows] == [('A', 1.), ('A', 3.)]
    assert view.observation_count == 2
    assert len(table.view(datetime(2026, 1, 3, tzinfo=timezone.utc))) == 3
    assert table.view(datetime(2026, 1, 3, tzinfo=timezone.utc)).session_count == 2
    with pytest.raises(TypeError):
        view.rows[0]['Weight'] = 10
    copied = view.to_frame()
    copied.loc[0, 'Weight'] = 999
    frame.loc[0, 'Weight'] = 888
    assert view.rows[0]['Weight'] == 1.
    with pytest.raises(ValueError, match='duplicated'):
        PreparedObservationTable.from_frame(pd.concat([frame, frame.iloc[[0]]]), identity())
    with pytest.raises(ValueError, match='exceeds availability'):
        PreparedObservationTable.from_frame(frame.assign(AvailableDate=pd.Timestamp('2025-12-31', tz='UTC')), identity())


def test_date_only_publication_requires_explicit_local_close():
    frame = pd.DataFrame({'Date': pd.to_datetime(['2026-11-02']), 'Code': ['SPX'], 'Close': [1.]})
    value = identity(Dataset.GLOBAL_INDEX_DAILY, 'SPX', available='Date')
    with pytest.raises(ValueError, match='explicit publication'):
        PreparedObservationTable.from_frame(frame, value)
    declaration = DatasetObservationInput('spx', Dataset.GLOBAL_INDEX_DAILY, 'SPX',
        availability=ObservationAvailability('America/New_York', '16:00'))
    table = PreparedObservationTable.from_frame(frame, value, declaration=declaration)
    assert not table.view(datetime(2026, 11, 2, 20, 59, tzinfo=timezone.utc)).rows
    assert len(table.view(datetime(2026, 11, 2, 21, tzinfo=timezone.utc))) == 1


@pytest.mark.parametrize('dataset,key', [
    (Dataset.ETF_OHLCV, ('Date',)),
    (Dataset.INDEX_CONSTITUENT_WEIGHT, ('Date', 'ConstituentSymbol')),
    (Dataset.STOCK_MONEYFLOW, ('Date', 'Symbol')),
    (Dataset.STRATEGY_FEATURE_EVIDENCE, ('Date',)),
    (Dataset.SHIBOR_DAILY, ('Date',)),
    (Dataset.INDEX_DAILY_BASIC, ('Date',)),
    (Dataset.ETF_SHARE_SIZE, ('Date',)),
    (Dataset.GLOBAL_INDEX_DAILY, ('Date',)),
    (Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, ('Date',)),
])
def test_published_product_keys_cover_real_table_shapes_without_rewriting_old_metadata(dataset, key):
    days = ['2026-01-01', '2026-01-01'] if len(key) == 2 else ['2026-01-01', '2026-01-02']
    frame = pd.DataFrame({'Date': pd.to_datetime(days, utc=True),
        'AvailableDate': pd.to_datetime(['2026-01-02', '2026-01-02'], utc=True)})
    if len(key) == 2:
        frame[key[1]] = ['600000.SH', '600001.SH']
    if dataset is Dataset.ETF_OHLCV:
        frame = frame.assign(Open=1., High=2., Low=.5, Close=1., Volume=100., Amount=100.)
    raw = dict(source_time_field='Date', availability_time_field='AvailableDate',
        source_calendar='SOURCE_NATIVE', available_at='source publication', request_range_policy='EXACT',
        data_contract_version=1)
    value = DataIdentity(dataset.value, 'old-tushare-publication', None,
        '2026-01-01', '2026-01-02', 'a' * 64, raw)
    before = json.dumps(dict(value.metadata), sort_keys=True)
    assert value.primary_key == key
    table = PreparedObservationTable.from_frame(frame, value)
    assert table.primary_key == key
    assert len(pickle.loads(pickle.dumps(table)).view(datetime(2026, 1, 3, tzinfo=timezone.utc))) == 2
    assert json.dumps(dict(value.metadata), sort_keys=True) == before
    assert 'primary_key' not in value.metadata
    with pytest.raises(ValueError, match='duplicated'):
        PreparedObservationTable.from_frame(pd.concat([frame, frame.iloc[[0]]]), value)
    with pytest.raises(ValueError, match='missing'):
        PreparedObservationTable.from_frame(frame.assign(**{key[-1]: None}), value)
    with pytest.raises(ValueError, match='key and time columns'):
        PreparedObservationTable.from_frame(frame.drop(columns=key[-1]), value)


def test_unknown_or_conflicting_product_key_is_not_inferred_from_columns():
    metadata = dict(source_time_field='Date', availability_time_field='Date', source_calendar='SSE',
                    available_at='source close', request_range_policy='EXACT')
    unknown = DataIdentity('unknown.product', 'fixture', None, '2026-01-01', '2026-01-02', 'a' * 64, metadata)
    with pytest.raises(ValueError, match='no declared primary key'):
        _ = unknown.primary_key
    conflicting = DataIdentity(Dataset.INDEX_CONSTITUENT_WEIGHT.value, 'fixture', '000905.SH',
        '2026-01-01', '2026-01-02', 'a' * 64, {**metadata, 'primary_key': ['Date']})
    with pytest.raises(ValueError, match='dataset contract'):
        _ = conflicting.primary_key


def test_moneyflow_dates_and_fixed_seed_request_roundtrip(tmp_path):
    item = DatasetObservationInput('flow', Dataset.STOCK_MONEYFLOW,
        history_start=date(2026, 1, 1))
    with pytest.raises(ValueError, match='non-empty tuple'):
        item.request(date(2026, 1, 2), date(2026, 1, 4), source_root=tmp_path)
    request = item.request(date(2026, 1, 2), date(2026, 1, 4), source_root=tmp_path,
        trading_dates=('2026-01-02', '2026-01-03', '2026-01-05'))
    assert request.parameters.trading_dates == ('2026-01-02', '2026-01-03')
    binding = DatasetObservationBinding(item, request, 'b' * 64)
    assert DatasetObservationBinding.from_dict(json.loads(json.dumps(binding.to_dict()))) == binding
    source = tmp_path / 'seed.csv'
    source.write_text('Date,value\n2026-01-01,1\n', encoding='utf-8')
    frozen = DatasetObservationInput('seed', Dataset.STRATEGY_FEATURE_EVIDENCE, 'S999-v1',
        history_start=date(2026, 1, 1), history_end=date(2026, 1, 2),
        asset=FrozenDataAsset('seed.csv', sha256(source.read_bytes()).hexdigest()))
    request = frozen.request(date(2026, 2, 1), date(2026, 2, 3), source_root=tmp_path)
    assert (request.start, request.end) == ('2026-01-01', '2026-01-02')
    assert DatasetObservationInput.from_dict(json.loads(json.dumps(frozen.to_dict()))) == frozen
    source.write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='content differs'):
        frozen.request(date(2026, 2, 1), date(2026, 2, 3), source_root=tmp_path)
    with pytest.raises(ValueError, match='relative'):
        FrozenDataAsset('../seed.csv', 'a' * 64)


def test_explicit_request_and_shared_identity_rejected_before_fetch(tmp_path):
    from test_equity_adjusted_binding import binding_fixture
    item = DatasetObservationInput('index', Dataset.GLOBAL_INDEX_DAILY, 'SPX')
    request = item.request(date(2026, 1, 1), date(2026, 1, 5), source_root=tmp_path)
    item.validate_request(request)
    with pytest.raises(ValueError, match='differs from declaration'):
        item.validate_request(replace(request, symbol='NDX'))
    with pytest.raises(ValueError, match='canonical start'):
        replace(item, history_start=date(2025, 1, 1)).validate_request(request)
    binding, requests = binding_fixture(MarketId.US)
    first = DatasetObservationBinding(item, request, 'a' * 64)
    second = DatasetObservationBinding(replace(item, name='index_again'), request, 'b' * 64)
    with pytest.raises(ValueError, match='inconsistent content'):
        replace(binding, observation_bindings=(first, second))
    same = replace(second, content_sha256=first.content_sha256)
    shared = replace(binding, observation_bindings=(first, same))
    assert shared.bind_requests(tuple(row for _, row in requests) + (request,))[-2:] == (
        ('observation:index', request), ('observation:index_again', request))


def test_resource_path_case_alias_is_rejected_before_registration(tmp_path):
    c, *_ = setup(tmp_path, MarketId.US, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP)
    seed = DatasetObservationInput('seed', Dataset.STRATEGY_FEATURE_EVIDENCE, 'S999-v1',
        history_start=date(2026, 1, 1), history_end=date(2026, 1, 2),
        asset=FrozenDataAsset('seed.csv', 'a' * 64))
    other = replace(seed, name='alias', asset=FrozenDataAsset('Seed.csv', 'a' * 64))
    with pytest.raises(ValueError, match='case-insensitive'):
        replace(c.definition, observation_inputs=(seed, other))


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('fee', [.001, .002])
def test_planning_context_and_table_are_bound_to_actual_step(tmp_path, market, fee):
    c, p, executor, bars, constraints, sessions, session_frame = setup(
        tmp_path, market, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP)
    original = c.definition.to_dict()
    assert 'planning_context' not in original and 'observation_inputs' not in original
    assert EquityStrategyDefinition.from_dict(original).to_dict() == original
    (tmp_path / 'strategy.py').write_text('''from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
def step(ctx, state):
    assert ctx.planning.fee_rate == ctx.parameters['expected_fee']
    assert ctx.planning.execution_spec.quantity_step == ctx.parameters['step']
    assert len(ctx.observations['index']) == 2
    assert ctx.observations['index'].as_of == ctx.point.decision_at
    return AccountStepResult(AccountDecision.from_facts(0., 'observed', facts={'fee': ctx.planning.fee_rate}, next_watch='next'), state.account)
''', encoding='utf-8')
    declaration = DatasetObservationInput('index', Dataset.INDEX_CONSTITUENT_WEIGHT, '000905.SH')
    c = replace(c, definition=replace(c.definition, entrypoint='strategy:step',
        parameters_json=json.dumps({'expected_fee': fee, 'step': c.definition.execution_spec.quantity_step}),
        parameter_schema_json=None,
        source_sha256=equity_source_hash(tmp_path, ('strategy.py',)),
        observation_inputs=(declaration,), planning_context=True))
    stamp = p._data.ends[0]
    frame = pd.DataFrame({'Date': [stamp, stamp], 'AvailableDate': [stamp, stamp],
                          'ConstituentSymbol': ['A', 'B'], 'Weight': [1., 2.]})
    table = PreparedObservationTable.from_frame(frame, identity(), declaration=declaration)
    p = PreparedReplay.from_frames(bars, constraints, c.definition.feature_graph,
        sessions=session_frame, trading_sessions=sessions, frequency=BarFrequency.DAILY,
        timezone=c.instrument.timezone, observation_tables={'index': table})
    assert p.with_graph(c.definition.feature_graph)._observations == p._observations
    interval = TimeInterval(p._data.starts[1], p._data.ends[1])
    point = ReplayPoint(stamp, interval.start, interval.start, interval.end,
        sessions[1].session_date.isoformat(), ExecutionPrecision.BAR_INTERVAL)
    portfolio = executor.snapshot_at(stamp, interval.start)
    account = executor.account_snapshot(point, c.instrument)
    proposal = AccountDecisionEngine(c, p).plan(interval, portfolio, account,
        AccountStrategyState(), PositionFeedback(), owner='fixture', fee_rate=fee)
    assert not proposal.plan.orders
    with pytest.raises(ValueError, match='STATEFUL_STEP'):
        replace(c.definition, computation=StrategyComputation.BATCH_HISTORY)
    # Two constituents on one date are one observation, not two warmup days.
    strict = replace(c, definition=replace(c.definition, observation_inputs=(
        replace(declaration, coverage=DataCoverageRequirement(minimum_observations=2, minimum_sessions=2)),)))
    with pytest.raises(ValueError, match='WARMUP_INSUFFICIENT'):
        AccountDecisionEngine(strict, p).plan(interval, portfolio, account,
            AccountStrategyState(), PositionFeedback(), owner='fixture', fee_rate=fee)
