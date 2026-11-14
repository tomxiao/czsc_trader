"""Host assembly of PTE's environment-scoped market data service."""

from contextlib import ExitStack
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from threading import Lock

from dataflows import Dataflows, DataSpace, EquityProduct, MarketId, ProviderConfig, ProviderKey, SourceRef


class EquityAdapter(StrEnum):
    TUSHARE_CN = 'TUSHARE_CN'
    FUTU_US = 'FUTU_US'
    DYNAMIC_FACTS = 'DYNAMIC_FACTS'


@dataclass(frozen=True, slots=True)
class EquitySourceConfig:
    market: MarketId
    source: SourceRef
    adapter: EquityAdapter
    endpoint: str | None = None
    calendar_source: SourceRef | None = None


def _source_config(config_root: Path) -> tuple[EquitySourceConfig, ...]:
    path = config_root / 'equity-sources.json'
    if not path.exists():
        return ()
    value = json.loads(path.read_text(encoding='utf-8'))
    if (type(value) is not dict or set(value) != {'schema_version', 'sources'}
            or type(value['schema_version']) is not int or value['schema_version'] != 2
            or type(value['sources']) is not list):
        raise ValueError('invalid PTE equity source configuration')
    sources = []
    identities = set()
    for row in value['sources']:
        required = {'market', 'provider', 'revision', 'adapter'}
        if type(row) is not dict or not required <= row.keys():
            raise ValueError('invalid PTE equity source entry')
        market = MarketId(row['market'])
        adapter = EquityAdapter(row['adapter'])
        source = SourceRef(row['provider'], row['revision'])
        if (market, source) in identities:
            raise ValueError('duplicate PTE equity source identity')
        identities.add((market, source))
        if adapter is EquityAdapter.DYNAMIC_FACTS:
            from dataflows.equity_dynamic import validate_facts_endpoint
            if set(row) != required | {'endpoint', 'calendar_source'}:
                raise ValueError('dynamic facts require an endpoint and an independent calendar source')
            validate_facts_endpoint(row['endpoint'])
            sources.append(EquitySourceConfig(market, source, adapter, row['endpoint'], SourceRef(**row['calendar_source'])))
        else:
            if set(row) != required or (market is MarketId.CN) != (adapter is EquityAdapter.TUSHARE_CN):
                raise ValueError('PTE equity adapter differs from its market or fields')
            sources.append(EquitySourceConfig(market, source, adapter))
    return tuple(sources)


def _open_quotes(host: str, port: int):
    from futu import OpenQuoteContext
    return OpenQuoteContext(host=host, port=port)


class _FutuQuotes:
    """Share one lazy quote-only connection within the host lifetime."""

    def __init__(self, host: str, port: int, resources: ExitStack | None) -> None:
        self.host, self.port, self.resources = host, port, resources
        self.context = None
        self.lock = Lock()

    def _close(self) -> None:
        with self.lock:
            self.context.close()
            self.context = None
            self.resources = None

    def _call(self, method, *args, **kwargs):
        with self.lock:
            if self.resources is None:
                raise RuntimeError('Futu quote access requires an owning PTE runtime')
            if self.context is None:
                self.context = _open_quotes(self.host, self.port)
                self.resources.callback(self._close)
            return getattr(self.context, method)(*args, **kwargs)

    def request_trading_days(self, *args, **kwargs):
        return self._call('request_trading_days', *args, **kwargs)

    def request_history_kline(self, *args, **kwargs):
        return self._call('request_history_kline', *args, **kwargs)


def dataflow_providers(*, config_root: Path, opend_host: str = '127.0.0.1',
                       opend_port: int = 11111, resources: ExitStack | None = None) -> ProviderConfig:
    env_file = config_root / '.env'
    equity = {}
    quotes = _FutuQuotes(opend_host, opend_port, resources)
    sources = _source_config(config_root)
    for item in sources:
        if item.adapter is EquityAdapter.TUSHARE_CN:
            from dataflows.tushare_equity import tushare_equity_bindings
            bindings = tushare_equity_bindings(source=item.source, env_file=env_file)
        elif item.adapter is EquityAdapter.FUTU_US:
            from dataflows.futu_equity import futu_equity_bindings
            bindings = futu_equity_bindings(source=item.source, quote_context=quotes)
        else:
            continue
        equity.update(bindings)
    for item in sources:
        if item.adapter is not EquityAdapter.DYNAMIC_FACTS:
            continue
        from dataflows.equity_dynamic import dynamic_equity_bindings
        calendar = equity.get(ProviderKey(EquityProduct.SESSIONS, item.market, item.calendar_source))
        if calendar is None:
            raise ValueError('dynamic equity facts calendar source is not registered')
        equity.update(dynamic_equity_bindings(source=item.source, market=item.market, endpoint=item.endpoint,
            calendar_source=item.calendar_source, calendar_binding=calendar))
    return ProviderConfig(env_file=env_file, equity_bindings=equity)


def create_dataflows(*, data_dir: Path, space: DataSpace, config_root: Path,
                     opend_host: str = '127.0.0.1', opend_port: int = 11111,
                     resources: ExitStack | None = None) -> Dataflows:
    """Bind a relative data space to the environment's stable shared data root."""
    providers = dataflow_providers(config_root=config_root, opend_host=opend_host,
                                  opend_port=opend_port, resources=resources)
    return Dataflows(base_dir=data_dir, space=space, providers=providers)


class AccountDataflows:
    """PTE-owned instances with one shared provider configuration and quote connection."""

    def __init__(self, data_dir: Path, space: DataSpace, providers: ProviderConfig):
        self._data_dir, self._space, self._providers = data_dir, space, providers
        self._accounts = {}
        self._lock = Lock()

    def for_account(self, account_id: str) -> Dataflows:
        from hashlib import sha256
        if type(account_id) is not str or not account_id:
            raise ValueError('DFLS account space requires a virtual account ID')
        with self._lock:
            if account_id not in self._accounts:
                key = sha256(account_id.encode()).hexdigest()
                self._accounts[account_id] = Dataflows(base_dir=self._data_dir,
                    space=DataSpace(self._space.path / 'strategy-accounts' / key), providers=self._providers)
            return self._accounts[account_id]
