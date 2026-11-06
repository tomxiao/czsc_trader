"""Native frozen V4 admission and forward decisions on isolated CN/US fixtures."""
from datetime import timedelta
from dataclasses import asdict, replace
from decimal import Decimal
from zoneinfo import ZoneInfo
from unittest.mock import patch
import json

import pytest
import pandas as pd
from dataflows import MarketId, EquityProduct, TimeInterval, ProviderBinding
from dataflows.equity_data import equity_metadata, sessions_from_metadata
from strategy_manager import PaperTradingApproval, StrategyRegistry
from czsc_trader.application import deploy_strategy
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.channel import ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID
from paper_trading_engine.equity_contracts import EquityAccountRules
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient, FormalV4ScheduleProvider, FormalV4Inputs
from paper_trading_engine.store import PaperStore
from test_v4_inspection_roundtrip import native_fixture, native_inspection_request, freeze_native_inspection
from test_equity_adjusted_observations import setup_adjusted


@pytest.fixture(params=[MarketId.CN, MarketId.US])
def formal_v4(tmp_path, request):
    market, successor = request.param if isinstance(request.param, tuple) else (request.param, False)
    def action_fixture(*args, **kwargs):
        result = setup_adjusted(*args, **kwargs)
        products = result[2]
        event_at = products[EquityProduct.BARS].iloc[2].BarStart
        pay_at = products[EquityProduct.BARS].iloc[3].BarStart
        products[EquityProduct.ACTIONS] = pd.DataFrame([
            dict(Date=event_at, AvailableDate=event_at, EventId='a-split', Kind='SPLIT',
                 Ratio=2., CashPerShare=0., PayAt=None),
            dict(Date=event_at, AvailableDate=event_at, EventId='b-dividend', Kind='CASH_DIVIDEND',
                 Ratio=1., CashPerShare=.1, PayAt=pay_at),
            dict(Date=pay_at, AvailableDate=pay_at, EventId='c-known-later', Kind='CASH_DIVIDEND',
                 Ratio=1., CashPerShare=0., PayAt=pay_at)])
        return result
    with patch('test_v4_inspection_roundtrip.setup_adjusted', side_effect=action_fixture):
        context, evaluation, products, replay = native_fixture(tmp_path, market)
    inspection, source = native_inspection_request(tmp_path, context, evaluation, products, replay)
    freeze_native_inspection(context.repository, inspection, source)
    repository = context.repository
    assert deploy_strategy(repository, 'S999-v1').status == 'PASS'
    registry = StrategyRegistry(repository.strategy_root)
    version = registry.get_version('S999', 'v1')
    root = PaperStore(tmp_path / 'formal.db')
    channel = FUTU_SIMULATE_CN_CHANNEL_ID if market is MarketId.CN else FUTU_US_SIM_CHANNEL_ID
    store = root.register_channel_account(ChannelAccountConfig('formal-channel', channel, 1234), capital=Decimal('1000000'))
    client = FormalV4AdviceClient(repo_root=tmp_path, store=store, dataflows=context.data, data_dir=tmp_path / 'runtime-data')
    with pytest.raises(Exception, match='not approved'):
        client.load_release('S999', 'v1')
    registry.approve_paper_trading(PaperTradingApproval('S999', 'v1', version.release_hash,
        'DEV', 'synthetic isolated fixture approval'))
    if successor:
        next_inspection = replace(inspection, target=replace(inspection.target,
            version='v2', parent_version='v1', change_summary='native V4 successor fixture'))
        freeze_native_inspection(context.repository, next_inspection, source, version='v2')
        assert deploy_strategy(repository, 'S999-v2').status == 'PASS'
        target = registry.get_version('S999', 'v2')
        registry.approve_paper_trading(PaperTradingApproval('S999', 'v2', target.release_hash,
            'DEV', 'synthetic successor approval'))
    release, candidate, _ = client.load_release('S999', 'v1')
    binding = client.validate_account_binding(strategy_id='S999', strategy_version='v1',
        symbol=candidate.instrument.symbol, asset='stock', fee_rate=evaluation.fee_rate)
    assert binding.instrument == candidate.instrument
    store.create_virtual_account('formal', 'formal', 'v1', release.release_hash, evaluation.initial_cash,
        symbol=candidate.instrument.symbol, asset_type='stock', strategy_id='S999',
        strategy_name_snapshot='native', strategy_version='v1', release_hash=release.release_hash,
        qualification_snapshot='PAPER_READY', selection_data_cutoff='2026-10-12', channel_id=channel,
        equity_rules=EquityAccountRules(candidate.instrument, candidate.definition.execution_spec))
    store.set_virtual_paused('formal', False)
    client.register_inputs('formal', evaluation.input_binding,
        expected_release_hash=release.release_hash, fee_rate=evaluation.fee_rate)
    # Real DFLS publications must obey each forward query's independent range.
    # The research fixture intentionally returned the whole fixed test window.
    def ranged(binding):
        def fetch(request):
            frame, metadata = binding.fetch(request)
            p = request.parameters
            days = frame.Date.dt.tz_convert(ZoneInfo(p.instrument.timezone)).dt.date
            frame = frame.loc[(days >= p.query.start) & (days <= p.query.end)].copy()
            if p.query.product is EquityProduct.ACTIONS and frame.empty:
                start = products[EquityProduct.BARS].iloc[0].BarStart
                frame = pd.DataFrame([dict(Date=start, AvailableDate=start, EventId='none', Kind='NONE',
                                          Ratio=1., CashPerShare=0., PayAt=None)])
            sessions = tuple(s for s in sessions_from_metadata(metadata)
                             if p.query.start <= s.session_date <= p.query.end)
            metadata = equity_metadata(request, sessions, availability_basis='SYNTHETIC_BAR_CLOSE')
            metadata['no_actions_verified'] = True
            return frame, metadata
        return ProviderBinding(binding.name, binding.revision, fetch)
    context.data._equity_providers = {key: ranged(value)
        for key, value in context.data._equity_providers.items()}
    row = products[EquityProduct.BARS].loc[lambda frame: frame.BarStart >= evaluation.window.start].iloc[0]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    yield client, store, root, interval, candidate, evaluation
    root.close()


