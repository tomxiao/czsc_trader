"""Prepare existing paired labels and decision-time bars; offline only."""
from hashlib import sha256
from pathlib import Path
from uuid import UUID
import json
import socket
import sys
import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX/'others'


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def write(p, value):
    with p.open('x', encoding='utf-8', newline='\n') as h:
        h.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def block(*a, **k):
    raise RuntimeError('EX033: no network authorized')


def classify(p, r, m, s):
    if not all(np.isfinite(x) for x in (p, r, m, s)):
        return None
    return bool(p <= 0 and m < 0 and s < 0 and r-s >= 0)


def precheck():
    cases = [(0,-.01,-.01,-.02,True),(.001,-.01,-.01,-.02,False),
             (-.01,-.02,-.01,-.02,True),(-.01,-.03,-.01,-.02,False),
             (-.01,-.01,0,-.02,False),(-.01,-.01,-.01,0,False),
             (-.01,float('nan'),-.01,-.02,None)]
    for p,r,m,s,y in cases:
        assert classify(p,r,m,s) == y
    days = pd.to_datetime(pd.Series(['2024-01-02','2024-01-03']))
    source = pd.Series([100.,99.], index=days)
    assert pd.to_datetime(pd.Series(['2024-01-02',None])).map(source).iloc[0] == 100
    assert pd.isna(pd.to_datetime(pd.Series(['2024-01-04'])).map(source).iloc[0])
    assert 10-(8-3) == 5 and (8 < 3+9)
    write(OUT/'preparation_precheck.json', {'status':'PASS','checks':10,'new_fits':0,'new_labels':0,'new_calls':0,'new_accounts':0})


