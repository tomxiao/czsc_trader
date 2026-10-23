"""Fixed factorial price/share screening; historical causal schedule, no search."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,json,importlib.util
from pathlib import Path
from hashlib import sha256
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;EX=ExperimentRef('S015',HERE.name)
PATH=['return_time_balance','extrema_order','excursion_balance','halfday_balance'];LEGACY=['r1','r5','vol20','range20','pressure'];STATE=['state_positive','state_zero']
ARMS=[('U',1),('B',1),('BF',1),('BP',1),('BPF',1),('BF',3),('BPF',3)]
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(4,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def columns(f):return LEGACY+(PATH if 'P' in f else [])+(STATE if 'F' in f else [])
def prepare():
    assert not (HERE/'others/training_refs.json').exists()
    p=read(BASE/'EX036_20261023/others/published_refs.json')['materials'];f=read(BASE/'EX027_20261023/others/published_refs.json')['materials']
    sources={'price_features':p['others/model_features.csv'],'labels':p['others/labels.csv'],'shares':f['others/own_shares.csv'],**{f'funding_lag{lag}':f[f'others/features_lag{lag}.csv'] for lag in (1,3)},'events':read(BASE/'EX026_20261023/others/delivery_validation.json')['materials']['events.csv'],'old_predictions':read(BASE/'EX032_20261023/others/delivery_validation.json')['materials']['others/predictions.csv']}
    proto={'question':'Does lagged20-day ETF share state add implementable screening value beyond old price/volume and/or intraday path, in the same three-intent-day all-cash-entry container?',
      'authority':'User autonomous stage2 under research_plan_20261024.md P1, no experiment cap; same research branch, source limits and original goals.',
      'arms':ARMS,'columns':{f:columns(f) for f,lag in ARMS},
      'training':'Canonical434dates; net3 closed-event labels mature known_date strictly before release, position earlier, minimum30; first ready then every20canonicaldays. Ridge10 with train mean/pop std and unpenalized intercept; threshold0 fixed. U shares B readiness, coefficient schedule but ignores score. Before first model cash. No unavailable/preheat synthetic labels.',
      'funding':'20-session TotalShare ratio state: expansion>0, unchanged==0, contraction reference; primary previoussession lag1, sensitivity lag3. Previousday08:30 availability assumption, no certified historicalrevision PIT. Share is units, not monetary flow.',
      'runtime':'Recompute declared price/path/share from public bound frames; embed frozen schedules only. Actual date availability and latest effective coefficients. Exact 3positive intent days, no same-exit-signal reentry, CYCLE_TARGET signal_cash_fraction entry_cycle allocation1 with locked budget including buy fees, standardfees/tick/limit/lot. Funding input identical admitted contract across arms.',
      'accounts':'7 fixed parameter identities × independent full434/common415 cash100000; no threshold/hold tuning; publicSRT/TDR. First serial technical replay retained plus all5ledgers, reproduce with parallel public execution.',
      'diagnosis':'Event common cohort measured separately for entryday and net3: count and gross opportunity amounts caught/missed; allready and oldpositions>=100 subsets, fourfold contributions, price5direction. Bridge old EX032 models on sharedvalidnet3 positions; factor differences F/B and F/BP and path with/withoutF, no single component significance requirement. Account return/cost/frequency/exposure and capital blocking are distinct.',
      'limits':'Seen development data, selected old state/net3; no fresh out of sample. Net3 prediction need not identify entry-day loss. Isolated event sums not account PnL, no causality claim. Two account windows sharepoststartupcashpath, not independent evidence.',
      'sources':sources,'resources':{'max_workers':4,'native_threads':1,'seed':13}}
    save(HERE/'protocols/plan.json',proto)
    files=[HERE/'protocols/plan.json',Path(__file__),HERE/'src/strategy_runtime/strategies/price_information.py']
    save(HERE/'others/training_refs.json',{p.relative_to(HERE).as_posix():material(p).to_dict() for p in files})
    print('TRAINING_FROZEN',flush=True)
def inputs():
    for k,v in read(HERE/'others/training_refs.json').items():assert EvidenceRef.from_dict(v).resolve(ROOT).read_bytes()==(HERE/k).read_bytes()
    refs=read(HERE/'protocols/plan.json')['sources']
    frames={k:pd.read_csv(EvidenceRef.from_dict(v).resolve(ROOT)) for k,v in refs.items()}
    x=frames['price_features'];labels=frames['labels'];datasets={}
    for lag in (1,3):
        f=frames[f'funding_lag{lag}'];assert x.date.tolist()==f.date.tolist()
        np.testing.assert_allclose(x[LEGACY],f[LEGACY],rtol=1e-10,atol=1e-12)
        g=x.copy();g['state_positive']=(f.f20>0).astype(float);g['state_zero']=(f.f20==0).astype(float)
        datasets[lag]=g.merge(labels[labels.target.eq('net3')].drop(columns='date'),on='position',validate='one_to_one')
    # Explicit bridge of independently frozen label versions, no silent replacement.
    e=frames['events'];e=e[e.horizon.eq(3)];assert e.date.tolist()==x.date.tolist()
    expected=e.net.where(e.status.eq('CLOSED'))/100000.
    np.testing.assert_allclose(datasets[1].y,expected,rtol=1e-10,atol=1e-12,equal_nan=True)
    return datasets,frames
def fit(g,cols):
    x=g[cols].to_numpy(float);mean=x.mean(0);scale=x.std(0);scale[scale==0]=1;a=np.c_[np.ones(len(x)),(x-mean)/scale];penalty=np.eye(a.shape[1])*10;penalty[0,0]=0
    return {'columns':cols,'center':mean.tolist(),'scale':scale.tolist(),'beta':np.linalg.solve(a.T@a+penalty,a.T@g.y.to_numpy(float)).tolist()}
def learn():
    assert not (HERE/'others/models_B_1.json').exists();datasets,frames=inputs();schedules={(f,lag):[] for f,lag in ARMS};manifest=[];preds=[];last=None
    for pos,date in enumerate(datasets[1].date):
        train=datasets[1];train=train[train.position.lt(pos)&train.y.notna()&train.known_date.lt(date)]
        if len(train)>=30 and (last is None or pos-last>=20):
            for (f,lag),schedule in schedules.items():
                tr=datasets[lag].loc[train.index];cols=columns(f);m=fit(tr,cols)
                schedule.append({'date':date,'train_known_max':tr.known_date.max(),'models':{'path':m}})
                manifest.append({'family':f,'lag':lag,'release':date,'position':pos,'train_n':len(tr),'positions_sha256':sha256(tr.position.to_numpy(dtype='<i8').tobytes()).hexdigest(),'training_xy_sha256':sha256(tr[cols+['y']].to_numpy(dtype='<f8').tobytes()).hexdigest(),'max_known':tr.known_date.max(),'columns':cols,'alpha':10})
            last=pos
        for (f,lag),schedule in schedules.items():
            m=schedule[-1]['models']['path'] if schedule else None
            p=float(np.r_[1.,(datasets[lag].loc[pos,m['columns']].to_numpy(float)-m['center'])/m['scale']]@m['beta']) if m else None
            preds.append({'date':date,'position':pos,'family':f,'lag':lag,'ready':bool(schedule),'model_date':schedule[-1]['date'] if schedule else None,'prediction':p,'permission':bool(schedule) and (f=='U' or p>=0)})
    for (f,lag),s in schedules.items():save(HERE/f'others/models_{f}_{lag}.json',s)
    save(HERE/'others/training_manifest.json',manifest);pd.DataFrame(preds).to_csv(HERE/'others/model_predictions.csv',index=False)
    save(HERE/'others/training_summary.json',{'first_release':schedules['B',1][0]['date'],'releases':len(schedules['B',1]),'fitted_models':len(manifest),'unique_fitted_models':len(manifest)-len(schedules['U',1]),'mature_min':30,'retrain_step':20,'alpha':10,'input_refs':read(HERE/'protocols/plan.json')['sources']})
    print('MODELS_LEARNED',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','learn']);{'prepare':prepare,'learn':learn}[p.parse_args().mode]()
