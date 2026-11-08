"""Explicit seed-only periods never fabricate or fetch inactive dynamic inputs."""
from test_v4_inspection_roundtrip import prepare_raw_reference
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataset, MarketId, ProviderBinding, EquityProduct, TimeInterval, DataIdentity
from strategy_runtime import (DatasetObservationInput, DatasetObservationBinding, ObservationAvailability,
    TableObservationStatus, PreparedObservationTable, EquityInputBinding, equity_source_hash)
from strategy_runtime.observation_preparation import resolve_observation_requests
from czsc_trader.research_tools import ResearchExecutionSession
from czsc_trader.research_tools.equity_replay import materialize_equity
from czsc_trader.application import EquityInspectionReplay
from czsc_trader.application.equity_inspection import replay_account, _copy_inputs
from strategy_manager import freeze_contracts as f
from paper_trading_engine.equity_advice import prepare_equity_decision
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient, FormalV4Inputs
from test_equity_adjusted_observations import setup_adjusted


def fixture(tmp_path, market, *, start=date(2026,10,14), missing=False):
    context, request, products, _, _ = setup_adjusted(tmp_path, market)
    declaration = DatasetObservationInput('increment', Dataset.SHIBOR_DAILY, history_start=date(2026,10,11),
        availability=ObservationAvailability(request.candidate.instrument.timezone, '17:00'), required_from=start)
    root = request.candidate.source_root
    (root / 'strategy.py').write_text(
        'from strategy_runtime import AccountDecision, AccountStepResult, StateRecord, TableObservationStatus\n'
        'def step(ctx, state):\n'
        '    view = ctx.observations["increment"]\n'
        '    active = view.status is TableObservationStatus.ACTIVE\n'
        '    assert bool(view.rows) == active\n'
        '    return AccountStepResult(AccountDecision.from_facts(int(active), "activation", '
        'facts={"status":view.status.value}, next_watch="next source day"), cycle_values=StateRecord())\n', encoding='utf-8')
    candidate = replace(request.candidate, definition=replace(request.candidate.definition,
        source_sha256=equity_source_hash(root, ('strategy.py',)), observation_inputs=(declaration,)))
    calls = []
    def fetch(query):
        calls.append(query)
        days = pd.DatetimeIndex([]) if missing else pd.date_range(query.start, query.end)
        return pd.DataFrame({'Date': days, 'OvernightRate': [2.] * len(days)}), {'primary_key': ['Date']}
    context.data._providers[Dataset.SHIBOR_DAILY.value] = ProviderBinding('increment', 'v1', fetch)
    return context, replace(request, candidate=candidate), products, calls


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('before', [True, False])
def test_inactive_and_cross_activation_research_inspection_pte(tmp_path, market, before):
    context, request, products, calls = fixture(tmp_path, market,
        start=date(2026,10,20) if before else date(2026,10,14))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        payload = materialize_equity(outcome.result).payload
        request = prepared.request
    binding, = request.input_binding.observation_bindings
    assert bool(calls) is not before
    assert (binding.request is None) is before
    assert (binding.content_sha256 is None) is before
    assert ('observation:increment' in request.input_binding.expected_identities) is not before
    assert EquityInputBinding.from_dict(request.input_binding.to_dict()) == request.input_binding
    if before:
        facts = payload['audit_inputs']['decision_inputs']['observations']['increment']
        assert facts == {'status': 'INACTIVE', 'activation_at': request.candidate.definition.observation_inputs[0].activation_at.isoformat()}
        assert binding.inactive_through == date(2026,10,15)
        assert not payload['runs']['candidate']['fills']
    else:
        assert len(payload['runs']['candidate']['fills']) == 1
    replay = EquityInspectionReplay(f.InspectionCoordinate('activation','standard'), request.input_binding,
        request.requests(context.execution_spec), request.window, request.initial_cash, request.fee_rate,
        execution_reference=prepare_raw_reference(context, request))
    isolated, copied = _copy_inputs(context.data, replay, tmp_path / 'isolated-inputs')
    observed = replay_account(request.candidate, isolated, copied)
    assert observed['facts']['fills'] == payload['runs']['candidate']['fills']
    for row in products[EquityProduct.BARS].iloc[1:].itertuples():
        interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
        online = prepare_equity_decision(isolated, request.candidate, copied.input_binding,
            copied.requests, interval, fee_rate=request.fee_rate,
            execution_reference=copied.execution_reference.fetch(isolated, interval, latency_seconds=context.execution_spec.data_latency_seconds))
        from strategy_runtime.account_planning import AccountDecisionEngine
        view = AccountDecisionEngine(request.candidate, online.v4_replay).table_views(interval.start)['increment']
        expected = TableObservationStatus.INACTIVE if interval.start < binding.input.activation_at else TableObservationStatus.ACTIVE
        assert view.status is expected


