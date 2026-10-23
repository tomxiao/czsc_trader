"""Same-event bridge of preserved EX032 predictions and authenticated EX049 predictions."""
from diagnose import ROOT, HERE, BASE, EX, read, save, resolve, material_from_report, material, SOURCES
import argparse
import pandas as pd
import numpy as np
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources

def amounts(frame, prediction, target):
    valid=frame[target].notna() & frame[prediction].notna()
    x=frame.loc[valid]; y=x[target].astype(float); reject=x[prediction]<0
    loss=-float(y[y<0].sum()); profit=float(y[y>0].sum())
    caught=-float(y[reject&(y<0)].sum()); missed=float(y[reject&(y>0)].sum())
    return {'n':len(x),'reject_n':int(reject.sum()),'negative_n':int((y<0).sum()),'positive_n':int((y>0).sum()),
        'rejected_negative_n':int((reject&(y<0)).sum()),'rejected_positive_n':int((reject&(y>0)).sum()),
        'loss_denominator_yuan':loss,'profit_denominator_yuan':profit,'identified_loss_yuan':caught,'missed_profit_yuan':missed,
        'identified_loss_fraction':caught/loss if loss else None,'missed_profit_fraction':missed/profit if profit else None}

def main(ref_path):
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
    refs=read(ref_path)
    if 'materials' in refs: refs=refs['materials']
    newref=refs['model_predictions.csv']
    new=pd.read_csv(resolve(newref))
    old=pd.read_csv(material_from_report('EX032_20261023','predictions','csv'))
    inputrefs=read(BASE/'EX032_20261023/others/input_refs.json')
    events=pd.read_csv(resolve(inputrefs['events'])); events=events[(events.horizon==3)&events.status.eq('CLOSED')]
    prices=pd.read_csv(resolve(inputrefs['features_lag1']))[['date','position','r5']]
    rows=[]; records=[]
    for lag in (1,3):
        selected=old[(old.lag==lag)&old.target.eq('net_h3')]
        f=selected.merge(events[['date','position','net','entry_net','before_entry_change']],on=['date','position'],validate='one_to_one').merge(prices,on=['date','position'],validate='one_to_one')
        assert len(f)==323
        np.testing.assert_allclose(f.y*100000,f.net,atol=1e-7,rtol=1e-10)
        for family, model_lag in [('B',1),('BF',lag)]:
            fresh=new[new.family.eq(family)&new.lag.eq(model_lag)&new.ready]
            g=f.merge(fresh[['date','position','prediction','model_date']],on=['date','position'],validate='one_to_one')
            assert len(g)==323
            original='base' if family=='B' else 'funded'
            for scheme,predcol in [('EX032_four_fold',original),('EX049_rolling','prediction')]:
                for target in ('net','entry_net'):
                    rows.append({'lag':lag,'family':family,'schedule':scheme,'target':target,**amounts(g,predcol,target),
                        'mse_net3':float(np.square(g[predcol]-g.y).mean())})
            g['old_prediction']=g[original];g['new_prediction']=g.prediction;g['family']=family;g['lag']=lag
            records.extend(g[['date','position','fold','model_date','family','lag','old_prediction','new_prediction','net','entry_net','before_entry_change','r5']].to_dict('records'))
    pd.DataFrame(records).to_csv(HERE/'others/common_event_bridge.csv',index=False)
    save(HERE/'others/bridge_results.json',{'same_events':323,'rows':rows,'sources':SOURCES,
        'scope':'net_h3 prediction filters applied to identical 323 CLOSED three-day independent events, including entry-day outcome. No account or re-fit.',
        'not_comparable':'Original EX032 entry_net_h1 model used 326 labels and a different target; it is not the filter tested here.',
        'selection':'Same previously seen development pool. Later rolling schedule does not erase historical choice or create independent validation.'})
    published=read(HERE/'others/published_refs.json')
    for p in (HERE/'src/bridge.py',HERE/'others/common_event_bridge.csv',HERE/'others/bridge_results.json'):
        published['materials'][str(p.relative_to(HERE)).replace('\\','/')]=material(ctx,p).to_dict()
    save(HERE/'others/published_refs.json',published)
    for row in rows:
        if row['target']=='net': print(row['lag'],row['family'],row['schedule'],round(row['identified_loss_fraction']*100,3),round(row['missed_profit_fraction']*100,3))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('refs',type=__import__('pathlib').Path);args=parser.parse_args();main(args.refs)
