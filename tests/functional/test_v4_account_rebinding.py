# Risk ownership: E2E-04
"""Account rebindings use authenticated native releases and durable account facts."""

from dataclasses import asdict, replace
from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
import json
import shutil
import sqlite3
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from czsc_trader.application import RepositoryContext, validate_release_package
from czsc_trader.application import runtime_migration
from dataflows import MarketId, TimeInterval
from paper_trading_engine import (
    AccountBindingUpdate, AccountBindingUpdateStatus, V4AccountBindingUpdate,
    V4StateContinuation, V4StateMigration, account_binding_facts_sha256, update_account_bindings,
)
from paper_trading_engine import account_maintenance
from paper_trading_engine.account_engine import AccountEngine
from execution_channels.futu.broker import BrokerOrder
from paper_trading_engine.ec_boundary import execution_rules
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient, FormalV4Inputs, FormalV4ScheduleProvider
from execution_channels.futu.order_reports import apply_order_report
from execution_channels.futu.store import PaperStore, RUNTIME_DATABASE_SCHEMA_VERSION
from strategy_manager import PaperTradingApproval, StrategyRegistry, freeze_contracts as f
from strategy_runtime import StateRecord, equity_source_hash
from test_formal_v4_runtime import formal_v4 as formal_v4


@pytest.fixture(scope="module")
def filled_position_seeds():
    # Immutable SQLite bytes only: each consumer owns its connection and files.
    return {}


def _fill_position(client, store, interval, candidate, seeds):
    client.register_recipe('formal', client.inputs('formal'))
    key = (candidate.instrument.market.value, store.virtual_account('formal')['release_hash'])
    if key in seeds:
        store._connection.deserialize(seeds[key])
        return
    engine = AccountEngine(store, client, now=lambda: interval.start)
    provider = FormalV4ScheduleProvider(client, engine)
    provider.run_scheduled('formal', provider.due_decision(store.virtual_account('formal'), interval.start), interval.start)
    intent, = store.account_intents('formal')
    store.set_setting('channel_reconciliation_status', 'OK')
    store.set_setting('futu_cash_reconciliation_status', 'OK')
    assert store.claim_account_intent(intent['intent_id'], moment=interval.start)
    order = BrokerOrder('rebind-fill', candidate.instrument.symbol, 'BUY', intent['quantity'],
                        float(intent['limit_price']), 'SUBMITTED', 0, 0., intent['intent_id'])
    store.bind_channel_order(intent['intent_id'], order.channel_order_id, asdict(order))
    report = dict(asdict(order), status='FILLED_ALL', cumulative_filled_quantity=intent['quantity'], average_fill_price=10.)
    apply_order_report(store, report, occurred_at=(interval.start + timedelta(minutes=1)).isoformat())
    store.set_virtual_paused('formal', True)
    seeds[key] = store._connection.serialize()


def _runtime(tmp_path, client, root, monkeypatch):
    # Use SQLite backup rather than file copy to preserve its transaction boundary.
    runtime = tmp_path / '.tmp/host'
    state = runtime / 'shared/state/runtime.db'
    state.parent.mkdir(parents=True, exist_ok=True)
    # Back up the existing real schema/account directly; initializing an empty
    # PaperStore here only writes a schema that the backup immediately replaces.
    with closing(sqlite3.connect(state)) as snapshot:
        root._connection.backup(snapshot)
    store = PaperStore(state)
    data = runtime / 'shared/data'
    shutil.copytree(client.data_dir, data)
    source = runtime / 'source'
    shutil.copytree(client.repo_root / 'strategies', source / 'strategies')
    releases = {name: SimpleNamespace(runtime_root=runtime, release_root=path, manifest_sha256=name,
        manifest={'database_schema': {'compatible': [RUNTIME_DATABASE_SCHEMA_VERSION]}})
        for name, path in (('source', source), ('target', client.repo_root))}
    monkeypatch.setattr(account_maintenance, 'load_release', lambda _, name: releases[name])
    return runtime, store, data


