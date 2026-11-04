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
    w=Path(__file__).resolve().parents[1]; family=w.parents[1]
    base=json.loads((family/'experiments/EX025_20261104/others/results.json').read_text())['accounts']['C6300']['account_ref']
    p=family/'assets/evidence'/base['experiment']['experiment_id']/base['evidence_id']
    raw=p.read_bytes();assert sha256(raw).hexdigest()==base['sha256']
    view=materialize_equity(raw,lambda x:(p.parent/(x['sha256']+'.json')).read_bytes()).payload
    bars=pd.DataFrame(view['audit_inputs']['bars']); c=bars.Close;o=bars.Open
    r=np.log(c).diff();s=r.rolling(20).std().shift(2);ranges=(bars.High-bars.Low)/c.shift()
    features=pd.DataFrame({'date':bars.Date.str[:10], 'drift':r.rolling(20).sum().shift(2)/(s*np.sqrt(20)),
        'range_state':np.log(ranges.rolling(5).mean()/ranges.rolling(20).mean()),
        'shock_today':r/s,'shock_yesterday':r.shift()/s,
        'intraday':np.log(c/o)/s,'gap':np.log(o/c.shift())/s}).set_index('date')
    events=pd.DataFrame(json.loads((family/'experiments/EX039_20261104/others/analysis_events_enriched.json').read_text()))
    models={'mean':[],'context':['drift','range_state'],
        'shock':['drift','range_state','shock_today','shock_yesterday'],
        'decomposition':['drift','range_state','intraday','gap','shock_yesterday']}
    predictions=[]
    for h in [1,3,6]:
        dataset=events[events.horizon==h].sort_values('signal_date').join(features,on='signal_date')
        for t in features.index[features.index>='2022-12-30']:
            if t>='2026-10-30':continue
            train=dataset[dataset.exit_date<=t].tail(126)
            if len(train)<126:continue
            assert train.signal_date.max()<t
            for name,cols in models.items():
                y=train.net_return.to_numpy(float)
                if cols:
                    model=make_pipeline(StandardScaler(),Ridge(alpha=10.))
                    model.fit(train[cols].to_numpy(float),y)
                    pred=float(model.predict(features.loc[[t],cols].to_numpy(float))[0])
                else:pred=float(y.mean())
                predictions.append({'signal_date':t,'horizon':h,'model':name,'prediction':pred,
                    'training_first':train.signal_date.min(),'latest_label_exit':train.exit_date.max(),'train_n':len(train)})
    rolling=pd.DataFrame(predictions);rolling['memory']='recent126'
    prior=pd.DataFrame(json.loads((family/'experiments/EX040_20261104/others/analysis_forecasts.json').read_text()));prior['memory']='expanding'
    allp=pd.concat([rolling,prior],ignore_index=True)
    combined=allp.merge(events,on=['signal_date','horizon'],how='left',validate='many_to_one')
    metrics={}
    def describe(g):
        y=g.net_return.dropna().to_numpy(float)
        return {'n':len(y),'mean':float(np.mean(y)) if len(y) else None,'p05':float(np.quantile(y,.05)) if len(y) else None,'win_rate':float(np.mean(y>0)) if len(y) else None}
    for (h,memory,name),g in combined.groupby(['horizon','memory','model']):
        g=g[g.status=='CLOSED'].copy()
        bas=combined[(combined.horizon==h)&(combined.model=='mean')&(combined.memory=='expanding')][['signal_date','prediction']].rename(columns={'prediction':'mean_prediction'})
        g=g.merge(bas,on='signal_date',validate='one_to_one');pos=g.prediction>0
        metrics[f'{h}:{memory}:{name}']={'observed':len(g),
            'mse_improvement':float(1-((g.prediction-g.net_return)**2).mean()/((g.mean_prediction-g.net_return)**2).mean()),
            'positive':describe(g[pos]),'nonpositive':describe(g[~pos]),
            'two_down_positive':describe(g[pos & (g.two_down==True)]),
            'two_down_nonpositive':describe(g[~pos & (g.two_down==True)]),
            'years':{str(y):{'positive':describe(g[pos & g.signal_date.str.startswith(str(y))]),
                           'nonpositive':describe(g[~pos & g.signal_date.str.startswith(str(y))])} for y in [2023,2024,2025,2026]}}
    assert all(rolling.latest_label_exit<=rolling.signal_date)
    rolling.to_json(w/'others/analysis_forecasts.json',orient='records',force_ascii=False,indent=2)
    output={'metrics':metrics,'decision':'按信息用途与跨时段方向解释，未增加硬验收门；重叠机会不独立，训练记忆不是市场状态真值。',
        'checks':['last126_mature_events_only','training_scaler_only','common_dates_with_EX040']}
    (w/'others/analysis_metrics.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for k,m in metrics.items():
        if ':recent126:' in k:print(k,round(m['mse_improvement'],4),m['positive'],m['nonpositive'],flush=True)


if __name__=='__main__':main()
