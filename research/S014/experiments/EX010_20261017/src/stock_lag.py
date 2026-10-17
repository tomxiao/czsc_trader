"""Direct omitted-own-price competitor for the lagged-industry clue."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import sys
import numpy as np
import pandas as pd
from resolved_inputs import ROOT,EXPERIMENT,RUN,previous
from followup import feature_and_models
from sector_features import BASE,MARKET,SECTOR,predict
from stock_lag_stats import compare
from study import groups
from czsc_trader.research_tools import EvidenceRef


def augmented(feature):
    out,old=feature_and_models(feature)
    for name,source in [('gap','gap'),('intraday','intraday'),('ret1','ret1'),('ret5','ret5'),('ret20','ret20'),('range','range'),('repair','gap_down_repair')]:
        series=np.log1p(out[source]) if name.startswith('ret') else out[source]
        out[f'prior_stock_{name}']=series.shift()
    stock=BASE+[f'prior_{c}' for c in MARKET]+[f'prior_stock_{c}' for c in ('gap','intraday','ret1','ret5','ret20','range','repair')]
    innovation=['innovation_gap','innovation_intraday','innovation1','innovation5','innovation20','sector_range','innovation_repair']
    variants={'stocklag':stock,'withsector':stock+[f'lag_{c}' for c in SECTOR],
        'withinnovation':stock+[f'prior_{c}' for c in innovation],
        'sectoralternative':old['lagboth']}
    return out,variants


def main():
    target=EXPERIMENT/'others/stock_lag_result.json'
    if target.exists():
        raise RuntimeError('Preserve existing results')
    for name,value in json.loads((EXPERIMENT/'protocols/stock_lag_published.json').read_text(encoding='utf-8')).items():
        path=EXPERIMENT/('protocols/stock_lag_design.json' if name=='stock-lag-design' else f'src/{name}.py')
        assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes()
    (data,dates,*_),prior=previous()
    f,variants=augmented(pd.read_csv(RUN/'features.csv').drop(columns='signal'))
    for n in (801,1200):
        prefix,_=augmented(pd.read_csv(RUN/'features.csv').drop(columns='signal').iloc[:n]);pd.testing.assert_frame_equal(f.iloc[:n],prefix)
    source=json.loads((ROOT/'research/S014/experiments/EX008_20261017/others/result.json').read_text(encoding='utf-8'))
    labels=pd.read_csv(EvidenceRef.from_dict(source['evidence']['run-labels']).resolve(ROOT))
    queue=labels.loc[labels.horizon.eq(1)&labels.maturity.ge(0)&labels.signal.ge(62)].copy();queue['year']=[dates[int(s)].year for s in queue.signal]
    for c in f:
        queue[c]=f[c].to_numpy()[queue.signal.to_numpy(dtype=int)]
    old=pd.read_csv(RUN/'followup_predictions.csv');tests=[];splits=[];fits=0;sys.path.insert(0,str(EXPERIMENT/'src'))
    with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        for year in (2023,2024,2025,2026):
            test=queue.loc[queue.year.eq(year)].copy();start,end=int(test.signal.min()),int(test.signal.max());train=queue.loc[queue.maturity.lt(start)]
            universe=f.iloc[62:end+1];assert train.maturity.max()<start
            split={'year':year,'train':len(train),'test':len(test),'first_signal':start,'latest_maturity':int(train.maturity.max()),'thresholds':{}}
            for name,cs in variants.items():
                trained,history=predict((f'ridge-{name}',train[cs].to_numpy(),universe[cs].to_numpy(),train.net_return.to_numpy()));fits+=1
                values=history[test.signal.to_numpy(dtype=int)-62];threshold=float(np.quantile(trained,.75))
                rolling=pd.Series(history,index=universe.index).shift().rolling(126).quantile(.75).loc[test.signal.to_numpy(dtype=int)].to_numpy()
                test[f'prediction_{name}']=values;test[f'frozen_{name}']=values>=threshold;test[f'rolling_threshold_{name}']=rolling
                test[f'rolling_{name}']=values>=rolling;test[f'zero_{name}']=values>0;split['thresholds'][name]=threshold
                if name=='sectoralternative':
                    prior_year=old.loc[old.year.eq(year)];np.testing.assert_allclose(values,prior_year.prediction_ridge_lagboth,rtol=0,atol=1e-10)
            tests.append(test);splits.append(split)
        p=pd.concat(tests,ignore_index=True).sort_values('signal').reset_index(drop=True);y=p.net_return.to_numpy();annual=[];pending=[]
        for mode in ('frozen','rolling','zero'):
            for name in variants:
                for year,g in [('ALL',p),*list(p.groupby('year'))]:
                    mask=g[f'{mode}_{name}'].to_numpy()
                    annual.append({'mode':mode,'name':name,'year':str(year),'n':len(g),'selected':int(mask.sum()),'filled':int(g.loc[mask,'entry_filled'].sum()),
                        'selected_mean':float(g.loc[mask,'net_return'].mean()) if mask.any() else None,'per_origin':float((g.net_return*mask).mean()),
                        'mae':float((g[f'prediction_{name}']-g.net_return).abs().mean())})
            for left,right in [('withsector','stocklag'),('withinnovation','stocklag'),('sectoralternative','stocklag'),('stocklag','lagmarket')]:
                a=p[f'{mode}_{left}'].to_numpy();b=old[f'{mode}_ridge_lagmarket'].to_numpy() if right=='lagmarket' else p[f'{mode}_{right}'].to_numpy()
                pending.append(({'mode':mode,'left':left,'right':right},pool.submit(compare,(groups(p,y,a,b),'allocation',1.,613))))
        comparisons=[{**identity,**job.result()} for identity,job in pending]
    p.to_csv(RUN/'stock_lag_predictions.csv',index=False,lineterminator='\n')
    f.to_csv(RUN/'stock_lag_features.csv',index_label='signal',lineterminator='\n')
    pd.DataFrame(annual).to_csv(EXPERIMENT/'others/stock_lag_annual.csv',index=False,lineterminator='\n')
    result={'fits':fits,'prior_reproductions':4,'splits':splits,'comparisons':comparisons,'source_calls':0,'strategy_accounts':0,'nominal_history':574,
        'limit':'Adaptivecommonqueuefirst62H1linearrankingtest,notindependentvalidationoraccountprofit.'}
    assert fits==16 and len(comparisons)==12
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('STOCK_LAG_COMPLETE',fits,len(comparisons))


if __name__=='__main__':
    main()
