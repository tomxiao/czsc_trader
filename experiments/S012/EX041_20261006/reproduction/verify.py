"""Reconstruct from authenticated inputs; no experiment implementation import."""
from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd
ROOT=Path.cwd();EXP=ROOT/'experiments/S012/EX041_20261006';P=EXP/'artifacts/rex'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
raw={}
for key,ref in read(P/'source_hashes.json').items():
    source=ROOT/'experiments/S012'/ref['experiment_id']/'artifacts/rex'/ref['artifact']
    assert sha256(source.read_bytes()).hexdigest()==ref['sha256']
    assert read(source.parent/'execution_receipt.json')['artifact_sha256'][ref['artifact']]==ref['sha256']
    raw[key]=pd.read_parquet(source);raw[key].attrs={}
d=raw['daily'];s=pd.read_parquet(P/'signals.parquet');v=pd.read_parquet(P/'valids.parquet')
pd.testing.assert_frame_equal(pd.read_parquet(P/'daily.parquet'),d)
assert len(d)==1535 and d.index[0]==pd.Timestamp('2020-06-05') and d.index[-1]==pd.Timestamp('2026-09-30')
for key,source,col in [('o01','old','L01'),('o01_q07','old','L03'),('n09','old','L02'),
                       ('m05_common','old','C_M05'),('momentum_common','old','C_MOMPOS'),('m05','native','R01')]:
    srcv=raw['old_valid' if source=='old' else 'native_valid'][col]
    pd.testing.assert_series_equal(v[key],srcv,check_names=False)
    pd.testing.assert_series_equal(s[key],raw[source][col]&srcv,check_names=False)
pd.testing.assert_series_equal(v.momentum,raw['features'].etf3.notna(),check_names=False)
pd.testing.assert_series_equal(s.momentum,raw['features'].etf3.gt(0),check_names=False)
pd.testing.assert_series_equal(s['union'],s.o01|s.m05,check_names=False)
pd.testing.assert_series_equal(v['union'],(v.o01&v.m05)|s['union'],check_names=False)
pd.testing.assert_series_equal(s.momentum_union,s.momentum|s['union'],check_names=False)
pd.testing.assert_series_equal(v.momentum_union,(v.momentum&v['union'])|s.momentum_union,check_names=False)
for key in ('m05_common','momentum_common'):
    native='m05' if key=='m05_common' else 'momentum'
    assert (s[key][v[key]]==s[native][v[key]]).all()
count=0;calendar=np.arange(len(d));year=d.index.year.to_numpy()
def eq(a,b):
    global count
    if a is None:assert not np.isfinite(b),(a,b)
    else:np.testing.assert_allclose(a,b,rtol=2e-9,atol=2e-12)
    count+=1
def mean(x):return np.mean(x) if len(x) else np.nan
def nonoverlap(mask,gap):
    out=[]
    for i,active in enumerate(mask):
        if active and (not out or i-out[-1]>=gap):out.append(i)
    return np.array(out,dtype=int)
panels={};lab=pd.read_parquet(P/'labels.parquet')
for h in (1,3,5,10):
 for delay in (0,1,2):
  for fee in (.001,.002):
    y=np.full(len(d),np.nan);ly=y.copy();op=d.Open.to_numpy();lo=d.Low.to_numpy();close=d.Close.to_numpy()
    for i in range(len(d)-1-delay-h):
        entry=op[i+1+delay];exit_=op[i+1+delay+h]
        limit=np.floor((close[i]+1e-10)/.001)*.001
        y[i]=(exit_*(1-fee))/(entry*(1+fee))-1
        if entry<=limit or lo[i+1+delay]<=limit:
            buy=min(entry,limit);ly[i]=(exit_*(1-fee))/(buy*(1+fee))-1
    panels[h,delay,fee]=(y,ly)
    np.testing.assert_allclose(lab[f'h{h}_d{delay}_f{fee}__net'],y,equal_nan=True)
    np.testing.assert_allclose(lab[f'h{h}_d{delay}_f{fee}__limit_net'],ly,equal_nan=True)
for r in read(P/'opportunities.json'):
    y,ly=panels[r['horizon'],r['delay'],r['fee']];key=r['signal']
    good=v[key].to_numpy()&np.isfinite(y);hit=good&s[key].to_numpy()
    ids=nonoverlap(hit,r['horizon']+1);fills=ids[np.isfinite(ly[ids])]
    for field,value in [('eligible_days',good.sum()),('events',hit.sum()),('net_mean',mean(y[hit])),
                         ('same_window_mean',mean(y[good])),('potential_events',len(ids)),
                         ('potential_fills',len(fills)),('potential_limit_net',mean(ly[fills])),
                         ('potential_per60',len(fills)*60/1535)]:eq(r[field],value)
for r in read(P/'annual.json'):
    y,ly=panels[r['horizon'],r['delay'],r['fee']];key=r['signal']
    hit=v[key].to_numpy()&np.isfinite(y)&s[key].to_numpy()
    ids=nonoverlap(hit,r['horizon']+1);fills=ids[np.isfinite(ly[ids])];fills=fills[year[fills]==r['year']]
    for field,value in [('events',(hit&(year==r['year'])).sum()),('net_mean',mean(y[hit&(year==r['year'])])),
                         ('potential_fills',len(fills)),('potential_limit_net',mean(ly[fills]))]:eq(r[field],value)
pairs={'M05_SCOPE':('m05_common','m05','m05_common'),'MOM_SCOPE':('momentum_common','momentum','momentum_common'),
       'O01_M05':('o01','union','o01_m05_common'),'MOM_ADD':('momentum','momentum_union','all_common'),
       'Q07':('o01','o01_q07','o01'),'N09_GATE':('momentum','n09','momentum_common')}
for r in read(P/'phase_comparisons.json'):
    a,b,c=pairs[r['comparison']];y,ly=panels[r['horizon'],r['delay'],r['fee']]
    good=v[c].to_numpy()&v[a].to_numpy()&v[b].to_numpy()&np.isfinite(y)&(calendar%(r['horizon']+1)==r['phase'])
    if r['omitted_year'] is not None:good &= year!=r['omitted_year']
    values=np.where(np.isfinite(ly[good]),ly[good],0)
    before=np.where(s[a][good],values,0);after=np.where(s[b][good],values,0)
    for field,value in [('slots',good.sum()),('before_limit',mean(before)),('after_limit',mean(after)),
                         ('marginal_limit',mean(after-before)),
                         ('before_fills',(s[a].to_numpy()&good&np.isfinite(ly)).sum()),
                         ('after_fills',(s[b].to_numpy()&good&np.isfinite(ly)).sum())]:eq(r[field],value)
    if r['comparison'] in ('M05_SCOPE','MOM_SCOPE') and r['slots']:eq(r['marginal_limit'],0.)
out=EXP/'artifacts/verification/independent.json';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'status':'PASS','numerical_fields_checked':count,'source_checks':len(raw),
    'checks':['source_receipt_sha','native_and_common_signals','unknown_union_semantics','216_paths','1512_annual','6624_phase_loo',
              'independent_price_fee_limit_labels','scope_controls_zero_on_common_calendar']},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print('INDEPENDENT PASS',count)
