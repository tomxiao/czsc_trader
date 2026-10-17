"""Existing S014 public bindings and published labels only; network prohibited."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from uuid import UUID
import pandas as pd
import requests
from dataflows import DataRequest,Dataset,PreparedDataRef
from czsc_trader.application import RepositoryContext,create_research_context
from czsc_trader.research_tools import ResearchBatchRef,EvidenceRef

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
RUN=ROOT/'research/S014/assets/runs'/EX.name/'first'


def material(experiment,name,kind='json'):
    result=json.loads((ROOT/f'research/S014/experiments/{experiment}/others/result.json').read_text(encoding='utf-8'))
    ref=EvidenceRef.from_dict(result['evidence'][name]);raw=ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest()==ref.sha256
    return (pd.read_csv(BytesIO(raw)) if kind=='csv' else json.loads(raw)),ref.to_dict()


def load():
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'))
    ready,ready_ref=material('EX004_20261016','input-readiness')
    original=requests.sessions.Session.request
    def prohibited(*args,**kwargs):raise RuntimeError('No external calls authorized')
    requests.sessions.Session.request=prohibited
    sources={'stock-readiness':ready_ref};data={}
    def fetch(req,bound,expected):
        prepared=PreparedDataRef(UUID(bound['space_id']),UUID(bound['preparation_id']),bound['manifest_sha256'])
        result=ctx.data.fetch(req,prepared=prepared)
        assert result.ready and result.identity.content_sha256==expected
        return result.dataframe.sort_values('Date').reset_index(drop=True)
    try:
        for item in ready['records']:
            r=item['request']
            data[r['dataset']]=fetch(DataRequest(Dataset(r['dataset']),r['symbol'],r['start'],r['end'],r['required_cutoff']),item['reference'],item['content_sha256'])
        for key,ex,name,symbol in [('market','EX009_20261017','upstream-verification','000001.SH'),('sector','EX010_20261017','resolved-upstream','000813.CSI')]:
            value,ref=material(ex,name);sources[key]=ref
            assert value['status']=='PASS'
            data[key]=fetch(DataRequest(Dataset.DOMESTIC_INDEX_DAILY,symbol,'2020-01-01','2026-10-15','2026-10-15'),value['reference'],value['identity']['content_sha256'])
    finally:requests.sessions.Session.request=original
    dates=pd.DatetimeIndex(pd.to_datetime(data['stock.ohlcv'].Date))
    assert len(dates)==1642
    calendar=data['calendar.trading_sessions']
    assert dates.equals(pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1),'Date'])))
    for key in ('stock.unadjusted_daily','security.price_limits','security.trading_status','market','sector'):
        assert dates.equals(pd.DatetimeIndex(pd.to_datetime(data[key].Date))),key
    assert data['security.trading_status'].Status.eq('TRADING').all()
    old,sources['old-labels']=material('EX004_20261016','labels','csv')
    short,sources['short-labels']=material('EX008_20261017','run-labels','csv')
    cols=['signal','horizon','entry','quantity','entry_filled','status','maturity','net_return','entry_price','exit_price']
    a=old.loc[old.horizon.isin([3,5,10]),cols].sort_values(['horizon','signal']).reset_index(drop=True)
    b=short.loc[short.horizon.isin([3,5,10]),cols].sort_values(['horizon','signal']).reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b,check_exact=False,rtol=0,atol=1e-12)
    labels=pd.concat([short,old.loc[old.horizon.eq(20)]],ignore_index=True)
    legacy,sources['legacy-features']=material('EX004_20261016','features','csv')
    previous,sources['previous-features']=material('EX010_20261017','run-stock-lag-features','csv')
    assert len(legacy)==len(previous)==len(dates)
    return data,dates,labels,legacy,previous,sources
