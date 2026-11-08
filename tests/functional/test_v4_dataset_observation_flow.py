"""Published tables keep their identity and causal views across V4 consumers."""
from test_v4_inspection_roundtrip import prepare_raw_reference
from dataclasses import replace
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataset, MarketId, ProviderBinding, EquityProduct, TimeInterval
from strategy_runtime import StrategyComputation, equity_source_hash
from strategy_runtime.dataset_observations import (DatasetObservationInput,
    FrozenDataAsset, ObservationAvailability)
from czsc_trader.research_tools import ResearchExecutionSession
from czsc_trader.research_tools.equity_replay import materialize_equity
from czsc_trader.application import EquityInspectionReplay
from czsc_trader.application.equity_inspection import replay_account, _copy_inputs
from strategy_manager import freeze_contracts as f
from paper_trading_engine.equity_advice import prepare_equity_decision
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient, FormalV4Inputs
from test_equity_adjusted_observations import setup_adjusted


def observation_fixture(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP):
    context, request, products, _, _ = setup_adjusted(tmp_path, market, computation)
    root = request.candidate.source_root
    asset = root / 'seed.csv'
    asset.write_text('date,value\n2026-10-12,7\n', encoding='utf-8')
    availability = ObservationAvailability('Asia/Shanghai', '16:00')
    observations = (
        DatasetObservationInput('weights', Dataset.INDEX_CONSTITUENT_WEIGHT, '000300.SH',
                                availability=availability),
        DatasetObservationInput('rate', Dataset.SHIBOR_DAILY, availability=availability),
        DatasetObservationInput('seed', Dataset.STRATEGY_FEATURE_EVIDENCE, 'S999-v1',
            history_start=date(2026,10,12), history_end=date(2026,10,12),
            asset=FrozenDataAsset('seed.csv', sha256(asset.read_bytes()).hexdigest()),
            availability=availability),
    )
    (root / 'strategy.py').write_text(
        'from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n'
        'def decision(ctx):\n'
        '    tables = ctx.observations\n'
        '    assert len(tables["weights"]) >= 2\n'
        '    assert len(tables["seed"]) == 1\n'
        '    return AccountDecision.from_facts(1, "table inputs", '
        'facts={"weights": len(tables["weights"]), "rate": len(tables["rate"])}, '
        'next_watch="next session")\n'
        'def step(ctx, state):\n'
        '    return AccountStepResult(decision(ctx), cycle_values=StateRecord())\n'
        'def batch(ctx):\n'
        '    return tuple(decision(row) for row in ctx.observations)\n', encoding='utf-8')
    candidate = replace(request.candidate, definition=replace(request.candidate.definition,
        source_sha256=equity_source_hash(root, ('strategy.py',)), observation_inputs=observations))
    calls = []
    def fetch(query):
        calls.append(query)
        days = pd.date_range(query.start, query.end, freq='D')
        if query.dataset is Dataset.INDEX_CONSTITUENT_WEIGHT:
            frame = pd.DataFrame([dict(Date=day, ConstituentSymbol=symbol, Weight=50.)
                for day in days for symbol in ('600000.SH', '600001.SH')])
            return frame, {'primary_key': ['Date', 'ConstituentSymbol']}
        return pd.DataFrame(dict(Date=days, OvernightRate=2.)), {'primary_key': ['Date']}
    for dataset in (Dataset.INDEX_CONSTITUENT_WEIGHT, Dataset.SHIBOR_DAILY):
        context.data._providers[dataset.value] = ProviderBinding('tables', 'v1', fetch)
    from dataflows.local_strategy_data import fetch_strategy_feature_evidence
    context.data._providers[Dataset.STRATEGY_FEATURE_EVIDENCE.value] = ProviderBinding(
        'seed', 'v1', fetch_strategy_feature_evidence)
    return context, replace(request, candidate=candidate), products, calls


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('computation', [StrategyComputation.STATEFUL_STEP, StrategyComputation.BATCH_HISTORY])
def test_tables_flow_through_research_inspection_and_pte(tmp_path, market, computation):
    context, request, products, calls = observation_fixture(tmp_path, market, computation)
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        prepared = context.evaluation.prepare(request, execution=session)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=session)
        assert outcome.result is not None, outcome.error
        materialized = materialize_equity(outcome.result).payload
        assert set(materialized['audit_inputs']['decision_inputs']['observations']) == {'weights', 'rate', 'seed'}
        request = prepared.request
    assert {query.dataset for query in calls} == {Dataset.INDEX_CONSTITUENT_WEIGHT, Dataset.SHIBOR_DAILY}
    replay = EquityInspectionReplay(f.InspectionCoordinate('main', 'standard'), request.input_binding,
        request.requests(context.execution_spec), request.window, request.initial_cash, request.fee_rate,
        execution_reference=prepare_raw_reference(context, request))
    facts = replay_account(request.candidate, context.data, replay)
    assert facts['facts']['fills'] == materialized['runs']['candidate']['fills']
    isolated, copied = _copy_inputs(context.data, replay, tmp_path / 'inspection-inputs')
    copied_facts = replay_account(request.candidate, isolated, copied)
    assert copied_facts['facts'] == facts['facts']
    row = products[EquityProduct.BARS].iloc[1]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    online = prepare_equity_decision(isolated, request.candidate, copied.input_binding,
        copied.requests, interval, fee_rate=request.fee_rate,
            execution_reference=copied.execution_reference.fetch(isolated, interval, latency_seconds=context.execution_spec.data_latency_seconds))
    from strategy_runtime.account_planning import AccountDecisionEngine
    observation = AccountDecisionEngine(request.candidate, online.v4_replay).observation(interval)
    assert observation is not None
    table = dict(online.v4_replay._observations)['weights'].view(interval.start)
    if market is MarketId.CN:
        assert len(table) == 2  # Today's close-dated snapshot is not yet visible.
    else:
        assert len(table) == 4  # Chinese source publication precedes the US opening.


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_forward_tables_pin_intervals_and_keep_seed_bounds(tmp_path, market):
    context, request, products, _ = observation_fixture(tmp_path, market)
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        request = context.evaluation.prepare(request, execution=session).request
    from dataflows.equity_data import equity_metadata, sessions_from_metadata, session_record
    def ranged(binding):
        def fetch(query):
            frame, metadata = binding.fetch(query)
            p = query.parameters
            days = frame.Date.dt.tz_convert(p.instrument.timezone).dt.date
            frame = frame.loc[(days >= p.query.start) & (days <= p.query.end)].copy()
            source_sessions = sessions_from_metadata(metadata)
            sessions = tuple(s for s in source_sessions
                if p.query.start <= s.session_date <= p.query.end)
            following = next((s for s in source_sessions if s.session_date > p.query.end), None)
            metadata = {**metadata, **equity_metadata(query, sessions, availability_basis='SYNTHETIC_BAR_CLOSE')}
            if following is not None and p.query.product in (EquityProduct.TRADING_FACTS, EquityProduct.SESSIONS):
                metadata['following_session'] = session_record(following)
            return frame, metadata
        return ProviderBinding(binding.name, binding.revision, fetch)
    context.data._equity_providers = {key: ranged(value) for key, value in context.data._equity_providers.items()}
    client = FormalV4AdviceClient(repo_root=tmp_path, store=SimpleNamespace(
        virtual_account=lambda account: {'last_decision_payload': None}),
        dataflows=context.data, data_dir=tmp_path / 'forward')
    recipe = FormalV4Inputs('a' * 64, request.input_binding.for_observations(), request.fee_rate,
        prepare_raw_reference(context, request))
    row = products[EquityProduct.BARS].iloc[1]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    value = client._forward_inputs('fixture', recipe, interval, candidate=request.candidate)
    queries = {x.input.name: x.request for x in value.binding.observation_bindings}
    assert queries['seed'].start == queries['seed'].end == '2026-10-12'
    assert queries['rate'].end == ('2026-10-12' if market is MarketId.CN else '2026-10-13')
    with patch.object(context.data, 'prepare', side_effect=AssertionError('must reuse pinned interval')):
        assert client._forward_inputs('fixture', recipe, interval, candidate=request.candidate) == value
    next_interval = TimeInterval(interval.start + timedelta(days=1), interval.end + timedelta(days=1))
    following = client._forward_inputs('fixture', recipe, next_interval, candidate=request.candidate)
    next_queries = {x.input.name: x.request for x in following.binding.observation_bindings}
    assert next_queries['seed'] == queries['seed']
    assert next_queries['rate'].end > queries['rate'].end