def test_formal_v4_forward_decision_uses_historical_prices_and_exact_deployment(formal_v4):
    client, store, _, interval, candidate, evaluation = formal_v4
    client.register_recipe('formal', client.inputs('formal'))
    prepared = client.prepare_interval('formal', interval, observed_at=interval.start)
    assert prepared.live_interval
    assert max(prepared.v4_replay._data.ends) <= interval.start
    assert interval.start not in prepared.v4_replay._data.starts
    assert prepared.candidate.source_root.is_relative_to(client.repo_root / 'strategies')
    assert prepared.candidate.definition == candidate.definition
    # DAILY recipes forward independently pinned history/calendars/constraints.
    assert prepared.binding.prepared != evaluation.input_binding.prepared
    assert max(prepared.v4_replay._data.ends) < interval.start
    assert prepared.binding.expected_identities != evaluation.input_binding.expected_identities
    from strategy_runtime.account_planning import AccountDecisionEngine
    with pytest.raises(ValueError, match='absent from declared calendar or input grid'):
        AccountDecisionEngine(candidate, prepared.v4_replay).observation(interval)
    unavailable = dict(prepared.v4_constraint, Date=interval.start,
                       AvailableDate=interval.start + timedelta(seconds=1))
    with pytest.raises(ValueError, match='available trading rules'):
        AccountDecisionEngine(candidate, prepared.v4_replay, live_constraint=unavailable)
    engine = AccountEngine(store, client, now=lambda: interval.start)
    provider = FormalV4ScheduleProvider(client, engine)
    task = provider.due_decision(store.virtual_account('formal'), interval.start)
    assert task.interval == interval
    provider.run_scheduled('formal', task, interval.start)
    document = json.loads(store.virtual_account('formal')['account_v4_json'])
    assert document['state']['revision'] == 1
    assert store.account_intents('formal')
    provider.run_scheduled('formal', task, interval.start + timedelta(seconds=1))
    assert json.loads(store.virtual_account('formal')['account_v4_json']) == document
    # An independent cumulative channel fill enters the same shared store path.
    from paper_trading_engine.broker import BrokerOrder
    from paper_trading_engine.order_reports import apply_order_report
    intent, = store.account_intents('formal')
    store.set_setting('channel_reconciliation_status', 'OK')
    store.set_setting('futu_cash_reconciliation_status', 'OK')
    assert store.claim_account_intent(intent['intent_id'], moment=interval.start)
    order = BrokerOrder('formal-fill', candidate.instrument.symbol, 'BUY', intent['quantity'],
                        float(intent['limit_price']), 'SUBMITTED', 0, 0., intent['intent_id'])
    store.bind_channel_order(intent['intent_id'], order.channel_order_id, asdict(order))
    report = dict(asdict(order), status='FILLED_ALL', cumulative_filled_quantity=intent['quantity'],
                  average_fill_price=10.)
    apply_order_report(store, report, occurred_at=(interval.start + timedelta(minutes=1)).isoformat())
    assert store.virtual_account('formal')['quantity'] == intent['quantity']
    with pytest.raises(ValueError, match='not currently executable'):
        client.prepare_interval('formal', interval, observed_at=interval.end)
    with pytest.raises(ValueError, match='identity differs'):
        client.register_inputs('formal', evaluation.input_binding,
            expected_release_hash='0' * 64, fee_rate=evaluation.fee_rate)
    # A restart reads the explicit publication; no replacement data is prepared.
    reopened = FormalV4AdviceClient(repo_root=client.repo_root, store=store,
                                   dataflows=client.dataflows, data_dir=client.data_dir)
    assert reopened.inputs('formal') == client.inputs('formal')
    # Repeated interval preparation survives a restart without invoking providers.
    with patch.object(reopened.dataflows, 'prepare', side_effect=AssertionError('must reuse interval archive')):
        assert reopened.prepare_interval('formal', interval, observed_at=interval.start).binding == prepared.binding
    next_interval = TimeInterval(interval.start + timedelta(days=1), interval.end + timedelta(days=1))
    next_prepared = reopened.prepare_interval('formal', next_interval, observed_at=next_interval.start)
    assert next_prepared.binding.prepared != prepared.binding.prepared
    assert max(next_prepared.v4_replay._data.ends) == interval.end
    reopened.apply_account_events('formal', next_prepared)
    assert store.virtual_account('formal')['quantity'] == 2 * intent['quantity']
    assert Decimal(store.virtual_account('formal')['receivable']) == Decimal('.2') * intent['quantity']
    after_actions = store.virtual_account('formal')
    reopened.apply_account_events('formal', next_prepared)
    assert store.virtual_account('formal') == after_actions
    payment_interval = TimeInterval(next_interval.start + timedelta(days=1), next_interval.end + timedelta(days=1))
    payment_prepared = reopened.prepare_interval('formal', payment_interval, observed_at=payment_interval.start)
    assert payment_prepared.binding.expected_identities['actions'] != next_prepared.binding.expected_identities['actions']
    assert payment_prepared.required_actions[:2] == next_prepared.required_actions
    reopened.apply_account_events('formal', payment_prepared)
    after_payment = store.virtual_account('formal')
    assert Decimal(after_payment['receivable']) == 0
    assert Decimal(after_payment['cash']) == Decimal(after_actions['cash']) + Decimal('.2') * intent['quantity']
    reopened.apply_account_events('formal', payment_prepared)
    assert store.virtual_account('formal') == after_payment
    archive = reopened._interval_path('formal', store.virtual_account('formal')['release_hash'], interval)
    archive.unlink()
    with pytest.raises(ValueError, match='input record is missing'):
        reopened.prepare_interval('formal', interval, observed_at=interval.start)
    path = candidate.source_root / candidate.definition.source_files[0]
    original = path.read_bytes()
    try:
        path.write_bytes(original + b'\n# tampered frozen bytes\n')
        with pytest.raises(Exception, match='differs|hash'):
            reopened.load_release('S999', 'v1')
    finally:
        path.write_bytes(original)


