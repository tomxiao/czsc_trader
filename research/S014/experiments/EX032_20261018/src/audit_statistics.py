"""Independent arithmetic and calendar-resampling audit; no fitted estimator."""
from pathlib import Path
from hashlib import sha256
import json
import socket
import numpy as np
import pandas as pd

EX=Path(__file__).resolve().parents[1]
OUT=EX/'others'


def main():
    def prohibited(*a,**k):
        raise RuntimeError('No network or fitting in statistics audit')
    socket.create_connection=prohibited
    socket.socket.connect=prohibited
    np.linalg.solve=prohibited
    np.linalg.lstsq=prohibited
    assert not (OUT/'independent_statistics_audit.json').exists()
    a=json.loads((OUT/'analysis.json').read_text(encoding='utf-8'))
    p=pd.read_csv(OUT/'predictions.csv')
    f=p.loc[p.A].copy()
    raw=pd.read_csv(OUT/'inputs.csv')
    cal=pd.read_csv(OUT/'calendar.csv')
    checks=[]
    def eq(name,x,y):
        if x is None or y is None:
            assert x is None and y is None,name
        else:
            np.testing.assert_allclose(x,y,rtol=1e-11,atol=2e-12,err_msg=name)
        checks.append(name)
    def metrics(g,w=None):
        w=np.ones(len(g)) if w is None else np.asarray(w)
        def avg(v,mask):
            den=w[mask].sum()
            return None if not den else float(np.dot(v[mask],w[mask])/den)
        y=g.Y3.to_numpy(float)
        resid=y-g.score_M1.to_numpy(float)
        d=[];r=[]
        for z,s,sign in [(1,1,1),(0,1,-1),(1,0,-1),(0,0,1)]:
            mask=(g.z.to_numpy()==z)&(g.S.to_numpy()==s)
            m,n=avg(y,mask),avg(resid,mask)
            d.append(None if m is None else sign*m)
            r.append(None if n is None else sign*n)
        out={'D':None if None in d else sum(d),'D_residual_M1':None if None in r else sum(r)}
        for new,base in [('M2','M1'),('M1','M0')]:
            out['allocation_'+new+'_minus_'+base]=avg(y*(g['sel_'+new].to_numpy(int)-g['sel_'+base].to_numpy(int)),np.ones(len(g),bool))
        return out
    scopes=[('main',f,a['main']),('without2026',f[f.year.ne(2026)],a['without_2026']),('exclude_roll',f[~f.roll],a['exclude_roll'])]
    scopes += [(str(y),f[f.year.eq(y)],a['annual'][str(y)]) for y in range(2023,2027)]
    scopes += [('leave_year_'+str(y),f[f.year.ne(y)],a['leave_one_year_out'][str(y)]) for y in range(2023,2027)]
    for name,g,result in scopes:
        for k,v in metrics(g).items(): eq(name+k,v,result[k])
        for z,s in [(1,1),(0,1),(1,0),(0,0)]:
            part=g[g.z.eq(z)&g.S.eq(s)]
            cell=result['four_cells']['cells'][f'z{z}_S{s}']
            eq(name+f'cell{z}{s}n',len(part),cell['n'])
            eq(name+f'cell{z}{s}mean',None if not len(part) else part.Y3.mean(),cell['raw']['mean'])
        for model in ['M0','M1','M2']:
            selected=g[g['sel_'+model]]
            row=result['participation'][model]
            eq(name+model+'n',len(selected),row['selected_count'])
            eq(name+model+'mean',None if not len(selected) else selected.Y3.mean(),row['selected_returns']['mean'])
    for metric,scopes in a['favorable_trimming']['results'].items():
        for scope,runs in scopes.items():
            for count,r in runs.items():
                g=f[~f.signal.isin(r['removed_signals'])]
                for k,v in metrics(g).items():eq('trim'+metric+scope+count+k,v,r['metrics'][k])
    # Reconstruct connected actual holding intervals independently.
    assignment={};cluster=0;end=-1
    for row in f[f.entry_filled].sort_values(['entry','maturity','signal']).itertuples():
        if row.entry>end:
            cluster+=1
        end=max(end,row.maturity)
        assignment[row.signal]=cluster
    for row in f[~f.entry_filled].sort_values('signal').itertuples():
        cluster+=1;assignment[row.signal]=cluster
    eq('clusters',cluster,a['holding']['cluster_count'])
    ids=f.signal.map(assignment)
    weights=1/ids.map(ids.value_counts()).to_numpy(float)
    for k,v in metrics(f,weights).items():eq('equalcluster'+k,v,a['holding']['equal_cluster'][k])
    for row in a['holding']['leave_one_cluster_out']:
        g=f[ids.ne(row['omitted_cluster'])]
        for k,v in metrics(g).items():eq('leavecluster'+str(row['omitted_cluster'])+k,v,row['metrics'][k])
    # Independently resample row multiplicities from calendar block membership.
    # Empty dates and the shorter final block are kept without constructing daily outcome sums.
    rng=np.random.default_rng(13)
    w=np.zeros((2000,len(f)))
    for year in range(2023,2027):
        days=cal.loc[cal.year.eq(year),'signal'].to_numpy()
        blocks=[days[i:i+20] for i in range(0,len(days),20)]
        membership=np.array([f.signal.isin(b).to_numpy(int) for b in blocks])
        draws=rng.integers(0,len(blocks),(2000,len(blocks)))
        counts=np.stack([np.bincount(d,minlength=len(blocks)) for d in draws])
        w += counts@membership
    y=f.Y3.to_numpy(float);res=y-f.score_M1.to_numpy(float)
    d=np.zeros(2000);dr=np.zeros(2000);valid=np.ones(2000,bool)
    for z,s,sign in [(1,1,1),(0,1,-1),(1,0,-1),(0,0,1)]:
        mask=(f.z.to_numpy()==z)&(f.S.to_numpy()==s)
        n=w[:,mask].sum(1);valid &= n>0
        d += sign*np.divide(w[:,mask]@y[mask],n,out=np.full(2000,np.nan),where=n>0)
        dr += sign*np.divide(w[:,mask]@res[mask],n,out=np.full(2000,np.nan),where=n>0)
    den=w.sum(1)
    distributions={'D':d,'D_residual_M1':dr}
    for new,base in [('M2','M1'),('M1','M0')]:
        distributions['allocation_'+new+'_minus_'+base]=w@(y*(f['sel_'+new].to_numpy(int)-f['sel_'+base].to_numpy(int)))/den
    for key,values in distributions.items():
        values=values[np.isfinite(values)]
        row=a['bootstrap']['ordinary_95'][key]
        eq('bootstrap'+key+'valid',len(values),row['valid'])
        eq('bootstrap'+key+'low',np.quantile(values,.025),row['low'])
        eq('bootstrap'+key+'high',np.quantile(values,.975),row['high'])
    for key in ['D','allocation_M2_minus_M1']:
        values=distributions[key][valid & (den>0)]
        row=a['bootstrap']['simultaneous_primary_two_95'][key]
        eq('simultaneous'+key+'low',np.quantile(values,.0125),row['low'])
        eq('simultaneous'+key+'high',np.quantile(values,.9875),row['high'])
    simple=raw[raw.A & raw.z.eq(1) & raw.S.eq(1)]
    eq('full_simple_triggers',len(simple),51)
    assert simple.label_ready.all() and simple.entry_filled.all()
    eq('full_simple_report',len(simple),a['full_period_raw']['full']['simple_z1_S1']['filled'])
    unknown=raw[raw.A & ~raw.label_ready]
    assert not unknown.signal.isin(simple.signal).any()
    changed=f[f.sel_M2.ne(f.sel_M1)]
    eq('changed_count',len(changed),1)
    eq('changed_signal',changed.signal.iloc[0],858)
    assert changed.S.eq(0).all() and changed.Y3.lt(0).all()
    result=dict(status='PASS',checks=len(checks),check_names=checks,new_model_fits=0,new_labels=0,new_calls=0,new_accounts=0,
        simple_rule_capacity=dict(all_triggers=len(simple),mature_filled=len(simple),unknown_label_triggers=0,
            optimistic_frequency_60=60*len(simple)/1642,required_closures=83,
            meaning='Upper bound applies only to A & z1 & S1 fixed simple rule, before holding conflicts, not to models or other strategies.'),
        changed_interaction_selections=changed[['signal','date','S','z','Y3']].to_dict('records'),
        method='Independent four-cell means, allocation differences, deleted-subset and overlap-cluster arithmetic; independent calendar-block membership weight construction for 2000 conditional bootstrap draws. No fit.',
        source_sha256={str(p.relative_to(EX)):sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),OUT/'analysis.json',OUT/'predictions.csv',OUT/'inputs.csv',OUT/'calendar.csv']})
    (OUT/'independent_statistics_audit.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','checks':len(checks),'capacity':result['simple_rule_capacity']}))


if __name__=='__main__':
    main()
