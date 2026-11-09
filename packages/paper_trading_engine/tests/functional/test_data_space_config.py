"""PTE environment paths are explicit, relative and independent of release roots."""

from pathlib import Path
from datetime import datetime
from contextlib import ExitStack
import json

import pytest

from dataflows import (AssetClass, DataSpace, EquityDataRequest, EquityProduct, EquityQuery,
                       InstrumentId, MarketId, ProviderKey, SourceRef)
from paper_trading_engine import data_space
from paper_trading_engine.runtime_config import PteRuntimeConfig


# Independent risk: PTE03; responsibility-level assertions.
@pytest.mark.parametrize("value", [
    Path("../other"),
], ids=['PTE03-C04'])
def test_runtime_rejects_nonrelative_or_escaping_data_space(value):
    with pytest.raises(ValueError):
        PteRuntimeConfig(data_space=value)


# Independent risk: PTE10; responsibility-level assertions.
def test_PTE10_C04_host_assembles_both_markets_and_shares_quote_lifetime(tmp_path, monkeypatch):
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
            for product in (EquityProduct.TRADING_FACTS,):
                assert ProviderKey(product, market, source) in providers
            assert ProviderKey(EquityProduct.BARS, market, source) not in providers
        for source in (SourceRef('us-data', 'v1'), SourceRef('us-aux', 'v2')):
            day = datetime(2026, 11, 5).date()
            request = EquityDataRequest(InstrumentId(MarketId.US, AssetClass.STOCK, 'MU'), source,
                                        EquityQuery(EquityProduct.SESSIONS, day, day))
            frame, _ = providers[request.parameters.provider_key].fetch(request)
            assert frame.SessionDate.tolist() == ['2026-11-05']
        assert len(opened) == 1
    assert closed == opened