def _upgrade_target(client, candidate, old, *, change_schema):
    repo = RepositoryContext(client.repo_root, client.repo_root / 'research',
                             client.repo_root / 'research/registrations', client.repo_root / 'strategies')
    manifest, _, _ = validate_release_package(repo, 'S999-v1')
    owner = f.ResearchEvidenceOwner('S999', 'EX001_20261016')
    from hashlib import sha256
    evidence = b'{"scope":"isolated account maintenance fixture"}'
    digest = sha256(evidence).hexdigest()
    path = repo.root / owner.repository_path / f'{digest}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(evidence)
    root = repo.root / '.tmp/changed-source'
    shutil.copytree(candidate.source_root, root)
    source = root / 'strategy.py'
    source.write_bytes(source.read_bytes() + b'\n# isolated revision\n')
    definition = replace(candidate.definition, source_sha256=equity_source_hash(root, candidate.definition.source_files))
    if change_schema:
        from strategy_runtime.equity_replay import StateField, StateValueType, StrategyStateSchema
        definition = replace(definition, state_schema=StrategyStateSchema((StateField('mapped', StateValueType.INT),)),
                             initial_account=StateRecord((('mapped', 0),)))
    changed = replace(candidate, source_root=root, definition=definition, candidate_id='C9890')
    request = runtime_migration.FrozenRuntimeUpgradeRequest(
        f.FrozenVersionReference('S999', 'v1', old, manifest['package_hash']), changed,
        f.ResearchEvidenceRef(owner, path.name, digest), 'isolated rebinding revision', 'DEV', (),
        repo.root / '.tmp/prepared-rebinding',
    )
    prepared = runtime_migration.prepare_frozen_runtime_upgrade(repo, request)
    runtime_migration.apply_frozen_runtime_upgrade(repo, prepared)
    target = prepared.migrated.release_hash
    StrategyRegistry(repo.strategy_root).approve_paper_trading(PaperTradingApproval(
        'S999', 'v1', target, 'DEV', 'isolated exact revision qualification'))
    return target


@pytest.mark.parametrize('formal_v4,change_schema', [
    pytest.param(MarketId.CN, False, id='PTE18-C01'),
    pytest.param(MarketId.CN, True, id='PTE18-C02'),
    pytest.param(MarketId.US, False, id='PTE18-C03'),
], indirect=['formal_v4'])
def test_rebind_active_v4_and_block_historical_execution(formal_v4, tmp_path, monkeypatch, change_schema, filled_position_seeds):
    client, store, root, interval, candidate, evaluation = formal_v4
    _fill_position(client, store, interval, candidate, filled_position_seeds)
    with store._connection:
        # Align the inherited fixture's technical account metadata with its authenticated release.
        store._connection.execute("UPDATE virtual_accounts SET selection_data_cutoff='2026-10-15' WHERE account_id='formal'")
    runtime, database, data = _runtime(tmp_path, client, root, monkeypatch)
    try:
        scoped = database.scope('formal-channel')
        before = scoped.virtual_account('formal')
        source_state = json.loads(before['account_v4_json'])
        source_hash = before['release_hash']
        new_hash = _upgrade_target(client, candidate, source_hash, change_schema=change_schema)
        local = ZoneInfo(candidate.instrument.timezone)
        opens = datetime(2026, 10, 16, 9, 30, tzinfo=local)
        effective = TimeInterval(opens, opens.replace(hour=15 if candidate.instrument.market.value == 'CN' else 16, minute=0))
        request = V4AccountBindingUpdate(AccountBindingUpdate('formal', source_hash, new_hash, 'v1'),
            'formal-channel', account_binding_facts_sha256(scoped, 'formal'), effective,
            execution_rules(candidate.instrument, candidate.definition.execution_spec),
            FormalV4Inputs(new_hash, evaluation.input_binding, evaluation.fee_rate, client.inputs('formal').execution_reference),
            V4StateContinuation('source', 'reviewed fixture state'))
        untouched = list(database._connection.iterdump())
        with pytest.raises(ValueError, match='reviewed snapshot'):
            update_account_bindings(runtime, 'target', (replace(request, expected_facts_sha256='0' * 64),))
        assert list(database._connection.iterdump()) == untouched
        if change_schema:
            with pytest.raises(ValueError, match='explicit V4 mapping'):
                update_account_bindings(runtime, 'target', (request,))
            assert list(database._connection.iterdump()) == untouched
            request = replace(request, state=V4StateMigration(StateRecord((('mapped', 42),)),
                'reviewed target field mapping', StateRecord(), StateRecord(), 'source'))
        old_history = {table: list(map(tuple, database._connection.execute(f'SELECT * FROM {table}')))
                       for table in ('orders', 'intents', 'fills', 'account_ledger', 'decisions', 'account_snapshots')}
        assert update_account_bindings(runtime, 'target', (request,)).status is AccountBindingUpdateStatus.COMMITTED
        after = scoped.virtual_account('formal')
        for key in ('cash', 'quantity', 'frozen_cash', 'receivable', 'initial_cash', 'total_assets', 'run_state'):
            assert after[key] == before[key]
        for table, records in old_history.items():
            assert list(map(tuple, database._connection.execute(f'SELECT * FROM {table}'))) == records
        target_state = json.loads(after['account_v4_json'])
        assert target_state['state']['revision'] == source_state['state']['revision'] + 1
        assert target_state['state']['binding'] != source_state['state']['binding']
        assert target_state['state']['event_cursor'] == source_state['state']['event_cursor']
        assert target_state['state']['cycle'] == source_state['state']['cycle']
        assert target_state['active'] == source_state['active']
        assert target_state['last_interval'] == source_state['last_interval']
        assert target_state['state']['account']['values'] == ([['mapped', 42]] if change_schema else [])
        reopened = FormalV4AdviceClient(repo_root=client.repo_root, store=scoped, dataflows=client.dataflows, data_dir=data)
        live_inputs = replace(request.inputs, binding=request.inputs.binding.for_observations())
        assert reopened.recipe('formal') == live_inputs
        assert reopened.inputs('formal') == live_inputs
        assert reopened._path('formal').read_bytes() == (client.data_dir / 'v4-inputs/formal.json').read_bytes()
        with pytest.raises(RuntimeError, match='RUNNING'):
            reopened.prepare_interval('formal', interval, observed_at=interval.start)
        scoped.set_virtual_paused('formal', False)
        with pytest.raises(ValueError, match='cutover'):
            reopened.prepare_interval('formal', interval, observed_at=interval.start)
        scoped.set_virtual_paused('formal', True)
        committed = list(database._connection.iterdump())
        assert update_account_bindings(runtime, 'target', (request,)).status is AccountBindingUpdateStatus.ALREADY_APPLIED
        assert list(database._connection.iterdump()) == committed
    finally:
        database.close()