def test_no_preparation_before_explicit_start_and_availability_offset(tmp_path):
    declaration = DatasetObservationInput('flow', Dataset.STOCK_MONEYFLOW, history_start=date(2026,10,10),
        availability=ObservationAvailability('Asia/Shanghai','17:00',1), required_from=date(2026,10,14))
    fake = SimpleNamespace(prepare=lambda *a, **kw: pytest.fail('inactive input must not fetch even its calendar'))
    assert resolve_observation_requests(fake,(declaration,),date(2026,10,12),date(2026,10,13),source_root=tmp_path) == (('observation:flow',None),)
    binding = DatasetObservationBinding(declaration,None,None,date(2026,10,13))
    assert DatasetObservationBinding.from_dict(MappingProxyType(binding.to_dict())) == binding
    assert 'content_sha256' not in binding.to_dict() and 'request' not in binding.to_dict()
    zone=ZoneInfo('Asia/Shanghai')
    assert declaration.activation_at == datetime(2026,10,15,17,tzinfo=zone)
    data = pd.DataFrame({'Date':pd.to_datetime(['2026-10-14']), 'AvailableDate':pd.to_datetime(['2026-10-14']), 'Symbol':['600000.SH'], 'NetMoneyflow':[1.]})
    identity=DataIdentity(Dataset.STOCK_MONEYFLOW.value,'fixture',None,'2026-10-14','2026-10-14','a'*64,
        {'primary_key':['Date','Symbol'],'source_time_field':'Date','availability_time_field':'AvailableDate',
         'source_calendar':'SSE','available_at':'EXPLICIT','request_range_policy':'EXACT'})
    table=PreparedObservationTable.from_frame(data,identity,declaration=declaration)
    assert table.view(datetime(2026,10,15,16,59,tzinfo=zone)).status is TableObservationStatus.INACTIVE
    assert len(table.view(declaration.activation_at)) == 1
    with pytest.raises(ValueError,match='empty interval'):
        replace(declaration,required_from=None).request(date(2026,10,8),date(2026,10,9),source_root=tmp_path)
    assert 'required_from' not in replace(declaration,required_from=None).to_dict()
    with pytest.raises(ValueError,match='unstarted declaration'):
        DatasetObservationBinding(declaration,None,None,date(2026,10,14))


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_active_missing_data_is_an_error(tmp_path, market):
    context, request, _, calls = fixture(tmp_path,market,missing=True)
    with ResearchExecutionSession(context,experiment=request.experiment) as session:
        with pytest.raises(ValueError,match='preparation failed'):
            context.evaluation.prepare(request,execution=session)
    assert calls


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
@pytest.mark.parametrize('missing', [False, True])
def test_forward_recipe_transitions_from_inactive_binding_to_actual_request(tmp_path,market,missing):
    context, request, products, calls = fixture(tmp_path,market,missing=missing)
    # Prepare a seed-only recipe ending before the dynamic source starts.
    from dataflows.equity_data import equity_metadata, sessions_from_metadata, session_record
    def ranged(binding):
        def fetch(query):
            frame,metadata=binding.fetch(query)
            p=query.parameters
            days=frame.Date.dt.tz_convert(p.instrument.timezone).dt.date
            frame=frame.loc[(days>=p.query.start)&(days<=p.query.end)].copy()
            source_sessions=sessions_from_metadata(metadata)
            sessions=tuple(s for s in source_sessions if p.query.start<=s.session_date<=p.query.end)
            following=next((s for s in source_sessions if s.session_date>p.query.end),None)
            following_record=session_record(following) if following is not None else metadata.get('following_session')
            metadata={**metadata, **equity_metadata(query,sessions,availability_basis='SYNTHETIC_BAR_CLOSE')}
            if p.query.product in (EquityProduct.TRADING_FACTS, EquityProduct.SESSIONS) and following_record is not None:
                metadata['following_session']=following_record
            return frame,metadata
        return ProviderBinding(binding.name,binding.revision,fetch)
    context.data._equity_providers={k:ranged(v) for k,v in context.data._equity_providers.items()}
    row=products[EquityProduct.BARS].iloc[1]
    seed_window=TimeInterval(row.BarStart.to_pydatetime(),row.Date.to_pydatetime())
    with ResearchExecutionSession(context,experiment=request.experiment) as session:
        request=context.evaluation.prepare(replace(request,window=seed_window),execution=session).request
    assert not calls
    recipe=FormalV4Inputs('a'*64,request.input_binding.for_observations(),request.fee_rate,
        prepare_raw_reference(context, request))
    client=FormalV4AdviceClient(repo_root=tmp_path,store=SimpleNamespace(virtual_account=lambda account:{'last_decision_payload':None}),dataflows=context.data,data_dir=tmp_path/'forward')
    first=client._forward_inputs('fixture',recipe,seed_window,cutoff=seed_window.start,candidate=request.candidate)
    client._save_interval(client._interval_path('fixture', recipe.release_hash, seed_window), first)
    assert first.binding.observation_bindings[0].request is None
    assert not calls
    with patch.object(context.data,'prepare',side_effect=AssertionError('pinned interval must be reused')):
        assert client._forward_inputs('fixture',recipe,seed_window,cutoff=seed_window.start,candidate=request.candidate) == first
    row=products[EquityProduct.BARS].iloc[-1]
    later=TimeInterval(row.BarStart.to_pydatetime(),row.Date.to_pydatetime())
    if missing:
        with pytest.raises(ValueError, match='preparation is incomplete'):
            client._forward_inputs('fixture',recipe,later,cutoff=later.start,candidate=request.candidate)
        assert len(calls) == 1
        assert not client._interval_path('fixture', recipe.release_hash, later).exists()
        return
    active=client._forward_inputs('fixture',recipe,later,cutoff=later.start,candidate=request.candidate)
    binding,=active.binding.observation_bindings
    assert binding.request.start == '2026-10-11'
    assert binding.request.end == '2026-10-14'
    assert binding.content_sha256 and binding.inactive_through is None
    assert len(calls) == 1
    from paper_trading_engine.execution_inputs import resolve_live_context
    calendar_request=next(query for role,query in active.binding.bind_requests(active.strategy_requests) if role=='sessions')
    calendar=context.data.fetch(calendar_request,prepared=active.binding.prepared)
    assert calendar.ready
    sessions=sessions_from_metadata(calendar.identity.metadata)
    # The synthetic calendar ends on Thursday; Friday is explicitly known for
    # the host's T+1 availability calculation, without adding a future price bar.
    tail=sessions[-1]
    assert tail.session_date == date(2026,10,15)
    next_session=replace(tail,session_date=date(2026,10,16),segments=tuple(
        TimeInterval(part.start+timedelta(days=1),part.end+timedelta(days=1)) for part in tail.segments))
    calendar_metadata={**calendar.identity.metadata,'sessions':[session_record(s) for s in (*sessions,next_session)]}
    execution_context=resolve_live_context(request.candidate,later,calendar.dataframe,calendar_metadata)
    online=prepare_equity_decision(context.data,request.candidate,active.binding,active.strategy_requests,later,
        fee_rate=request.fee_rate,live=True,execution_context=execution_context,
        execution_reference=active.execution_reference.fetch(context.data,later,
            latency_seconds=context.execution_spec.data_latency_seconds))
    from strategy_runtime.account_planning import AccountDecisionEngine
    view=AccountDecisionEngine(request.candidate,online.v4_replay).table_views(later.start)['increment']
    assert view.status is TableObservationStatus.ACTIVE and len(view) == 4
