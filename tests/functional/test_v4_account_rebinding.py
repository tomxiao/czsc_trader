"""Account rebindings use authenticated native releases and durable account facts."""

from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
import shutil
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
from paper_trading_engine.broker import BrokerOrder
from paper_trading_engine.equity_contracts import EquityAccountRules
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient, FormalV4Inputs, FormalV4ScheduleProvider
from paper_trading_engine.order_reports import apply_order_report
from paper_trading_engine.store import PaperStore, RUNTIME_DATABASE_SCHEMA_VERSION
from strategy_manager import PaperTradingApproval, StrategyRegistry, freeze_contracts as f
from strategy_runtime import StateRecord, equity_source_hash
from test_formal_v4_runtime import formal_v4 as formal_v4


def _fill_position(client, store, interval, candidate):
    client.register_recipe('formal', client.inputs('formal'))
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


def _runtime(tmp_path, client, root, monkeypatch):
    # Use SQLite backup rather than file copy to preserve its transaction boundary.
    runtime = tmp_path / '.tmp/host'
    state = runtime / 'shared/state/runtime.db'
    store = PaperStore(state)
    root._connection.backup(store._connection)
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


@pytest.mark.parametrize('change_schema', [False, True])
def test_rebind_active_v4_and_block_historical_execution(formal_v4, tmp_path, monkeypatch, change_schema):
    client, store, root, interval, candidate, evaluation = formal_v4
    _fill_position(client, store, interval, candidate)
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
            EquityAccountRules(candidate.instrument, candidate.definition.execution_spec),
            FormalV4Inputs(new_hash, evaluation.input_binding, evaluation.fee_rate),
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
        assert reopened.recipe('formal') == request.inputs
        assert reopened.inputs('formal') == request.inputs
        assert reopened._path('formal').read_bytes() == (client.data_dir / 'v4-inputs/formal.json').read_bytes()
        with pytest.raises(ValueError, match='cutover'):
            reopened.prepare_interval('formal', interval, observed_at=interval.start)
        committed = list(database._connection.iterdump())
        assert update_account_bindings(runtime, 'target', (request,)).status is AccountBindingUpdateStatus.ALREADY_APPLIED
        assert list(database._connection.iterdump()) == committed
    finally:
        database.close()


@pytest.mark.parametrize('formal_v4', [(MarketId.CN, True), (MarketId.US, True)], indirect=True)
def test_rebind_to_qualified_successor_version(formal_v4, tmp_path, monkeypatch):
    client, store, root, interval, candidate, evaluation = formal_v4
    _fill_position(client, store, interval, candidate)
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
            EquityAccountRules(candidate.instrument, candidate.definition.execution_spec),
            FormalV4Inputs(target.release_hash, evaluation.input_binding, evaluation.fee_rate),
            V4StateContinuation('source', 'reviewed successor compatibility'))
        assert update_account_bindings(runtime, 'target', (request,)).status is AccountBindingUpdateStatus.COMMITTED
        after = scoped.virtual_account('formal')
        assert after['strategy_version'] == 'v2' and after['release_hash'] == target.release_hash
        assert json.loads(after['account_v4_json'])['active'] == active
        assert scoped.account_fills('formal') == fills
        assert after['cash'] == before['cash'] and after['quantity'] == before['quantity']
    finally:
        database.close()


@pytest.mark.parametrize('formal_v4', [MarketId.CN], indirect=True)
def test_legacy_migration_reconciles_positions_and_rolls_back_batch(formal_v4, tmp_path, monkeypatch):
    from paper_trading_engine import v4_account_maintenance as maintenance

    client, store, root, interval, candidate, evaluation = formal_v4
    _fill_position(client, store, interval, candidate)
    target_hash = store.virtual_account('formal')['release_hash']
    old_hash = 'a' * 64
    with store._connection:
        # Retain the confirmed fills and ledger, then model a pre-V4 account snapshot.
        store._connection.execute("UPDATE virtual_accounts SET release_hash=?,selection_data_cutoff='2026-10-15',"
                                  "equity_rules_json=NULL WHERE account_id='formal'", (old_hash,))
        store._connection.execute("DELETE FROM equity_strategy_state WHERE account_id='formal'")
    store.create_virtual_account('flat', 'flat', 'v1', old_hash, 1000, symbol=candidate.instrument.symbol,
        asset_type='stock', strategy_id='S999', strategy_name_snapshot='old', strategy_version='v1',
        release_hash=old_hash, qualification_snapshot='PAPER_READY', selection_data_cutoff='2026-10-15')
    runtime, database, _ = _runtime(tmp_path, client, root, monkeypatch)
    try:
        scoped = database.scope('formal-channel')
        opens = datetime(2026, 10, 16, 9, 30, tzinfo=ZoneInfo(candidate.instrument.timezone))
        effective = TimeInterval(opens, opens.replace(hour=15, minute=0))
        updates = tuple(V4AccountBindingUpdate(AccountBindingUpdate(name, old_hash, target_hash, 'v1'),
            'formal-channel', account_binding_facts_sha256(scoped, name), effective,
            EquityAccountRules(candidate.instrument, candidate.definition.execution_spec),
            FormalV4Inputs(target_hash, evaluation.input_binding, evaluation.fee_rate),
            V4StateMigration(StateRecord(), 'reviewed fixture migration', StateRecord() if name == 'formal' else None))
            for name in ('formal', 'flat'))
        unchanged = list(database._connection.iterdump())
        original = maintenance._apply

        def fail_second(store, update, prepared, plan_sha256):
            if update.account_id == 'flat':
                raise RuntimeError('injected second write failure')
            original(store, update, prepared, plan_sha256)

        with monkeypatch.context() as patch:
            patch.setattr(maintenance, '_apply', fail_second)
            with pytest.raises(RuntimeError, match='second write failure'):
                update_account_bindings(runtime, 'target', updates)
        assert list(database._connection.iterdump()) == unchanged
        fill, = scoped.account_fills('formal')
        before = scoped.virtual_account('formal')
        assert update_account_bindings(runtime, 'target', updates).status is AccountBindingUpdateStatus.COMMITTED
        after = scoped.virtual_account('formal')
        document = json.loads(after['account_v4_json'])
        assert document['active']['quantity'] == before['quantity'] == after['quantity']
        assert document['active']['cycle_id'] == fill['fill_id']
        assert document['active']['entry_interval']['start'] == fill['occurred_at']
        assert after['cash'] == before['cash']
        assert scoped.account_fills('formal') == [fill]
        record = scoped.v4_runtime_binding('formal')
        assert record['legacy_actions_before'] == effective.start.isoformat()
        assert scoped.v4_runtime_binding('flat')['plan_sha256'] == record['plan_sha256']
        with pytest.raises(ValueError, match='cutover'):
            scoped.save_account_decision('formal', {**json.loads(before['last_decision_payload']),
                'strategy': {'strategy_id': 'S999', 'version': 'v1', 'release_hash': target_hash}})
        assert update_account_bindings(runtime, 'target', updates).status is AccountBindingUpdateStatus.ALREADY_APPLIED
    finally:
        database.close()