def test_moneyflow_resolves_open_dates_and_rejects_missing_calendar(tmp_path):
    from strategy_runtime.observation_preparation import resolve_observation_requests
    from dataflows import Dataflows, DataSpace, ProviderConfig
    seen = []
    def calendar(query):
        seen.append(query)
        return pd.DataFrame({'Date': pd.date_range('2026-10-12', periods=3), 'IsOpen': ['1', '0', '1']}), {}
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('data')),
        providers=ProviderConfig(bindings={Dataset.TRADING_CALENDAR: ProviderBinding('fixture', 'v1', calendar)}))
    declaration = DatasetObservationInput('flow', Dataset.STOCK_MONEYFLOW)
    (_, query), = resolve_observation_requests(flows, (declaration,), date(2026,10,12),
        date(2026,10,14), source_root=tmp_path)
    assert query.parameters.trading_dates == ('2026-10-12', '2026-10-14')
    assert len(seen) == 1
    empty = Dataflows(base_dir=tmp_path, space=DataSpace(Path('empty')),
        providers=ProviderConfig(bindings={}))
    with pytest.raises(ValueError, match='calendar preparation'):
        resolve_observation_requests(empty, (declaration,), date(2026,10,12), date(2026,10,14), source_root=tmp_path)


def test_request_rejects_undeclared_observation_before_data_access(tmp_path):
    from dataflows import DataRequest
    context, request, _, _ = observation_fixture(tmp_path, MarketId.CN)
    queries = tuple(query for name, query in request.request_items(context.execution_spec)
                    if name.startswith('observation:'))
    wrong = DataRequest(Dataset.GLOBAL_INDEX_DAILY, 'SPX', '2026-10-12', '2026-10-15', None)
    with patch.object(context.data, 'prepare', side_effect=AssertionError('must reject before data access')):
        with pytest.raises(ValueError, match='differs from declaration'):
            replace(request, observation_requests=(wrong, *queries[1:]))


