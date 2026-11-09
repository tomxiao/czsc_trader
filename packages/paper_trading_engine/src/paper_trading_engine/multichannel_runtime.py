"""Compose shared account services; keep the existing console scoped to CN."""
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from dataflows import TimeInterval

from .account_engine import AccountEngine
from .account_data_preparer import AccountDataPreparer
from .account_strategy_cycle import AccountStrategyCycle
from execution_channels.futu.audit import AuditRecorder
from execution_channels.futu.channel import ChannelAccountConfig
from execution_channels.futu.channel_accounts import DEFAULT_CHANNEL_ACCOUNT
from .coordinator import PteCoordinator, ReconnectableExecution
from .equity_advice import PreparedEquityDecision
from .formal_v4_advice import FormalV4AdviceClient, FormalV4ScheduleProvider
from execution_channels.futu.futu_execution import ChannelExecution
from execution_channels.futu.futu_gateway import FutuGateway, FutuGatewayError
from .srt_advice_client import SrtAdviceClient
from .scheduling_contracts import ScheduledDecision


class ChannelBatchError(RuntimeError):
    """All channels were attempted; at least one did not complete."""


class AccountAdviceRouter:
    def __init__(self, legacy, formal):
        self.legacy, self.formal = legacy, formal

    def get_decision(self, *args, **kwargs):
        client = self.formal if type(kwargs['prepared']) is PreparedEquityDecision else self.legacy
        return client.get_decision(*args, **kwargs)

    def validate_account_binding(self, **kwargs):
        return self.legacy.validate_account_binding(**kwargs)


@dataclass
class ChannelServices:
    store: object
    accounts: AccountEngine
    execution: object
    cycle: AccountStrategyCycle
    formal: FormalV4AdviceClient
    retirement_calendar: object | None = None

    def refresh_account(self):
        return self.execution.refresh_account()

    def refresh_orders(self):
        if self.retirement_calendar is not None:
            self.retirement_calendar.prepare(self.execution)
        self.execution.refresh_orders()
        return self.execution.submit_pending(reconcile=False)


class RuntimeScheduleProvider:
    def __init__(self, runtime, *, preparation_time):
        self.runtime = runtime
        self.preparation_time = max(time.fromisoformat(preparation_time), time(20))

    def due_decision(self, account, observed_at):
        if account['run_state'] != 'RUNNING':
            return None
        services = self.runtime.services[account['channel_account_id']]
        if account['equity_rules_json'] is not None:
            return FormalV4ScheduleProvider(services.formal, services.accounts).due_decision(account, observed_at)
        # Legacy CN daily strategy contract is explicit and independent of V4 clocks.
        local = observed_at.astimezone(ZoneInfo('Asia/Shanghai'))
        start = datetime.combine(local.date(), self.preparation_time, local.tzinfo)
        if local < start:
            return None
        end = datetime.combine(local.date() + timedelta(days=1), time(), local.tzinfo)
        identity = sha256(f"legacy:{account['account_id']}:{account['release_hash']}:{local.date()}".encode()).hexdigest()
        return ScheduledDecision(identity, TimeInterval(start, end), start)

    def run_scheduled(self, account_id, task, observed_at):
        account = self.runtime.store.virtual_account(account_id)
        if account['run_state'] != 'RUNNING':
            raise ValueError('only a running account can execute a scheduled decision')
        services = self.runtime.services[account['channel_account_id']]
        if account['equity_rules_json'] is not None:
            return FormalV4ScheduleProvider(services.formal, services.accounts).run_scheduled(
                account_id, task, observed_at, clock=lambda: datetime.now(timezone.utc))
        return services.cycle.run(account_id,
            signal_date=task.decision_at.astimezone(ZoneInfo('Asia/Shanghai')).date(), observed_at=observed_at)


