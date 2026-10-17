"""Independent labels, 16 estimator refits and simple existing-state comparator."""
import json
from hashlib import sha256
import numpy as np
import pandas as pd
from study import EX,RUN,ROOT,BASE,RULES,prepare,ridge

def main():
    if (EX/'others/audit.json').exists():raise RuntimeError('Preserve audit')
    checks=[]
    def check(name,ok):
        assert bool(ok),name
        checks.append(name)
    fresh,dates,labels,cuts,sources=prepare();saved=pd.read_csv(RUN/'observations.csv')
    pd.testing.assert_frame_equal(fresh,saved,check_exact=False,rtol=0,atol=1e-11)
    check('public pinned inputs and all observations reproduce',True)
    check('decision after entry and before earlier exit',(saved.decision==saved.entry).all() and (saved.decision<saved.early_exit).all() and (saved.early_exit<=saved.maturity).all())
    check('same-share cash extension',np.allclose(saved.target,saved.quantity*(saved.late_price-saved.early_price)*.999/100000,atol=1e-11,rtol=0))
    check('overnight intraday boundary add to target',np.allclose(saved.target,saved.overnight+saved.intraday+saved.boundary_adjustment,atol=1e-11,rtol=0))
    check('repair erasure nested within no followthrough',(~saved.loc[saved.parent,'repair_erased']|saved.loc[saved.parent,'no_followthrough']).all())
    predictions=pd.read_csv(EX/'others/predictions.csv');annual=pd.read_csv(EX/'others/annual.csv');models=[];refits=0
    for h in (3,5):
        allh=saved.loc[saved.horizon.eq(h)];test=allh.loc[allh.parent&allh.state_ready&allh.year.ge(2023)].copy()
        for year,g in test.groupby('year'):
            train=allh.loc[allh.maturity.lt(g.decision.min())].copy();train['gap_state']=train.state.ge(cuts[year]);g=g.copy()
            for rule in RULES:
                train[rule+'_interaction']=train[rule].astype(float)*train.gap_state.astype(float);g[rule+'_interaction']=g[rule].astype(float)*g.gap_state.astype(float)
            for name,cols in [('base',BASE),('augmented',BASE+RULES+[r+'_interaction' for r in RULES])]:
                expected=ridge(train[cols].to_numpy(float),g[cols].to_numpy(float),train.target.to_numpy());actual=predictions.loc[(predictions.horizon==h)&(predictions.year==year)&(predictions.model==name),'prediction']
                check(f'annual refit H{h}/{year}/{name}',np.allclose(expected,actual,rtol=0,atol=1e-11));refits+=1
        pred=predictions.loc[predictions.horizon.eq(h)].pivot(index='signal',columns='model',values='prediction');test=test.set_index('signal')
        for name in ('base','augmented'):
            test[name+'_gain']=-pred.loc[test.index,name].lt(0).astype(float)*test.target
        test['low_exit_gain']=-test.gap_state.eq(False).astype(float)*test.target
        for scope,part in [('ALL',test),('WITHOUT2026',test.loc[test.year.ne(2026)]),*[(str(y),v) for y,v in test.groupby('year')]]:
            models.append({'horizon':h,'scope':scope,'n':len(part),'base_gain':float(part.base_gain.mean()),'augmented_gain':float(part.augmented_gain.mean()),
                'increment':float((part.augmented_gain-part.base_gain).mean()),'low_exit_gain':float(part.low_exit_gain.mean()),'augmented_minus_low_exit':float((part.augmented_gain-part.low_exit_gain).mean())})
        for row in annual.loc[annual.horizon.eq(h)&annual.scope.eq('ALL')].itertuples():
            base=np.zeros(len(test)) if row.base=='hold' else test[row.base].astype(float).to_numpy()
            delta=test.target*(base-test[row.rule].astype(float))
            check(f'paired probe H{h}/{row.rule}/{row.base}',abs(delta.mean()-row.delta)<1e-12)
    pd.DataFrame(models).to_csv(EX/'others/model_comparisons.csv',index=False,lineterminator='\n')
    p=saved.loc[(saved.horizon==3)&saved.parent&saved.state_ready];by_signal=p.copy()
    by_signal['signal_year']=pd.to_datetime(labels.drop_duplicates('signal').set_index('signal').loc[p.signal,'signal_date']).dt.year.to_numpy()
    attr=by_signal.groupby(['gap_state','signal_year'])[['target','overnight','intraday','boundary_adjustment']].mean().reset_index()
    attr.to_csv(EX/'others/attribution.csv',index=False,lineterminator='\n')
    check('primary filled parent count',len(p)==213 and p.gap_state.sum()==153)
    refs=json.loads((EX/'protocols/published_design.json').read_text(encoding='utf-8'))
    check('locked source identity',sha256((EX/'src/study.py').read_bytes()).hexdigest()==refs['study']['sha256'])
    manifest=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()} for p in sorted([*EX.rglob('*.py'),*EX.rglob('*.json'),*EX.rglob('*.csv'),*RUN.glob('*.csv')]) if p.name!='audit.json']
    (EX/'others/audit.json').write_text(json.dumps({'status':'PASS','checks':checks,'check_count':len(checks),'refits':refits,'manifest':manifest,'source_calls':0},indent=2)+'\n',encoding='utf-8',newline='\n')
    print('PASS',len(checks),refits)
if __name__=='__main__':main()
