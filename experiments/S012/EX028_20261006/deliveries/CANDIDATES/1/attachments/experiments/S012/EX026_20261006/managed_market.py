"""Reuse authenticated public DFLS preparation; never invent input identities."""
from datetime import date
from pathlib import Path
from hashlib import sha256
from uuid import UUID
import json
import pandas as pd
from dataflows import DataRequest, Dataset, PreparedDataRef, DataStatus
from strategy_runtime import canonical_sha256
from czsc_trader.backtesting.execution_data import BacktestExecutionData

def load(context):
    root=Path.cwd()
    path=root/'experiments/S012/EX021_20261005/artifacts/rex/execution_failure.json'
    manifest=json.loads((path.parents[2]/'experiment_manifest.json').read_text(encoding='utf-8'))
    expected=manifest['files']['artifacts/rex/execution_failure.json']['sha256']
    assert sha256(path.read_bytes()).hexdigest()==expected
    metadata=json.loads(path.read_text(encoding='utf-8'))['trace']['data_requests']
    first=next(x for x in metadata if x['operation']=='prepare' and x['dataset']==Dataset.ETF_OHLCV.value)
    prepared=PreparedDataRef(UUID(first['prepared']['space_id']),UUID(first['prepared']['preparation_id']),first['prepared']['manifest_sha256'])
    group=[x for x in metadata if x['operation']=='prepare' and x['prepared']==first['prepared']]
    names={Dataset.ETF_OHLCV.value:'adjusted_daily',Dataset.ETF_UNADJUSTED_DAILY.value:'execution_daily',Dataset.ETF_UNADJUSTED_INTRADAY.value:'execution_30m',Dataset.TRADING_CALENDAR.value:'trading_calendar'}
    requests={};results={}
    for item in group:
        name=names[item['dataset']]
        req=DataRequest(Dataset(item['dataset']),item['symbol'],item['start'],item['end'],item['required_cutoff'],item['frequency'])
        result=context.data.fetch(req,prepared=prepared)
        if result.status is not DataStatus.READY or result.identity.content_sha256!=item['identity']['content_sha256']:
            raise ValueError('managed market changed or not ready: '+name)
        requests[name]=req;results[name]=result
    assert set(results)==set(names.values())
    calendar=results['trading_calendar'].dataframe
    sessions=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1),'Date']),name='dt')
    assert len(sessions)==1534 and sessions[0]==pd.Timestamp('2020-06-08') and sessions[-1]==pd.Timestamp('2026-09-30')
    def prices(frame):
        mapping={'Date':'dt','Open':'open','High':'high','Low':'low','Close':'close','Volume':'vol','Amount':'amount'}
        # Owned numeric projection. Original prepared frames and their complete
        # quality/temporal identities remain unchanged in DFLS and the trace.
        value=pd.DataFrame({dst:frame[src].to_numpy(copy=True) for src,dst in mapping.items()})
        value.dt=pd.to_datetime(value.dt)
        return value
    identities={name:r.identity.content_sha256 for name,r in results.items()}
    fingerprint=canonical_sha256({'symbol':'518850.SH','asset_type':'etf','evaluation_start':'2020-06-08','evaluation_end':'2026-09-30','inputs':identities})
    adjusted=prices(results['adjusted_daily'].dataframe);adjusted.insert(1,'symbol','518850.SH')
    data=BacktestExecutionData(root/'data/backtest','518850.SH','etf',adjusted,prices(results['execution_daily'].dataframe),prices(results['execution_30m'].dataframe),fingerprint,date(2026,9,30),sessions,requests=requests,prepared=prepared,input_identities=identities)
    return data,results
