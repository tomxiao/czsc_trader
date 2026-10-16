"""Explicit common-shock, recovery and relative-response mechanism contrasts."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import sys
import numpy as np
import pandas as pd
from inputs import ROOT, EXPERIMENT, RUN, previous, prior_csv
from market_features import predict
from followup import STRONG
from study import groups
from mechanism_stats import compare


def event_masks(g,stockq,marketq):
    recovery=g.market_previous5.lt(0)
    selloff=g.ret1.le(stockq)
    laggard=g.market_ret5.gt(0)&g.relative_close5.lt(0)
    weak=g.market_intraday.le(0)
    return {'market-recovery':(recovery&g.market_intraday.gt(0),recovery&g.market_intraday.le(0)),
        'common-selloff':(selloff&g.market_ret1.le(marketq),selloff&g.market_ret1.gt(marketq)),
        'laggard-repair':(laggard&g.intraday.gt(0),laggard&g.intraday.le(0)),
        'relative-leader':(weak&g.relative_close1.gt(0),weak&g.relative_close1.le(0))}


def main():
    target=EXPERIMENT/'others/mechanism_result.json'
    if target.exists():
        raise RuntimeError('Preserve existing results')
    from czsc_trader.research_tools import EvidenceRef
    for name,value in json.loads((EXPERIMENT/'protocols/mechanism_published.json').read_text(encoding='utf-8')).items():
        path=EXPERIMENT/('protocols/mechanism_design.json' if name=='mechanism-design' else f'src/{name}.py')
        assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==path.read_bytes()
    (data,dates,*_),prior=previous()
    feature=pd.read_csv(RUN/'followup_features.csv').drop(columns='signal')
    feature['market_previous5']=feature.market_ret5.shift()
    feature['relative_close1']=np.log1p(feature.ret1)-feature.beta*feature.market_ret1
    feature['relative_close5']=np.log1p(feature.ret5)-feature.beta*feature.market_ret5
    labels=prior_csv(prior,'labels')
    frame=labels.loc[labels.maturity.ge(0)&labels.signal.ge(61)].copy()
    frame['year']=[dates[int(s)].year for s in frame.signal]
    for c in feature:
        frame[c]=feature[c].to_numpy()[frame.signal.to_numpy(dtype=int)]
    old=pd.read_csv(RUN/'followup_predictions.csv')
    tests=[];splits=[];fits=0
    for h in (1,3,5,10):
        queue=frame.loc[frame.horizon.eq(h)].sort_values('signal')
        for year in (2023,2024,2025,2026):
            test=queue.loc[queue.year.eq(year)].copy()
            cutoff=int(test.signal.min());train=queue.loc[queue.maturity.lt(cutoff)]
            sq,mq=(float(np.quantile(train[c],.1)) for c in ('ret1','market_ret1'))
            test['stockq10']=sq;test['marketq10']=mq
            if h in (1,3):
                test['stock_prediction']=old.loc[old.horizon.eq(h)&old.year.eq(year),'prediction_ridge_strong'].to_numpy()
            else:
                test['stock_prediction']=predict(('ridge-strong',train[STRONG].to_numpy(),test[STRONG].to_numpy(),train.net_return.to_numpy()))[1]
                fits+=1
            splits.append({'horizon':h,'year':year,'stockq10':sq,'marketq10':mq,'latest_maturity':int(train.maturity.max()),'first_signal':cutoff})
            for name,(a,b) in event_masks(test,sq,mq).items():
                test[f'selected_{name}']=a
                test[f'control_{name}']=b
            tests.append(test)
    predictions=pd.concat(tests,ignore_index=True)
    annual=[];pending=[]
    sys.path.insert(0,str(EXPERIMENT/'src'))
    with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        for h,raw in predictions.groupby('horizon'):
            part=raw.sort_values('signal').reset_index(drop=True)
            for name in ('market-recovery','common-selloff','laggard-repair','relative-leader'):
                a,b=part[f'selected_{name}'].to_numpy(),part[f'control_{name}'].to_numpy()
                for mode in ('raw','residual'):
                    values=part.net_return.to_numpy()
                    if mode=='residual':
                        values=values-part.stock_prediction.to_numpy()
                    pending.append(({'horizon':int(h),'name':name,'mode':mode},pool.submit(compare,(groups(part,values,a,b),'conditional',1.,213+int(h)))))
                    for year,g in part.groupby('year'):
                        for scope,mask in [('all',np.ones(len(g),dtype=bool)),('repair',g.gap_down_repair.eq(1).to_numpy())]:
                            sa=a[g.index]&mask;sb=b[g.index]&mask
                            annual.append({'horizon':int(h),'name':name,'mode':mode,'year':int(year),'scope':scope,
                                'selected':int(sa.sum()),'control':int(sb.sum()),'filled':int(g.loc[sa,'entry_filled'].sum()),
                                'selected_mean':float(values[g.index][sa].mean()) if sa.any() else None,
                                'control_mean':float(values[g.index][sb].mean()) if sb.any() else None})
                retained=[]
                for s in part.loc[a|b,'signal']:
                    if not retained or int(s)>retained[-1]+20:
                        retained.append(int(s))
                keep=part.signal.isin(retained).to_numpy()
                for year,g in part.groupby('year'):
                    sa=(a&keep)[g.index];sb=(b&keep)[g.index]
                    annual.append({'horizon':int(h),'name':name,'mode':'decluster','year':int(year),'scope':'all',
                        'selected':int(sa.sum()),'control':int(sb.sum()),'filled':int(g.loc[sa,'entry_filled'].sum()),
                        'selected_mean':float(g.loc[sa,'net_return'].mean()) if sa.any() else None,
                        'control_mean':float(g.loc[sb,'net_return'].mean()) if sb.any() else None})
        comparisons=[{**identity,**job.result()} for identity,job in pending]
    predictions.to_csv(RUN/'mechanism_predictions.csv',index=False,lineterminator='\n')
    pd.DataFrame(annual).to_csv(EXPERIMENT/'others/mechanism_annual.csv',index=False,lineterminator='\n')
    result={'new_fits':fits,'comparisons':comparisons,'splits':splits,'nominal_history':440,'new_source_calls':0,'strategy_accounts':0,
        'limit':'Adaptive design,seen pool,explicit mechanisms do not identify cause;residual is model-dependent;year splits not independent holdout.'}
    assert fits==8 and len(comparisons)==32
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('MECHANISMS_COMPLETE',fits,len(comparisons))


if __name__=='__main__':
    main()
