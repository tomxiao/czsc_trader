"""Counterevidence for the observed market-context ranking improvement."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import sys
import numpy as np
import pandas as pd
from inputs import ROOT, EXPERIMENT, RUN, previous, prior_csv
from market_features import STOCK, MARKET, RELATIVE, MODELS, predict
from market_stats import compare as original_compare
from followup_stats import compare
from study import groups


STRONG=STOCK+['intraday','intraday5','stock_ret60','stock_range20']
VARIANTS={'stock':STOCK,'original':MODELS['ridge-relative'],'strong':STRONG,'context':STRONG+MARKET,
    'relative':STRONG+MARKET+RELATIVE,'unit':STRONG+MARKET+['unit_gap','unit_intraday','unit_repair','repair_market_interaction'],
    'oldmarket':STRONG+[f'old_{x}' for x in MARKET]}


def augmented(bars,market):
    out=market.copy()
    out['stock_ret60']=bars.Close.pct_change(60)
    out['stock_range20']=((bars.High-bars.Low)/bars.Close).rolling(20).mean()
    out['unit_gap']=out.gap-out.market_gap
    out['unit_intraday']=out.intraday-out.market_intraday
    out['unit_repair']=(out.unit_gap.lt(0)&out.unit_intraday.gt(0)).astype(float)
    for name in MARKET:
        out[f'old_{name}']=out[name].shift(20)
    return out


def main():
    target=EXPERIMENT/'others/followup_result.json'
    if target.exists():
        raise RuntimeError('Preserve existing followup')
    from czsc_trader.research_tools import EvidenceRef
    for name,value in json.loads((EXPERIMENT/'protocols/followup_published.json').read_text(encoding='utf-8')).items():
        path=EXPERIMENT/('protocols/followup_design.json' if name=='followup-design' else f'src/{name}.py')
        if EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()!=path.read_bytes():
            raise RuntimeError('Followup source changed')
    (data,dates,*_),prior=previous()
    features=augmented(data['stock.ohlcv'],pd.read_csv(RUN/'features.csv').drop(columns='signal'))
    for n in (801,1200):
        pd.testing.assert_frame_equal(features.iloc[:n],augmented(data['stock.ohlcv'].iloc[:n],pd.read_csv(RUN/'features.csv').drop(columns='signal').iloc[:n]))
    labels=prior_csv(prior,'labels')
    labels=labels.loc[labels.horizon.isin([1,3])&labels.maturity.ge(0)&labels.signal.ge(61)].copy()
    labels['year']=[dates[int(s)].year for s in labels.signal]
    for c in features:
        labels[c]=features[c].to_numpy()[labels.signal.to_numpy(dtype=int)]
    original=pd.read_csv(RUN/'predictions.csv')
    allcols=list(dict.fromkeys(x for v in VARIANTS.values() for x in v))
    assert np.isfinite(labels[allcols].to_numpy()).all()
    splits=[];tests=[];fits=0
    sys.path.insert(0,str(EXPERIMENT/'src'))
    with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        for h in (1,3):
            queue=labels.loc[labels.horizon.eq(h)].sort_values('signal')
            for year in (2023,2024,2025,2026):
                test=queue.loc[queue.year.eq(year)].copy()
                start=int(test.signal.min()); end=int(test.signal.max())
                train=queue.loc[queue.maturity.lt(start)]
                universe=features.iloc[61:end+1]
                split={'horizon':h,'year':year,'train':len(train),'test':len(test),'latest_maturity':int(train.maturity.max()),
                    'first_test_signal':start,'frozen_thresholds':{}}
                assert train.maturity.max()<start
                jobs={(algo,name):pool.submit(predict,(f'{algo}-{name}',train[cols].to_numpy(),universe[cols].to_numpy(),train.net_return.to_numpy()))
                    for algo in ('ridge','tree') for name,cols in VARIANTS.items()}
                for (algo,name),job in jobs.items():
                    trained,history=job.result();fits+=1
                    key=f'{algo}_{name}'
                    values=history[test.signal.to_numpy(dtype=int)-61]
                    threshold=float(np.quantile(trained,.75))
                    series=pd.Series(history,index=universe.index)
                    rolling=series.shift().rolling(126).quantile(.75)
                    test[f'prediction_{key}']=values
                    test[f'frozen_{key}']=values>=threshold
                    test[f'rolling_{key}']=values>=rolling.loc[test.signal.to_numpy(dtype=int)].to_numpy()
                    test[f'rolling_threshold_{key}']=rolling.loc[test.signal.to_numpy(dtype=int)].to_numpy()
                    split['frozen_thresholds'][key]=threshold
                    if name in ('stock','original'):
                        oldkey=f'{algo}_'+('stock' if name=='stock' else 'relative')
                        old=original.loc[original.horizon.eq(h)&original.year.eq(year)]
                        np.testing.assert_allclose(values,old[f'prediction_{oldkey}'],rtol=0,atol=1e-10)
                splits.append(split);tests.append(test)
        predictions=pd.concat(tests,ignore_index=True)
        annual=[];pending=[];contributions=[]
        for h,raw in predictions.groupby('horizon'):
            part=raw.sort_values('signal').reset_index(drop=True);y=part.net_return.to_numpy()
            a=part.gap.lt(0)&part.intraday.gt(0);b=part.gap.lt(0)&part.intraday.le(0);c=part.gap.ge(0)&part.intraday.gt(0)
            categories=np.select([a,b,c],['A-lowgap-repair','B-lowgap-nonrepair','C-upgap-upcandle'],default='D-other')
            for algo in ('ridge','tree'):
                for mode in ('frozen','rolling'):
                    for name in VARIANTS:
                        key=f'{algo}_{name}';selected=part[f'{mode}_{key}'].to_numpy()
                        for year,g in [('ALL',part),*list(part.groupby('year'))]:
                            chosen=selected[g.index]
                            for scope,mask in [('all',np.ones(len(g),dtype=bool)),('repair',a[g.index].to_numpy())]:
                                sel=chosen&mask;other=~chosen&mask
                                annual.append({'horizon':int(h),'algo':algo,'mode':mode,'variant':name,'year':str(year),'scope':scope,
                                    'n':int(mask.sum()),'selected':int(sel.sum()),'filled':int(g.loc[sel,'entry_filled'].sum()),
                                    'selected_mean':float(g.loc[sel,'net_return'].mean()) if sel.any() else None,
                                    'unselected_mean':float(g.loc[other,'net_return'].mean()) if other.any() else None,
                                    'per_origin':float((g.net_return*sel).mean()),
                                    'mae':float((g[f'prediction_{key}']-g.net_return).abs().mean())})
                    pairs=[('strong','stock'),('context','strong'),('relative','strong'),('unit','strong'),('oldmarket','strong'),('original','stock'),('relative','all')]
                    for left,right in pairs:
                        sa=part[f'{mode}_{algo}_{left}'].to_numpy()
                        sb=np.ones(len(part),dtype=bool) if right=='all' else part[f'{mode}_{algo}_{right}'].to_numpy()
                        identity={'horizon':int(h),'algo':algo,'mode':mode,'left':left,'right':right}
                        pending.append((identity,pool.submit(compare,(groups(part,y,sa,sb),'allocation',1.,113+int(h)))))
                        change=sa.astype(float)-sb.astype(float)
                        retained=[]
                        for s in part.loc[change!=0,'signal']:
                            if not retained or int(s)>retained[-1]+10:
                                retained.append(int(s))
                        keep=part.signal.isin(retained).to_numpy()
                        for year,g in part.groupby('year'):
                            for category in np.unique(categories):
                                gi=g.index.to_numpy();mask=categories[gi]==category
                                delta=change[gi]; vals=y[gi]
                                contributions.append({**identity,'year':int(year),'category':category,
                                    'added':int(((delta>0)&mask).sum()),'removed':int(((delta<0)&mask).sum()),
                                    'contribution_per_origin':float((vals*delta*mask).sum()/len(g)),
                                    'decluster_contribution_per_origin':float((vals*delta*mask*keep[gi]).sum()/len(g))})
        comparisons=[{**identity,**job.result()} for identity,job in pending]
    predictions.to_csv(RUN/'followup_predictions.csv',index=False,lineterminator='\n')
    features.to_csv(RUN/'followup_features.csv',index_label='signal',lineterminator='\n')
    pd.DataFrame(annual).to_csv(EXPERIMENT/'others/followup_annual.csv',index=False,lineterminator='\n')
    pd.DataFrame(contributions).to_csv(EXPERIMENT/'others/followup_contributions.csv',index=False,lineterminator='\n')
    result={'fits':fits,'new_fits':80,'reproduction_fits':32,'test_rows':len(predictions),'splits':splits,'comparisons':comparisons,
        'new_source_calls':0,'strategy_accounts':0,'nominal_history':408,
        'limit':'Adaptive explanation on seen pool,56contrasts plus unenumerated descriptive subgroups; no independent validation or investable account.'}
    assert fits==112 and len(comparisons)==56
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('FOLLOWUP_COMPLETE',fits,len(comparisons))


if __name__=='__main__':
    main()