@pytest.mark.parametrize('at,closed,expected', [
    ('2026-10-14T16:00', (), '2026-10-09'),
    ('2026-10-16T14:59', (), '2026-10-09'),
    ('2026-10-16T15:00', (), '2026-10-16'),
    ('2026-10-15T15:00', ('2026-10-16',), '2026-10-15'),
    ('2026-10-15T14:59', ('2026-10-16',), '2026-10-09'),
    ('2026-10-18T16:00', tuple(f'2026-10-{day}' for day in range(12,17)), '2026-10-09'),
])
def test_weekly_selection_requires_complete_source_week(tmp_path, at, closed, expected):
    from strategy_runtime.observation_preparation import resolve_observation_requests
    from dataflows import Dataflows, DataSpace, ProviderConfig
    moment = datetime.fromisoformat(at).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    def calendar(query):
        days = pd.date_range(query.start, query.end)
        return pd.DataFrame({'Date': days, 'IsOpen': [int(day.weekday() < 5 and day.strftime('%Y-%m-%d') not in closed)
                                                    for day in days]}), {}
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('calendar')),
        providers=ProviderConfig(bindings={Dataset.TRADING_CALENDAR: ProviderBinding('synthetic', 'v1', calendar)}))
    declaration = DatasetObservationInput('weekly', Dataset.ETF_OHLCV, '588080.SH', frequency='weekly',
        availability=ObservationAvailability('Asia/Shanghai', '15:00'))
    (_, query), = resolve_observation_requests(flows, (declaration,), date(2026,10,5), moment.date(),
        source_root=tmp_path, as_of=moment)
    assert query.end == expected
    # A fully specified publication is reproduced by another consumer.
    (_, repeated), = resolve_observation_requests(flows, (declaration,), date(2026,10,5), moment.date(),
        source_root=tmp_path, as_of=moment)
    assert repeated == query


def test_weekly_selection_rejects_partial_first_week(tmp_path):
    from strategy_runtime.observation_preparation import resolve_observation_requests
    from dataflows import Dataflows, DataSpace, ProviderConfig
    def calendar(query):
        days = pd.date_range(query.start, query.end)
        return pd.DataFrame({'Date': days, 'IsOpen': [int(day.weekday() < 5) for day in days]}), {}
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('calendar')),
        providers=ProviderConfig(bindings={Dataset.TRADING_CALENDAR: ProviderBinding('synthetic', 'v1', calendar)}))
    declaration = DatasetObservationInput('weekly', Dataset.ETF_OHLCV, '588080.SH', frequency='weekly',
        history_start=date(2026,10,7), availability=ObservationAvailability('Asia/Shanghai', '15:00'))
    with pytest.raises(ValueError, match='start omits source sessions'):
        resolve_observation_requests(flows, (declaration,), date(2026,10,7), date(2026,10,16), source_root=tmp_path)
