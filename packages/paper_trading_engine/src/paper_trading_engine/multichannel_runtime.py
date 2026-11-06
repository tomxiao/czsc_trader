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
from .audit import AuditRecorder
from .channel import ChannelAccountConfig
from .channel_accounts import DEFAULT_CHANNEL_ACCOUNT
from .coordinator import PteCoordinator, ReconnectableExecution
from .equity_advice import PreparedEquityDecision
from .formal_v4_advice import FormalV4AdviceClient, FormalV4ScheduleProvider
from .futu_execution import FutuExecution
from .futu_gateway import FutuGateway, FutuGatewayError
from .srt_advice_client import SrtAdviceClient
from .trading_window import ScheduledDecision


class ChannelBatchError(RuntimeError):
    """All channels were attempted; at least one did not complete."""


class AccountAdviceRouter:
    def __init__(self, legacy, formal):
        self.legacy, self.formal = legacy, formal

    def get_decision(self, *args, **kwargs):
        client = self.formal if type(kwargs['prepared']) is PreparedEquityDecision else self.legacy
        return client.get_decision(*args, **kwargs)


@dataclass
class ChannelServices:
    store: object
    accounts: AccountEngine
    execution: object
    cycle: AccountStrategyCycle
    formal: FormalV4AdviceClient

    def refresh_account(self):
        return self.execution.refresh_account()

    def refresh_orders(self):
        self.execution.refresh_orders()
        return self.execution.submit_pending(reconcile=False)


class RuntimeScheduleProvider:
    def __init__(self, runtime, *, preparation_time):
        self.runtime = runtime
        self.preparation_time = time.fromisoformat(preparation_time)

    def due_decision(self, account, observed_at):
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
        services = self.runtime.services[account['channel_account_id']]
        if account['equity_rules_json'] is not None:
            return FormalV4ScheduleProvider(services.formal, services.accounts).run_scheduled(account_id, task, observed_at)
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
            if account['run_state'] == 'RETIRED':
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

    def begin_shutdown(self):
        for services in self.services.values():
            services.accounts.begin_shutdown()
            services.execution.begin_shutdown()

    def close(self):
        try:
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
                if account['run_state'] == 'RETIRED':
                    continue
                if account['equity_rules_json'] is not None:
                    formal._account_release(account['account_id'])
                else:
                    binding = legacy.validate_account_binding(strategy_id=account['strategy_id'],
                        strategy_version=account['strategy_version'], symbol=account['symbol'], asset=account['asset_type'])
                    if binding.release_hash != account['release_hash']:
                        raise ValueError('stored account release differs from deployed release')
            config = None if registration['config_json'] is None else ChannelAccountConfig(**json.loads(registration['config_json']))
            from .futu_execution import FeeReconciliationPolicy
            policy_json = scoped.get_setting("fee_reconciliation_policy")
            fee_policy = None if policy_json is None else FeeReconciliationPolicy(**{k: Decimal(str(v)) for k,v in json.loads(policy_json).items()})
            def connect(scoped=scoped, config=config, audit=audit, fee_policy=fee_policy):
                gateway = gateway_factory(config=config, host=args.opend_host, port=args.opend_port, audit=audit)
                try:
                    return FutuExecution(scoped, gateway, config=config, audit=audit, fee_policy=fee_policy)
                except BaseException:
                    gateway.close()
                    raise
            try:
                execution = ReconnectableExecution(scoped, args.symbol, connect, initial=connect())
            except (FutuGatewayError, ConnectionError, TimeoutError, OSError) as exc:
                execution = ReconnectableExecution(scoped, args.symbol, connect, error=exc)
            accounts = AccountEngine(scoped, AccountAdviceRouter(legacy, formal), audit=audit)
            cycle = AccountStrategyCycle(accounts, AccountDataPreparer(advice=legacy), scoped, audit=audit)
            services_by_id[identity] = ChannelServices(scoped, accounts, execution, cycle, formal)
            if identity == DEFAULT_CHANNEL_ACCOUNT:
                from .account_chart import AccountChartService
                from .chart_market_data import AccountChartMarketData
                chart = AccountChartService(scoped, market_data=AccountChartMarketData(dataflows=dataflows),
                                           cache_dir=args.database.parent / 'charts')
                console = PteCoordinator(accounts, execution, strategy_cycle=cycle, audit=audit,
                                         account_chart=chart, runtime_identity=args.runtime_identity)
        if console is None:
            raise ValueError('legacy console scope is missing')
        return MultiChannelRuntime(store, services_by_id, console_view=console,
            runtime_identity=args.runtime_identity, preparation_time=getattr(args, 'data_prepare_time', '20:30'))
    except BaseException:
        for services in services_by_id.values():
            services.execution.close()
        raise
