"""US channel facts pass through the ordinary account and order lifecycle."""
from datetime import timedelta
from decimal import Decimal

import pytest
from dataflows import TimeInterval
from strategy_runtime.inspection import InspectionRuntimePermit
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.store import PaperStore
from paper_trading_engine.broker import BrokerOrder
from paper_trading_engine.equity_contracts import EquityAccountRules, EquityOrderReport, EQUITY_OFFLINE_CHANNEL_ID
from paper_trading_engine.equity_advice import EquityAdviceClient, prepare_equity_decision
from paper_trading_engine.equity_execution import EquityExecution
from equity_test_support import setup_formal_equity


def prepare_inspection_inputs(context, request):
    """Prepare PTE V2 inputs directly, independently of research replay APIs."""
    from dataclasses import replace
    from dataflows import EquityProduct, PreparePolicy
    from strategy_runtime.equity_definition import EquityAuxiliaryBinding, EquityInputBinding
    prepared = context.data.prepare(request.requests(context.execution_spec), policy=PreparePolicy.REUSE)
    assert prepared.ready, [item.error for item in prepared.items]
    identities = {}
    for key, query in request.request_items(context.execution_spec):
        result = context.data.fetch(query, prepared=prepared.reference)
        assert result.ready, result.error
        identities[key] = result.identity.content_sha256
    binding = EquityInputBinding(prepared.reference, request.candidate.instrument,
        context.execution_spec.fingerprint,
        tuple((product.name.lower(), identities[product.name.lower()]) for product in EquityProduct),
        request.candidate.warmup_bars,
        auxiliary_inputs=tuple(EquityAuxiliaryBinding(item,
            identities[item.data_key(EquityProduct.BARS)], identities[item.data_key(EquityProduct.SESSIONS)])
            for item in request.candidate.definition.auxiliary_inputs))
    return replace(request, prepared=prepared.reference, input_binding=binding)


class RecordedChannel:
    channel_id = EQUITY_OFFLINE_CHANNEL_ID

    def place_order(self, intent):
        return BrokerOrder('recorded-' + intent.intent_id, intent.symbol, intent.side, intent.quantity,
            intent.limit_price, 'SUBMITTED', 0, 0., intent.intent_id, order_type=intent.order_type)


def equity_account(tmp_path, cash_policy=None, *, auxiliary=False):
    from equity_test_support import setup_auxiliary
    context, request, products, _ = (setup_auxiliary if auxiliary else setup_formal_equity)(tmp_path)
    if cash_policy is not None:
        from dataclasses import replace
        from strategy_runtime import StrategyRuntime
        from czsc_trader.research_tools.evaluation_access import EvaluationAccess
        from czsc_trader.research_tools import EquityBuyHold, EvaluationBenchmark
        spec = replace(context.execution_spec, account=replace(context.execution_spec.account,cash_availability=cash_policy))
        context = replace(context, execution_spec=spec, runtime=StrategyRuntime(execution_spec=spec),
            evaluation=EvaluationAccess(dataflows=context.data,strategy_id=context.strategy_id,execution_spec=spec))
        candidate = replace(request.candidate,definition=replace(request.candidate.definition,execution_spec=spec))
        request = replace(request,candidate=candidate,benchmark=EvaluationBenchmark(EquityBuyHold(spec)))
    request = prepare_inspection_inputs(context, request)
    workspace = tmp_path / '.tmp/strategy-inspection/us-test'
    isolated = workspace / 'repository'
    isolated.mkdir(parents=True)
    permit = InspectionRuntimePermit('us-test', 'S999-v1', 'a'*64, 'b'*64, 'c'*64, isolated, workspace)
    store = PaperStore(workspace / 'paper.db', inspection_permit=permit)
    store.create_virtual_account('us', 'US fixture', 'v1', 'a'*64, 1000, symbol='LITE', asset_type='stock',
        strategy_id='S999', strategy_name_snapshot='US fixture', strategy_version='v1', release_hash='a'*64,
        qualification_snapshot='INSPECTION', selection_data_cutoff='2026-09-30',
        channel_id=EQUITY_OFFLINE_CHANNEL_ID, equity_rules=EquityAccountRules(request.candidate.instrument, context.execution_spec))
    store.set_virtual_paused('us', False)
    return context, request, store, permit