def test_formal_input_contract_rejects_unknown_fields():
    with pytest.raises(ValueError, match='unsupported'):
        FormalV4Inputs.from_dict({'schema_version': 1, 'extra': True})


def test_formal_v4_maintenance_prepares_data_without_adopting_interval(formal_v4):
    client, store, _, interval, _, _ = formal_v4
    client.register_recipe('formal', client.inputs('formal'))
    account = store.virtual_account('formal')
    archive = client._interval_path('formal', account['release_hash'], interval)
    result = client.prepare_data('formal', interval, as_of=interval.end + timedelta(hours=1))
    assert result.ready and result.reference is not None
    prices = [item.request for item in result.items if getattr(item.request.parameters, 'query', None)
              and item.request.parameters.query.product is EquityProduct.BARS]
    assert prices and all(request.parameters.query.end < interval.start.astimezone(
        ZoneInfo(request.parameters.instrument.timezone)).date() for request in prices)
    assert not archive.exists()
    assert store.virtual_account('formal') == account
    assert not store.account_intents('formal')


def test_legacy_cutover_blocks_dividend_payment_crossing_the_boundary(formal_v4):
    client, store, _, interval, _, _ = formal_v4
    recipe = client.inputs('formal')
    payment_interval = TimeInterval(interval.start + timedelta(days=2), interval.end + timedelta(days=2))
    record = {'inputs': recipe.to_dict(), 'forward': True,
              'effective_interval': {'start': payment_interval.start.isoformat(), 'end': payment_interval.end.isoformat()},
              'legacy_actions_before': payment_interval.start.isoformat()}
    with patch.object(store, 'v4_runtime_binding', return_value=record):
        with pytest.raises(ValueError, match='pre-cutover dividend has unresolved payment'):
            client.prepare_interval('formal', payment_interval, observed_at=payment_interval.start)
    assert not store.account_intents('formal')
    assert Decimal(store.virtual_account('formal')['receivable']) == 0
