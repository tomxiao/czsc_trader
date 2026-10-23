"""Independent zero-fit conjunction audit with interval dynamic programming."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import importlib.util,json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[3];BASE=HERE.parent
def read(p):return json.loads(p.read_bytes())
def prior_module(ex,name):
    p=BASE/ex/'src'/name;refs=read(BASE/ex/'others/published_refs.json')['materials'];assert EvidenceRef.from_dict(refs['src/'+name]).resolve(ROOT).read_bytes()==p.read_bytes()
    spec=importlib.util.spec_from_file_location(ex+'_'+name.replace('.','_'),p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def interval(p,values):
    full=np.full(434,np.nan);full[p.position.to_numpy(int)]=values;rng=np.random.default_rng(13);means=[]
    for _ in range(499):
        indices=(rng.integers(415,size=22)[:,None]+np.arange(20)).reshape(-1)[:434];v=full[indices];v=v[np.isfinite(v)]
        if len(v):means.append(v.mean())
    return np.quantile(means,[.025,.975])
def summary(out,p,policy,label,a):
    y=p[label].to_numpy();keep=p['keep/'+policy].to_numpy(bool);a.eq(out['n'],len(p));a.check_amount(out['selected'],y[keep]);a.check_amount(out['excluded'],y[~keep])
    a.eq(out['caught_loss_fraction'],a.ratio(-sum(y[(y<0)&(~keep)]),-sum(y[y<0])))
    a.eq(out['missed_profit_fraction'],a.ratio(sum(y[(y>0)&(~keep)]),sum(y[y>0])))
    a.eq(out['retained_event_sum'],sum(y[keep]));a.eq(out['retained_amount'],sum(y[keep])*100000)
def difference(out,p,policy,ref,label,a):
    y=p[label].to_numpy();keep=p['keep/'+policy].to_numpy(bool);old=p['keep/'+ref].to_numpy(bool)
    removed=old&(~keep);added=keep&(~old);change=np.where(keep,y,0)-np.where(old,y,0)
    values={'n':len(p),'removed_n':sum(removed),'added_n':sum(added),'removed_loss_amount':-sum(y[removed&(y<0)])*100000,'removed_profit_amount':sum(y[removed&(y>0)])*100000,'added_event_amount':sum(y[added])*100000,'net_retained_amount_increment':sum(change)*100000,'mean_per_common_event':change.mean()}
    for k,v in values.items():a.eq(out[k],v)
    a.eq(out['ci95_mean_per_common_event'],interval(p,change))
    a.eq(values['net_retained_amount_increment'],values['removed_loss_amount']-values['removed_profit_amount']+values['added_event_amount'])
    if ref in (policy.replace('/AND','/path'),policy.replace('/AND','/risk')):a.eq(sum(added),0)
def main():
    audit=prior_module('EX036_20261023','independent_audit.py');dp=prior_module('EX038_20261023','independent_audit.py')
    frozen=read(HERE/'others/protocol_refs.json')
    for name,folder in [('composition.py','src'),('composition.json','protocols')]:assert EvidenceRef.from_dict(frozen[name]).resolve(ROOT).read_bytes()==(HERE/folder/name).read_bytes()
    proto=read(HERE/'protocols/composition.json');paths={k:EvidenceRef.from_dict(v).resolve(ROOT) for k,v in proto['source_refs'].items()}
    for key in ('EX036_20261023/src/validate.py','EX038_20261023/src/attribution.py','EX039_20261023/src/standalone.py'):assert (BASE/key).read_bytes()==paths[key].read_bytes()
    for ex in ('EX038_20261023','EX039_20261023'):assert read(paths[ex+'/others/independent_audit.json'])['status']=='PASS'
    p39=pd.read_csv(paths['EX039_20261023/others/predictions.csv']);p38=pd.read_csv(paths['EX038_20261023/others/predictions.csv']);features=pd.read_csv(paths['EX036_20261023/others/model_features.csv']);labels=pd.read_csv(paths['EX036_20261023/others/labels.csv']);events=pd.read_csv(paths['original_events']);actual=pd.read_csv(HERE/'others/decisions.csv');result=read(HERE/'others/results.json')
    g1=p39[p39.target=='net3'].sort_values('position');g2=p39[p39.target=='loss3'].sort_values('position');g3=p38[p38['case']=='net3/temporal_order/linear'].sort_values('position');g4=p38[p38['case']=='loss3/volatility_transition/linear'].sort_values('position')
    positions=g1.position.tolist();assert len(positions)==len(set(positions))==323
    p=features.set_index('position').loc[positions].reset_index()[['position','date','r1','r5']];p['fold']=g1.fold.to_numpy()
    for source in (g1,g2,g3,g4):
        audit.eq(source.position.tolist(),positions);audit.eq(source.fold.to_numpy(),p.fold.to_numpy());assert source.date.tolist()==p.date.tolist();audit.eq(source.payoff.to_numpy(),g1.y.to_numpy())
    for label in ('net3','entry'):p[label]=labels[labels.target==label].set_index('position').loc[positions,'y'].to_numpy();assert p[label].notna().all()
    p['keep/all']=True;p['keep/legacy']=g1['keep/legacy'].to_numpy(bool);p['keep/A/path']=g1['keep/path'].to_numpy(bool);p['keep/A/risk']=g2['keep/volatility'].to_numpy(bool);p['keep/B/path']=g3['keep/full'].to_numpy(bool);p['keep/B/risk']=g4['keep/full'].to_numpy(bool)
    audit.eq(p['keep/legacy'].to_numpy(),g3['keep/baseline'].to_numpy());audit.eq(g1.legacy.to_numpy(),g3.baseline.to_numpy())
    thresholds39=read(paths['EX039_20261023/others/thresholds.json']);thresholds38=read(paths['EX038_20261023/others/thresholds.json'])
    for fold in range(4):
        for source,col,key in [(g1,'path','A/path'),(g1,'legacy','legacy'),(g3,'full','B/path')]:
            selected=source[source.fold==fold];audit.eq(p.loc[p.fold==fold,'keep/'+key].to_numpy(),selected[col].to_numpy()>=0)
        for source,records,model,key in [(g2,thresholds39,'volatility','A/risk'),(g4,thresholds38,'full','B/risk')]:
            if key=='A/risk':threshold=next(r['threshold'] for r in records if r['target']=='loss3' and r['fold']==fold and r['model']==model)
            else:threshold=next(r['threshold'] for r in records if r['case']=='loss3/volatility_transition/linear' and r['fold']==fold and r['variant']==model)
            selected=source[source.fold==fold];audit.eq(p.loc[p.fold==fold,'keep/'+key].to_numpy(),selected[model].to_numpy()<=threshold)
    for pair in ('A','B'):p['keep/'+pair+'/AND']=p['keep/'+pair+'/path']&p['keep/'+pair+'/risk']
    assert set(p.columns)==set(actual.columns)
    for col in p.columns:
        if col=='date':assert p[col].tolist()==actual[col].tolist()
        else:audit.eq(actual[col],p[col])
    h3=events[events.horizon==3].set_index('position').loc[positions];h1=events[events.horizon==1].set_index('position').loc[positions];assert h3.status.eq('CLOSED').all()
    for col in ('entry_date','quantity','buy_price'):assert h3[col].tolist()==h1[col].tolist()
    audit.eq(p.net3.to_numpy(),h3.net.to_numpy()/100000);audit.eq(p.entry.to_numpy(),h1.entry_net.to_numpy()/100000)
    omit=p.net3.abs().nlargest(5).index;groups={'all':p,'omit_largest5_net3':p.drop(omit)}
    for fold,z in p.groupby('fold'):groups['fold/'+str(fold)]=z
    for short in (False,True):
        for long in (False,True):groups[f'state/r1_{"positive" if short else "nonpositive"}/r5_{"positive" if long else "nonpositive"}']=p[((p.r1>0)==short)&((p.r5>0)==long)]
    audit.eq(result['population_n'],323);audit.eq(result['omitted_positions'],p.loc[omit,'position'].tolist());assert set(result['policies'])==set(proto['rules'])
    for policy,out in result['policies'].items():
        for label in ('net3','entry'):
            assert set(out['outcomes'][label])==set(groups)
            for name,z in groups.items():summary(out['outcomes'][label][name],z,policy,label,audit)
        counts=dp.frequency(events,set(p.loc[p['keep/'+policy],'position']),3,features.date.tolist());f=out['frequency_upper_bound'];audit.eq(f['counts'],counts);audit.eq(f['median_max'],np.median(counts));audit.eq(f['windows'],275);audit.eq(f['at_least3_windows'],sum(n>=3 for n in counts))
    for key,out in result['paired'].items():
        policy,ref=key.split(' vs ')
        for label in ('net3','entry'):
            assert set(out[label])==set(groups)
            for name,z in groups.items():difference(out[label][name],z,policy,ref,label,audit)
    assert len(result['paired'])==8
    design=read(HERE/'others/design_counts.json');assert design['new_model_fits']==design['continuous_accounts']==design['parameter_search']==0
    assets=[Path(__file__),HERE/'src/composition.py',HERE/'protocols/composition.json',HERE/'others/decisions.csv',HERE/'others/results.json',HERE/'others/design_counts.json']
    output={'status':'PASS','checks':audit.CHECKS,'common_events':323,'policies':8,'outcomes':2,'groups':len(groups),'paired_comparisons':8,'bootstrap_intervals_checked':160,'frequency_windows_dp_checked':2200,'new_fits':0,'sha256':{str(p.relative_to(HERE)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in assets},'method':'Reconstructed selections and labels from authenticated frozen sources; prior decisions verified against their already-frozen thresholds. Independently recomputed amounts/counts/folds/four states/common extreme omission, all paired increments and block intervals; DP interval bound checked against reported greedy counts. Imported source bytes authenticated.','limitations':['Adaptive fixed composition on previously seen development events.','AND vs legacy can add events; AND vs each own component is a strict subset.','Event amounts are not continuous-account returns; frequency is only an optimistic bound.']}
    (HERE/'others/independent_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(output,ensure_ascii=False))
if __name__=='__main__':main()
