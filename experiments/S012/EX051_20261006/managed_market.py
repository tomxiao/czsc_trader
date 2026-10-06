"""Reuse only the public typed prepared binding of the current FULL witness."""
import pandas as pd
from strategy_runtime import StrategyInputBinding
from .scope_contract import market_request, require

def load(context,scope):
    # The exact prepared manifest is resolved by DFLS, without cache access,
    # provider re-fetch, invented identities, or lookahead quality masks.
    asset = scope['market_assets'][0]
    binding = StrategyInputBinding.from_mapping(asset['input_binding'])
    frames = {}
    for name, raw in asset['execution_requests'].items():
        result = context.data.fetch(market_request(raw),prepared=binding.prepared)
        require(result.ready and result.identity.content_sha256==asset['execution_input_identities'][name],
                'current prepared market is not ready or changed: '+name)
        frames[name] = result.dataframe
    result = context.data.fetch(binding.plan.requests['features'],prepared=binding.prepared)
    require(result.ready, 'current prepared features not ready')
    features = result.dataframe
    require(binding.plan.requests['features'].parameters.source_sha256==scope['feature_sha256'],
            'wrong prepared feature source')
    calendar=frames['trading_calendar']
    sessions=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1),'Date']))
    require(len(sessions)==1534 and sessions[0]==pd.Timestamp('2020-06-08')
            and sessions[-1]==pd.Timestamp('2026-09-30'), 'calendar differs from gated window')
    # Prepared features cover prior-close calculation dates, not the final execution day.
    require(pd.DatetimeIndex(pd.to_datetime(features.Date)).equals(
                pd.DatetimeIndex(pd.to_datetime(binding.plan.calculation_dates))), 'feature window differs')
    bound_signals=pd.DatetimeIndex(pd.to_datetime([
        binding.plan.signal_dates[day.date()] for day in sessions]))
    daily_dates=pd.DatetimeIndex(pd.to_datetime(frames['execution_daily'].Date))
    positions=daily_dates.get_indexer(sessions)
    require((positions>0).all() and daily_dates[positions-1].equals(bound_signals)
            and bound_signals.equals(pd.DatetimeIndex(pd.to_datetime(features.Date))),
            'prepared features must match bound predecessor-close signal dates')
    # Preserve original attrs/evidence. Worker simulate owns numeric copies.
    source={'package':'strategy_runtime','path':'resources/features.csv','sha256':scope['feature_sha256']}
    return features,frames['execution_daily'],frames['execution_30m'],source
