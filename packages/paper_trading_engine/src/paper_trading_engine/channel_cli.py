"""Maintenance CLI for explicit channel registration and native V4 accounts."""
from .ec_boundary import execution_rules

from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json

from execution_channels.futu.channel import ChannelAccountConfig
from .runtime_lock import RuntimeDatabaseLock
from execution_channels.futu.store import PaperStore


def _prepare_data(args):
    from dataflows import TimeInterval
    from .data_space import create_dataflows
    from .formal_v4_advice import FormalV4AdviceClient

    if args.as_of.utcoffset() is None or args.as_of > datetime.now(timezone.utc):
        raise ValueError('prepare-data requires an aware as-of timestamp no later than now')
    interval = TimeInterval(args.interval_start, args.interval_end)
    with ExitStack() as resources:
        root = PaperStore.open_readonly(args.database)
        resources.callback(root.close)
        store = root.scope(args.channel_account_id)
        flows = create_dataflows(data_dir=args.data_dir, space=args.data_space, config_root=args.config_root,
            opend_host=args.opend_host, opend_port=args.opend_port, resources=resources)
        client = FormalV4AdviceClient(repo_root=args.repo_root, store=store, dataflows=flows, data_dir=args.data_dir)
        result = client.prepare_data(args.account_id, interval, as_of=args.as_of)
        return {'account_id': args.account_id, 'status': result.status, 'as_of': args.as_of.isoformat(),
                'prepared': None if result.reference is None else asdict(result.reference),
                'items': [{'dataset': item.request.dataset, 'symbol': item.request.symbol,
                           'start': item.request.start, 'end': item.request.end, 'status': item.status,
                           'sha256': None if item.identity is None else item.identity.content_sha256,
                           'error': None if item.error is None else item.error.message} for item in result.items]}


