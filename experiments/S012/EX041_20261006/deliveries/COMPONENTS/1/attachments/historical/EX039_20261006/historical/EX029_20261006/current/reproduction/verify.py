"""Independent numerical audit of stored evidence, without experiment imports."""
from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd

ROOT=Path.cwd();EXP=ROOT/'experiments/S012/EX029_20261006';P=EXP/'artifacts/rex'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
d=pd.read_parquet(P/'daily.parquet');f=pd.read_parquet(P/'features.parquet')
s=pd.read_parquet(P/'signals.parquet');v=pd.read_parquet(P/'valids.parquet')
a=pd.read_parquet(P/'alignment.parquet');stored=pd.read_parquet(P/'labels.parquet')
specs=read(P/'hypothesis_definitions.json');parents={x['id']:x['parent'] for x in specs}
metrics=read(P/'opportunities.json');annual=read(P/'annual.json')
count=0
def eq(actual,expected):
    global count
    if actual is None:assert not np.isfinite(expected),(actual,expected)
    else:np.testing.assert_allclose(actual,expected,rtol=2e-9,atol=2e-12)
    count+=1
def mean(x):
    x=np.asarray(x,dtype=float);x=x[np.isfinite(x)]
    return x.mean() if len(x) else np.nan
def schedule(mask,gap):
    out=[]
    for n in range(len(mask)):
        if mask[n] and (not out or n-out[-1]>=gap):out.append(n)
    return np.array(out,dtype=int)
raw={}
for key,ref in read(P/'source_hashes.json').items():
    source=ROOT/'experiments/S012'/ref['experiment_id']/'artifacts/rex'/ref['artifact']
    assert sha256(source.read_bytes()).hexdigest()==ref['sha256']
    x=pd.read_parquet(source);x.attrs={};raw[key]=x
for prefix in sorted({x.removesuffix('_DecisionTime') for x in a if x.endswith('_DecisionTime')}):
    found=a[prefix+'_AvailableDate'].notna()
    assert (a.loc[found,prefix+'_AvailableDate']<=a.loc[found,prefix+'_DecisionTime']).all()
    assert (a.loc[found,prefix+'_SourceDate']<a.index[found]).all()
    assert (a.loc[found,prefix+'_DecisionTime']-a.loc[found,prefix+'_AvailableDate']<=pd.Timedelta(days=7)).all()
# Recompute source changes at each recorded as-of date, independently of feature code.
for key in ('xau','fx'):
    z=raw[key].set_index(pd.to_datetime(raw[key].Date)).sort_index()
    for h in (1,5,20,60):
        expected=(z.BidClose/z.BidClose.shift(h)-1).reindex(pd.DatetimeIndex(a[key+'_SourceDate']))
        np.testing.assert_allclose(f[f'{key}{h}'],expected.to_numpy(),equal_nan=True,atol=1e-12)
        count+=len(d)
y=raw['real_yield'].set_index(pd.to_datetime(raw['real_yield'].Date)).RealYield10YPercent
n=raw['nominal_yield'].set_index(pd.to_datetime(raw['nominal_yield'].Date)).NominalYield10YPercent
z=pd.concat([y.rename('r'),n.rename('n')],axis=1,sort=True).dropna()
for name,series in [('real5',z.r-z.r.shift(5)),('be5',(z.n-z.r)-(z.n-z.r).shift(5))]:
    expected=series.reindex(pd.DatetimeIndex(a.yield_SourceDate)).to_numpy()
    np.testing.assert_allclose(f[name],expected,equal_nan=True,atol=1e-12);count+=len(d)
futures=raw['futures'].copy();futures['Date']=pd.to_datetime(futures.Date)
futures=futures[(futures.Volume>0)&((pd.to_datetime(futures.MaturityDate)-futures.Date).dt.days>=20)]
futures=futures.sort_values(['Date','OpenInterest','Contract']).drop_duplicates('Date',keep='last').set_index('Date')
spot=raw['sge'].set_index(pd.to_datetime(raw['sge'].Date)).Close
base=futures.Settle/spot-1
native=[]
for i in range(len(base)):
    date=base.index[i];pos=futures.index.get_indexer([date])[0]
    stable=pos>=5 and len(set(futures.Contract.iloc[pos-5:pos+1]))==1
    native.append(base.iloc[i]-base.iloc[i-5] if i>=5 and stable else np.nan)
expected=pd.Series(native,index=base.index).reindex(pd.DatetimeIndex(a.basis_SourceDate)).to_numpy()
np.testing.assert_allclose(f.basis5,expected,equal_nan=True,atol=1e-12);count+=len(d)

