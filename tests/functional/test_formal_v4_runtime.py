# Risk ownership: E2E-01
"""Native frozen V5 admission and forward decisions on isolated CN/US fixtures."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal
from zoneinfo import ZoneInfo
from unittest.mock import patch
import json
import shutil
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import pandas as pd
from dataflows import MarketId, EquityProduct, TimeInterval, ProviderBinding, EquityDataRequest, PriceAdjustment, PreparePolicy
from dataflows.equity_data import equity_metadata, session_record, sessions_from_metadata
from strategy_manager import PaperTradingApproval, StrategyRegistry
from paper_trading_engine.account_engine import AccountEngine
from execution_channels.futu.channel import ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID
from paper_trading_engine.ec_boundary import execution_rules
from paper_trading_engine.equity_runtime import EquityRuntimeAdviceClient, EquityScheduleProvider
from execution_channels.futu.store import PaperStore
from test_v4_inspection_roundtrip import native_fixture
from paper_trading_engine.execution_reference import ExecutionReferenceBinding


def raw_binding(dataflows, binding):
    primary = dict(binding.request_bindings)['bars']
    parameters = replace(primary, query=replace(primary.query, adjustment=PriceAdjustment.NONE))
    request = EquityDataRequest(parameters.instrument, parameters.source, parameters.query)
    result = dataflows.prepare((request,), policy=PreparePolicy.REUSE)
    assert result.ready
    return ExecutionReferenceBinding(parameters, result.reference, result.items[0].identity.content_sha256)


def _install_v5_fixture(repository, candidate, reference):
    from czsc_trader.application.runtime_migration import _upgrade_json, _upgrade_materials
    from strategy_manager import canonical_sha256

    registry = StrategyRegistry(repository.strategy_root)
    family, version = reference.rsplit('-', 1)
    upgraded, manifest, contents, _ = _upgrade_materials(candidate, registry.get_version(family, version))
    package = repository.strategy_root / family / 'releases' / version
    for relative, data in contents.items():
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    version_path = repository.strategy_root / family / 'versions' / f'{version}.json'
    version_path.write_bytes(_upgrade_json(upgraded.to_dict()))
    receipt_path = repository.strategy_root / 'deployments' / f'{reference}.json'
    receipt = json.loads(receipt_path.read_bytes())
    receipt.update(strategy_version_hash=upgraded.release_hash, package_hash=manifest['package_hash'])
    receipt.pop('receipt_hash')
    receipt_path.write_bytes(_upgrade_json({**receipt, 'receipt_hash': canonical_sha256(receipt)}))
    return upgraded


@pytest.fixture(params=[MarketId.CN, MarketId.US])
def formal_v4(tmp_path, request):
    market, successor = request.param if isinstance(request.param, tuple) else (request.param, False)
    context, evaluation, products, replay = native_fixture(tmp_path, market)
    repository = context.repository
    # Already inspected/frozen synthetic bytes; lifecycle tests own fresh creation.
    # Every consumer gets independent registry, approval, inputs and account state.
    seed = Path(__file__).parents[1] / 'fixtures/published' / f'{market.value}-{int(successor)}'
    shutil.copytree(seed, repository.strategy_root, dirs_exist_ok=True)
    registry = StrategyRegistry(repository.strategy_root)
    # Single-connection business flows use real SQLite without durability I/O.
    # Rebinding consumers back up this source into their own disk-backed runtime.
    root = PaperStore(Path(':memory:'))
    channel = FUTU_SIMULATE_CN_CHANNEL_ID if market is MarketId.CN else FUTU_US_SIM_CHANNEL_ID
    store = root.register_channel_account(ChannelAccountConfig('formal-channel', channel, 1234), capital=Decimal('1000000'))
    client = EquityRuntimeAdviceClient(repo_root=tmp_path, store=store, dataflows=context.data, data_dir=tmp_path / 'runtime-data')
    version = _install_v5_fixture(repository, evaluation.candidate, 'S999-v1')
    if successor:
        second = _install_v5_fixture(repository, evaluation.candidate, 'S999-v2')
        registry.approve_paper_trading(PaperTradingApproval('S999', 'v2', second.release_hash,
            'DEV', 'synthetic isolated successor approval'))
    with pytest.raises(Exception, match='not approved'):
        client.load_release('S999', 'v1')
    registry.approve_paper_trading(PaperTradingApproval('S999', 'v1', version.release_hash,
        'DEV', 'synthetic isolated fixture approval'))
    release, candidate, _ = client.load_release('S999', 'v1')
    assert candidate.content_identity == evaluation.candidate.content_identity
    binding = client.validate_account_binding(strategy_id='S999', strategy_version='v1',
        symbol=candidate.instrument.symbol, asset='stock', fee_rate=evaluation.fee_rate)
    assert binding.instrument == candidate.instrument
    store.create_virtual_account('formal', 'formal', 'v1', release.release_hash, evaluation.initial_cash,
        symbol=candidate.instrument.symbol, asset_type='stock', strategy_id='S999',
        strategy_name_snapshot='native', strategy_version='v1', release_hash=release.release_hash,
        qualification_snapshot='PAPER_READY', selection_data_cutoff='2026-10-12', channel_id=channel,
        equity_rules=execution_rules(candidate.instrument, candidate.definition.execution_spec))
    store.set_virtual_paused('formal', False)
    reference = replay.execution_reference
    assert isinstance(reference, ExecutionReferenceBinding)
    primary = dict(evaluation.input_binding.request_bindings)['bars']
    assert reference.parameters == replace(primary, query=replace(primary.query, adjustment=PriceAdjustment.NONE))
    client.register_inputs('formal', evaluation.input_binding,
        expected_release_hash=release.release_hash, fee_rate=evaluation.fee_rate,
        execution_reference=reference)
    # Real DFLS publications must obey each forward query's independent range.
    # The research fixture intentionally returned the whole fixed test window.
    def ranged(binding):
        def fetch(request):
            frame, metadata = binding.fetch(request)
            p = request.parameters
            calendar = sessions_from_metadata(metadata)
            # Explicit extra synthetic session for online T+1 sellability; no price row is added.
            if p.query.product is EquityProduct.SESSIONS and p.query.end > calendar[-1].session_date:
                from dataflows import TradingSession
                last = calendar[-1]
                following_session = TradingSession(last.session_date + timedelta(days=1), last.timezone,
                    tuple(TimeInterval(part.start + timedelta(days=1), part.end + timedelta(days=1))
                          for part in last.segments))
                calendar = (*calendar, following_session)
                opening = following_session.segments[0].start
                frame = pd.concat([frame, pd.DataFrame([{'Date': opening, 'AvailableDate': opening,
                    'SessionDate': following_session.session_date.isoformat()}])], ignore_index=True)
            days = frame.Date.dt.tz_convert(ZoneInfo(p.instrument.timezone)).dt.date
            frame = frame.loc[(days >= p.query.start) & (days <= p.query.end)].copy()
            following = next((session_record(s) for s in calendar if s.session_date > p.query.end),
                             metadata.get('following_session'))
            sessions = tuple(s for s in calendar if p.query.start <= s.session_date <= p.query.end)
            acquisition = metadata.get('acquisition_method')
            metadata = equity_metadata(request, sessions, availability_basis='SYNTHETIC_BAR_CLOSE')
            if acquisition is not None:
                metadata['acquisition_method'] = acquisition
            if p.query.product is EquityProduct.TRADING_FACTS and following is not None:
                metadata['following_session'] = following
            return frame, metadata
        return ProviderBinding(binding.name, binding.revision, fetch)
    context.data._equity_providers = {key: ranged(value)
        for key, value in context.data._equity_providers.items()}
    row = products[EquityProduct.BARS].loc[lambda frame: frame.BarStart >= evaluation.window.start].iloc[0]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    yield client, store, root, interval, candidate, evaluation
    root.close()




def test_daily_decision_prepares_after_close_and_waits_for_next_session(formal_v4):
    client, store, _, interval, candidate, _ = formal_v4
    client.register_recipe('formal', client.inputs('formal'))
    calendar = client._calendar_products(client.recipe('formal'), interval.start)['sessions']
    sessions = sessions_from_metadata(calendar.identity.metadata)
    previous = max((s for s in sessions if s.segments[-1].end < interval.start),
                   key=lambda s: s.session_date)
    gate = previous.segments[-1].end + timedelta(hours=5)
    client._calendar_products(client.recipe('formal'), gate)
    engine = AccountEngine(store, client, now=lambda: gate)
    provider = EquityScheduleProvider(client, engine)
    account = store.virtual_account('formal')
    with patch.object(client.dataflows, 'prepare', side_effect=AssertionError('prices before close gate')):
        assert provider.due_decision(account, gate - timedelta(seconds=1)) is None
        with pytest.raises(ValueError, match='close plus 5 hours'):
            client.prepare_interval('formal', interval, observed_at=gate - timedelta(seconds=1))
        with pytest.raises(ValueError, match='close plus 5 hours'):
            client.prepare_data('formal', interval, as_of=gate - timedelta(seconds=1))
    task = provider.due_decision(account, gate)
    assert task.decision_at == gate and task.interval == interval
    provider.run_scheduled('formal', task, gate)
    decision = json.loads(store.virtual_account('formal')['last_decision_payload'])
    assert decision['signal_date'] == previous.session_date.isoformat()
    assert decision['valid_session'] == interval.start.astimezone(ZoneInfo(candidate.instrument.timezone)).date().isoformat()
    intents = store.account_intents('formal')
    assert intents and all(row['status'] == 'PENDING_SUBMIT' for row in intents)
    assert all(datetime.fromisoformat(leg['submit_after']) == interval.start for leg in decision['plan_legs'])
    assert task.submit_after > gate
    # Restart reuses the successful interval without replacing its publications.
    reopened = EquityRuntimeAdviceClient(repo_root=client.repo_root, store=store,
                                   dataflows=client.dataflows, data_dir=client.data_dir)
    with patch.object(client.dataflows, 'prepare', side_effect=AssertionError('must reuse prepared interval')):
        prepared = reopened.prepare_interval('formal', interval, observed_at=gate + timedelta(seconds=1))
    store.set_virtual_paused('formal', True)
    with patch.object(client.dataflows, 'prepare', side_effect=AssertionError('paused must not prepare')):
        assert provider.due_decision(store.virtual_account('formal'), gate) is None
        for operation in (
            lambda: client.prepare_interval('formal', interval, observed_at=gate),
            lambda: client.prepare_data('formal', interval, as_of=gate),
            lambda: provider.drive_decision('formal', gate),
            lambda: engine.refresh_account('formal', prepared=prepared),
            lambda: engine.drive_account_decision('formal', prepared=prepared),
        ):
            with pytest.raises(RuntimeError, match='RUNNING|paused'):
                operation()




def test_online_v4_decision_and_execution_use_the_scoped_runtime(formal_v4, monkeypatch):
    from execution_channels.futu.broker import BrokerAccount, BrokerOrder, BrokerPosition, BrokerSnapshot
    from paper_trading_engine.multichannel_runtime import build_multichannel_runtime
    from paper_trading_engine.online_verify import main, verify
    from paper_trading_engine.web import create_server

    client, store, root, interval, candidate, evaluation = formal_v4
    client.register_recipe('formal', client.inputs('formal'))
    market = candidate.instrument.market.value
    currency = 'CNY' if market == 'CN' else 'USD'
    target = 900 if market == 'CN' else 989
    capital = 1_000_000
    calendar = client._calendar_products(client.recipe('formal'), interval.start)['sessions']
    prior_close = max(s.segments[-1].end for s in sessions_from_metadata(calendar.identity.metadata)
                      if s.segments[-1].end < interval.start)
    now = prior_close + timedelta(hours=5)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    class Broker:
        channel_id = store.execution_channel_id
        channel_account_id = 'formal-channel'
        order = None
        cash = capital
        quantity = 0
        submissions = 0

        def account_snapshot(self):
            positions = (BrokerPosition(candidate.instrument.symbol, self.quantity, self.quantity),) if self.quantity else ()
            account = BrokerAccount('SIMULATE', market, self.cash, self.cash + self.quantity * 10,
                                    0., currency=currency, channel_account_id=self.channel_account_id)
            return BrokerSnapshot(account, positions, self.order_snapshot())

        def order_snapshot(self):
            return () if self.order is None else (self.order,)

        def historical_order_snapshot(self, start, end):
            return self.order_snapshot()

        def place_order(self, intent):
            self.submissions += 1
            self.order = BrokerOrder('42', intent.symbol, intent.side, intent.quantity, intent.limit_price,
                                     'SUBMITTED', 0, 0., intent.intent_id, updated_at=interval.start.isoformat(),
                                     channel_account_id=self.channel_account_id, session=intent.session)
            return self.order

        def close(self):
            pass

    broker = Broker()

    def gateway_factory(*, config, **kwargs):
        if config is None:
            raise ConnectionError('other channel unavailable')
        return broker

    identity = {'mode': 'DEV', 'repo_root': str(client.repo_root)}
    args = SimpleNamespace(repo_root=client.repo_root, data_dir=client.data_dir, config_root=client.repo_root,
                           database=client.repo_root / 'formal.db', symbol=candidate.instrument.symbol,
                           asset='stock', opend_host='127.0.0.1', opend_port=11111, runtime_identity=identity)
    runtime = build_multichannel_runtime(args, root, client.dataflows, gateway_factory=gateway_factory)
    monkeypatch.setattr('paper_trading_engine.multichannel_runtime.datetime', Clock)
    execution = runtime.services['formal-channel'].execution
    execution._delegate.now = lambda: now
    execution.refresh()
    root.set_setting('scheduler_heartbeat_at', datetime.now(timezone.utc).isoformat())
    server = create_server(runtime.console_view, port=0, multichannel_runtime=runtime)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    account = store.virtual_account('formal')
    expected = {
        'channel_account_id': 'formal-channel', 'release_hash': account['release_hash'], 'run_state': 'RUNNING',
        'decision': {'interval': {'start': interval.start.isoformat(), 'end': interval.end.isoformat()},
                     'action': 'BUY', 'target_quantity': target, 'fresh': True, 'judgment': 'hold'},
        'quantity': 0, 'orders': 0, 'fills': 0,
    }
    plan = {'release': identity, 'channels': {'formal-channel': {
        'channel_id': store.execution_channel_id, 'market': market, 'currency': currency,
    }}, 'accounts': {'formal': expected}}
    try:
        with urlopen(base + '/api/channels/futu-simulate-cn/snapshot', timeout=5) as response:
            assert json.load(response)['scope']['channel'] == FUTU_SIMULATE_CN_CHANNEL_ID
        blocked = verify(server.server_port, {**plan, 'accounts': {'formal': {
            **expected, 'decision': {k: v for k, v in expected['decision'].items() if k != 'fresh'},
        }}})
        assert blocked['status'] == 'BLOCKED', blocked
        report = verify(server.server_port, plan, drive_dev=True)
        assert report['status'] == 'PASS', report
        assert store.account_intents('formal') and not broker.submissions
        def read_json(path, body=None):
            request = Request(base + path, None if body is None else json.dumps(body).encode(),
                              {'Content-Type': 'application/json'})
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        other_market = 'US' if market == 'CN' else 'CN'
        assert [row['account_id'] for row in read_json(f'/api/virtual-accounts?market={market}')['accounts']] == ['formal']
        assert read_json(f'/api/virtual-accounts?market={other_market}')['accounts'] == []
        assert [row['account_id'] for row in read_json(f'/api/comparison?market={market}')['accounts']] == ['formal']
        assert read_json(f'/api/comparison?market={other_market}')['accounts'] == []
        assert 'formal-channel' in {row['channel_account_id'] for row in read_json(f'/api/channel-accounts?market={market}')['channels']}
        assert not any(row.get('account_id') == 'formal' for row in read_json(f'/api/audit-events?market={other_market}')['events'])
        assert read_json(f'/api/system/status?market={market}')['scope']['market'] == market
        chart = read_json('/api/virtual-accounts/formal/chart')
        snapshot = read_json('/api/virtual-accounts/formal/snapshot')
        assert chart['scope']['account_id'] == 'formal'
        assert chart['forward_observation_start'] == snapshot['decision']['signal_date']
        assert snapshot['account']['forward_observation_start'] == chart['forward_observation_start']
        assert read_json('/api/channel-accounts/formal-channel/pause', {})['paused'] is True
        assert read_json('/api/channel-accounts/formal-channel/resume', {})['paused'] is False
        decision_id = store.virtual_account('formal')['last_decision_id']
        assert decision_id
        report = verify(server.server_port, plan, drive_dev=True)
        assert report['status'] == 'FAIL'
        assert [c['evidence']['status'] for c in report['checks'] if c['status'] == 'FAIL'] == ['DECISION_REUSED']
        expected['decision'].pop('fresh')
        assert verify(server.server_port, plan)['status'] == 'PASS'
        assert store.virtual_account('formal')['last_decision_id'] == decision_id
        old_intent, = store.account_intents('formal', decision_id)
        old_cash = store.virtual_account('formal')['frozen_cash']
        from execution_channels.futu.adoption import AccountAdoption
        evaluate = runtime.services['formal-channel'].accounts.advice.get_decision

        def revised(*args, **kwargs):
            decision = evaluate(*args, **kwargs)
            return replace(decision, strategy_output={**decision.strategy_output, 'explanation': {
                **decision.strategy_output['explanation'], 'next_watch': 'review after the next close',
            }})

        adopt = AccountAdoption._adopt
        def fail_after_adoption(*args):
            adopt(*args)
            raise RuntimeError('injected replacement failure')

        decision_path = '/api/virtual-accounts/formal/decision'
        with monkeypatch.context() as changes:
            changes.setattr(runtime.services['formal-channel'].accounts.advice, 'get_decision', revised)
            with monkeypatch.context() as fail:
                fail.setattr(AccountAdoption, '_adopt', fail_after_adoption)
                with pytest.raises(HTTPError, match='409') as rejected:
                    read_json(decision_path, {})
                assert 'injected replacement failure' in json.load(rejected.value)['error']
                assert store.virtual_account('formal')['last_decision_id'] == decision_id
                assert store.account_intent(old_intent['intent_id'])['status'] == 'PENDING_SUBMIT'
                assert store.virtual_account('formal')['frozen_cash'] == old_cash
            replaced = read_json(decision_path, {})
            assert replaced['status'] == 'DECISION_AND_INTENTS_SUPERSEDED'
            assert replaced['superseded_decision_id'] == decision_id
            assert replaced['superseded_intent_ids'] == [old_intent['intent_id']]
            assert store.account_decision('formal', decision_id)['status'] == 'SUPERSEDED'
            assert store.account_intent(old_intent['intent_id'])['status'] == 'SUPERSEDED'
            assert store.virtual_account('formal')['frozen_cash'] == old_cash
            assert replaced['validity']['end'] == (interval.end + timedelta(hours=5)).isoformat()
            assert read_json(decision_path, {})['status'] == 'DECISION_REUSED'
            decision_id = replaced['decision_id']

        assert read_json('/api/virtual-accounts/formal/pause', {})['account']['run_state'] == 'PAUSED'
        request = Request(base + '/api/virtual-accounts/formal/decision', b'{}',
                          {'Content-Type': 'application/json'})
        with pytest.raises(HTTPError) as rejected:
            urlopen(request, timeout=5)
        assert rejected.value.code == 409
        assert read_json('/api/virtual-accounts/formal/resume', {})['account']['run_state'] == 'RUNNING'

        store.set_paused(False)
        execution.submit_pending()
        assert broker.submissions == 0  # Overnight decisions cannot submit before T+1 opens.
        now = interval.start
        task = runtime.schedule_provider.due_decision(store.virtual_account('formal'), interval.start)
        runtime.schedule_provider.run_scheduled('formal', task, interval.start)
        execution.submit_pending()
        assert broker.submissions == 1 and broker.order.quantity == target
        with pytest.raises(HTTPError, match='409') as live:
            urlopen(request, timeout=5)
        assert 'zero fills' in json.load(live.value)['error']
        broker.quantity = target
        broker.cash = capital - target * 10 * (1 + evaluation.fee_rate)
        broker.order = replace(broker.order, status='FILLED_ALL', cumulative_filled_quantity=target,
                               average_fill_price=10., updated_at=(interval.start + timedelta(seconds=1)).isoformat())
        execution.refresh()
        execution.refresh()
        expected.update(run_state='RUNNING', quantity=target, orders=1, fills=1)
        report = verify(server.server_port, plan)
        assert report['status'] == 'PASS', report
        assert broker.submissions == 1
        with urlopen(base + '/api/channel-accounts/formal-channel/snapshot', timeout=5) as response:
            assert abs(Decimal(json.load(response)['cash_difference'])) < Decimal('.01')
        with urlopen(base + '/api/audit-events?channel_account_id=futu-cn-default', timeout=5) as response:
            assert not any(event['account_id'] == 'formal' for event in json.load(response)['events'])

        plan_path = client.repo_root / 'online-plan.json'
        plan_path.write_text(json.dumps(plan), encoding='utf-8')
        output = client.repo_root / 'online-result.json'
        assert main(['--port', str(server.server_port), '--plan', str(plan_path), '--json-output', str(output)]) == 0
        assert json.loads(output.read_bytes())['status'] == 'PASS'
        now = interval.end
        with pytest.raises(HTTPError, match='409') as closed:
            urlopen(request, timeout=5)
        assert 'confirmed fills' in json.load(closed.value)['error']
        now = interval.end + timedelta(hours=5)
        next_task = runtime.schedule_provider.due_decision(store.virtual_account('formal'), now)
        assert next_task is None or next_task.task_id != task.task_id
        assert store.virtual_account('formal')['last_decision_id'] == decision_id
    finally:
        server.shutdown()
        worker.join()
        server.server_close()
        runtime.account_chart.close()


@pytest.mark.parametrize("filled", (0, 1, None), ids=("cancelled-zero", "cancelled-partial", "submission-race"))
def test_v4_rerun_after_order_window_uses_confirmed_channel_facts(formal_v4, monkeypatch, filled):
    from dataclasses import asdict
    from execution_channels.futu.broker import BrokerOrder
    from execution_channels.futu.order_reports import apply_order_report

    client, store, _, interval, candidate, _ = formal_v4
    client.register_recipe('formal', client.inputs('formal'))
    engine = AccountEngine(store, client, now=lambda: interval.start)
    provider = EquityScheduleProvider(client, engine)
    prior = provider.drive_decision('formal', interval.start)
    intent, = store.account_intents('formal', prior['decision_id'])
    store.set_setting('channel_reconciliation_status', 'OK')
    store.set_setting('futu_cash_reconciliation_status', 'OK')
    evaluate = client.get_decision

    def revised(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        return replace(result, strategy_output={**result.strategy_output, 'explanation': {
            **result.strategy_output['explanation'], 'next_watch': 'updated review text',
        }})

    if filled is None:
        def claim_after_evaluation(*args, **kwargs):
            result = revised(*args, **kwargs)
            assert store.claim_account_intent(intent['intent_id'], moment=interval.start)
            return result

        monkeypatch.setattr(client, 'get_decision', claim_after_evaluation)
        with pytest.raises(RuntimeError, match='may already have been submitted'):
            provider.drive_decision('formal', interval.start)
        assert store.account_intent(intent['intent_id'])['status'] == 'SUBMITTING'
        assert store.virtual_account('formal')['last_decision_id'] == prior['decision_id']
        assert len(store.account_decisions('formal')) == 1
        return

    assert store.claim_account_intent(intent['intent_id'], moment=interval.start)
    order = BrokerOrder('rerun-cancel', candidate.instrument.symbol, 'BUY', intent['quantity'],
                        float(intent['limit_price']), 'SUBMITTED', 0, 0., intent['intent_id'])
    store.bind_channel_order(intent['intent_id'], order.channel_order_id, asdict(order))
    closed = interval.end + timedelta(seconds=1)
    report = dict(asdict(order), status='CANCELLED_PART' if filled else 'CANCELLED_ALL',
                  cumulative_filled_quantity=filled, average_fill_price=10. if filled else 0.,
                  updated_at=closed.isoformat())
    apply_order_report(store, report, occurred_at=closed.isoformat())
    monkeypatch.setattr(client, 'get_decision', revised)
    old_order = store.account_order(order.channel_order_id)
    if filled:
        with pytest.raises(RuntimeError, match='confirmed fills'):
            provider.drive_decision('formal', closed)
        assert store.virtual_account('formal')['last_decision_id'] == prior['decision_id']
    else:
        result = provider.drive_decision('formal', closed)
        assert result['status'] == 'DECISION_SUPERSEDED'
        assert result['cycle_id'] == prior['cycle_id']
        assert result['execution_disposition'] == 'WINDOW_CLOSED'
        assert store.account_decision('formal', result['decision_id'])['state_reason'] == 'EXECUTION_EXPIRED'
        assert not store.account_intents('formal', result['decision_id'])
        assert Decimal(store.virtual_account('formal')['frozen_cash']) == 0
    assert store.account_order(order.channel_order_id) == old_order