class MultiChannelRuntime:
    def __init__(self, store, services, *, console_view, runtime_identity, preparation_time='20:30'):
        self.store, self.services = store, services
        self.console_view = console_view
        self.runtime_identity = runtime_identity
        self.strategy_cycle = None
        self.account_chart = console_view.account_chart
        self.schedule_provider = RuntimeScheduleProvider(self, preparation_time=preparation_time)
        self.channel_operations = services
        self.startup_timings = {}
        self.market_data_resources = None

    def _all(self, operation):
        results, errors = {}, {}
        for identity, services in self.services.items():
            try:
                results[identity] = getattr(services, operation)()
            except Exception as exc:
                errors[identity] = str(exc)
        if errors:
            raise ChannelBatchError(json.dumps({'completed': list(results), 'failed': errors}, ensure_ascii=False))
        return results

    def startup(self):
        # ReconnectableExecution exposes external unavailability. Ledger faults stay fatal.
        for identity, services in self.services.items():
            try:
                services.execution.refresh()
            except Exception:
                if services.execution.status().get('reconciliation_status') != 'UNAVAILABLE':
                    raise
        return self.status()

    def refresh_account(self):
        return self._all('refresh_account')

    def refresh_orders(self):
        return self._all('refresh_orders')

    def refresh(self):
        self.refresh_orders()
        now = datetime.now(timezone.utc)
        failures = {}
        for account in self.store.strategy_virtual_accounts():
            if account['run_state'] != 'RUNNING':
                continue
            try:
                task = self.schedule_provider.due_decision(account, now)
                if task is not None:
                    self.schedule_provider.run_scheduled(account['account_id'], task, now)
            except Exception as exc:
                failures[account['account_id']] = str(exc)
        if failures:
            raise ChannelBatchError(json.dumps(failures, ensure_ascii=False))
        return self.status()

    def status(self):
        return {'scope': 'MULTICHANNEL', 'runtime': self.runtime_identity,
                'channels': {key: value.execution.status() for key, value in self.services.items()}}

    def drive_virtual_account_decision(self, account_id: str):
        account = self.store.virtual_account(account_id)
        if account['run_state'] in {'RETIRING', 'RETIRED'}:
            raise ValueError('inactive account cannot drive a strategy decision')
        if account['run_state'] != 'RUNNING':
            raise RuntimeError('only a running account can drive a strategy decision')
        if account['equity_rules_json'] is None:
            return self.console_view.drive_virtual_account_decision(account_id)
        services = self.services[account['channel_account_id']]
        return FormalV4ScheduleProvider(services.formal, services.accounts).drive_decision(
            account_id, datetime.now(timezone.utc), clock=lambda: datetime.now(timezone.utc),
        )

    def _services_for_account(self, account_id: str) -> ChannelServices:
        return self.services[self.store.virtual_account(account_id)['channel_account_id']]

    def _set_virtual_paused(self, account_id: str, paused: bool):
        services = self._services_for_account(account_id)
        store = services.store
        if store.virtual_account(account_id)['run_state'] in {'RETIRING', 'RETIRED'}:
            raise ValueError('inactive account cannot pause or resume')
        if not paused and store.equity_account_rules(account_id) is not None:
            services.formal._account_release(account_id)
            services.formal.inputs(account_id)
        elif not paused:
            account = store.virtual_account(account_id)
            binding = services.accounts.advice.validate_account_binding(
                strategy_id=account['strategy_id'], strategy_version=account['strategy_version'],
                symbol=account['symbol'], asset=account['asset_type'])
            if binding.release_hash != account['release_hash']:
                raise ValueError('stored account release differs from deployed release')
        with services.accounts._decision_lock, store.atomic_decision_update():
            account = store.set_virtual_paused(account_id, paused)
            services.accounts.audit.record(
                'ACCOUNT_PAUSED' if paused else 'ACCOUNT_RESUMED', source='web.control',
                actor_type='OPERATOR', account_id=account_id, strategy_id=account['strategy_id'],
                strategy_version=account['strategy_version'], release_hash=account['release_hash'],
                channel=store.execution_channel_id,
            )
            return account

    def pause_virtual(self, account_id: str):
        return self._set_virtual_paused(account_id, True)

    def resume_virtual(self, account_id: str):
        return self._set_virtual_paused(account_id, False)

    def acknowledge_execution_gap(self, account_id: str, intent_id: str, resolution_note: str):
        return self._services_for_account(account_id).execution.acknowledge_execution_gap(
            account_id, intent_id, resolution_note,
        )

    def repair_account_ledger(self, account_id: str, intent_id: str):
        return self._services_for_account(account_id).execution.repair_account_ledger(account_id, intent_id)

    def retire_account(self, request):
        services = self._services_for_account(request.account_id)
        with services.accounts._decision_lock:
            return services.execution.retire_account(request)

    def begin_shutdown(self):
        for services in self.services.values():
            services.accounts.begin_shutdown()
            services.execution.begin_shutdown()

    def close(self):
        try:
            if self.account_chart is not None:
                self.account_chart.close()
            for services in self.services.values():
                services.execution.close()
        finally:
            try:
                self.store.close()
            finally:
                if self.market_data_resources is not None:
                    self.market_data_resources.close()