@pytest.mark.parametrize('tamper', ['auxiliary', 'session'])
def test_equity_auxiliary_pte_authenticates_inputs_and_prepared_snapshot(tmp_path, tamper):
    from dataclasses import replace
    context, request, store, _ = equity_account(tmp_path, auxiliary=True)
    interval = TimeInterval(request.window.start, request.window.start + timedelta(minutes=30))
    requests = request.requests(context.execution_spec)
    binding = request.input_binding
    with pytest.raises(ValueError, match='lacks required products'):
        prepare_equity_decision(context.data, request.candidate, binding, requests[:-1], interval, fee_rate=request.fee_rate)
    corrupted = replace(binding, auxiliary_inputs=(replace(binding.auxiliary_inputs[0], bars_sha256='0' * 64),))
    with pytest.raises(ValueError, match='product identity differs'):
        prepare_equity_decision(context.data, request.candidate, corrupted, requests, interval, fee_rate=request.fee_rate)
    prepared = prepare_equity_decision(context.data, request.candidate, binding, requests, interval, fee_rate=request.fee_rate)
    assert prepared.history.Close.iloc[-1] == 10.
    assert prepared.auxiliary_histories['market'].Close.iloc[-1] == 100.
    assert prepared.auxiliary_histories['market'].Date.max() <= interval.start
    if tamper == 'auxiliary':
        prepared.auxiliary_histories['market'].loc[:, 'Close'] = 1.
    else:
        prepared.sessions.loc[:, 'SessionDate'] = '2026-01-01'
    engine = AccountEngine(store, EquityAdviceClient(store), now=lambda: interval.start)
    try:
        with pytest.raises(ValueError, match='decision inputs changed after authentication'):
            engine.refresh_account('us', prepared=prepared)
        clean = prepare_equity_decision(context.data, request.candidate, binding, requests, interval, fee_rate=request.fee_rate)
        engine.refresh_account('us', prepared=clean)
        assert store.account_intents('us')[0]['quantity'] == 98
    finally:
        store.close()


def test_equity_partial_fill_duplicate_restart_and_market_isolation(tmp_path):
    context, request, store, permit = equity_account(tmp_path)
    interval = TimeInterval(request.window.start, request.window.start + timedelta(minutes=30))
    prepared = prepare_equity_decision(context.data, request.candidate, request.input_binding,
        request.requests(context.execution_spec), interval, fee_rate=request.fee_rate)
    engine = AccountEngine(store, EquityAdviceClient(store), now=lambda: interval.start)
    engine.refresh_account('us', prepared=prepared)
    execution = EquityExecution(store, RecordedChannel(), now=lambda: interval.start)
    execution.reconcile(cash=Decimal('1000'), quantity=0, account_id='us')
    order_id, = execution.submit_pending('us')
    intent, = store.account_intents('us')
    assert intent['quantity'] == 98
    partial = EquityOrderReport(order_id, 3, Decimal('10'), interval.start + timedelta(minutes=1), 'FILLED_PART')
    execution.apply_report(partial)
    assert store.virtual_account('us')['quantity'] == 3
    execution.apply_report(partial)
    assert store.virtual_account('us')['quantity'] == 3
    path = store.path
    store.close()
    with pytest.raises(Exception, match='inspection'):
        PaperStore(path)
    store = PaperStore(path, inspection_permit=permit)
    execution = EquityExecution(store, RecordedChannel(), now=lambda: interval.start)
    execution.apply_report(EquityOrderReport(order_id, 98, Decimal('10'), interval.start + timedelta(minutes=2), 'FILLED_ALL'))
    assert store.virtual_account('us')['quantity'] == 98
    assert not store.account_invariant_violations()
    with pytest.raises(ValueError,match='fill is later'):
        AccountEngine(store,EquityAdviceClient(store),now=lambda:interval.start).refresh_account('us',prepared=prepared)
    for status,quantity,at,match in [
            ('SUBMITTED',98,interval.start+timedelta(minutes=2),'terminal'),
            ('FILLED_ALL',98,interval.start+timedelta(minutes=1),'backwards')]:
        with pytest.raises(ValueError,match=match):
            execution.apply_report(EquityOrderReport(order_id,quantity,Decimal('10'),at,status))
    store.close()


@pytest.mark.parametrize('case',['action','payment'])
def test_future_confirmed_equity_event_cannot_enter_past_decision(tmp_path,case):
    context, request, store, _ = equity_account(tmp_path)
    interval = TimeInterval(request.window.start,request.window.start+timedelta(minutes=30))
    prepared = prepare_equity_decision(context.data,request.candidate,request.input_binding,
        request.requests(context.execution_spec),interval,fee_rate=request.fee_rate)
    effective = interval.end if case == 'action' else interval.start
    store.apply_equity_event('us',event_id='future-confirmed',kind='CASH_DIVIDEND',effective_at=effective,
        available_at=effective,source_sha256='f'*64,cash_per_share=Decimal('.1'),pay_at=interval.end)
    if case == 'payment':
        store.settle_equity_receivables('us',at=interval.end)
    with pytest.raises(ValueError,match=case+' is later'):
        AccountEngine(store,EquityAdviceClient(store),now=lambda:interval.start).refresh_account('us',prepared=prepared)
    assert not store.account_decisions('us')
    store.close()


