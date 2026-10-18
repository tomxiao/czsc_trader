"""Independently recompute EX033 descriptive statistics, without importing analysis."""
from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd

EX=Path(__file__).resolve().parents[1]
OUT=EX/'others'
N=0


def verify(a,b,label):
    global N
    N+=1
    if a is None or b is None:
        assert a is None and b is None,label
    else:
        assert np.allclose(a,b,atol=1e-11,rtol=1e-10,equal_nan=True),label


def stats(values,reported,label):
    a=np.asarray(values,float)
    verify(len(a),reported['n'],label+' n')
    verify(a.sum(),reported['sum'],label+' sum')
    verify(a.mean() if len(a) else None,reported['mean'],label+' mean')
    verify(np.median(a) if len(a) else None,reported['median'],label+' median')
    verify((a<0).sum(),reported['negative_n'],label+' negative n')
    for key,fn in [('min',np.min),('max',np.max),('q10',lambda x:np.quantile(x,.1)),('worst_10pct_mean',lambda x:np.sort(x)[:int(np.ceil(.1*len(x)))].mean())]:
        verify(fn(a) if len(a) else None,reported[key],label+' '+key)
    verify(a[a<0].mean() if (a<0).any() else None,reported['negative_mean'],label+' negative mean')


def contrast(frame):
    x=frame[frame.hold_P & frame.common_decline]
    a=x[x.relative_resilient].action_delta
    b=x[~x.relative_resilient].action_delta
    return a.mean()-b.mean() if len(a) and len(b) else None


def audit_group(frame,reported,label):
    for name in ['R','B','P','candidate','candidate_minus_R','candidate_minus_P']:
        stats(frame[name],reported['actions'][name],label+' '+name)
    verify(contrast(frame),reported['raw_contrast']['difference'],label+' contrast')


