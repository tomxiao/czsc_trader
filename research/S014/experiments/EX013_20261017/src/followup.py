"""Bounded falsification of two clues; never modify original outcomes."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from inputs import ROOT,EX
from features import GROUPS
from study import predict
from czsc_trader.research_tools import EvidenceRef

RUN=ROOT/'research/S014/assets/runs'/EX.name/'corrected'
OUT=RUN.parent/'followup'


def choose(scores,signals,stable):
    if not stable:return scores>=scores.shift().rolling(126).quantile(.75)
    ties=np.array([int(sha256(f'S014-{i}-13017'.encode()).hexdigest()[:12],16)/16**12 for i in scores.index])
    a=scores.to_numpy();decision=np.zeros(len(a),dtype=bool)
    for i in range(126,len(a)):
        before=a[i-126:i];less=(before<a[i])|((before==a[i])&(ties[i-126:i]<ties[i]))
        decision[i]=less.mean()>=.75
    return pd.Series(decision,index=scores.index)


def main():
    if OUT.exists():raise RuntimeError('Preserve followup')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    design=read(EX/'protocols/followup_design.json')
    for receipt in ('published_implementation','published_implementation_v2','published_followup'):
        for name,value in read(EX/f'protocols/{receipt}.json').items():
            ref=EvidenceRef.from_dict(value);raw=ref.resolve(ROOT).read_bytes();assert sha256(raw).hexdigest()==ref.sha256
            p=EX/('protocols/correction.json' if name=='correction' else 'protocols/followup_design.json' if name=='followup-design' else f'src/{name}.py')
            assert p.read_bytes()==raw,p
    f=pd.read_csv(RUN/'features.csv',index_col='signal');labels=pd.read_csv(RUN/'labels.csv')
    old=pd.read_csv(RUN/'predictions.csv');result=read(EX/'others/computation_result_v2.json')
    frames=[];stats=[];events=[];splits=[];fits=0
    for target in design['targets']:
        family,algo=target['family'],target['algorithm'];cols=GROUPS[family]
        queue=labels.loc[labels.horizon.eq(5)].sort_values('signal')
        for variant in ['original','clipped','recent252','lean',*[f'without_{c}' for c in cols]]:
            base=design['lean_baseline'] if variant=='lean' else result['baseline_columns']
            added=[c for c in cols if variant!=f'without_{c}']
            yearly=[]
            for year in (2023,2024,2025,2026):
                test=queue.loc[queue.year.eq(year)].copy();first=int(test.signal.min());last=int(test.signal.max())
                train=queue.loc[queue.maturity.lt(first)]
                if variant=='recent252':train=train.tail(252)
                y=train.net_return.to_numpy();bounds=np.quantile(y,[.01,.99])
                if variant=='clipped':y=np.clip(y,*bounds)
                history=f.loc[np.isfinite(f).all(axis=1)&(f.index<=last)]
                for name,columns in [('base',base),('added',base+added)]:
                    score=pd.Series(predict((algo,f.loc[train.signal,columns].to_numpy(),history[columns].to_numpy(),y)),index=history.index);fits+=1
                    test[f'prediction_{name}']=score.loc[test.signal].to_numpy()
                    for stable in (False,True):test[f'{"rank" if stable else "original"}_{name}']=choose(score,test.signal,stable).loc[test.signal].to_numpy()
                    if variant=='original':
                        prior=old.loc[old.horizon.eq(5)&old.year.eq(year)]
                        np.testing.assert_allclose(test[f'prediction_{name}'],prior[f'prediction_{algo}_{"base" if name=="base" else family}'],rtol=0,atol=1e-10)
                test['family']=family;test['variant']=variant;test['algorithm']=algo;yearly.append(test)
                splits.append({'family':family,'variant':variant,'year':year,'train_n':len(train),'latest_maturity':int(train.maturity.max()),'first_test':first,'clip_bounds':bounds.tolist()})
            p=pd.concat(yearly,ignore_index=True).sort_values('signal').reset_index(drop=True);frames.append(p)
            greedy=np.zeros(len(p),dtype=bool);last_maturity=-1
            for i,row in p.iterrows():
                if row.entry>last_maturity:greedy[i]=True;last_maturity=int(row.maturity)
            for mode in ('original','rank'):
                a=p[f'{mode}_added'].to_numpy(dtype=bool);b=p[f'{mode}_base'].to_numpy(dtype=bool);delta=p.net_return.to_numpy()*(a.astype(float)-b.astype(float))
                for year,g in [('ALL',p),*list(p.groupby('year'))]:
                    ix=g.index.to_numpy();d=delta[ix];positive=np.flatnonzero(d>0);trim=d.copy();trim[positive[np.argsort(d[positive])[-3:]]]=0
                    keep=greedy[ix]
                    stats.append({'family':family,'variant':variant,'mode':mode,'year':str(year),'n':len(g),'selected':int(a[ix].sum()),'base_selected':int(b[ix].sum()),
                        'delta':float(d.mean()),'drop_best3':float(trim.mean()),'nonoverlap_n':int(keep.sum()),'nonoverlap_delta':float(d[keep].mean()) if keep.any() else None,
                        'selected_mean':float(g.loc[a[ix],'net_return'].mean()) if a[ix].any() else None})
            if variant=='original':
                x=f.loc[p.signal].reset_index(drop=True)
                parent=(x.expansion.gt(1)&x.ret1.gt(0)) if family=='compression' else (x.drawdown60.lt(0)&x.ret1.gt(0)&x.recovery_fraction.ge(.5))
                state=x.prior_compression.lt(1) if family=='compression' else x.peak_age.ge(20)
                for year,g in [('ALL',p),*list(p.groupby('year'))]:
                    ix=g.index.to_numpy();a=(parent&state).to_numpy()[ix];b=(parent&~state).to_numpy()[ix]
                    for mode in ('raw','baseline_residual'):
                        y=g.net_return.to_numpy()-(g.prediction_base.to_numpy() if mode=='baseline_residual' else 0)
                        events.append({'family':family,'year':str(year),'mode':mode,'selected':int(a.sum()),'control':int(b.sum()),
                            'selected_mean':float(y[a].mean()) if a.any() else None,'control_mean':float(y[b].mean()) if b.any() else None,
                            'difference':float(y[a].mean()-y[b].mean()) if a.any() and b.any() else None})
    OUT.mkdir(parents=True);pd.concat(frames,ignore_index=True).to_csv(OUT/'predictions.csv',index=False,lineterminator='\n')
    pd.DataFrame(stats).to_csv(EX/'others/followup_annual.csv',index=False,lineterminator='\n')
    pd.DataFrame(events).to_csv(EX/'others/direct_mechanisms.csv',index=False,lineterminator='\n')
    (EX/'others/followup_result.json').write_text(json.dumps({'fits':fits,'splits':splits,'targets':design['targets'],'source_calls':0,'strategy_accounts':0},indent=2)+'\n',encoding='utf-8',newline='\n')
    print('FOLLOWUP_COMPLETE',fits)


if __name__=='__main__':main()
