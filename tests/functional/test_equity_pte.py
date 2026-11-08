"""US channel facts pass through the ordinary account and order lifecycle."""
from datetime import timedelta
from decimal import Decimal

import pytest
from dataflows import TimeInterval
from paper_trading_engine.ec_boundary import execution_permit
from strategy_runtime.inspection import InspectionRuntimePermit
from execution_channels.futu.store import PaperStore
from execution_channels.futu.broker import BrokerOrder
from paper_trading_engine.ec_boundary import execution_rules
from execution_channels.futu.equity_contracts import EQUITY_OFFLINE_CHANNEL_ID
from paper_trading_engine.equity_advice import prepare_equity_decision
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
    store = PaperStore(workspace / 'paper.db', inspection_permit=execution_permit(permit))
    store.create_virtual_account('us', 'US fixture', 'v1', 'a'*64, 1000, symbol='LITE', asset_type='stock',
        strategy_id='S999', strategy_name_snapshot='US fixture', strategy_version='v1', release_hash='a'*64,
        qualification_snapshot='INSPECTION', selection_data_cutoff='2026-09-30',
        channel_id=EQUITY_OFFLINE_CHANNEL_ID, equity_rules=execution_rules(request.candidate.instrument, context.execution_spec))
    store.set_virtual_paused('us', False)
    return context, request, store, permit








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










def test_legacy_equity_runtime_requires_explicit_v4_migration(tmp_path):
    from paper_trading_engine.execution_reference import PreparedExecutionReference
    context, request, _, _ = setup_formal_equity(tmp_path)
    request = prepare_inspection_inputs(context, request)
    interval = TimeInterval(request.window.start, request.window.start + timedelta(minutes=30))
    reference = PreparedExecutionReference(Decimal('10'), request.window.start, 'a'*64)
    with pytest.raises(ValueError, match='requires V4'):
        prepare_equity_decision(context.data, request.candidate, request.input_binding,
            request.requests(context.execution_spec), interval, fee_rate=request.fee_rate,
            execution_reference=reference)
