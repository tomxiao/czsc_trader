"""Independent original PreparedDataRef reads for A; no C reader or exports."""
from uuid import UUID

import numpy as np
import pandas as pd
import requests
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from strategy_runtime.pricing import ExecutionPricing

import authenticate_shock_population as P


def load():
    requests.sessions.Session.request = P.deny
    ctx = create_research_context(RepositoryContext.discover(P.ROOT), ResearchBatchRef('S014'), providers=ProviderConfig(bindings={}))
    receipt = P.read(P.ROOT / 'research/S014/experiments/EX046_20261020/others/accounts/run-001.json')
    account = P.published(receipt['evidence'])
    assert account['result_hash'] == 'a3c398bd3f3259bbf8e46a6339a36a8bd83b2ccd924526240b0ca604b0f21bcb'
    binding = P.published(receipt['binding_ref'])
    frames, identities = {}, {}

    def fetch(name, query, pin, expected=None):
        assert not query.get('parameters')
        prepared = PreparedDataRef(UUID(pin['space_id']), UUID(pin['preparation_id']), pin['manifest_sha256'])
        request = DataRequest(Dataset(query['dataset']), query['symbol'], query['start'], query['end'], query['required_cutoff'], query['frequency'])
        result = ctx.data.fetch(request, prepared=prepared)
        assert result.ready and (expected is None or result.identity.content_sha256 == expected)
        frame = result.dataframe.copy(deep=True)
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.Date))
        frame = frame.sort_index()
        assert not frame.index.has_duplicates
        identities[name] = result.identity.content_sha256
        return frame

    source = binding['input_bindings']['full']
    market = fetch('source_market', source['plan']['requests']['market'], source['prepared'])
    assert np.isfinite(market[['Open', 'High', 'Low', 'Close']].to_numpy(dtype=float)).all() and (market[['Open', 'High', 'Low', 'Close']] > 0).all().all()
    for name in ['execution_daily', 'adjusted_daily', 'price_limits', 'trading_status']:
        frames[name] = fetch(name, binding['execution_requests'][name], binding['execution_prepared'], binding['execution_identities'][name])
    rename = {'Date': 'dt', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'vol'}
    raw, adjusted = [frames[name].reset_index(drop=True).rename(columns=rename) for name in ['execution_daily', 'adjusted_daily']]
    projected = ExecutionPricing.from_dict(account['request_identity']['pricing']).apply(raw.copy(), raw_daily=raw, adjusted_daily=adjusted)
    projected = projected.rename(columns={v: k for k, v in rename.items()})
    projected.index = pd.DatetimeIndex(pd.to_datetime(projected.Date))
    frames['projected_execution'] = projected
    # Oracle's adjusted_daily key intentionally contains the independently
    # fetched original source-market HFQ closes, rather than assuming the
    # execution-adjusted request has an identical date/precision domain.
    frames['execution_adjusted_daily'] = frames['adjusted_daily']
    frames['adjusted_daily'] = market
    proof = {'original_account_ref': receipt['evidence'], 'original_binding_ref': receipt['binding_ref'],
             'source_prepared': source['prepared'], 'source_market_request': source['plan']['requests']['market'],
             'execution_prepared': binding['execution_prepared'], 'execution_fingerprint': binding['execution_fingerprint'],
             'content_identities': identities, 'prepared_public_fetches': 5, 'new_preparations': 0, 'new_supplier_calls': 0, 'raw_exports': 0}
    return account, frames, proof