@pytest.mark.parametrize('formal_v4', [
    pytest.param((MarketId.CN, True), id='E2E04-C01'),
    pytest.param((MarketId.US, True), id='E2E04-C02'),
], indirect=True)
def test_rebind_to_qualified_successor_version(formal_v4, tmp_path, monkeypatch, filled_position_seeds):
    client, store, root, interval, candidate, evaluation = formal_v4
    _fill_position(client, store, interval, candidate, filled_position_seeds)
    runtime, database, _ = _runtime(tmp_path, client, root, monkeypatch)
    try:
        scoped = database.scope('formal-channel')
        before = scoped.virtual_account('formal')
        active = json.loads(before['account_v4_json'])['active']
        fills = scoped.account_fills('formal')
        target, _, _ = client.load_release('S999', 'v2')
        opens = datetime(2026, 10, 16, 9, 30, tzinfo=ZoneInfo(candidate.instrument.timezone))
        cutover = TimeInterval(opens, opens.replace(hour=15 if candidate.instrument.market is MarketId.CN else 16, minute=0))
        request = V4AccountBindingUpdate(AccountBindingUpdate('formal', before['release_hash'], target.release_hash, 'v2'),
            'formal-channel', account_binding_facts_sha256(scoped, 'formal'), cutover,
            execution_rules(candidate.instrument, candidate.definition.execution_spec),
            FormalV4Inputs(target.release_hash, evaluation.input_binding, evaluation.fee_rate, client.inputs('formal').execution_reference),
            V4StateContinuation('source', 'reviewed successor compatibility'))
        assert update_account_bindings(runtime, 'target', (request,)).status is AccountBindingUpdateStatus.COMMITTED
        after = scoped.virtual_account('formal')
        assert after['strategy_version'] == 'v2' and after['release_hash'] == target.release_hash
        assert json.loads(after['account_v4_json'])['active'] == active
        assert scoped.account_fills('formal') == fills
        assert after['cash'] == before['cash'] and after['quantity'] == before['quantity']
    finally:
        database.close()


