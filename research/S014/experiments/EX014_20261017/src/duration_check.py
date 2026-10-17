"""Falsify low-state H1 to H3 cash erosion; preserve earlier exports."""
import json
import numpy as np
import pandas as pd
from study import ROOT,EX,RUN,OLD,source,nonoverlap
from followup import pair_summary,mean_ci

def main():
    if (EX/'others/duration_check.json').exists():raise RuntimeError('Preserve result')
    d=pd.read_csv(RUN/'duration.csv');g=pd.read_csv(RUN/'observations.csv');f=pd.read_csv(RUN/'features.csv',index_col='signal')
    labels,_=source('ex013-corrected-labels-csv');p,_=source('ex013-corrected-predictions-csv')
    # Export order is fixed by source: each scope has low/high, five increments each.
    old=pd.read_csv(EX/'others/duration_increment_ci.csv');rows=[]
    for scope,part in old.groupby('scope',sort=False):
        assert len(part)==10
        part=part.rename(columns={'high':'ci_high','low':'ci_low'}).copy();part.insert(1,'state',['low']*5+['high']*5);rows.append(part)
    pd.concat(rows,ignore_index=True).to_csv(EX/'others/duration_increment_ci_corrected.csv',index=False,lineterminator='\n')
    h1=labels.loc[labels.horizon.eq(1)].set_index('signal');g['increment']=g.net_return-h1.loc[g.signal,'net_return'].to_numpy()
    pred1=p.loc[p.horizon.eq(1)].set_index('signal');pred3=p.loc[p.horizon.eq(3)].set_index('signal')
    g['predicted_increment']=pred3.loc[g.signal,'prediction_ridge_base'].to_numpy()-pred1.loc[g.signal,'prediction_ridge_base'].to_numpy()
    g['residual_increment']=g.increment-g.predicted_increment
    low=g.loc[g.parent&~g.high].copy();result=[];clusters=[]
    for scope,part in [('ALL',low),('WITHOUT2026',low.loc[low.year.ne(2026)]),*[(str(y),v) for y,v in low.groupby('year')]]:
        c=-1;end=-1;ids=[]
        for row in part.itertuples():
            if row.entry>end:c+=1
            ids.append(c);end=max(end,row.maturity)
        part=part.copy();part['cluster']=ids
        if scope=='ALL':clusters=part.to_dict('records')
        values=part.groupby('cluster').increment.mean();leave=[float(values.drop(k).mean()) for k in values.index] if len(values)>1 else []
        no=nonoverlap(part)
        result.append({'scope':scope,'n':len(part),'mean':float(part.increment.mean()),'residual_mean':float(part.residual_increment.mean()),
            'clusters':len(values),'cluster_equal':float(values.mean()),'leave_one_min':min(leave) if leave else None,'leave_one_max':max(leave) if leave else None,
            'nonoverlap_n':len(no),'nonoverlap_mean':float(no.increment.mean()),'drop_worst3':float(part.increment.sort_values().iloc[3:].mean()),
            'delay_count':int((part.maturity>part.planned_exit).sum()),'filled':int(part.entry_filled.sum())})
    pd.DataFrame(clusters).to_csv(EX/'others/low_extension_clusters.csv',index=False,lineterminator='\n')
    # Within historical preselected price matches, ask about each leg's extension and their difference.
    pairs=pd.read_csv(OLD/'others/session_matches.csv');lookup=g.set_index('signal');paired=[]
    for scope,part in [('ALL',pairs),('WITHOUT2026',pairs.loc[pairs.year.ne(2026)]),*[(str(y),v) for y,v in pairs.groupby('year')]]:
        a=lookup.loc[part.a,'increment'].to_numpy();b=lookup.loc[part.b,'increment'].to_numpy()
        paired.append({'scope':scope,'n':len(part),'high_increment':float(a.mean()),'low_increment':float(b.mean()),'high_minus_low':float((a-b).mean())})
    # Distinguish low environment repair from general low-state stock exposure.
    controls=['vol20','ret1','ret5'];matches=[];controlsummary=[]
    for year,part in g.groupby('year'):
        train=labels.loc[labels.horizon.eq(3)&labels.maturity.lt(int(part.signal.min()))]
        center=f.loc[train.signal,controls].mean();scale=f.loc[train.signal,controls].std(ddof=0).replace(0,1.)
        z=(f.loc[part.signal,controls]-center)/scale;lookup=part.set_index('signal')
        candidates=list(part.loc[~part.parent&~part.high,'signal'].astype(int))
        for signal in part.loc[part.parent&~part.high,'signal'].astype(int):
            if not candidates:break
            distances=np.sqrt(((z.loc[candidates].to_numpy()-z.loc[signal].to_numpy())**2).mean(axis=1));j=int(np.argmin(distances))
            if distances[j]>1:continue
            control=candidates.pop(j);a=lookup.loc[signal];b=lookup.loc[control]
            matches.append({'year':int(year),'a':signal,'b':control,'a_entry':int(a.entry),'b_entry':int(b.entry),'a_end':int(a.maturity),'b_end':int(b.maturity),
                'distance':float(distances[j]),'low_repair_increment':float(a.increment),'control_increment':float(b.increment),'difference':float(a.increment-b.increment)})
    matches=pd.DataFrame(matches);matches.to_csv(EX/'others/low_nonrepair_matches.csv',index=False,lineterminator='\n')
    for scope,part in [('ALL',matches),('WITHOUT2026',matches.loc[matches.year.ne(2026)]),*[(str(y),v) for y,v in matches.groupby('year')]]:
        summary,_=pair_summary(part,'difference');controlsummary.append({'scope':scope,**summary,'low_mean':float(part.low_repair_increment.mean()),'control_mean':float(part.control_increment.mean())})
    payload={'low_extension':result,'original_price_pairs':paired,'nonrepair_control':controlsummary,'source_calls':0,'account_runs':0}
    (EX/'others/duration_check.json').write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(payload))
if __name__=='__main__':main()