def equity_protocol(context, request):
    from strategy_runtime.inspection import collect_inspection_environment
    from paper_trading_engine.equity_inspection import (EquityPteDecision, EquityPteReport, EquityPteRestart,
        EquityPteReconcile, EquityPteScenario, EquityPteInspectionProtocol)
    interval = TimeInterval(request.window.start, request.window.start + timedelta(minutes=30))
    reconcile = EquityPteReconcile(Decimal('1000'), 0)
    buy = EquityPteDecision(interval, interval.start)
    partial = EquityPteReport(0, 3, Decimal('10'), interval.start+timedelta(minutes=1), 'FILLED_PART')
    complete = EquityPteReport(0, 98, Decimal('10'), interval.start+timedelta(minutes=2), 'FILLED_ALL')
    scenarios = [EquityPteScenario('partial-restart', (reconcile,buy,partial,partial,EquityPteRestart(),complete), Decimal('19.02'),98,Decimal(0))]
    for code, outcome, at in [('REJECTED','REJECTED',interval.start),('UNKNOWN','UNKNOWN',interval.start),('EXPIRED','ACCEPTED',interval.end)]:
        scenarios.append(EquityPteScenario(code, (reconcile,EquityPteDecision(interval,at,outcome,code)),
            Decimal('9.2102') if code in {'UNKNOWN','EXPIRED'} else Decimal('1000'), 0, Decimal(0)))
    scenarios.append(EquityPteScenario('mismatch', (EquityPteReconcile(Decimal('999'),0),
        EquityPteDecision(interval,interval.start,expected='RECONCILIATION_BLOCKED')),Decimal(1000),0,Decimal(0)))
    return EquityPteInspectionProtocol(collect_inspection_environment(context.repository.root),tuple(scenarios))


def test_equity_runner_rejects_unverified_release(tmp_path):
    from paper_trading_engine.equity_inspection import inspect_equity_release, EquityPteInspectionProtocol
    context, request, store, permit = equity_account(tmp_path)
    store.close()
    protocol = equity_protocol(context, request)
    assert EquityPteInspectionProtocol.from_dict(protocol.to_dict()) == protocol
    with pytest.raises(Exception, match='release|file|目录|系统|package'):
        inspect_equity_release(candidate=request.candidate,dataflows=context.data,binding=request.input_binding,
            requests=request.requests(context.execution_spec),initial_cash=request.initial_cash,fee_rate=request.fee_rate,
            permit=permit,protocol=protocol)


def test_equity_events_settled_sale_and_market_rules(tmp_path):
    from strategy_runtime import CashAvailabilityPolicy
    context, request, store, permit = equity_account(tmp_path,CashAvailabilityPolicy.SETTLED_ONLY)
    start = request.window.start
    interval = TimeInterval(start,start+timedelta(minutes=30))
    execution = EquityExecution(store,RecordedChannel(),now=lambda:interval.start)
    def decide():
        prepared = prepare_equity_decision(context.data,request.candidate,request.input_binding,
            request.requests(context.execution_spec),interval,fee_rate=request.fee_rate)
        AccountEngine(store,EquityAdviceClient(store),now=lambda:interval.start).refresh_account('us',prepared=prepared)
        account = store.virtual_account('us')
        execution.reconcile(cash=Decimal(account['cash'])+Decimal(account['frozen_cash']),quantity=account['quantity'],account_id='us')
        return execution.submit_pending('us')[0]
    buy = decide()
    execution.apply_report(EquityOrderReport(buy,98,Decimal('10'),start+timedelta(minutes=1),'FILLED_ALL'))
    action = dict(event_id='dividend',kind='CASH_DIVIDEND',effective_at=start+timedelta(minutes=2),
        available_at=start,source_sha256='d'*64,cash_per_share=Decimal('.1'),pay_at=start+timedelta(hours=2))
    assert store.apply_equity_event('us',**action)
    assert not store.apply_equity_event('us',**action)
    with pytest.raises(ValueError,match='different facts'):
        store.apply_equity_event('us',**{**action,'cash_per_share':Decimal('.2')})
    assert Decimal(store.virtual_account('us')['receivable']) == Decimal('9.8')
    interval = TimeInterval(interval.end,interval.end+timedelta(minutes=30))
    sell = decide()
    execution.apply_report(EquityOrderReport(sell,98,Decimal('10'),interval.start+timedelta(minutes=1),
        'FILLED_ALL',start+timedelta(hours=3)))
    assert Decimal(store.virtual_account('us')['cash']) == Decimal('19.02')
    assert Decimal(store.virtual_account('us')['receivable']) == Decimal('988.82')
    assert store.settle_equity_receivables('us',at=start+timedelta(hours=2)) == 1
    assert store.settle_equity_receivables('us',at=start+timedelta(hours=2)) == 0
    path = store.path
    store.close()
    store = PaperStore(path,inspection_permit=permit)
    assert store.settle_equity_receivables('us',at=start+timedelta(hours=3)) == 1
    assert Decimal(store.virtual_account('us')['cash']) == Decimal('1007.84')
    assert not store.account_invariant_violations()
    with pytest.raises(ValueError,match='mix market'):
        store.create_virtual_account('cn','CN','v1','a'*64,1000,strategy_id='S999',strategy_name_snapshot='CN',
            strategy_version='v1',release_hash='a'*64,qualification_snapshot='INSPECTION',selection_data_cutoff='2026-09-30')
    store.close()


