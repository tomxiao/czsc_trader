"""Independent table warmup remains explicit across preparation and replay."""
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from dataflows import DataCoverageRequirement, Dataset, MarketId, MoneyflowParameters, ProviderBinding
from strategy_runtime import equity_source_hash
from strategy_runtime.dataset_observations import DatasetObservationInput, ObservationAvailability
from czsc_trader.research_tools import ResearchExecutionSession
from test_equity_adjusted_observations import setup_adjusted


def independent_fixture(tmp_path, market):
    context, request, _, _, raw_calls = setup_adjusted(tmp_path, market)
    root = request.candidate.source_root
    (root / 'strategy.py').write_text(
        'from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n'
        'def step(ctx, state):\n'
        '    table = ctx.observations["signal"]\n'
        '    assert len(table) >= 300\n'
        '    assert float(ctx.history.last()["Close"]) == 20\n'
        '    return AccountStepResult(AccountDecision.from_facts(0, "independent warmup", '
        'facts={"rows": len(table)}, next_watch="next session"), cycle_values=StateRecord())\n',
        encoding='utf-8')
    item = DatasetObservationInput('signal', Dataset.ETF_OHLCV, '510500.SH', frequency='daily',
        coverage=DataCoverageRequirement(maximum_start_lag_days=None, minimum_observations=300),
        availability=ObservationAvailability('Asia/Shanghai', '15:00'))
    definition = replace(request.candidate.definition, auxiliary_inputs=(), observation_inputs=(item,),
        source_sha256=equity_source_hash(root, ('strategy.py',)))
    calls = []

    def fetch(query):
        from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence
        from dataflows.history_repair import frame_content_sha256
        calls.append(query)
        days = pd.bdate_range(query.start, query.end)
        frame = pd.DataFrame(dict(Date=days, Open=20., High=21., Low=19., Close=20.,
                                  Volume=10000., Amount=200000.))
        calendar_days = pd.date_range(query.start, query.end)
        calendar = pd.DataFrame({'Date': calendar_days.strftime('%Y-%m-%d'),
                                 'is_open': calendar_days.isin(days).astype(int)})
        expected = days.strftime('%Y-%m-%d').tolist()
        quality = build_quality_evidence(frame, frequency='daily', expected_dates=expected)
        metadata = {'adjustment': 'hfq', 'daily_session_coverage': {
            'source': 'synthetic-weekday-calendar', 'exchange': 'SSE',
            'start_date': query.start, 'end_date': query.end,
            'listing_date': '2020-01-01', 'listing_source': 'synthetic-fixture',
            'calendar': calendar.to_dict('records'), 'calendar_sha256': frame_content_sha256(calendar),
            'expected_dates': expected, 'verified_sessions': len(expected)},
            'ohlcv_quality_evidence': bind_quality_frame(quality, frame, adjustment='hfq')}
        frame.attrs = {key: metadata[key] for key in ('daily_session_coverage', 'ohlcv_quality_evidence')}
        return frame, metadata

    context.data._providers[Dataset.ETF_OHLCV.value] = ProviderBinding('table-fixture', 'v1', fetch)
    first = pd.bdate_range(end='2026-10-12', periods=300)[0].date()
    query = item.request(first, date(2026,10,15), source_root=root)
    return context, replace(request, candidate=replace(request.candidate, definition=definition),
                            observation_requests=(query,)), calls, raw_calls


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_independent_300_day_warmup_prepares_evaluates_and_keys_cache(tmp_path, market):
    context, request, calls, raw_calls = independent_fixture(tmp_path, market)
    original_definition = request.candidate.definition
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        prepared = context.evaluation.prepare(request, execution=session)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=session)
        assert outcome.result is not None, outcome.error
        assert prepared.request.candidate.definition == original_definition
        assert prepared.request.history_start == date(2026,10,12)
        assert prepared.request.observation_requests == request.observation_requests
        assert all(call.query.start == date(2026,10,12) for call in raw_calls)
        first = date.fromisoformat(request.observation_requests[0].start) - timedelta(days=7)
        other = replace(request.observation_requests[0], start=first.isoformat())
        alternative = replace(request, observation_requests=(other,))
        second = context.evaluation.prepare(alternative, execution=session)
        assert second.request.observation_requests == (other,)
        assert second.request.input_binding != prepared.request.input_binding
        with patch.object(context.data, 'prepare', side_effect=AssertionError('exact cache hit required')):
            again = context.evaluation.prepare(request, execution=session)
        assert again.request.input_binding == prepared.request.input_binding
        with pytest.raises(ValueError, match='binding differs from prepared data'):
            context.evaluation.prepare(replace(alternative, input_binding=prepared.request.input_binding),
                                       execution=session)
    assert len(calls) == 2


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_independent_warmup_does_not_waive_required_rows(tmp_path, market):
    context, request, _, _ = independent_fixture(tmp_path, market)
    short = replace(request.observation_requests[0], start='2026-10-12')
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        with pytest.raises(ValueError, match='preparation failed'):
            context.evaluation.prepare(replace(request, observation_requests=(short,)), execution=session)