def main():
    socket.socket.connect = block
    socket.create_connection = block
    assert not (OUT/'events.csv').exists()
    for name in ('published_design','preparation_lock'):
        for rel, value in read(EX/f'protocols/{name}.json').items():
            assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes() == (ROOT/rel).read_bytes()
    sources = {}

    def local(rel):
        path=ROOT/rel
        sources[rel]=sha256(path.read_bytes()).hexdigest()
        return read(path)

    old = 'research/S014/experiments/EX023_20261018'
    diagnostic = local(old+'/others/loss_state_diagnostics.json')
    source_result = local(old+'/others/result.json')
    diag_ref = EvidenceRef.from_dict(source_result['evidence']['ex023-others-loss_state_diagnostics-json'])
    assert diag_ref.resolve(ROOT).read_bytes() == (ROOT/old/'others/loss_state_diagnostics.json').read_bytes()
    accounts = local(old+'/others/comparison_accounts.json')['records']
    account_refs = {}
    trades = {}
    for name in ('support_entry_H10','support_exit_reserve_H10'):
        record=next(r for r in accounts if r['variant']==name)
        ref=EvidenceRef.from_dict(record['evidence'])
        raw=ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest()==ref.sha256
        value=json.loads(raw)
        assert value['result_hash']==record['result_hash'] and len(value['runs'])==1
        table=pd.DataFrame(value['runs'][0]['ledgers']['trades']['data'])
        table['entry_date']=pd.to_datetime(table.entry_date).dt.normalize()
        table['exit_date']=pd.to_datetime(table.exit_date).dt.normalize()
        assert not table.entry_date.duplicated().any()
        trades[name]=table.set_index('entry_date')
        account_refs[name]=record['evidence']
    ctx=create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'), providers=ProviderConfig(bindings={}))
    identities=[]

    def fetch(dataset, symbol, start, bound, expected=None):
        prepared=PreparedDataRef(UUID(bound['space_id']),UUID(bound['preparation_id']),bound['manifest_sha256'])
        result=ctx.data.fetch(DataRequest(dataset,symbol,start,'2026-10-15','2026-10-15'),prepared=prepared)
        assert result.ready
        if expected is not None:
            assert result.identity.content_sha256 == expected
        df=result.dataframe.copy()
        df['Date']=pd.to_datetime(df.Date).dt.normalize()
        df=df.sort_values('Date').set_index('Date')
        assert not df.index.has_duplicates
        identities.append({'dataset':dataset.value,'symbol':symbol,'start':start,'reference':bound,'content_sha256':result.identity.content_sha256,'rows':len(df)})
        return df

    stock=fetch(Dataset.STOCK_OHLCV,'600722.SH','2019-12-31',diagnostic['prepared_reference'])
    indexes=[]
    for folder,file,symbol in [('EX009_20261017','upstream_verification.json','000001.SH'),('EX010_20261017','upstream_verification_resolved.json','000813.CSI')]:
        v=local(f'research/S014/experiments/{folder}/others/{file}')
        assert v['status']=='PASS' and v['request']['symbol']==symbol
        indexes.append(fetch(Dataset.DOMESTIC_INDEX_DAILY,symbol,'2020-01-01',v['reference'],v['identity']['content_sha256']))
    market,sector=indexes
    calendar=stock.loc['2020-01-01':].index
    assert len(calendar)==1642 and market.index.equals(calendar) and sector.index.equals(calendar)
    f=pd.DataFrame(index=calendar)
    for name,df in [('stock',stock),('market',market),('sector',sector)]:
        # Exact preceding stock/SSE session, never previous available index observation.
        previous=pd.Series(stock.index[:-1],index=stock.index[1:]).reindex(calendar)
        prior=previous.map(df.Close)
        f[name+'_return']=df.Close.reindex(calendar)/prior-1
    f['amplitude']=(stock.High-stock.Low).reindex(calendar)/stock.Close.reindex(calendar)
    f['hfq_close']=stock.Close.reindex(calendar)
    f['previous_date']=previous
    f.to_csv(OUT/'decision_features.csv', index_label='date', lineterminator='\n')
    pd.DataFrame({'date':calendar}).to_csv(OUT/'calendar.csv',index=False,lineterminator='\n')
    entries=[r for r in diagnostic['episodes'] if r['window']=='ALL']
    assert len(entries)==138
    early=[r for r in entries if r['early_break']]
    paired=[r for r in early if r['both_closed'] and r['matched_B_entry']]
    outside=[r for r in early if not (r['both_closed'] and r['matched_B_entry'])]
    assert len(early)==103 and len(paired)==100 and len(outside)==3
    rows=[]
    support=stock.Close.where(stock.index>=pd.Timestamp('2020-01-01')).shift().rolling(5).min()
    for record in paired:
        r=dict(record)
        e=pd.Timestamp(r['entry_date']); d=pd.Timestamp(r['decision_date'])
        i=stock.index.get_loc(e); j=stock.index.get_loc(d)
        assert i<=j<i+9 and d<pd.Timestamp(r['exit_or_mark_date'])
        breaks=stock.Close.iloc[i:j+1] < support.iloc[i:j+1]
        assert breaks.iloc[-1] and breaks.iloc[:-1].sum()==0
        b=trades['support_entry_H10'].loc[e]; early_trade=trades['support_exit_reserve_H10'].loc[e]
        assert b.status==early_trade.status=='CLOSED'
        assert np.isclose(float(b.net_return),r['B_position_return'],atol=1e-14)
        assert np.isclose(float(early_trade.net_return),r['R_position_return'],atol=1e-14)
        assert early_trade.exit_date==pd.Timestamp(r['exit_or_mark_date'])
        p=stock.loc[d,'Close']/diagnostic['scale_anchor']/(float(early_trade.entry_price)*1.001)-1
        assert np.isclose(p,r['close_net_of_buy_fee_return'],atol=1e-12)
        assert (p>0)==r['positive_mark']
        feat=f.loc[d]
        values=[r['close_net_of_buy_fee_return'],feat.stock_return,feat.market_return,feat.sector_return]
        valid=all(np.isfinite(v) for v in values)
        assert valid, 'Incomplete decision features: preserve as preparation failure, never classify missing as zero'
        r.update(R_exit_date=r['exit_or_mark_date'],B_exit_date=str(b.exit_date.date()),
            stock_return=float(feat.stock_return),market_return=float(feat.market_return),sector_return=float(feat.sector_return),
            amplitude=float(feat.amplitude),remaining_to_H10_sessions=10-(j-i),
            common_decline=bool(feat.market_return<0 and feat.sector_return<0),relative_resilient=bool(feat.stock_return>=feat.sector_return),
            hold_candidate=classify(*values),hold_P=not r['positive_mark'],
            action_delta=r['B_position_return']-r['R_position_return'],feature_previous_date=str(feat.previous_date.date()))
        rows.append(r)
    events=pd.DataFrame(rows).sort_values(['decision_date','entry_date']).reset_index(drop=True)
    events['event_id']=np.arange(len(events))
    assert (~events.positive_mark).sum()==85 and events.positive_mark.sum()==15
    assert events.decision_date.nunique()==100
    events.to_csv(OUT/'events.csv',index=False,lineterminator='\n')
    write(OUT/'inputs.json',{'status':'PASS','source_sha256':sources,'source_diagnostic':diag_ref.to_dict(),
        'account_evidence':account_refs,'native_identities':identities,'early_events':103,'paired':100,'nonpositive_pairs':85,'positive_pairs':15,
        'unmatched_events':outside,'outside_scope_non_early':35,'all_inputs_complete':True,
        'calendar_rows':1642,'events_sha256':sha256((OUT/'events.csv').read_bytes()).hexdigest(),
        'features_sha256':sha256((OUT/'decision_features.csv').read_bytes()).hexdigest(),
        'new_data_calls':0,'new_fits':0,'new_labels':0,'new_accounts':0,
        'availability':'Same-date completed close convention inherited; publication/revision history not independently certified.'})
    print(json.dumps({'status':'PASS','paired':100,'early_events':103,'unmatched':3,'new_calls':0,'new_fits':0,'new_labels':0,'new_accounts':0}))


if __name__=='__main__':
    precheck() if sys.argv[-1]=='precheck' else main()
