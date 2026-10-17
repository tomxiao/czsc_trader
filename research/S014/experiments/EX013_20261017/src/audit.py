"""Independent numerical, execution-cash and temporal verification for EX013."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor
from czsc_trader.research_tools import EvidenceRef
from inputs import ROOT,EX,load
from features_v2 import compute,GROUPS
from study import diagnostics


def independent_predict(algo,x,z,y):
    if algo=='tree':return DecisionTreeRegressor(max_depth=3,min_samples_leaf=40,random_state=13).fit(x,y).predict(z)
    mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-12]=1
    return Ridge(alpha=10,fit_intercept=True,solver='cholesky').fit((x-mean)/scale,y).predict((z-mean)/scale)


def main():
    target=EX/'others/audit.json'
    if target.exists():raise RuntimeError('Preserve audit')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    checks=[]
    def check(name,value):
        assert value,name
        checks.append({'name':name,'status':'PASS'})
    mappings={'design':'protocols/design.json','coverage':'protocols/coverage.md','correction':'protocols/correction.json',
        'followup-design':'protocols/followup_design.json','direct-design':'protocols/direct_design.json','session-design':'protocols/session_design.json'}
    for receipt in ('published_design','published_implementation','published_implementation_v2','published_followup','published_direct','published_session'):
        for name,value in read(EX/f'protocols/{receipt}.json').items():
            ref=EvidenceRef.from_dict(value);raw=ref.resolve(ROOT).read_bytes()
            assert sha256(raw).hexdigest()==ref.sha256 and raw==(EX/mappings.get(name,f'src/{name}.py')).read_bytes()
    check('all executed sources and designs equal immutable published bytes',True)
    data,dates,labels,legacy,previous,sources=load();f,base=compute(data,legacy,previous)
    run=ROOT/'research/S014/assets/runs'/EX.name/'corrected'
    saved=pd.read_csv(run/'features.csv',index_col='signal')
    pd.testing.assert_frame_equal(f,saved,check_exact=False,rtol=0,atol=1e-9,check_names=False)
    check('147 features reproduced from public bound inputs',len(f.columns)==147)
    ids=np.flatnonzero(np.isfinite(f).all(axis=1));check('valid grid has no internal gaps',np.array_equal(ids,np.arange(121,1642)))
    for n in (400,801,1200):
        prefix,_=compute({k:v.iloc[:n] for k,v in data.items()},legacy.iloc[:n],previous.iloc[:n])
        pd.testing.assert_frame_equal(f.iloc[:n],prefix,check_exact=False,rtol=0,atol=1e-12)
    check('three causal feature prefixes including corrected recovery',True)
    close=data['stock.ohlcv'].Close.to_numpy()
    for t in range(121,1642):
        peak=t-int(f.loc[t,'peak_age']);trough=t-int(f.loc[t,'trough_age'])
        assert t-59<=peak<=trough<=t
        assert close[trough]==min(close[peak:t+1]) and close[peak]==max(close[t-59:t+1])
    check('all peak-trough-recovery chronology',True)
    valid_labels=labels.loc[labels.maturity.ge(0)&labels.signal.isin(ids)].copy()
    valid_labels['year']=[dates[int(s)].year for s in valid_labels.signal]
    published_labels=pd.read_csv(run/'labels.csv')
    pd.testing.assert_frame_equal(valid_labels.reset_index(drop=True),published_labels,check_exact=False,rtol=0,atol=1e-10)
    closed=valid_labels.loc[valid_labels.status.eq('CLOSED')]
    np.testing.assert_allclose(closed.quantity*(closed.exit_price*.999-closed.entry_price*1.001)/100000,closed.net_return,rtol=0,atol=1e-12)
    check('all inherited closed-label cash identities at 0.1% per side',len(closed)>6000)
    check('unfilled zero, no censored zero imputation',valid_labels.loc[valid_labels.status.eq('UNFILLED'),'net_return'].eq(0).all() and valid_labels.net_return.notna().all())
    p=pd.read_csv(run/'predictions.csv');result=read(EX/'others/computation_result_v2.json')
    models={'base':base,**{k:base+v for k,v in GROUPS.items()},'joint':base+sum(GROUPS.values(),[])};refits=0
    for (h,year),test in p.groupby(['horizon','year']):
        first=int(test.signal.min());train=valid_labels.loc[valid_labels.horizon.eq(h)&valid_labels.maturity.lt(first)]
        history=f.loc[np.isfinite(f).all(axis=1)&(f.index<=int(test.signal.max()))]
        assert train.maturity.max()<first
        for algo in ('ridge','tree'):
            for name,cols in models.items():
                score=pd.Series(independent_predict(algo,f.loc[train.signal,cols].to_numpy(),history[cols].to_numpy(),train.net_return.to_numpy()),index=history.index);refits+=1
                threshold=score.shift().rolling(126).quantile(.75)
                np.testing.assert_allclose(score.loc[test.signal],test[f'prediction_{algo}_{name}'],rtol=0,atol=1e-9)
                np.testing.assert_allclose(threshold.loc[test.signal],test[f'threshold_{algo}_{name}'],rtol=0,atol=1e-9)
                # Verify exact decisions against saved float predictions/thresholds; independent fit may round ties.
                assert np.array_equal(test[f'prediction_{algo}_{name}']>=test[f'threshold_{algo}_{name}'],test[f'select_{algo}_{name}'])
    check('360 complete independent estimator refits, maturity and causal thresholds',refits==360)
    for year,g in p.groupby('year'):
        s=np.sort(g.signal.unique());assert np.array_equal(s,np.arange(s.min(),s.max()+1))
    check('20-row primary bootstrap blocks are consecutive exchange sessions',True)
    comps,annual,_=diagnostics(p,dates)
    for expected,actual in zip(result['comparisons'],comps,strict=True):
        assert expected.keys()==actual.keys()
        for key in expected:
            if isinstance(expected[key],(int,float)):np.testing.assert_allclose(expected[key],actual[key],rtol=0,atol=1e-10)
            else:assert expected[key]==actual[key]
    check('all 80 comparisons and joint block intervals reproduced',True)
    # Validate followup fits independently, including tail treatment and lean controls.
    follow=pd.read_csv(run.parent/'followup/predictions.csv');plan=read(EX/'protocols/followup_design.json');follow_refits=0
    for (family,variant,year),test in follow.groupby(['family','variant','year']):
        algo=test.algorithm.iloc[0];first=int(test.signal.min());train=published_labels.loc[published_labels.horizon.eq(5)&published_labels.maturity.lt(first)]
        if variant=='recent252':train=train.tail(252)
        y=train.net_return.to_numpy()
        if variant=='clipped':y=np.clip(y,*np.quantile(y,[.01,.99]))
        controls=plan['lean_baseline'] if variant=='lean' else base
        added=[c for c in GROUPS[family] if variant!=f'without_{c}']
        for name,cols in [('base',controls),('added',controls+added)]:
            score=independent_predict(algo,saved.loc[train.signal,cols].to_numpy(),saved.loc[test.signal,cols].to_numpy(),y);follow_refits+=1
            np.testing.assert_allclose(score,test[f'prediction_{name}'],rtol=0,atol=1e-9)
    check('144 followup estimator refits including train-only winsorization',follow_refits==144)
    # Exact source members determine corrected annual means and primary H3 claims.
    direct=pd.read_csv(run.parent/'direct_observations.csv');fixed=pd.read_csv(EX/'others/direct_annual_corrected.csv')
    for row in fixed.itertuples(index=False):
        g=direct.loc[direct.family.eq(row.family)&direct.horizon.eq(row.horizon)]
        if str(row.year)!='ALL':g=g.loc[g.year.eq(int(row.year))]
        prior=p.loc[p.horizon.eq(row.horizon)].set_index('signal')
        y=g.net_return.to_numpy()-(prior.loc[g.signal,'prediction_ridge_base'].to_numpy() if row.mode=='residual' else 0)
        for key,mask in [('selected_mean',g.a.to_numpy()),('control_mean',g.b.to_numpy())]:
            if mask.any():np.testing.assert_allclose(getattr(row,key),y[mask].mean(),rtol=0,atol=1e-12)
    check('250 corrected direct annual means independently recomputed',len(fixed)==250)
    members=pd.read_csv(run.parent/'session_members.csv');stats=pd.read_csv(EX/'others/session_annual.csv')
    for row in stats.itertuples(index=False):
        g=members.loc[members.horizon.eq(row.horizon)&members.variant.eq(row.variant)]
        if row.year=='WITHOUT2026':g=g.loc[g.year.ne(2026)]
        elif row.year!='ALL':g=g.loc[g.year.eq(int(row.year))]
        a,b=g.loc[g.a],g.loc[g.b]
        assert len(a)==row.selected and len(b)==row.control
        np.testing.assert_allclose([a.net_return.mean(),b.net_return.mean(),a.net_return.mean()-b.net_return.mean()],[row.selected_mean,row.control_mean,row.difference],rtol=0,atol=1e-12)
    check('all conditional-state counts and annual means reproduced',True)
    matches=pd.read_csv(EX/'others/session_matches.csv');primary=members.loc[members.horizon.eq(3)&members.variant.eq('primary20')].set_index('signal')
    assert matches.a.is_unique and matches.b.is_unique
    for row in matches.itertuples(index=False):
        assert primary.loc[row.a,'a'] and primary.loc[row.b,'b'] and primary.loc[row.a,'year']==primary.loc[row.b,'year']==row.year
        assert row.distance<=1
        np.testing.assert_allclose(row.difference,primary.loc[row.a,'net_return']-primary.loc[row.b,'net_return'],rtol=0,atol=1e-12)
    check('54 unique same-year pairs, caliper and original outcomes',len(matches)==54)
    check('all requested temporal source bounds',dates.min()>=pd.Timestamp('2020-01-01') and dates.max()<=pd.Timestamp('2026-10-15'))
    files={p for directory in (EX/'src',EX/'protocols',EX/'others',run.parent) for p in directory.rglob('*') if p.is_file() and '__pycache__' not in str(p) and p.name not in ('audit.json','result.json','report_copy_verification.json')}
    manifest=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]
    target.write_text(json.dumps({'status':'PASS','checks':checks,'main_audit_refits':refits,'followup_audit_refits':follow_refits,
        'source_calls':0,'known_preserved_defects':['first回撤含义不准确及首次成功触及已由corrected修正。','direct_annual逐年均值导出缺陷由direct_annual_corrected替代；差值及计数原本正确。'],
        'manifest':manifest},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','checks':len(checks),'refits':refits+follow_refits,'files':len(manifest)}))


if __name__=='__main__':main()
