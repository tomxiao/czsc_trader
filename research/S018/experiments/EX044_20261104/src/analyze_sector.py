from pathlib import Path
import json
import numpy as np
import pandas as pd

W=Path(__file__).resolve().parents[1];O=W/'others';F=W.parents[1]


def summary(x):
    r=x.net_return.to_numpy(float)
    return {'n':len(r),'mean':float(np.mean(r)) if len(r) else None,
        'win_rate':float(np.mean(r>0)) if len(r) else None,
        'p05':float(np.quantile(r,.05)) if len(r) else None}


def main():
    mu=pd.read_json(O/'analysis_MU_hfq.json');so=pd.read_json(O/'analysis_SOXX_hfq.json')
    assert mu.time_key.tolist()==so.time_key.tolist()
    m=np.log(mu.close).diff();s=np.log(so.close).diff()
    beta=m.rolling(60).cov(s).shift(2)/s.rolling(60).var().shift(2)
    common=beta*(s+s.shift());relative=m+m.shift()-common
    features=pd.DataFrame({'signal_date':mu.time_key.str[:10], 'mu_two_down':(m<0)&(m.shift()<0),
        'beta':beta,'common2':common,'relative2':relative,'mu2':m+m.shift()})
    for t in range(251,len(mu),31):
        mm=m.iloc[t-61:t-1];ss=s.iloc[t-61:t-1]
        assert len(mm)==60 and np.isclose(beta.iloc[t],mm.cov(ss)/ss.var())
    assert np.allclose((common+relative).iloc[62:],(m+m.shift()).iloc[62:])
    events=pd.read_json(F/'experiments/EX039_20261104/others/analysis_events_enriched.json')
    merged=events.merge(features,on='signal_date',validate='many_to_one')
    result={}
    for h in [1,3,6]:
        g=merged[(merged.horizon==h)&(merged.status=='CLOSED')].copy()
        td=g.mu_two_down;both=(g.common2<0)&(g.relative2<0)
        masks={'all':pd.Series(True,index=g.index),'two_down_hfq':td,
            'common_dominates':td&(g.common2<g.relative2),'relative_dominates':td&(g.common2>=g.relative2),
            'both_negative':td&both,'common_negative_relative_nonnegative':td&(g.common2<0)&(g.relative2>=0),
            'common_nonnegative_relative_negative':td&(g.common2>=0)&(g.relative2<0)}
        for name,mask in masks.items():
            x=g[mask];result[f'{h}:{name}']={**summary(x),
                'years':{str(y):summary(x[x.signal_date.str.startswith(str(y))]) for y in [2023,2024,2025,2026]}}
    output={'metrics':result,'beta_summary':features.loc[features.signal_date>='2023-01-03','beta'].describe().to_dict(),
        'checks':['prior60_beta_excludes_latest_two_returns','common_plus_relative_equals_mu','events_unique_per_horizon'],
        'scope':'Descriptive mechanism evidence only; no executable account and no independent validation.'}
    (O/'analysis_sector_metrics.json').write_bytes((json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
    merged.to_json(O/'analysis_sector_events.json',orient='records',force_ascii=False,indent=2,double_precision=15)
    print({k:{a:v[a] for a in ['n','mean','win_rate','p05']} for k,v in result.items()})


if __name__=='__main__':main()