def test_split_pending_order_conflict_and_idempotent_adjustment(tmp_path):
    context, request, store, _ = equity_account(tmp_path)
    interval = TimeInterval(request.window.start, request.window.start+timedelta(minutes=30))
    prepared = prepare_equity_decision(context.data,request.candidate,request.input_binding,
        request.requests(context.execution_spec),interval,fee_rate=request.fee_rate)
    AccountEngine(store,EquityAdviceClient(store),now=lambda:interval.start).refresh_account('us',prepared=prepared)
    execution = EquityExecution(store,RecordedChannel(),now=lambda:interval.start)
    execution.reconcile(cash=Decimal('1000'),quantity=0,account_id='us')
    order, = execution.submit_pending('us')
    execution.apply_report(EquityOrderReport(order,3,Decimal('10'),interval.start+timedelta(minutes=1),'FILLED_PART'))
    action = dict(event_id='split',kind='SPLIT',effective_at=interval.end,available_at=interval.start,
                  source_sha256='e'*64,ratio=Decimal('2'))
    with pytest.raises(ValueError,match='outstanding'):
        store.apply_equity_event('us',**action)
    execution.apply_report(EquityOrderReport(order,98,Decimal('10'),interval.start+timedelta(minutes=2),'FILLED_ALL'))
    assert store.apply_equity_event('us',**action)
    assert not store.apply_equity_event('us',**action)
    account = store.virtual_account('us')
    assert account['quantity'] == 196
    assert Decimal(account['average_cost']) == Decimal('5.005')
    assert not store.account_invariant_violations()
    with pytest.raises(ValueError,match='fractional'):
        store.apply_equity_event('us',**{**action,'event_id':'fractional','ratio':Decimal('.001')})
    store.close()


def test_equity_utc_dst_half_day_boundaries_and_unprepared_interval(tmp_path):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from paper_trading_engine.equity_contracts import require_equity_interval
    context, request, store, _ = equity_account(tmp_path)
    rules = store.equity_account_rules('us')
    ny = ZoneInfo('America/New_York')
    for month,day,hour in [(10,30,13),(11,2,14)]:
        start = datetime(2026,month,day,9,30,tzinfo=ny)
        interval = TimeInterval(start,start+timedelta(minutes=30))
        assert start.astimezone(timezone.utc).hour == hour
        assert require_equity_interval(interval,start.astimezone(timezone.utc),rules) == start.date().isoformat()
    halfday = TimeInterval(datetime(2026,11,27,12,30,tzinfo=ny),datetime(2026,11,27,13,tzinfo=ny))
    assert require_equity_interval(halfday,halfday.start,rules) == '2026-11-27'
    with pytest.raises(ValueError,match='outside'):
        require_equity_interval(halfday,halfday.end,rules)
    invalid = TimeInterval(request.window.start+timedelta(hours=8),request.window.start+timedelta(hours=8,minutes=30))
    with pytest.raises(ValueError,match='absent'):
        prepare_equity_decision(context.data,request.candidate,request.input_binding,
            request.requests(context.execution_spec),invalid,fee_rate=request.fee_rate)
    store.close()
