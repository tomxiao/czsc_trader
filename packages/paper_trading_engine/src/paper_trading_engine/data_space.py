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


@dataclass(frozen=True, slots=True)
class EquitySourceConfig:
    market: MarketId
    source: SourceRef
    adapter: EquityAdapter
    evidence_manifest: Path | None


def _source_config(config_root: Path, data_dir: Path) -> tuple[EquitySourceConfig, ...]:
    path = config_root / 'equity-sources.json'
    if not path.exists():
        return ()
    value = json.loads(path.read_text(encoding='utf-8'))
    if (type(value) is not dict or set(value) != {'schema_version', 'sources'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or type(value['sources']) is not list):
        raise ValueError('invalid PTE equity source configuration')
    sources = []
    identities = set()
    for row in value['sources']:
        required = {'market', 'provider', 'revision', 'adapter'}
        if type(row) is not dict or not required <= row.keys() <= required | {'evidence_manifest'}:
            raise ValueError('invalid PTE equity source entry')
        market = MarketId(row['market'])
        adapter = EquityAdapter(row['adapter'])
        if (market is MarketId.CN) != (adapter is EquityAdapter.TUSHARE_CN):
            raise ValueError('PTE equity adapter differs from its declared market')
        source = SourceRef(row['provider'], row['revision'])
        if (market, source) in identities:
            raise ValueError('duplicate PTE equity source identity')
        identities.add((market, source))
        manifest = None
        if 'evidence_manifest' in row:
            raw = row['evidence_manifest']
            if type(raw) is not str or not raw:
                raise ValueError('PTE equity evidence manifest must be a relative file path')
            relative = Path(raw)
            manifest = (data_dir / relative).resolve()
            if relative.anchor or '..' in relative.parts or not manifest.is_relative_to(data_dir.resolve()):
                raise ValueError('PTE equity evidence manifest must stay under the data directory')
        sources.append(EquitySourceConfig(market, source, adapter, manifest))
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


def create_dataflows(*, data_dir: Path, space: DataSpace, config_root: Path,
                     opend_host: str = '127.0.0.1', opend_port: int = 11111,
                     resources: ExitStack | None = None) -> Dataflows:
    """Bind a relative data space to the environment's stable shared data root."""
    env_file = config_root / '.env'
    equity = {}
    quotes = _FutuQuotes(opend_host, opend_port, resources)
    for item in _source_config(config_root, data_dir):
        if item.adapter is EquityAdapter.TUSHARE_CN:
            from dataflows.tushare_equity import tushare_equity_bindings
            bindings = tushare_equity_bindings(source=item.source, env_file=env_file)
        else:
            from dataflows.futu_equity import futu_equity_bindings
            bindings = futu_equity_bindings(source=item.source, quote_context=quotes)
        # Formal execution facts come from declared evidence, never research assumptions.
        equity.update((key, binding) for key, binding in bindings.items()
                      if key.product in {EquityProduct.BARS, EquityProduct.SESSIONS})
        if item.evidence_manifest is not None:
            from dataflows.equity_evidence import equity_evidence_bindings
            equity.update(equity_evidence_bindings(source=item.source, market=item.market,
                manifest_path=item.evidence_manifest,
                session_binding=bindings[ProviderKey(EquityProduct.SESSIONS, item.market, item.source)]))
    return Dataflows(
        base_dir=data_dir,
        space=space,
        providers=ProviderConfig(env_file=env_file, equity_bindings=equity),
    )