@pytest.mark.parametrize('case,match', [
    ('future', 'exceeds evaluation end'),
    ('cutoff', 'declared calendar and interval'),
    ('fixed_start', 'canonical start'),
    ('fixed_end', 'fixed end'),
    ('coverage', 'differs from declaration'),
    ('active_old_end', 'ends before required-from'),
    ('inactive_physical', 'inactive observation'),
])
def test_explicit_bounds_reject_contract_violations(tmp_path, case, match):
    context, request, _, _ = independent_fixture(tmp_path, MarketId.CN)
    item, = request.candidate.definition.observation_inputs
    query, = request.observation_requests
    if case == 'future':
        query = replace(query, end='2026-10-16')
    elif case == 'cutoff':
        query = replace(query, required_cutoff='2026-10-15')
    elif case == 'fixed_start':
        item = replace(item, history_start=date(2025,1,1))
    elif case == 'fixed_end':
        item = replace(item, history_start=date.fromisoformat(query.start), history_end=date(2026,10,14))
    elif case == 'coverage':
        query = replace(query, coverage=DataCoverageRequirement())
    else:
        item = replace(item, history_start=date.fromisoformat(query.start),
                       required_from=date(2026,10,14) if case == 'active_old_end' else date(2026,10,16))
        if case == 'active_old_end':
            query = replace(query, end='2026-10-13')
    definition = replace(request.candidate.definition, observation_inputs=(item,))
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        with patch.object(context.data, 'prepare', side_effect=AssertionError('reject before data access')):
            with pytest.raises(ValueError, match=match):
                invalid = replace(request, candidate=replace(request.candidate, definition=definition),
                                  observation_requests=(query,))
                context.evaluation.prepare(invalid, execution=session)


@pytest.mark.parametrize('kind', ['weekly', 'moneyflow'])
def test_explicit_calendar_sensitive_selections_are_revalidated(tmp_path, kind):
    context, request, _, _ = independent_fixture(tmp_path, MarketId.CN)

    def calendar(query):
        days = pd.date_range(query.start, query.end)
        return pd.DataFrame({'Date': days, 'IsOpen': [int(day.weekday() < 5) for day in days]}), {}

    context.data._providers[Dataset.TRADING_CALENDAR.value] = ProviderBinding('calendar', 'v1', calendar)
    item = DatasetObservationInput('signal', Dataset.ETF_OHLCV if kind == 'weekly' else Dataset.STOCK_MONEYFLOW,
        '510500.SH' if kind == 'weekly' else None, frequency='weekly' if kind == 'weekly' else 'daily',
        availability=ObservationAvailability('Asia/Shanghai', '15:00'))
    query = item.request(date(2026,10,5), date(2026,10,15), source_root=request.candidate.source_root,
                         trading_dates=('2026-10-05',) if kind == 'moneyflow' else ())
    if kind == 'moneyflow':
        assert query.parameters == MoneyflowParameters(('2026-10-05',))
    definition = replace(request.candidate.definition, observation_inputs=(item,))
    invalid = replace(request, candidate=replace(request.candidate, definition=definition),
                      observation_requests=(query,))
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        with pytest.raises(ValueError, match='declared calendar and interval'):
            context.evaluation.prepare(invalid, execution=session)
