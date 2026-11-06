"""PTE environment paths are explicit, relative and independent of release roots."""

from pathlib import Path
from datetime import datetime
from contextlib import ExitStack
import json

import pytest

from dataflows import (AssetClass, DataSpace, EquityDataRequest, EquityProduct, EquityQuery,
                       InstrumentId, MarketId, ProviderKey, SourceRef)
from paper_trading_engine import data_space
from paper_trading_engine.cli import build_parser
from paper_trading_engine.runtime_config import PteRuntimeConfig
from paper_trading_engine.errors import AdviceClientError
from paper_trading_engine.srt_advice_client import SrtAdviceClient


@pytest.mark.parametrize("value", [Path("."), Path("../other"), Path("C:/market")])
def test_runtime_rejects_nonrelative_or_escaping_data_space(value):
    with pytest.raises(ValueError):
        PteRuntimeConfig(data_space=value)


def test_cli_converts_environment_space_to_typed_contract(tmp_path):
    args = build_parser().parse_args([
        "serve", "--repo-root", str(tmp_path), "--data-space", "markets/cn",
    ])
    assert args.data_space == DataSpace(Path("markets/cn"))


def test_advice_data_access_requires_host_injection(tmp_path):
    client = SrtAdviceClient(repo_root=tmp_path, data_dir=tmp_path / "data")
    with pytest.raises(AdviceClientError, match="host-configured DFLS"):
        client.latest_completed_signal_date(datetime(2026, 9, 14, 22))


def test_host_injects_space_and_credentials_location_without_reading_credentials(tmp_path, monkeypatch):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(data_space, "Dataflows", create)
    data_space.create_dataflows(
        data_dir=tmp_path / "shared/data", space=DataSpace(Path("market")),
        config_root=tmp_path / "shared/config",
    )
    assert captured["base_dir"] == tmp_path / "shared/data"
    assert captured["space"] == DataSpace(Path("market"))
    assert captured["providers"].env_file == tmp_path / "shared/config/.env"


def test_host_assembles_both_markets_and_shares_quote_lifetime(tmp_path, monkeypatch):
    (tmp_path / 'equity-sources.json').write_text(json.dumps({'schema_version': 2, 'sources': [
        {'market': 'CN', 'adapter': 'TUSHARE_CN', 'provider': 'cn-data', 'revision': 'v1'},
        {'market': 'US', 'adapter': 'FUTU_US', 'provider': 'us-data', 'revision': 'v1'},
        {'market': 'US', 'adapter': 'FUTU_US', 'provider': 'us-aux', 'revision': 'v2'},
        {'market': 'CN', 'adapter': 'DYNAMIC_FACTS', 'provider': 'cn-facts', 'revision': 'v2',
         'endpoint': 'https://feed.example.test/cn', 'calendar_source': {'provider': 'cn-data', 'revision': 'v1'}},
        {'market': 'US', 'adapter': 'DYNAMIC_FACTS', 'provider': 'us-facts', 'revision': 'v2',
         'endpoint': 'https://feed.example.test/us', 'calendar_source': {'provider': 'us-data', 'revision': 'v1'}},
    ]}), encoding='utf-8')
    opened = []
    closed = []

    class Quotes:
        def request_trading_days(self, **kwargs):
            assert kwargs['market'] == 'US'
            return 0, [{'time': '2026-11-05', 'trade_date_type': 'WHOLE'}]

        def close(self):
            closed.append(self)

    def open_quotes(host, port):
        assert (host, port) == ('127.0.0.1', 11112)
        result = Quotes()
        opened.append(result)
        return result

    monkeypatch.setattr(data_space, '_open_quotes', open_quotes)
    monkeypatch.setattr(data_space, 'Dataflows', lambda **kwargs: kwargs['providers'])
    with ExitStack() as resources:
        providers = data_space.create_dataflows(data_dir=tmp_path / 'data', space=DataSpace(Path('market')),
            config_root=tmp_path, opend_port=11112, resources=resources).equity_bindings
        assert not opened
        assert ProviderKey(EquityProduct.BARS, MarketId.CN, SourceRef('cn-data', 'v1')) in providers
        assert ProviderKey(EquityProduct.BARS, MarketId.CN, SourceRef('cn-data', 'v2')) not in providers
        for market, name in ((MarketId.CN, 'cn-facts'), (MarketId.US, 'us-facts')):
            source = SourceRef(name, 'v2')
            for product in (EquityProduct.ACTIONS, EquityProduct.TRADING_FACTS):
                assert ProviderKey(product, market, source) in providers
            assert ProviderKey(EquityProduct.BARS, market, source) not in providers
        for source in (SourceRef('us-data', 'v1'), SourceRef('us-aux', 'v2')):
            day = datetime(2026, 11, 5).date()
            request = EquityDataRequest(InstrumentId(MarketId.US, AssetClass.STOCK, 'MU'), source,
                                        EquityQuery(EquityProduct.SESSIONS, day, day))
            frame, _ = providers[request.parameters.provider_key].fetch(request)
            assert frame.SessionDate.tolist() == ['2026-11-05']
            assert ProviderKey(EquityProduct.ACTIONS, MarketId.US, source) not in providers
        assert len(opened) == 1
    assert closed == opened


def test_host_rejects_retired_file_configuration(tmp_path):
    (tmp_path / 'equity-sources.json').write_text(json.dumps({'schema_version': 2, 'sources': [
        {'market': 'CN', 'adapter': 'TUSHARE_CN', 'provider': 'cn-data', 'revision': 'v1',
         'evidence_manifest': '../elsewhere.json'},
    ]}), encoding='utf-8')
    with pytest.raises(ValueError, match='market or fields'):
        data_space.create_dataflows(data_dir=tmp_path / 'data', space=DataSpace(Path('market')), config_root=tmp_path)