def run_channel_command(args):
    if args.channel_action == 'prepare-data':
        return _prepare_data(args)
    if args.channel_action in {'list', 'status'}:
        store = PaperStore.open_readonly(args.database)
        try:
            if args.channel_action == 'list':
                return store.channel_accounts()
            scoped = store.scope(args.channel_account_id)
            return {'channel_account_id': scoped.channel_account_id,
                    'currency': scoped._scope_currency, 'paused': scoped.is_paused(),
                    'capital_pool': asdict(scoped.capital_pool_balance()),
                    'accounts': scoped.virtual_accounts(), 'orders': scoped.account_orders(),
                    'reconciliation_status': scoped.get_setting('channel_reconciliation_status'),
                    'cash_reconciliation_status': scoped.get_setting('futu_cash_reconciliation_status'),
                    'observed_at': scoped.get_setting('last_reconcile_at'),
                    'source': 'PERSISTED_SNAPSHOT', 'events': scoped.query_audit_events(limit=50)}
        finally:
            store.close()
    lock = RuntimeDatabaseLock(args.database).acquire()
    store = None
    try:
        store = PaperStore(args.database)
        value = json.loads(args.definition.read_text(encoding='utf-8')) if args.definition else None
        if args.channel_action == 'register':
            if type(value) is not dict or set(value) != {'account', 'capital', 'fee_policy'}:
                raise ValueError('channel definition requires account, capital and fee_policy')
            config = ChannelAccountConfig(**value['account'])
            from execution_channels.futu.futu_execution import FeeReconciliationPolicy
            policy = FeeReconciliationPolicy(**{k: Decimal(str(v)) for k, v in value['fee_policy'].items()})
            with store.atomic_decision_update():
                scoped = store.register_channel_account(config, capital=Decimal(value['capital']))
                existing = scoped.get_setting('fee_reconciliation_policy')
                encoded = json.dumps(asdict(policy), default=str, sort_keys=True)
                if existing is not None and existing != encoded:
                    raise ValueError('fee policy change requires an explicit reviewed migration')
                scoped.set_setting('fee_reconciliation_policy', encoded)
                scoped.create_channel_reconciliation_account()
            return {'channel_account_id': config.channel_account_id, 'registered': True}
        scoped = store.scope(args.channel_account_id)
        if args.channel_action == 'pause':
            scoped.set_paused(True)
            return {'channel_account_id': scoped.channel_account_id, 'paused': True}
        if args.channel_action == 'pause-account':
            from execution_channels.futu.audit import AuditRecorder
            with scoped.atomic_decision_update():
                account = scoped.set_virtual_paused(args.account_id, True)
                AuditRecorder(scoped).record('ACCOUNT_PAUSED', source='cli.channel', actor_type='OPERATOR',
                    account_id=args.account_id, channel=scoped.execution_channel_id)
            return account
        from .formal_v4_advice import FormalV4AdviceClient
        client = FormalV4AdviceClient(repo_root=args.repo_root, store=scoped, dataflows=None, data_dir=args.data_dir)
        if args.channel_action == 'resume-account':
            from execution_channels.futu.audit import AuditRecorder
            client._account_release(args.account_id)
            client.inputs(args.account_id)
            with scoped.atomic_decision_update():
                account = scoped.set_virtual_paused(args.account_id, False)
                AuditRecorder(scoped).record('ACCOUNT_RESUMED', source='cli.channel', actor_type='OPERATOR',
                    account_id=args.account_id, channel=scoped.execution_channel_id)
            return account
        if args.channel_action == 'create-v4':
            expected = {'account_id','name','strategy_id','strategy_version','release_hash','symbol','asset','fee_rate','initial_cash'}
            if type(value) is not dict or set(value) != expected:
                raise ValueError('invalid explicit V4 account definition')
            binding = client.validate_account_binding(strategy_id=value['strategy_id'],
                strategy_version=value['strategy_version'], symbol=value['symbol'], asset=value['asset'], fee_rate=value['fee_rate'])
            if binding.release_hash != value['release_hash']:
                raise ValueError('requested release differs from qualified deployed release')
            _, candidate, _ = client.load_release(binding.strategy_id, binding.version)
            account = scoped.create_virtual_account(value['account_id'], value['name'], binding.version,
                candidate.implementation_hash, value['initial_cash'], symbol=binding.symbol, asset_type=value['asset'],
                strategy_id=binding.strategy_id, strategy_name_snapshot=binding.name, strategy_version=binding.version,
                release_hash=binding.release_hash, qualification_snapshot=binding.qualification.value,
                selection_data_cutoff=binding.selection_data_cutoff.isoformat(),
                equity_rules=execution_rules(candidate.instrument, candidate.definition.execution_spec))
            return account
        if args.channel_action in {'bind-inputs', 'bind-recipe'}:
            from strategy_runtime import EquityInputBinding
            if type(value) is not dict or set(value) != {'account_id', 'release_hash', 'fee_rate', 'binding'}:
                raise ValueError('invalid explicit V4 input definition')
            if args.channel_action == 'bind-recipe':
                from .formal_v4_advice import FormalV4Inputs
                return {'input_identity': client.register_recipe(value['account_id'], FormalV4Inputs(
                    value['release_hash'], EquityInputBinding.from_dict(value['binding']), value['fee_rate']))}
            return {'input_identity': client.register_inputs(value['account_id'], EquityInputBinding.from_dict(value['binding']),
                expected_release_hash=value['release_hash'], fee_rate=value['fee_rate'])}
        if args.channel_action == 'resume':
            from execution_channels.futu.futu_gateway import FutuGateway
            from execution_channels.futu.futu_execution import ChannelExecution, FeeReconciliationPolicy
            raw = next(r for r in store.channel_accounts() if r['channel_account_id'] == scoped.channel_account_id)
            if raw['config_json'] is None:
                raise ValueError('channel resume requires an explicit registered external account')
            config = ChannelAccountConfig(**json.loads(raw['config_json']))
            policy = FeeReconciliationPolicy(**{k: Decimal(v) for k,v in json.loads(scoped.get_setting('fee_reconciliation_policy')).items()})
            gateway = FutuGateway(config=config, host=args.opend_host, port=args.opend_port)
            try:
                return ChannelExecution(scoped, gateway, config=config, fee_policy=policy).resume()
            finally:
                gateway.close()
        raise ValueError('unsupported channel maintenance operation')
    finally:
        if store is not None:
            store.close()
        lock.release()