def _check_rebound_input_update(client, store, monkeypatch, recipe_case):
    """Exercise registration after real rebinding, without another expensive fixture."""
    from dataflows import EquityDataRequest, PreparePolicy
    from paper_trading_engine.ec_boundary import account_input_identity
    from paper_trading_engine.execution_reference import ExecutionReferenceBinding

    original = client.inputs('formal')
    record = store.v4_runtime_binding('formal')
    account = store.virtual_account('formal')
    raw = original.execution_reference
    session = dict(original.binding.request_bindings)['sessions']
    prepared = client.dataflows.prepare((raw.request,
        EquityDataRequest(session.instrument, session.source, session.query)), policy=PreparePolicy.REUSE)
    assert prepared.ready
    updated = replace(original, execution_reference=ExecutionReferenceBinding(
        raw.parameters, prepared.reference, raw.content_sha256))
    assert updated.to_dict() != original.to_dict()
    expected = account_input_identity(original)
    projected = account_input_identity(updated)
    untouched = list(store._connection.iterdump())

    if recipe_case == 'rollback':
        save = store._save_v4_runtime_binding
        def fail_after_save(*args):
            save(*args)
            raise RuntimeError('injected recipe write failure')
        with monkeypatch.context() as patch:
            patch.setattr(store, '_save_v4_runtime_binding', fail_after_save)
            with pytest.raises(RuntimeError, match='recipe write failure'):
                client.register_recipe('formal', updated)
        assert list(store._connection.iterdump()) == untouched
        assert client.recipe('formal') == original
        return

    client.register_inputs('formal', updated.binding, expected_release_hash=updated.release_hash,
        fee_rate=updated.fee_rate, execution_reference=updated.execution_reference)
    assert client.recipe('formal') is None
    client.register_recipe('formal', updated)
    current = store.v4_runtime_binding('formal')
    assert current['inputs'] == projected.to_dict() and current['forward'] is True
    assert current['effective_interval'] == record['effective_interval']
    assert current['plan_sha256'] == record['plan_sha256']
    assert store.virtual_account('formal') == account
    if recipe_case == 'stale':
        with pytest.raises(ValueError, match='expected snapshot'):
            store.replace_v4_runtime_inputs('formal', projected, expected_inputs=expected, forward=True)
        assert store.v4_runtime_binding('formal') == current
    for value in (original, updated):
        from strategy_runtime import canonical_sha256
        key = 'v4_input_record:' + canonical_sha256(value.to_dict())
        assert json.loads(store._connection.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()[0]) == account_input_identity(value).to_dict()
    readonly = PaperStore.open_readonly(store.path)
    try:
        reader = FormalV4AdviceClient(repo_root=client.repo_root, store=readonly.scope('formal-channel'),
            dataflows=None, data_dir=client.data_dir)
        assert reader.inputs('formal') == updated and reader.recipe('formal') == updated
    finally:
        readonly.close()


