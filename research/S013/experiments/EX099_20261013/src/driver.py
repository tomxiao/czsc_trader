"""Explicit phases only: inputs, freeze, A fit, BCD fit. No automatic continuation."""
from pathlib import Path
import sys
import json
import numpy as np
import pandas as pd
import governance as g

W=g.WORK
sys.path.insert(0,str(W/'models'))
import stage2_models as m

def csvwrite(frame,p):
    p.parent.mkdir(parents=True,exist_ok=True)
    frame.to_csv(p,index_label='signal_date',float_format='%.17g')
def csvread(p):
    f=pd.read_csv(p,index_col='signal_date',float_precision='round_trip')
    f.index=pd.to_datetime(f.index).as_unit('ns'); return f
def feature_series(d):
    t=d.set_index('trade_date').turnover_rate_f
    return (t/t.rolling(20,min_periods=20).mean()-1).shift(1)
def share_series(d):
    t=d.set_index('trade_date').total_share
    return np.log(t/t.shift(5)).shift(1)
def inputs():
    old=g.read(g.ROOT/'research/S013/experiments/EX079_20261012/protocols/plan.json')['input_references']
    features=csvread(g.public(old['features.csv']))[list(m.FEATURES)]
    market=[]
    for name,builder in (('G1',feature_series),('G2',share_series)):
        raw=pd.read_csv(W/f'data/{name}_ordered.csv',float_precision='round_trip')
        raw.trade_date=pd.to_datetime(raw.trade_date).dt.as_unit('ns')
        values=builder(raw)
        for cut in (35,200,1000):
            np.testing.assert_allclose(builder(raw.iloc[:cut]),values.iloc[:cut],equal_nan=True,atol=0,rtol=0)
        features[name.lower()]=values.reindex(features.index).to_numpy()
        market.append({'group':name,'sha256':g.digest(W/f'data/{name}_ordered.csv'),'lag':1,'prefix_checks':3,
            'source_last_used_for_T':'previous_actual_session','valid_on_original_axis':int(features[name.lower()].notna().sum())})
    csvwrite(features,W/'inputs/features.csv')
    g.write(W/'inputs/input_checks.json',{'status':'PASS','original14_exact':True,'signal_dates':len(features),
        'first':str(features.index[0].date()),'last':str(features.index[-1].date()),'market':market,
        'common_complete':int(np.isfinite(features.to_numpy()).all(axis=1).sum()),
        'historical_publication_verified':False,'conditional_snapshot_exploration':True,'no_imputation':True,
        'old_input_references':{'features.csv':old['features.csv']}})
    print('INPUT_FEATURE_CHECKS_PASS',len(features),flush=True)

def freeze(number):
    exp=g.ExperimentRef('S013',f'EX{number:03}_20261013')
    files=[W/'governance.py',W/'driver.py',W/'models/stage2_models.py',W/'models/synthetic_checks.py',W/'models/synthetic_checks.json',
           W/'execution/label_kernel.py',W/'execution/synthetic_checks.py',W/'execution/synthetic_checks.json',
           W/'data/collect.py',W/'data/audit.py',W/'inputs/input_checks.json']
    files += list(sorted((W/'data').glob('*.json')))+list(sorted((W/'data').glob('*.csv')))
    old=g.read(g.ROOT/'research/S013/experiments/EX079_20261012/protocols/plan.json')['input_references']
    checks={'model_synthetic':g.read(W/'models/synthetic_checks.json'),
            'execution_synthetic':g.read(W/'execution/synthetic_checks.json'),'feature_checks':g.read(W/'inputs/input_checks.json')}
    if any(checks[k]['status']!='PASS' for k in checks): raise ValueError('Prerequisites not PASS')
    g.freeze(exp,files,checks,{'features.csv':old['features.csv'],'prices.csv':old['prices.csv']})
    print('PRE_RESEARCH_FREEZE_PASS',number,flush=True)

def core():
    f=csvread(W/'inputs/features.csv')
    labels=csvread(W/'execution/labels.csv')
    if not labels.index.equals(f.index): raise ValueError('Label/feature axes must be exact')
    for c in ('end_l0','end_l1'): labels[c]=pd.to_datetime(labels[c])
    attempts=csvread(W/'execution/attempts.csv')
    attempts.release_date=pd.to_datetime(attempts.release_date)
    for c in ('filled','closed'):
        if attempts[c].dtype!=bool: raise ValueError('Boolean actual fill/close required')
    return f,labels,attempts
def freeze_guard(number):
    exp=g.ExperimentRef('S013',f'EX{number:03}_20261013')
    mf=g.read(exp.resolve(g.ROOT)/'protocols/preflight.json')
    for name,sha in mf['sources'].items():
        if g.digest(g.ROOT/name)!=sha: raise ValueError('source drift '+name)
    return exp
def fit(number):
    freeze_guard(number)
    out=W/f'result{number}'; marker=out/'study_attempt.json'
    if marker.exists(): raise ValueError('Actual fit already attempted; no automatic repeat')
    f,l,a=core(); g.write(marker,{'status':'STARTED','max_fits':12 if number==99 else 36})
    result=m.forecasts(f,l,groups=('A',) if number==99 else ('B','C','D'),common_groups=('B','C'),max_fits=12 if number==99 else 36)
    for name in ('scores','means','reasons'): csvwrite(result[name],out/(name+'.csv'))
    if number==99: scores=result['scores']; means=result['means']
    else:
        scores=pd.concat([csvread(W/'result99/scores.csv'),result['scores']],axis=1)
        means=csvread(W/'result99/means.csv')
        np.testing.assert_allclose(means,result['means'],equal_nan=True,rtol=0,atol=0)
    common=pd.Series(np.isfinite(f.to_numpy()).all(axis=1),index=f.index)
    panels,choices=m.panels(scores,l,means,a,eligible=common)
    pairs=[('A1','A0')] if number==99 else [('B1','A1'),('C1','A1'),('D1','A1'),('A1','A0')]
    paired=m.paired_panels(scores.where(common,axis=0),l,means,choices,pairs)
    bootstrap=m.paired_bootstrap(scores.where(common,axis=0),l,means,choices,pairs)
    extra,_=m.panels(scores[['A0','A1']],l,means,a)
    g.write(out/'statistics.json',{'panels':panels,'A_full_original_prediction_support':extra,'paired':paired,
        'bootstrap':bootstrap,'fit_years':result['fit_years'],'actual_fit_count':result['fit_count'],
        'full_accounts':0,'new_candidates':0,'common_input_dates':int(common.sum()),'conditional_snapshot_exploration':True})
    for model,schedules in choices.items():
        for clock,selected in schedules.items(): csvwrite(selected,out/'selections'/f'{model}_{clock}.csv')
    csvwrite(scores,out/'all_scores.csv')
    g.write(out/'study_complete.json',{'status':'COMPLETE','actual_fit_count':result['fit_count'],
        'statistics_sha256':g.digest(out/'statistics.json'),'full_window_accounts':0})
    print('FIXED_RESEARCH_COMPLETE',number,result['fit_count'],flush=True)

if __name__=='__main__':
    if sys.argv[1]=='inputs': inputs()
    elif sys.argv[1]=='freeze': freeze(int(sys.argv[2]))
    elif sys.argv[1]=='fit': fit(int(sys.argv[2]))
