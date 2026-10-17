"""Discriminate lagged industry content from lagged market, scale and cutoffs."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import sys
import numpy as np
import pandas as pd
from resolved_inputs import ROOT,EXPERIMENT,RUN,previous
from sector_features import BASE,SECTOR,MARKET,predict
from followup_stats import compare
from study import groups
from czsc_trader.research_tools import EvidenceRef


def feature_and_models(feature):
    out=feature.copy()
    out['innovation_repair']=(out.innovation_gap.lt(0)&out.innovation_intraday.gt(0)).astype(float)
    innovation=['innovation_gap','innovation_intraday','innovation1','innovation5','innovation20','sector_range','innovation_repair']
    for c in [*MARKET,*innovation]:
        out[f'prior_{c}']=out[c].shift()
    variants={'base':BASE,'lagsector':BASE+[f'lag_{c}' for c in SECTOR],
        'lagmarket':BASE+[f'prior_{c}' for c in MARKET],
        'laginnovation':BASE+[f'prior_{c}' for c in innovation],
        'lagboth':BASE+[f'prior_{c}' for c in MARKET]+[f'lag_{c}' for c in SECTOR],
        'lagvol':BASE+['lag_sector_range'],'lagdirection':BASE+[f'lag_{c}' for c in SECTOR if c!='sector_range']}
    return out,variants


def main():
    target=EXPERIMENT/'others/followup_result.json'
    if target.exists():
        raise RuntimeError('Preserve existing followup')
    for name,value in json.loads((EXPERIMENT/'protocols/followup_published.json').read_text(encoding='utf-8')).items():
        path=EXPERIMENT/('protocols/followup_design.json' if name=='followup-design' else f'src/{name}.py')
        assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes()
    (data,dates,*_),prior=previous()
    feature,variants=feature_and_models(pd.read_csv(RUN/'features.csv').drop(columns='signal'))
    for n in (801,1200):
        prefix,_=feature_and_models(pd.read_csv(RUN/'features.csv').drop(columns='signal').iloc[:n])
        pd.testing.assert_frame_equal(feature.iloc[:n],prefix)
    old=json.loads((ROOT/'research/S014/experiments/EX008_20261017/others/result.json').read_text(encoding='utf-8'))
    labels=pd.read_csv(EvidenceRef.from_dict(old['evidence']['run-labels']).resolve(ROOT))
    cs=list(dict.fromkeys(c for v in variants.values() for c in v));valid=np.isfinite(feature[cs].to_numpy()).all(axis=1)
    queue=labels.loc[labels.horizon.eq(1)&labels.maturity.ge(0)&labels.signal.map(lambda s:bool(valid[int(s)]))].copy()
    queue['year']=[dates[int(s)].year for s in queue.signal]
    for c in feature:
        queue[c]=feature[c].to_numpy()[queue.signal.to_numpy(dtype=int)]
    tests=[];splits=[];fits=0;sys.path.insert(0,str(EXPERIMENT/'src'))
    with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        for year in (2023,2024,2025,2026):
            test=queue.loc[queue.year.eq(year)].copy();start,end=int(test.signal.min()),int(test.signal.max())
            train=queue.loc[queue.maturity.lt(start)];first=int(np.flatnonzero(valid)[0]);universe=feature.iloc[first:end+1]
            assert train.maturity.max()<start
            split={'year':year,'train':len(train),'test':len(test),'first_signal':start,'latest_maturity':int(train.maturity.max()),'thresholds':{}}
            jobs={(algo,name):pool.submit(predict,(f'{algo}-{name}',train[cols].to_numpy(),universe[cols].to_numpy(),train.net_return.to_numpy()))
                for algo in ('ridge','tree') for name,cols in variants.items()}
            for (algo,name),job in jobs.items():
                trained,history=job.result();fits+=1;key=f'{algo}_{name}'
                values=history[test.signal.to_numpy(dtype=int)-first];threshold=float(np.quantile(trained,.75))
                rolling=pd.Series(history,index=universe.index).shift().rolling(126).quantile(.75).loc[test.signal.to_numpy(dtype=int)].to_numpy()
                test[f'prediction_{key}']=values;test[f'frozen_{key}']=values>=threshold
                test[f'rolling_threshold_{key}']=rolling;test[f'rolling_{key}']=values>=rolling;test[f'zero_{key}']=values>0
                split['thresholds'][key]=threshold
            splits.append(split);tests.append(test)
        p=pd.concat(tests,ignore_index=True).sort_values('signal').reset_index(drop=True)
        y=p.net_return.to_numpy();annual=[];pending=[];diagnostics=[]
        for algo in ('ridge','tree'):
            for mode in ('frozen','rolling','zero'):
                for name in variants:
                    selected=p[f'{mode}_{algo}_{name}'].to_numpy()
                    for year,g in [('ALL',p),*list(p.groupby('year'))]:
                        for scope,mask in [('all',np.ones(len(g),dtype=bool)),('repair',g.gap_down_repair.eq(1).to_numpy())]:
                            a,b=selected[g.index]&mask,~selected[g.index]&mask
                            annual.append({'algo':algo,'mode':mode,'name':name,'year':str(year),'scope':scope,'n':int(mask.sum()),
                                'selected':int(a.sum()),'filled':int(g.loc[a,'entry_filled'].sum()),
                                'selected_mean':float(g.loc[a,'net_return'].mean()) if a.any() else None,
                                'control_mean':float(g.loc[b,'net_return'].mean()) if b.any() else None,
                                'per_origin':float((g.net_return*a).mean()),'mae':float((g[f'prediction_{algo}_{name}']-g.net_return).abs().mean())})
                pairs=[('lagsector','base'),('lagmarket','base'),('laginnovation','base'),('lagboth','lagmarket'),('lagvol','base'),('lagdirection','base'),('lagsector','lagmarket')]
                for left,right in pairs:
                    a=p[f'{mode}_{algo}_{left}'].to_numpy();b=p[f'{mode}_{algo}_{right}'].to_numpy()
                    identity={'algo':algo,'mode':mode,'left':left,'right':right}
                    pending.append((identity,pool.submit(compare,(groups(p,y,a,b),'allocation',1.,513))))
                    delta=y*(a.astype(float)-b.astype(float))
                    for year,g in p.groupby('year'):
                        changed=(a!=b)&p.year.eq(year).to_numpy();retained=[]
                        for s in p.loc[changed,'signal']:
                            if not retained or int(s)>retained[-1]+10:
                                retained.append(int(s))
                        keep=p.signal.isin(retained).to_numpy()
                        diagnostics.append({**identity,'year':int(year),'changed':int(changed.sum()),'delta':float(delta[g.index].mean()),
                            'decluster_delta':float((delta[g.index]*keep[g.index]).mean())})
        comparisons=[{**identity,**job.result()} for identity,job in pending]
    p.to_csv(RUN/'followup_predictions.csv',index=False,lineterminator='\n')
    feature.to_csv(RUN/'followup_features.csv',index_label='signal',lineterminator='\n')
    pd.DataFrame(annual).to_csv(EXPERIMENT/'others/followup_annual.csv',index=False,lineterminator='\n')
    pd.DataFrame(diagnostics).to_csv(EXPERIMENT/'others/followup_participation.csv',index=False,lineterminator='\n')
    result={'fits':fits,'test_rows':len(p),'first_feature_signal':int(np.flatnonzero(valid)[0]),'splits':splits,'comparisons':comparisons,
        'source_calls':0,'strategy_accounts':0,'nominal_history':562,
        'limit':'AdaptiveH1followup,commonqueuefirst62ratherthan61,newbaselinesrefittedfairly;zero thresholdnotoptimized;allseenpool,noaccount.'}
    assert fits==56 and len(comparisons)==42
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('FOLLOWUP_COMPLETE',fits,len(comparisons))


if __name__=='__main__':
    main()