def main():
    result=json.loads((OUT/'analysis.json').read_text(encoding='utf-8'))
    f=pd.read_csv(OUT/'events.csv')
    f['R']=f.R_position_return
    f['B']=f.B_position_return
    f['P']=f.R+f.hold_P*f.action_delta
    f['candidate']=f.R+f.hold_candidate*f.action_delta
    f['candidate_minus_R']=f.candidate-f.R
    f['candidate_minus_P']=f.candidate-f.P
    audit_group(f,result,'all')
    for which in ['decision_year','entry_year']:
        for year in range(2020,2027):
            audit_group(f[f[which]==year],result[which][str(year)],which+str(year))
    audit_group(f[f.decision_year!=2026],result['without_2026_decisions'],'without2026')
    for flag in [False,True]:
        audit_group(f[f.positive_mark==flag],result['floating_mark_groups'][str(flag)],'P '+str(flag))
    for c in [False,True]:
        for r in [False,True]:
            subset=f[f.hold_P & (f.common_decline==c) & (f.relative_resilient==r)]
            rep=result['nonpositive_2x2'][f'C{int(c)}_R{int(r)}']
            stats(subset.action_delta,rep['action_delta'],'cell delta')
            for name in ['R','B','P','candidate','candidate_minus_R','candidate_minus_P']:
                stats(subset[name],rep['actions'][name],'cell action')
    support=result['common_support']
    eligible=f[f.hold_P & f.common_decline].copy()
    weights=pd.Series(0.,index=eligible.index)
    expected_strata=[]
    for (y,t),g in eligible.groupby(['decision_year','remaining_to_H10_sessions']):
        a=g[g.relative_resilient]; b=g[~g.relative_resilient]
        w=min(len(a),len(b))
        if w:
            weights.loc[a.index]=w/len(a)
            weights.loc[b.index]=w/len(b)
            expected_strata.append((y,t,w))
    included=eligible.loc[weights>0]
    a=included[included.relative_resilient]; b=included[~included.relative_resilient]
    verify(len(included),support['supported_n'],'support count')
    verify(len(a),support['supported_resilient_n'],'support resilient')
    verify(len(b),support['supported_extra_weak_n'],'support weak')
    verify(len(expected_strata),support['matched_strata_n'],'support strata')
    verify(sum(x[2] for x in expected_strata),support['total_stratum_weight'],'support weight')
    verify(sorted(included.event_id),support['supported_event_ids'],'support identities')
    wa=weights.loc[a.index]; wb=weights.loc[b.index]
    verify(np.average(a.action_delta,weights=wa)-np.average(b.action_delta,weights=wb),support['weighted_contrast'],'support contrast')
    for name in ['close_net_of_buy_fee_return','stock_return','amplitude','remaining_to_H10_sessions']:
        va=eligible.loc[eligible.relative_resilient,name].to_numpy()
        vb=eligible.loc[~eligible.relative_resilient,name].to_numpy()
        pooled=np.sqrt((((va-va.mean())**2).sum()+((vb-vb.mean())**2).sum())/(len(va)+len(vb)-2))
        ma=np.average(a[name],weights=wa); mb=np.average(b[name],weights=wb)
        rep=support['confounders'][name]
        verify(pooled,rep['full_eligible_pooled_sd'],'pooled SD '+name)
        verify(ma,rep['weighted_resilient_mean'],'weighted a '+name)
        verify(mb,rep['weighted_extra_weak_mean'],'weighted b '+name)
        verify((ma-mb)/pooled,rep['weighted_standardized_mean_difference'],'SMD '+name)
    robust=result['robustness']
    for metric in ['candidate_minus_R','candidate_minus_P','raw_contrast']:
        if metric=='raw_contrast':
            rank=eligible.copy()
            n1=rank.relative_resilient.sum(); n0=len(rank)-n1
            rank['value']=np.where(rank.relative_resilient,rank.action_delta/n1,-rank.action_delta/n0)
        else:
            rank=f.copy();rank['value']=rank[metric]
        rank=rank[rank.value>0].sort_values('value',ascending=False,kind='stable')
        for rep in robust['top_positive_deletions'][metric]:
            k=rep['k']
            verify(rep['available'],len(rank)>=k,'deletion availability')
            if len(rank)<k:
                continue
            removed=rank.head(k).event_id.tolist()
            verify(removed,rep['removed_event_ids'],'removed identities')
            kept=f[~f.event_id.isin(removed)]
            verify(contrast(kept) if metric=='raw_contrast' else kept[metric].mean(),rep['value'],'deletion result')
    prior=json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'))
    cluster_map={int(k):v for k,v in prior['cluster_assignments'].items()}
    f['cluster_id']=f.event_id.map(cluster_map)
    verify(f.cluster_id.nunique(),robust['cluster_n'],'cluster count')
    for rep in robust['leave_one_cluster_out']:
        rest=f[f.cluster_id!=rep['omitted_cluster']]
        verify(rest.candidate_minus_R.mean(),rep['candidate_minus_R'],'LOCO R')
        verify(rest.candidate_minus_P.mean(),rep['candidate_minus_P'],'LOCO P')
        verify(contrast(rest),rep['raw_contrast'],'LOCO contrast')
    for name in ['candidate_minus_R','candidate_minus_P']:
        verify(f.groupby('cluster_id')[name].mean().mean(),robust['cluster_equal'][name],'cluster equal '+name)
    # Independently draw calendar block counts, retaining empty blocks.
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(OUT/'calendar.csv').date))
    mapping={}; year_ids={}; cursor=0
    for year in sorted(set(dates.year)):
        yd=dates[dates.year==year]
        ids=[]
        for start in range(0,len(yd),20):
            ids.append(cursor)
            for d in yd[start:start+20]:mapping[d]=cursor
            cursor+=1
        year_ids[year]=np.array(ids)
    eventblocks=np.array([mapping[d] for d in pd.to_datetime(f.decision_date)])
    verify(cursor,result['bootstrap']['block_n'],'block count')
    verify(cursor-len(set(eventblocks)),result['bootstrap']['zero_event_block_n'],'empty block count')
    rng=np.random.default_rng(13)
    draws={name:[] for name in ['candidate_minus_R','candidate_minus_P','raw_contrast']}
    pos=(f.hold_P & f.common_decline & f.relative_resilient).to_numpy()
    neg=(f.hold_P & f.common_decline & ~f.relative_resilient).to_numpy()
    delta=f.action_delta.to_numpy()
    for _ in range(2000):
        selections=np.concatenate([rng.choice(ids,size=len(ids),replace=True) for ids in year_ids.values()])
        multiplicity=np.bincount(selections,minlength=cursor)[eventblocks]
        if multiplicity.sum():
            for name in ['candidate_minus_R','candidate_minus_P']:
                draws[name].append(np.dot(f[name],multiplicity)/multiplicity.sum())
        if multiplicity[pos].sum() and multiplicity[neg].sum():
            draws['raw_contrast'].append(np.dot(delta[pos],multiplicity[pos])/multiplicity[pos].sum()-np.dot(delta[neg],multiplicity[neg])/multiplicity[neg].sum())
    for name,values in draws.items():
        rep=result['bootstrap']['results'][name]
        verify(len(values),rep['valid'],'bootstrap valid '+name)
        verify(2000-len(values),rep['invalid'],'bootstrap invalid '+name)
        verify(np.quantile(values,[.025,.975]),rep['ordinary_95pct_interval'],'bootstrap interval '+name)
        verify(np.mean(np.array(values)>0),rep['fraction_above_zero'],'bootstrap sign '+name)
    conclusion={'status':'PASS','checks':N,'analysis_imported':False,'new_calls':0,'new_fits':0,'new_labels':0,'new_accounts':0,
                'verified':['All action summary statistics','Decision and entry year groups','Positive/nonpositive groups and 2x2','Common-support min-count weights and pooled SMD','Top positive deletion identities','100 holding-interval clusters and LOCO','2000 calendar block draws with empty blocks'],
                'key_findings':{'candidate_minus_R':float(f.candidate_minus_R.mean()),'candidate_minus_P':float(f.candidate_minus_P.mean()),'common_support_weight':int(sum(x[2] for x in expected_strata)),'support_contrast':support['weighted_contrast']},
                'source_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),OUT/'analysis.json',OUT/'events.csv',OUT/'calendar.csv']}}
    with (OUT/'independent_statistics_audit.json').open('x',encoding='utf-8',newline='\n') as h:
        h.write(json.dumps(conclusion,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':'PASS','checks':N}))


if __name__=='__main__':main()
