"""Account for concentration of matched evidence in overlapping episodes."""
import json
import numpy as np
import pandas as pd
from inputs import ROOT,EX


def main():
    target=EX/'others/cluster_result.json'
    if target.exists():raise RuntimeError('Preserve cluster diagnostics')
    run=ROOT/'research/S014/assets/runs'/EX.name/'corrected'
    labels=pd.read_csv(run/'labels.csv');labels=labels.loc[labels.horizon.eq(3)].set_index('signal')
    matches=pd.read_csv(EX/'others/session_matches.csv').sort_values('a').reset_index(drop=True)
    cluster=[];current=-1;last=-1;last_year=None
    for r in matches.itertuples(index=False):
        entry,maturity=labels.loc[r.a,['entry','maturity']]
        if r.year!=last_year or entry>last:current+=1;last=int(maturity)
        else:last=max(last,int(maturity))
        cluster.append(current);last_year=r.year
    matches['cluster']=cluster
    summary=[];kept=[];occupied=[]
    for i,r in matches.iterrows():
        spans=[tuple(int(v) for v in labels.loc[int(s),['entry','maturity']]) for s in (r.a,r.b)]
        # Pair itself must also have two nonoverlapping observations.
        overlap=lambda a,b:max(a[0],b[0])<=min(a[1],b[1])
        if overlap(*spans) or any(overlap(x,y) for x in spans for y in occupied):continue
        kept.append(int(i));occupied.extend(spans)
    for year,g in [('ALL',matches),*list(matches.groupby('year'))]:
        averages=g.groupby('cluster').difference.mean();keep=g.index.isin(kept)
        leave=[float(g.loc[g.cluster.ne(k),'difference'].mean()) for k in g.cluster.unique() if len(g.loc[g.cluster.ne(k)])]
        summary.append({'year':str(year),'pairs':len(g),'clusters':len(averages),'pair_weighted':float(g.difference.mean()),
            'cluster_equal_weight':float(averages.mean()),'leave_cluster_min':min(leave),'leave_cluster_max':max(leave),
            'both_legs_nonoverlap_pairs':int(keep.sum()),'both_legs_nonoverlap_mean':float(g.loc[keep,'difference'].mean()) if keep.any() else None})
    effects=[]
    for key,g in matches.groupby('cluster'):
        effects.append({'cluster':int(key),'year':int(g.year.iloc[0]),'a_signals':g.a.astype(int).tolist(),
            'a_dates':[str(labels.loc[int(s),'signal_date']) for s in g.a],'pairs':len(g),'mean':float(g.difference.mean()),
            'contribution_to_all':float(g.difference.sum()/len(matches))})
    rng=np.random.default_rng(13317);draws=[]
    for _ in range(2000):
        parts=[]
        for year,g in matches.groupby('year'):
            ids=g.cluster.unique();picked=rng.choice(ids,size=len(ids),replace=True)
            parts.extend(g.loc[g.cluster.eq(k),'difference'].to_numpy() for k in picked)
        draws.append(float(np.concatenate(parts).mean()))
    target.write_text(json.dumps({'summaries':summary,'clusters':effects,'both_legs_kept_indices':kept,
        'cluster_bootstrap_ci':[float(np.quantile(draws,.025)),float(np.quantile(draws,.975))],
        'limitation':'高组簇抽样未充分处理低组跨簇依赖；双侧去重使用事后退出，仅诊断。','source_calls':0},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'summaries':summary,'ci':[float(np.quantile(draws,.025)),float(np.quantile(draws,.975))]},ensure_ascii=False))


if __name__=='__main__':main()