@pytest.mark.parametrize('formal_v4,with_order,recipe_case', [
    pytest.param(MarketId.CN, True, 'success', id='PTE19-C01'),
    pytest.param(MarketId.US, False, 'stale', id='PTE19-C02'),
    pytest.param(MarketId.US, True, 'rollback', id='PTE19-C03'),
], indirect=['formal_v4'])
def test_legacy_same_session_cutover_cancels_locally_then_drives_new_release(
        formal_v4, tmp_path, monkeypatch, with_order, recipe_case):
    from paper_trading_engine import v4_account_maintenance as maintenance
    client, store, root, _, candidate, evaluation = formal_v4
    target_hash = store.virtual_account('formal')['release_hash']
    old_hash = 'a' * 64
    opens = datetime(2026, 10, 16, 9, 30, tzinfo=ZoneInfo(candidate.instrument.timezone))
    effective = TimeInterval(opens, opens.replace(hour=15 if candidate.instrument.market is MarketId.CN else 16, minute=0))
    with store._connection:
        store._connection.execute("UPDATE virtual_accounts SET release_hash=?,selection_data_cutoff='2026-10-15',"
                                  "equity_rules_json=NULL WHERE account_id='formal'", (old_hash,))
        store._connection.execute("DELETE FROM equity_strategy_state WHERE account_id='formal'")
    before_cash = store.virtual_account('formal')['cash']
    with_budget = with_order and candidate.instrument.market is MarketId.CN
    order = {'side': 'BUY', 'quantity': 100, 'order_type': 'LIMIT', 'limit_price': 10.}
    payload = {'decision_id': 'legacy-plan', 'symbol': candidate.instrument.symbol,
        'strategy': {'strategy_id': 'S999', 'version': 'v1', 'release_hash': old_hash},
        'signal_date': '2026-10-15', 'valid_session': '2026-10-16', 'actual_quantity': 0,
        'available_cash': before_cash, 'fee_rate': evaluation.fee_rate,
        'orders': [order] if with_order else [], 'cycle_target_quantity': 100 if with_order else 0}
    store.save_account_decision('formal', payload)
    if with_order:
        store.create_account_intent(account_id='formal', decision_id='legacy-plan', order_sequence=0,
            symbol=candidate.instrument.symbol, side='BUY', quantity=100, limit_price=10,
            valid_session='2026-10-16', fee_rate=evaluation.fee_rate)
    if with_budget:
        # A legacy unfilled ACTIVE budget must survive cancellation and migration.
        budget = {'cycle_id': 'b' * 64, 'opening_signal_identity': 'c' * 64, 'target_quantity': 100,
            'allocation_fraction': '1', 'cash_budget': before_cash, 'buy_cost_including_fees': '0', 'phase': 'ACTIVE'}
        with store._connection:
            store._connection.execute("UPDATE virtual_accounts SET entry_cycle_json=? WHERE account_id='formal'",
                                      (json.dumps(budget),))
    store.set_virtual_paused('formal', True)
    runtime, database, data = _runtime(tmp_path, client, root, monkeypatch)
    try:
        scoped = database.scope('formal-channel')
        request = V4AccountBindingUpdate(AccountBindingUpdate('formal', old_hash, target_hash, 'v1'),
            'formal-channel', account_binding_facts_sha256(scoped, 'formal'), effective,
            execution_rules(candidate.instrument, candidate.definition.execution_spec),
            FormalV4Inputs(target_hash, evaluation.input_binding, evaluation.fee_rate, client.inputs('formal').execution_reference),
            V4StateMigration(StateRecord(), 'legacy same-session migration',
                pending_cycle_values=StateRecord() if with_budget else None))
        original = maintenance._apply
        def fail_after_apply(*args):
            original(*args)
            raise RuntimeError('injected post-cancellation failure')
        untouched = list(database._connection.iterdump())
        with monkeypatch.context() as patch:
            patch.setattr(maintenance, '_apply', fail_after_apply)
            with pytest.raises(RuntimeError, match='post-cancellation'):
                update_account_bindings(runtime, 'target', (request,))
        assert list(database._connection.iterdump()) == untouched
        assert update_account_bindings(runtime, 'target', (request,)).status is AccountBindingUpdateStatus.COMMITTED
        after = scoped.virtual_account('formal')
        assert Decimal(after['cash']) == Decimal(before_cash) and Decimal(after['frozen_cash']) == 0
        prior = scoped.account_decision('formal', 'legacy-plan')
        assert prior['payload'] == payload
        assert prior['status'] == ('CANCELLED' if with_order else 'COMPLETED')
        assert database._connection.execute('SELECT decision_id FROM decision_adoptions WHERE account_id=?',
                                           ('formal',)).fetchone()[0] == 'legacy-plan'
        document = json.loads(after['account_v4_json'])
        if with_order:
            assert scoped.account_intents('formal')[0]['status'] == 'CANCELLED'
            assert len(scoped.query_audit_events(event_type='ORDER_INTENT_CANCELLED')) == 1
            if with_budget:
                assert document['budget'] is None and document['pending_cycle'] is None
                event = scoped.query_audit_events(event_type='ACCOUNT_STRATEGY_BOUND')[0]
                assert event['details']['retired_legacy_budget']['budget']['target_quantity'] == 100
            assert document['state']['event_cursor'] == database._connection.execute(
                "SELECT MAX(rowid) FROM account_ledger WHERE account_id='formal'").fetchone()[0]
        assert update_account_bindings(runtime, 'target', (request,)).status is AccountBindingUpdateStatus.ALREADY_APPLIED
        # Update the rebound recipe before driving the same service as the Web API.
        reopened = FormalV4AdviceClient(repo_root=client.repo_root, store=scoped, dataflows=client.dataflows, data_dir=data)
        _check_rebound_input_update(reopened, scoped, monkeypatch, recipe_case)
        scoped.set_virtual_paused('formal', False)
        from dataflows import EquityProduct, ProviderBinding, TradingSession
        from dataflows.equity_data import session_record
        # Extend this isolated supplier's explicit calendar beyond the
        # fixture's final session so CN next-session sellability is known.
        def extend_calendar(binding):
            def fetch(request):
                frame, metadata = binding.fetch(request)
                if request.parameters.query.product is EquityProduct.SESSIONS:
                    next_open = effective.start + timedelta(days=3)
                    next_close = effective.end + timedelta(days=3)
                    metadata = dict(metadata, following_session=session_record(TradingSession(
                        next_open.date(), candidate.instrument.timezone, (TimeInterval(next_open, next_close),))))
                return frame, metadata
            return ProviderBinding(binding.name, binding.revision, fetch)
        reopened.dataflows._equity_providers = {key: extend_calendar(value)
            for key, value in reopened.dataflows._equity_providers.items()}
        engine = AccountEngine(scoped, reopened, now=lambda: effective.start)
        provider = FormalV4ScheduleProvider(reopened, engine)
        result = provider.drive_decision('formal', effective.start)
        assert result['status'] == 'DECISION_COMPLETED' and not result['reused_decision']
        current = scoped.virtual_account('formal')['last_decision_id']
        assert current != 'legacy-plan'
        latest = scoped.account_decision('formal', current)
        assert latest['payload']['strategy']['release_hash'] == target_hash
        assert latest['valid_session'] == '2026-10-16'
        assert latest['state_events'][0]['related_decision_id'] == 'legacy-plan'
    finally:
        database.close()


