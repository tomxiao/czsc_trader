"""Market-context phase-two tests; every outcome uses inherited execution labels."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import sys
import time
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from market_features import features, predict, masks, MODELS, MARKET, RELATIVE
from inputs import ROOT, EXPERIMENT, RUN, previous, prior_csv, load_index
from market_stats import compare


def precheck(bars,index,stock):
    full=features(bars,index,stock)
    for n in (200,801,1200):
        pd.testing.assert_frame_equal(full.iloc[:n],features(bars.iloc[:n],index.iloc[:n],stock.iloc[:n]))
    changed=index.copy()
    changed.loc[801:,['Open','High','Low','Close']]*=2
    pd.testing.assert_frame_equal(full.iloc[:801],features(bars,changed,stock).iloc[:801])
    # Beta must not use the current day's stock or market returns.
    np.testing.assert_allclose(full.beta.iloc[801],features(bars,changed,stock).beta.iloc[801])
    np.testing.assert_allclose((full.market_gap+full.market_intraday).iloc[1:],full.market_ret1.iloc[1:],atol=1e-12,rtol=0)
    lag=index.Close.iloc[:801].copy()
    r=np.log(lag/lag.shift()).iloc[-61:-1].to_numpy()
    s=np.log(bars.Close/bars.Close.shift()).iloc[:801].iloc[-61:-1].to_numpy()
    np.testing.assert_allclose(full.beta.iloc[800],np.cov(s,r,ddof=1)[0,1]/np.var(r,ddof=1),rtol=0,atol=1e-10)
    return ['real_prefix_3','future_perturbation','current_return_excluded_from_beta','market_log_decomposition','manual_beta60']


def groups(frame,values,a,b):
    return [(int(y),g.signal.to_numpy(dtype=int),values[g.index],a[g.index],b[g.index]) for y,g in frame.groupby('year')]


def main():
    started=time.monotonic()
    if RUN.exists():
        raise RuntimeError('Preserve existing run')
    for file in ('published_design.json','implementation_published.json'):
        for name,value in json.loads((EXPERIMENT/'protocols'/file).read_text(encoding='utf-8')).items():
            path=EXPERIMENT/('protocols/design.json' if name=='design' else 'protocols/implementation.json' if name=='implementation' else f'src/{name}.py')
            if EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()!=path.read_bytes():
                raise RuntimeError('Predeclared material changed')
    (data,dates,observation,*_),result=previous()
    index=load_index()
    stock=prior_csv(result,'features').drop(columns='signal')
    labels=prior_csv(result,'labels')
    entries=prior_csv(result,'entries')
    checks=precheck(data['stock.ohlcv'],index,stock)
    market=features(data['stock.ohlcv'],index,stock)
    columns=list(dict.fromkeys(x for cs in MODELS.values() for x in cs))
    valid=np.isfinite(market[columns].to_numpy()).all(axis=1)
    frame=labels.loc[labels.maturity.ge(0)&labels.signal.map(lambda x:bool(valid[int(x)]))].copy()
    for name in market:
        frame[name]=market[name].to_numpy()[frame.signal.to_numpy(dtype=int)]
    frame['year']=[dates[int(x)].year for x in frame.signal]
    sys.path.insert(0,str(EXPERIMENT/'src'))
    tests,splits=[],[]
    with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        task=('ridge-stock',np.arange(60).reshape(20,3),np.ones((2,3)),np.arange(20))
        np.testing.assert_array_equal(predict(task)[1],pool.submit(predict,task).result()[1])
        checks.append('spawn_serial_equal')
        for h in (1,3,5,10):
            available=frame.loc[frame.horizon.eq(h)].sort_values('signal')
            for year in (2023,2024,2025,2026):
                test=available.loc[available.year.eq(year)].copy()
                cutoff=int(test.signal.min())
                train=available.loc[available.maturity.lt(cutoff)]
                split={'horizon':h,'year':year,'train':len(train),'test':len(test),
                    'latest_maturity':int(train.maturity.max()),'first_test_signal':cutoff,'thresholds':{}}
                assert split['latest_maturity']<cutoff
                jobs={name:pool.submit(predict,(name,train[cols].to_numpy(),test[cols].to_numpy(),train.net_return.to_numpy())) for name,cols in MODELS.items()}
                for name,job in jobs.items():
                    a,b=job.result()
                    threshold=float(np.quantile(a,.75))
                    key=name.replace('-','_')
                    test[f'prediction_{key}']=b
                    test[f'selected_{key}']=b>=threshold
                    split['thresholds'][name]=threshold
                splits.append(split)
                tests.append(test)
        predictions=pd.concat(tests,ignore_index=True)
        annual,comparisons,pending=[],[],[]
        for h,original in predictions.groupby('horizon'):
            part=original.sort_values('signal').reset_index(drop=True)
            y=part.net_return.to_numpy()
            for name in MODELS:
                key=name.replace('-','_')
                base='tree_stock' if name.startswith('tree') else 'ridge_stock'
                a,b=part[f'selected_{key}'].to_numpy(),part[f'selected_{base}'].to_numpy()
                pending.append(({'kind':'model','horizon':int(h),'name':name,'control':base},
                    pool.submit(compare,(groups(part,y,a,b),'allocation',1.,13+int(h)))))
                for year,g in [('ALL',part),*list(part.groupby('year'))]:
                    chosen=g[f'selected_{key}']
                    annual.append({'kind':'model','horizon':int(h),'name':name,'year':str(year),'n':len(g),
                        'selected':int(chosen.sum()),'filled':int((chosen&g.entry_filled).sum()),
                        'selected_mean':float(g.loc[chosen,'net_return'].mean()) if chosen.any() else None,
                        'per_origin':float((g.net_return*chosen).mean()),'mae':float((g[f'prediction_{key}']-g.net_return).abs().mean())})
            events=masks(part)
            events['stock-repair-residual']=events['stock-repair']
            for name,(a,b) in events.items():
                a,b=a.to_numpy(),b.to_numpy()
                values=y-part.prediction_ridge_relative.to_numpy() if name.endswith('residual') else y
                pending.append(({'kind':'event','horizon':int(h),'name':name},pool.submit(compare,(groups(part,values,a,b),'conditional',1.,41+int(h)))))
                for year,g in part.groupby('year'):
                    ia,ib=a[g.index],b[g.index]
                    annual.append({'kind':'event','horizon':int(h),'name':name,'year':str(year),'n':len(g),
                        'selected':int(ia.sum()),'control':int(ib.sum()),'filled':int(g.loc[ia,'entry_filled'].sum()),
                        'selected_mean':float(values[g.index][ia].mean()) if ia.any() else None,
                        'control_mean':float(values[g.index][ib].mean()) if ib.any() else None,
                        'per_origin':float((values[g.index]*ia).mean())})
                # All diagnostics use the original features and masks, no optimized rule.
                chosen=[]
                for s in part.loc[a|b,'signal']:
                    if not chosen or int(s)>chosen[-1]+10:
                        chosen.append(int(s))
                keep=part.signal.isin(chosen).to_numpy()
                for year,g in part.groupby('year'):
                    ia,ib=(a&keep)[g.index],(b&keep)[g.index]
                    annual.append({'kind':'decluster','horizon':int(h),'name':name,'year':str(year),'n':len(g),
                        'selected':int(ia.sum()),'control':int(ib.sum()),
                        'selected_mean':float(values[g.index][ia].mean()) if ia.any() else None,
                        'control_mean':float(values[g.index][ib].mean()) if ib.any() else None})
        comparisons=[{**identity,**job.result()} for identity,job in pending]
    RUN.mkdir(parents=True)
    market.to_csv(RUN/'features.csv',index_label='signal',lineterminator='\n')
    predictions.to_csv(RUN/'predictions.csv',index=False,lineterminator='\n')
    pd.DataFrame(annual).to_csv(EXPERIMENT/'others/annual.csv',index=False,lineterminator='\n')
    output={'model_fits':len(splits)*len(MODELS),'test_rows':len(predictions),'splits':splits,'comparisons':comparisons,
        'nominal_history':352,'new_source_calls':0,'strategy_accounts':0,'prechecks':checks,
        'seconds':time.monotonic()-started,'first_usable_signal':int(np.flatnonzero(valid)[0]),
        'limit':'Seen development pool; train-outside-year is not unseen holdout; independent overlapping attempts; no annual account acceptance.'}
    assert output['model_fits']==112 and len(comparisons)==56 and output['seconds']<7200
    (EXPERIMENT/'others/computation_result.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in output.items() if k not in ('splits','comparisons')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