for h in (1,3,5,10,20):
  for delay in (0,2):
    entry=np.full(len(d),np.nan);exitp=entry.copy();low=entry.copy()
    offset=1+delay
    entry[:-offset]=d.Open.to_numpy()[offset:];low[:-offset]=d.Low.to_numpy()[offset:]
    exitp[:-offset-h]=d.Open.to_numpy()[offset+h:]
    gross=exitp/entry-1
    limit=np.trunc((d.Close.to_numpy()+1e-10)/.001)*.001
    price=np.where(entry<=limit,entry,np.where(low<=limit,limit,np.nan))
    idlog=np.full(len(d),np.nan);onlog=idlog.copy()
    for t in range(len(d)-offset-h+1):
        ix=slice(t+offset,t+offset+h)
        idlog[t]=np.log(d.Close.to_numpy()[ix]/d.Open.to_numpy()[ix]).sum()
        if t+offset+h<len(d):
            onlog[t]=np.log(d.Open.to_numpy()[t+offset+1:t+offset+h+1]/d.Close.to_numpy()[ix]).sum()
    for fee in (.001,.002):
      net=(1+gross)*(1-fee)/(1+fee)-1
      limit_net=exitp/price*(1-fee)/(1+fee)-1
      for col,values in [('net',net),('limit_net',limit_net),('gross',gross),('intraday_log',idlog),('overnight_log',onlog)]:
        np.testing.assert_allclose(stored[f'h{h}_d{delay}_f{fee}__{col}'],values,equal_nan=True,atol=1e-12)
        count+=len(d)
      for r in (r for r in metrics if (r['horizon'],r['delay'],r['fee'])==(h,delay,fee)):
        key=r['signal'];par=parents.get(key)
        mask=v[key].to_numpy()&np.isfinite(net)&f[['etf5','etf20','vol20','xau20','fx5']].notna().all(axis=1).to_numpy()
        if par:mask&=v[par].to_numpy()
        hit=mask&s[key].to_numpy();phit=mask&(s[par].to_numpy() if par else True)
        chosen=schedule(hit,h+1);pa=schedule(phit,h+1);filled=chosen[np.isfinite(limit_net[chosen])]
        cells=f.loc[mask,['etf5','vol20','xau20','fx5']].copy()
        cells['year']=cells.index.year
        cuts=cells.vol20.groupby(cells.year).transform(lambda x:np.searchsorted(x.quantile([1/3,2/3]).to_numpy(),x.to_numpy(),side='right'))
        cells['etf_sign']=cells.etf5>0;cells['gold_sign']=cells.xau20>0;cells['fx_sign']=cells.fx5>0;cells['bucket']=cuts
        cells['net']=net[mask]
        baseline=cells.groupby(['year','etf_sign','gold_sign','fx_sign','bucket']).net.transform('mean')
        residual=np.full(len(d),np.nan);residual[mask]=cells.net.to_numpy()-baseline.to_numpy()
        values={'eligible_days':mask.sum(),'events':hit.sum(),'parent_events':phit.sum(),
          'net_mean':mean(net[hit]),'unconditional_same_fee':mean(net[mask]),'parent_same_fee':mean(net[phit]),
          'parent_lift':mean(net[hit])-mean(net[phit]),'matched_increment':mean(residual[hit]),
          'nonoverlap_events':len(chosen),'nonoverlap_net':mean(net[chosen]),'limit_potential_fills':len(filled),
          'limit_potential_net':mean(limit_net[filled]),'potential_per60_original1535':len(filled)*60/1535,
          'intraday_log_mean':mean(idlog[hit]),'overnight_log_mean':mean(onlog[hit]),
          'fixed_parent_base_contribution':mean(net[pa]),'fixed_parent_filtered_contribution':mean(net[pa]*s[key].to_numpy()[pa])}
        xx=f.loc[mask,['etf5','etf20','vol20','xau20','fx5']].to_numpy();yy=d.index[mask].year
        sd=xx.std(axis=0);sd[sd==0]=1
        design=np.column_stack([np.ones(len(xx)),s[key].to_numpy()[mask],(xx-xx.mean(axis=0))/sd,*[(yy==y).astype(float) for y in sorted(set(yy))[1:]]])
        values['ols_increment']=np.linalg.pinv(design).dot(net[mask])[1] if len(xx)>=20 and len(set(s[key].to_numpy()[mask]))==2 and np.linalg.matrix_rank(design)==design.shape[1] else np.nan
        for k,x in values.items():eq(r[k],x)
        for aa in (x for x in annual if (x['signal'],x['horizon'],x['delay'],x['fee'])==(key,h,delay,fee)):
          am=mask&(d.index.year==aa['year']);ah=hit&am
          for k,x in [('eligible_days',am.sum()),('events',ah.sum()),('net_mean',mean(net[ah])),('matched_increment',mean(residual[ah]))]:eq(aa[k],x)

inference=read(P/'inference.json');ps=sorted((x['p'],x['signal']) for x in inference if x['p'] is not None)
independent_q={};last=1.
for rank in range(len(ps),0,-1):
    p,key=ps[rank-1];last=min(last,p*len(ps)/rank);independent_q[key]=last
for x in inference:eq(x['q'],independent_q[x['signal']])
assert len(specs)==19 and len(s.columns)==30 and len(metrics)==600 and len(annual)==4200 and len(inference)==19
out={'status':'PASS','scope':'独立源SHA、源变化与可得时间、换月排除、全部20标签场景、600路径、4200年度、BH19诊断；不复现bootstrap和循环移位随机抽样，不证明真实历史发布时刻或账户绩效。','numerical_fields_checked':count,'sources':len(raw),'sessions':len(d),'hypotheses':len(specs),'paths':len(metrics),'annual_rows':len(annual),'bh_family':len(ps)}
(EXP/'artifacts/verification').mkdir(parents=True,exist_ok=True)
(EXP/'artifacts/verification/independent.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
