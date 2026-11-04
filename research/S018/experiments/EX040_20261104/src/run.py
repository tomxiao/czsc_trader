from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from czsc_trader.research_tools.equity_replay import materialize_equity


def main():
    w=Path(__file__).resolve().parents[1]
    family=w.parents[1]
    base=json.loads((family/'experiments/EX025_20261104/others/results.json').read_text())['accounts']['C6300']['account_ref']
    p=family/'assets/evidence'/base['experiment']['experiment_id']/base['evidence_id']
    raw=p.read_bytes();assert sha256(raw).hexdigest()==base['sha256']
    view=materialize_equity(raw,lambda x:(p.parent/(x['sha256']+'.json')).read_bytes()).payload
    bars=pd.DataFrame(view['audit_inputs']['bars'])
    c=bars.Close; o=bars.Open; r=np.log(c).diff(); sigma=r.rolling(20).std().shift(2)
    features=pd.DataFrame({'date':bars.Date.str[:10],
        'drift':r.rolling(20).sum().shift(2)/(sigma*np.sqrt(20)),
        'range_state':np.log(((bars.High-bars.Low)/c.shift()).rolling(5).mean()/((bars.High-bars.Low)/c.shift()).rolling(20).mean()),
        'shock_today':r/sigma,'shock_yesterday':r.shift()/sigma,
        'intraday':np.log(c/o)/sigma,'gap':np.log(o/c.shift())/sigma})
    features=features.set_index('date')
    # Physical prefixes must reproduce every feature used at that date.
    for t in range(251,len(bars),31):
        b=bars.iloc[:t+1]; rr=np.log(b.Close).diff();ss=rr.iloc[-22:-2].std()
        assert np.isclose(features.iloc[t]['drift'],rr.iloc[-22:-2].sum()/(ss*np.sqrt(20)))
        assert np.isclose(features.iloc[t]['shock_today'],rr.iloc[-1]/ss)
        assert np.isclose(features.iloc[t]['shock_yesterday'],rr.iloc[-2]/ss)
        ran=(b.High-b.Low)/b.Close.shift()
        assert np.isclose(features.iloc[t]['range_state'],np.log(ran.iloc[-5:].mean()/ran.iloc[-20:].mean()))
    event=json.loads((family/'experiments/EX039_20261104/others/analysis_events_enriched.json').read_text())
    events=pd.DataFrame(event)
    models={'mean':[], 'context':['drift','range_state'],
            'shock':['drift','range_state','shock_today','shock_yesterday'],
            'decomposition':['drift','range_state','intraday','gap','shock_yesterday']}
    predictions=[]
    for horizon in [1,3,6]:
        dataset=events[events.horizon==horizon].copy().sort_values('signal_date')
        dataset=dataset.join(features,on='signal_date')
        for t in features.index[features.index >= '2022-12-30']:
            if t >= '2026-10-30':continue
            train=dataset[dataset.exit_date<=t]
            if len(train)<126:continue
            assert train.signal_date.max()<t
            y=train.net_return.to_numpy(float)
            for name,cols in models.items():
                if cols:
                    fitted=make_pipeline(StandardScaler(),Ridge(alpha=10.))
                    fitted.fit(train[cols].to_numpy(float),y)
                    value=float(fitted.predict(features.loc[[t],cols].to_numpy(float))[0])
                else:value=float(y.mean())
                predictions.append({'signal_date':t,'horizon':horizon,'model':name,'prediction':value,
                    'train_n':len(train),'latest_label_exit':train.exit_date.max()})
    pred=pd.DataFrame(predictions)
    merged=pred.merge(events,on=['signal_date','horizon'],how='left',validate='many_to_one')
    metrics={}
    for (h,name), group in merged.groupby(['horizon','model']):
        valid=group[group.status=='CLOSED'].copy()
        ref=merged[(merged.horizon==h)&(merged.model=='mean')][['signal_date','prediction']].rename(columns={'prediction':'mean_prediction'})
        valid=valid.merge(ref,on='signal_date',validate='one_to_one')
        def describe(x):
            r=x.net_return.to_numpy(float)
            return {'n':len(x),'mean':float(np.mean(r)) if len(r) else None,
                'p05':float(np.quantile(r,.05)) if len(r) else None,
                'win_rate':float(np.mean(r>0)) if len(r) else None}
        pos=valid.prediction>0
        mse=float(np.mean((valid.prediction-valid.net_return)**2))
        base_mse=float(np.mean((valid.mean_prediction-valid.net_return)**2))
        metrics[f'{h}:{name}']={'forecasts':len(group),'observed':len(valid),
            'mse_improvement':1-mse/base_mse,'positive':describe(valid[pos]),'nonpositive':describe(valid[~pos]),
            'two_down_positive':describe(valid[pos & (valid.two_down==True)]),
            'two_down_nonpositive':describe(valid[~pos & (valid.two_down==True)]),
            'years':{str(year):{'positive':describe(valid[pos & valid.signal_date.str.startswith(str(year))]),
                'nonpositive':describe(valid[~pos & valid.signal_date.str.startswith(str(year))])} for year in [2023,2024,2025,2026]}}
    assert all(pred.latest_label_exit<=pred.signal_date)
    pred.to_json(w/'others/analysis_forecasts.json',orient='records',force_ascii=False,indent=2)
    out={'models':models,'metrics':metrics,'checks':['physical_prefix_features','mature_labels_only','common_dates_per_horizon'],
         'limits':'全部为已见开发池；日期因果训练不恢复独立性。缺少成交或末端未完成的预测未填零；重叠标签不独立，筛选未形成完整账户。'}
    (w/'others/analysis_metrics.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