def build_multichannel_runtime(args, store, dataflows, *, gateway_factory=FutuGateway):
    services_by_id = {}
    console = None
    try:
        for registration in store.channel_accounts():
            identity = registration['channel_account_id']
            scoped = store.scope(identity)
            audit = AuditRecorder(scoped)
            legacy = SrtAdviceClient(repo_root=args.repo_root, data_dir=args.data_dir,
                                     asset=args.asset, audit=audit, dataflows=dataflows)
            formal = FormalV4AdviceClient(repo_root=args.repo_root, store=scoped,
                                         dataflows=dataflows, data_dir=args.data_dir)
            for account in scoped.strategy_virtual_accounts():
                if account['run_state'] in {'PAUSED', 'RETIRING', 'RETIRED'}:
                    continue
                if account['equity_rules_json'] is not None:
                    formal._account_release(account['account_id'])
                else:
                    binding = legacy.validate_account_binding(strategy_id=account['strategy_id'],
                        strategy_version=account['strategy_version'], symbol=account['symbol'], asset=account['asset_type'])
                    if binding.release_hash != account['release_hash']:
                        raise ValueError('stored account release differs from deployed release')
            config = None if registration['config_json'] is None else ChannelAccountConfig(**json.loads(registration['config_json']))
            from execution_channels.futu.futu_execution import FeeReconciliationPolicy
            policy_json = scoped.get_setting("fee_reconciliation_policy")
            fee_policy = None if policy_json is None else FeeReconciliationPolicy(**{k: Decimal(str(v)) for k,v in json.loads(policy_json).items()})
            def connect(scoped=scoped, config=config, audit=audit, fee_policy=fee_policy):
                gateway = gateway_factory(config=config, host=args.opend_host, port=args.opend_port, audit=audit)
                try:
                    return ChannelExecution(scoped, gateway, config=config, audit=audit, fee_policy=fee_policy)
                except BaseException:
                    gateway.close()
                    raise
            try:
                execution = ReconnectableExecution(scoped, args.symbol, connect, initial=connect())
            except (FutuGatewayError, ConnectionError, TimeoutError, OSError) as exc:
                execution = ReconnectableExecution(scoped, args.symbol, connect, error=exc)
            accounts = AccountEngine(scoped, AccountAdviceRouter(legacy, formal), audit=audit)
            cycle = AccountStrategyCycle(accounts, AccountDataPreparer(advice=legacy), scoped, audit=audit)
            from .retirement_calendar import RetirementCalendar
            services_by_id[identity] = ChannelServices(scoped, accounts, execution, cycle, formal,
                RetirementCalendar(scoped, dataflows, args.config_root))
            if identity == DEFAULT_CHANNEL_ACCOUNT:
                console = PteCoordinator(accounts, execution, strategy_cycle=cycle, audit=audit,
                                         runtime_identity=args.runtime_identity)
        if console is None:
            raise ValueError('legacy console scope is missing')
        from .account_chart import AccountChartService
        from .chart_market_data import AccountChartMarketData

        def formal_inputs(account_id):
            account = store.virtual_account(account_id)
            formal = services_by_id[account['channel_account_id']].formal
            inputs = formal.recipe(account_id) or formal.inputs(account_id)
            if inputs.release_hash != account['release_hash']:
                raise ValueError('chart input binding differs from the account release')
            return inputs

        console.account_chart = AccountChartService(
            store, market_data=AccountChartMarketData(dataflows=dataflows, formal_inputs=formal_inputs),
            cache_dir=args.database.parent / 'charts',
            audit_for_account=lambda account: services_by_id[account['channel_account_id']].accounts.audit,
        )
        return MultiChannelRuntime(store, services_by_id, console_view=console,
            runtime_identity=args.runtime_identity, preparation_time=getattr(args, 'data_prepare_time', '20:30'))
    except BaseException:
        for services in services_by_id.values():
            services.execution.close()
        raise