@pytest.mark.parametrize('evidence', [
    pytest.param('SUBMISSION_UNCERTAIN', id='PTE18-C04'),
    pytest.param('filled', id='PTE18-C05'),
])
def test_same_session_cutover_never_discards_execution_or_v4_state(evidence):
    from paper_trading_engine import v4_account_maintenance as maintenance
    from execution_channels.futu.lifecycle import DecisionState
    zone = ZoneInfo('America/New_York')
    interval = TimeInterval(datetime(2026, 10, 16, 9, 30, tzinfo=zone), datetime(2026, 10, 16, 16, tzinfo=zone))
    account = {'equity_rules_json': None, 'cash': '1000', 'frozen_cash': '0'}
    decision = {'decision_id': 'old', 'status': DecisionState.PENDING, 'payload': {}, 'state_reason': 'PLAN_GENERATED'}
    intent = {'decision_id': 'old', 'status': 'PENDING_SUBMIT', 'attention_required': 0,
              'channel_order_id': None, 'side': 'SELL', 'payload': '{}'}
    rows = {'intents': [intent], 'orders': [], 'fills': [],
        'decisions': [{'decision_id': 'old', 'valid_session': '2026-10-16', 'payload': '{}'}],
        'decision_adoptions': [{'decision_id': 'old'}]}
    document = {'last_interval': None}
    if evidence == 'SUBMISSION_UNCERTAIN':
        intent['status'] = evidence
    else:
        rows['intents'] = []
        rows['orders'] = [{'decision_id': 'old', 'channel_order_id': 'broker', 'cumulative_filled_quantity': 100,
            'payload': json.dumps({'status': 'FILLED_ALL', 'cumulative_filled_quantity': 100})}]
        decision.update(status=DecisionState.COMPLETED, state_reason='PLAN_FILLED')
        rows['fills'] = [{'decision_id': 'old', 'order_id': 'broker', 'quantity': 100,
                          'occurred_at': interval.start.isoformat()}]
    facts = {'account': account, 'rows': rows, 'active_binding': None}
    update = SimpleNamespace(effective_interval=interval, rules=SimpleNamespace(timezone=zone))
    version = SimpleNamespace(forward_start='2026-10-16', selection_data_cutoff='2026-10-15')
    with pytest.raises(ValueError, match='block|overlap|follow'):
        replaceable = maintenance._validate_execution(facts, [decision])
        maintenance._validate_cutover(facts, version, update, document, replaceable)
