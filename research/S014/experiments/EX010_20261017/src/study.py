"""Execution-aligned industry incremental tests on the authorized S014 window."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import sys
import time
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from resolved_inputs import ROOT,EXPERIMENT,RUN,previous,old_csv,indices
from sector_features import features,predict,masks,MODELS
from sector_stats import compare


def groups(p,y,a,b):
    return [(int(year),g.signal.to_numpy(dtype=int),y[g.index],a[g.index],b[g.index]) for year,g in p.groupby('year')]


def precheck(bars,market,sector,inherited):
    full=features(bars,market,sector,inherited)
    for n in (200,801,1200):
        pd.testing.assert_frame_equal(full.iloc[:n],features(bars.iloc[:n],market.iloc[:n],sector.iloc[:n],inherited.iloc[:n]))
    changed=sector.copy();changed.loc[801:,['Open','High','Low','Close']]*=2
    altered=features(bars,market,changed,inherited)
    pd.testing.assert_frame_equal(full.iloc[:801],altered.iloc[:801])
    np.testing.assert_allclose(full.loc[801,['alpha2','beta_market2','beta_sector2']].to_numpy(dtype=float),
        altered.loc[801,['alpha2','beta_market2','beta_sector2']].to_numpy(dtype=float),rtol=0,atol=0)
    np.testing.assert_allclose((full.sector_gap+full.sector_intraday).iloc[1:],full.sector_ret1.iloc[1:],rtol=0,atol=1e-12)
    return ['3real_feature_prefixes','future_sector_perturbation','T_excluded_from_exposures','sector_log_decomposition']


def main():
    started=time.monotonic()
    if RUN.exists():
        raise RuntimeError('Preserve existing run')
    for filename in ('published_design.json','implementation_published.json'):
        for name,value in json.loads((EXPERIMENT/'protocols'/filename).read_text(encoding='utf-8')).items():
            path=EXPERIMENT/('protocols/design.json' if name=='design' else 'protocols/implementation.json' if name=='implementation' else f'src/{name}.py')
            assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes()
    (data,dates,observation,_,labels,*_),prior=previous()
    market,sector=indices(prior)
    assert dates.equals(pd.DatetimeIndex(pd.to_datetime(market.Date))) and dates.equals(pd.DatetimeIndex(pd.to_datetime(sector.Date)))
    inherited=old_csv(prior,'followup-features').drop(columns='signal')
    old_predictions=old_csv(prior,'followup-predictions')
    # EX009's loaded inherited labels do not include newly created H1; use its bound predecessor EX008 labels.
    raw=json.loads((ROOT/'research/S014/experiments/EX008_20261017/others/result.json').read_text(encoding='utf-8'))
    labels=pd.read_csv(EvidenceRef.from_dict(raw['evidence']['run-labels']).resolve(ROOT))
    checks=precheck(data['stock.ohlcv'],market,sector,inherited)
    feature=features(data['stock.ohlcv'],market,sector,inherited)
    cols=list(dict.fromkeys(c for v in MODELS.values() for c in v))
    valid=np.isfinite(feature[cols].to_numpy()).all(axis=1)
    frame=labels.loc[labels.horizon.isin([1,3])&labels.maturity.ge(0)&labels.signal.map(lambda s:bool(valid[int(s)]))].copy()
    frame['year']=[dates[int(s)].year for s in frame.signal]
    for c in feature:
        frame[c]=feature[c].to_numpy()[frame.signal.to_numpy(dtype=int)]
    sys.path.insert(0,str(EXPERIMENT/'src'))
    tests=[];splits=[];fits=0
    with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        task=('ridge-test',np.arange(60).reshape(20,3),np.ones((2,3)),np.arange(20))
        np.testing.assert_array_equal(predict(task)[1],pool.submit(predict,task).result()[1])
        checks.append('spawn_serial_equal')
        for h in (1,3):
            queue=frame.loc[frame.horizon.eq(h)].sort_values('signal')
            for year in (2023,2024,2025,2026):
                test=queue.loc[queue.year.eq(year)].copy();start=int(test.signal.min());end=int(test.signal.max())
                train=queue.loc[queue.maturity.lt(start)]
                universe=feature.iloc[np.flatnonzero(valid)[0]:end+1]
                first=int(universe.index.min())
                sq,iq=(float(np.quantile(train[c],.1)) for c in ('ret1','innovation1'))
                split={'horizon':h,'year':year,'train':len(train),'test':len(test),'first_test_signal':start,
                    'latest_maturity':int(train.maturity.max()),'stockq10':sq,'sectorq10':iq,'thresholds':{}}
                assert train.maturity.max()<start
                jobs={(algo,name):pool.submit(predict,(f'{algo}-{name}',train[cs].to_numpy(),universe[cs].to_numpy(),train.net_return.to_numpy()))
                    for algo in ('ridge','tree') for name,cs in MODELS.items()}
                for (algo,name),job in jobs.items():
                    trained,all_scores=job.result();fits+=1
                    key=f'{algo}_{name}';values=all_scores[test.signal.to_numpy(dtype=int)-first]
                    threshold=float(np.quantile(trained,.75))
                    rolling=pd.Series(all_scores,index=universe.index).shift().rolling(126).quantile(.75)
                    test[f'prediction_{key}']=values;test[f'frozen_{key}']=values>=threshold
                    test[f'rolling_threshold_{key}']=rolling.loc[test.signal.to_numpy(dtype=int)].to_numpy()
                    test[f'rolling_{key}']=values>=test[f'rolling_threshold_{key}'].to_numpy()
                    split['thresholds'][key]=threshold
                    if name in ('stock','market'):
                        oldkey=f'{algo}_'+('strong' if name=='stock' else 'relative')
                        old=old_predictions.loc[old_predictions.horizon.eq(h)&old_predictions.year.eq(year)]
                        np.testing.assert_allclose(values,old[f'prediction_{oldkey}'],rtol=0,atol=1e-10)
                for name,(a,b) in masks(test,sq,iq).items():
                    test[f'event_{name}']=a;test[f'control_{name}']=b
                splits.append(split);tests.append(test)
        predictions=pd.concat(tests,ignore_index=True)
        annual=[];pending=[];diagnostics=[]
        for h,rawpart in predictions.groupby('horizon'):
            part=rawpart.sort_values('signal').reset_index(drop=True);y=part.net_return.to_numpy()
            for algo in ('ridge','tree'):
                for mode in ('frozen','rolling'):
                    for name in MODELS:
                        key=f'{algo}_{name}';selected=part[f'{mode}_{key}'].to_numpy()
                        for year,g in [('ALL',part),*list(part.groupby('year'))]:
                            for scope,mask in [('all',np.ones(len(g),dtype=bool)),('repair',g.gap_down_repair.eq(1).to_numpy())]:
                                a=selected[g.index]&mask;b=~selected[g.index]&mask
                                annual.append({'kind':'model','horizon':int(h),'algo':algo,'mode':mode,'name':name,'year':str(year),'scope':scope,
                                    'n':int(mask.sum()),'selected':int(a.sum()),'control':int(b.sum()),'filled':int(g.loc[a,'entry_filled'].sum()),
                                    'selected_mean':float(g.loc[a,'net_return'].mean()) if a.any() else None,
                                    'control_mean':float(g.loc[b,'net_return'].mean()) if b.any() else None,
                                    'per_origin':float((g.net_return*a).mean()),'mae':float((g[f'prediction_{key}']-g.net_return).abs().mean())})
                    pairs=[('market','stock'),('sector','market'),('plain','market'),('both','market'),('lagged','market'),('oldsector','market'),('both','all')]
                    for left,right in pairs:
                        a=part[f'{mode}_{algo}_{left}'].to_numpy()
                        b=np.ones(len(part),dtype=bool) if right=='all' else part[f'{mode}_{algo}_{right}'].to_numpy()
                        identity={'kind':'model','horizon':int(h),'algo':algo,'mode':mode,'left':left,'right':right}
                        pending.append((identity,pool.submit(compare,(groups(part,y,a,b),'allocation',1.,313+int(h)))))
                        delta=y*(a.astype(float)-b.astype(float))
                        for year,g in part.groupby('year'):
                            changed=(a!=b)&part.year.eq(year).to_numpy();retained=[]
                            for s in part.loc[changed,'signal']:
                                if not retained or int(s)>retained[-1]+10:
                                    retained.append(int(s))
                            keep=part.signal.isin(retained).to_numpy()
                            diagnostics.append({**identity,'year':int(year),'changed':int(changed.sum()),
                                'added':int((a[g.index]&~b[g.index]).sum()),'removed':int((~a[g.index]&b[g.index]).sum()),
                                'delta':float(delta[g.index].mean()),'decluster_delta':float((delta[g.index]*keep[g.index]).mean())})
                    # Direct relative-encoding increment beyond adding the same raw industry series.
                    a=part[f'{mode}_{algo}_both'].to_numpy();b=part[f'{mode}_{algo}_plain'].to_numpy()
                    for year,g in part.groupby('year'):
                        diagnostics.append({'kind':'both-plain-descriptive','horizon':int(h),'algo':algo,'mode':mode,'year':int(year),
                            'delta':float((y*(a.astype(float)-b.astype(float)))[g.index].mean())})
            for name in masks(part,0.,0.):
                a,b=part[f'event_{name}'].to_numpy(),part[f'control_{name}'].to_numpy()
                for mode in ('raw','residual'):
                    values=y-part.prediction_ridge_market.to_numpy() if mode=='residual' else y
                    pending.append(({'kind':'event','horizon':int(h),'name':name,'mode':mode},
                        pool.submit(compare,(groups(part,values,a,b),'conditional',1.,413+int(h)))))
                    for year,g in part.groupby('year'):
                        sa,sb=a[g.index],b[g.index]
                        annual.append({'kind':'event','horizon':int(h),'name':name,'mode':mode,'year':str(year),'scope':'all','n':len(g),
                            'selected':int(sa.sum()),'control':int(sb.sum()),'filled':int(g.loc[sa,'entry_filled'].sum()),
                            'selected_mean':float(values[g.index][sa].mean()) if sa.any() else None,
                            'control_mean':float(values[g.index][sb].mean()) if sb.any() else None,
                            'per_origin':float((values[g.index]*sa).mean())})
                retained=[]
                for s in part.loc[a|b,'signal']:
                    if not retained or int(s)>retained[-1]+10:
                        retained.append(int(s))
                keep=part.signal.isin(retained).to_numpy()
                for year,g in part.groupby('year'):
                    sa,sb=(a&keep)[g.index],(b&keep)[g.index]
                    annual.append({'kind':'decluster','horizon':int(h),'name':name,'mode':'raw','year':str(year),'scope':'all','n':len(g),
                        'selected':int(sa.sum()),'control':int(sb.sum()),'filled':int(g.loc[sa,'entry_filled'].sum()),
                        'selected_mean':float(g.loc[sa,'net_return'].mean()) if sa.any() else None,
                        'control_mean':float(g.loc[sb,'net_return'].mean()) if sb.any() else None})
        comparisons=[{**identity,**job.result()} for identity,job in pending]
    RUN.mkdir(parents=True)
    feature.to_csv(RUN/'features.csv',index_label='signal',lineterminator='\n')
    predictions.to_csv(RUN/'predictions.csv',index=False,lineterminator='\n')
    pd.DataFrame(annual).to_csv(EXPERIMENT/'others/annual.csv',index=False,lineterminator='\n')
    pd.DataFrame(diagnostics).to_csv(EXPERIMENT/'others/participation.csv',index=False,lineterminator='\n')
    result={'fits':fits,'new_fits':80,'prior_reproductions':32,'test_rows':len(predictions),'splits':splits,'comparisons':comparisons,
        'prechecks':checks,'first_feature_signal':int(np.flatnonzero(valid)[0]),
        'rank_deficient_sessions':feature.index[feature.exposure_status.eq('RANK_DEFICIENT')].tolist(),
        'max_condition':float(feature.condition.max()),'nominal_history':520,'new_source_calls':0,'strategy_accounts':0,
        'seconds':time.monotonic()-started,'limit':'Seenpool,overlappingattempts,model-dependentconditionalinformation;noaccountannualacceptance.'}
    assert fits==112 and len(comparisons)==80 and result['seconds']<7200
    (EXPERIMENT/'others/computation_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('comparisons','splits')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
