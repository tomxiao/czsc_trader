"""Independent P1 training reconstruction and causal runtime checks; no accounts."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import json
import importlib.util
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from datetime import date
from types import SimpleNamespace
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import ParameterSet, TradableWindow

HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[3];BASE=HERE.parent
def read(p):return json.loads(p.read_bytes())
def save(name,v):(HERE/'others'/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def close(a,b):np.testing.assert_allclose(a,b,rtol=3e-8,atol=2e-11,equal_nan=True)
def module(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def sources():
    for k,v in read(HERE/'others/training_refs.json').items():assert EvidenceRef.from_dict(v).resolve(ROOT).read_bytes()==(HERE/k).read_bytes()
    proto=read(HERE/'protocols/plan.json')
    return proto,{k:pd.read_csv(EvidenceRef.from_dict(v).resolve(ROOT)) for k,v in proto['sources'].items()}
def train_audit(proto,frames):
    x=frames['price_features'];labels=frames['labels'];assert len(x)==434 and x.position.tolist()==list(range(434))
    datasets={}
    for lag in (1,3):
        f=frames[f'funding_lag{lag}'];assert f.date.tolist()==x.date.tolist()
        g=x.copy();g['state_positive']=(f.f20>0).astype(float);g['state_zero']=(f.f20==0).astype(float)
        datasets[lag]=g.merge(labels[labels.target.eq('net3')].drop(columns='date'),on='position',validate='one_to_one')
    events=frames['events'];events=events[events.horizon.eq(3)]
    assert events.date.tolist()==x.date.tolist();close(datasets[1].y,events.net.where(events.status.eq('CLOSED'))/100000.)
    schedules={(fam,lag):read(HERE/f'others/models_{fam}_{lag}.json') for fam,lag in proto['arms']}
    manifest=read(HERE/'others/training_manifest.json');lookup={(r['family'],r['lag'],r['release']):r for r in manifest};assert len(lookup)==len(manifest)
    releases=[];last=None;fits=0
    for pos,day in enumerate(x.date):
        g=datasets[1];tr=g[(g.position<pos)&g.y.notna()&(g.known_date<day)]
        if len(tr)<30 or (last is not None and pos-last<20):continue
        releases.append(pos);last=pos
        for (fam,lag),schedule in schedules.items():
            sample=datasets[lag].loc[tr.index];cols=proto['columns'][fam];record=schedule[len(releases)-1]
            assert record['date']==day and record['train_known_max']==sample.known_date.max()<day and set(record['models'])=={'path'}
            m=record['models']['path'];assert m['columns']==cols
            values=sample[cols].to_numpy(float);center=values.mean(0);scale=values.std(0);scale[scale==0]=1
            design=np.c_[np.ones(len(values)),(values-center)/scale]
            augmented=np.vstack([design,np.diag([0.]+[np.sqrt(10.)]*len(cols))]);response=np.r_[sample.y.to_numpy(),np.zeros(len(cols)+1)]
            beta=np.linalg.lstsq(augmented,response,rcond=None)[0]
            close(m['center'],center);close(m['scale'],scale);close(m['beta'],beta)
            expected={'family':fam,'lag':lag,'release':day,'position':pos,'train_n':len(sample),'positions_sha256':sha256(sample.position.to_numpy(dtype='<i8').tobytes()).hexdigest(),'training_xy_sha256':sha256(sample[cols+['y']].to_numpy(dtype='<f8').tobytes()).hexdigest(),'max_known':sample.known_date.max(),'columns':cols,'alpha':10}
            assert lookup[fam,lag,day]==expected
            prefix=datasets[lag][datasets[lag].date<=day];prefix=prefix[prefix.position.lt(pos)&prefix.y.notna()&prefix.known_date.lt(day)]
            pd.testing.assert_frame_equal(prefix,sample);fits+=1
    predictions=pd.read_csv(HERE/'others/model_predictions.csv');assert len(predictions)==434*7 and not predictions[['family','lag','position']].duplicated().any()
    prefix_checks=0
    for (fam,lag),schedule in schedules.items():
        assert [r['date'] for r in schedule]==x.date.iloc[releases].tolist()
        observed=predictions[predictions.family.eq(fam)&predictions.lag.eq(lag)].sort_values('position');assert observed.date.tolist()==x.date.tolist()
        def predicted(records,frame):
            values=np.full(len(frame),np.nan)
            dates=frame.date.to_numpy()
            for index,record in enumerate(records):
                start=int(np.searchsorted(dates,record['date']))
                stop=int(np.searchsorted(dates,records[index+1]['date'])) if index+1<len(records) else len(frame)
                if start==stop:continue
                m=record['models']['path'];matrix=frame.iloc[start:stop][m['columns']].to_numpy(float)
                values[start:stop]=m['beta'][0]+((matrix-np.asarray(m['center']))/np.asarray(m['scale']))@np.asarray(m['beta'][1:])
            return values
        expected=predicted(schedule,datasets[lag]);close(expected,observed.prediction)
        assert observed.ready.tolist()==np.isfinite(expected).tolist()
        assert observed.permission.tolist()==(np.isfinite(expected)&((fam=='U')|(expected>=0))).tolist()
        for cutoff,day in enumerate(x.date):
            trimmed=[v for v in schedule if v['date']<=day]
            # Independent prediction over a physically truncated feature/schedule prefix.
            close(predicted(trimmed,datasets[lag].iloc[:cutoff+1]),expected[:cutoff+1]);prefix_checks+=1
    summary=read(HERE/'others/training_summary.json');assert summary['fitted_models']==fits==140 and summary['releases']==len(releases)==20
    save('training_audit.json',{'status':'PASS','first_release':x.date.iloc[releases[0]],'first_release_position':releases[0],'releases':len(releases),'model_fits_independently_reconstructed':fits,'prediction_rows':len(predictions),'full_prefix_replays':prefix_checks,'training_samples_strictly_known_before_release':True,'method':'Authenticated net3 labels and features; independent release population/hash reconstruction, augmented least-squares Ridge10, every prediction and all 434 cutoff prefixes for each of seven configurations. U shares B model but ignores score.','limitations':['Seen development sample, not new independent validation.','Share-state historical release/revision assumption remains unverified by source.'],'audit_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()})
    print('TRAINING_AUDIT_PASS',flush=True)
def runtime_audit(proto,frames):
    source=HERE/'src/strategy_runtime/strategies/price_information.py';m=module(source,'p1_runtime_audit')
    oldpath=BASE/'EX026_20261023/src/study.py';oldref=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/protocol_refs.json')['study.py']);assert oldpath.read_bytes()==oldref.resolve(ROOT).read_bytes()
    old=module(oldpath,'p1_historical_loader');adj,raw,bars,rules,ids=old.inputs(old.sources())
    for f in (adj,raw,bars):f.attrs={}
    shares=frames['shares'];prior=frames['price_features'];pricecols=[c for c in m.COLUMNS if not c.startswith('state_')]
    x=m.causal_features(adj,raw,bars);assert len(x)==435 and not x.feature_ready.iloc[0] and x.feature_ready.iloc[1:].all()
    close(x.iloc[1:][pricecols],prior[pricecols]);features={};checks=[]
    for lag in (1,3):
        v=shares.set_index('Date').TotalShare;dates=pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d').tolist();expected=[]
        for day in x.index.strftime('%Y-%m-%d'):
            i=dates.index(day);ratio=float(v.loc[dates[i-lag]]/v.loc[dates[i-lag-20]]-1)
            expected.append([float(ratio>0),float(ratio==0)])
        ff=m.funding_features(x,adj,shares,lag);close(ff[['state_positive','state_zero']],expected);features[lag]=ff
        funding=frames[f'funding_lag{lag}'];close(ff.iloc[1:].state_positive,(funding.f20>0).astype(float));close(ff.iloc[1:].state_zero,(funding.f20==0).astype(float))
        for pos in (0,39,99,183,351,433):
            end=pd.to_datetime(adj.Date.iloc[75+pos]);aa=adj.iloc[:76+pos];rr=raw.iloc[:76+pos];bb=bars.iloc[:8*(pos+1)];ss=shares[pd.to_datetime(shares.Date)<end]
            prefix=m.funding_features(m.causal_features(aa,rr,bb),aa,ss,lag);pd.testing.assert_frame_equal(prefix,ff.iloc[:pos+2],check_exact=True)
    predictions=pd.read_csv(HERE/'others/model_predictions.csv')
    for fam,lag in proto['arms']:
        schedule=read(HERE/f'others/models_{fam}_{lag}.json');params={'family':fam,'lag':lag,'hold':3,'exposure':1.,'schedule':schedule};out=m.intentions(features[lag],params)
        observed=predictions[predictions.family.eq(fam)&predictions.lag.eq(lag)].sort_values('position');close(out.path_prediction.iloc[1:][observed.ready.to_numpy()],observed.prediction[observed.ready]);close(out.permission.iloc[1:],observed.permission)
        age=0;expected=[]
        for permission in out.permission:
            if age>=3:age=0
            elif age:age+=1
            elif permission:age=1
            expected.append(age)
        close(out.intent_age,expected);assert out.loc[out.target_position.eq(0),'entry_allocation_fraction'].isna().all();assert out.loc[out.target_position.eq(1),'entry_allocation_fraction'].eq(1).all()
        for cutoff in (0,39,99,183,351,433):
            day=features[lag].index[cutoff+1];p={**params,'schedule':[v for v in schedule if v['date']<=day.strftime('%Y-%m-%d')]}
            pd.testing.assert_frame_equal(m.intentions(features[lag].iloc[:cutoff+2],p),out.iloc[:cutoff+2])
        runtime=m.PriceInformation(ParameterSet(params));assert runtime.definition.decision.output_kind=='CYCLE_TARGET'
        assert runtime.definition.execution.settings['capital']=={'fee_rate':.001,'mode':'signal_cash_fraction','target_scope':'entry_cycle'}
        for start in (date(2025,1,2),date(2025,2,6)):
            window=TradableWindow(start,date(2026,10,21));runtime.calendar_request(window);scope=runtime.derive_calculation_scope(window,tuple(pd.Timestamp(d).date() for d in adj.Date));assert scope.calculation_dates[0]==date(2024,12,31)
            inputs={name:frame[pd.to_datetime(frame.Date).dt.normalize()<=pd.Timestamp(scope.inputs[name].end)] for name,frame in [('market',adj),('execution',raw),('intraday',bars),('shares',shares)]}
            computed=runtime.calculate_context_history(inputs,SimpleNamespace(sessions=pd.DatetimeIndex(scope.calculation_dates)));pd.testing.assert_frame_equal(computed,out.reindex(pd.DatetimeIndex(scope.calculation_dates)))
    one={'columns':['r1'],'center':[0.],'scale':[1.],'beta':[1.,0.]};p={'family':'B','lag':1,'hold':3,'exposure':.5,'schedule':[{'date':'2025-01-02','train_known_max':'2024-12-31','models':{'path':one}}]}
    out=m.intentions(features[1],p);assert out.target_position.iloc[:10].tolist()==[0.,1.,1.,1.,0.,1.,1.,1.,0.,1.];assert out.loc[out.target_position.eq(1),'entry_allocation_fraction'].eq(.5).all()
    bads=[]
    for field,value in [('hold',True),('exposure',1.1),('lag',2)]:z=deepcopy(p);z[field]=value;bads.append(z)
    z=deepcopy(p);z['schedule'][0]['train_known_max']='2025-01-02';bads.append(z)
    z=deepcopy(p);z['schedule'][0]['models']['path']['scale']=[0.];bads.append(z)
    for z in bads:
        try:m.validate_parameters(z)
        except ValueError:pass
        else:raise AssertionError('invalid parameter accepted')
    save('runtime_checks.json',{'status':'PASS','source_sha256':sha256(source.read_bytes()).hexdigest(),'feature_rows':434,'price_features':pricecols,'share_lags':[1,3],'independent_share_state_rows':870,'price_share_prefixes':12,'configuration_signal_prefixes':42,'scope_checks':14,'checks':['Authenticated prior 13 price/path features','Independent scalar 20-session share ratios at lag1/lag3','Future-truncated data and coefficient schedules','Seven configurations predictions and three-intent-day state machine','CYCLE_TARGET signal_cash_fraction entry_cycle with signal-owned allocation','Flat allocation NaN legal and no static policy allocation','Five malformed parameter boundaries rejected'],'input_loader':oldref.to_dict(),'data_identities':ids,'accounts_created':0,'limits':['Budget locking and actual execution are verified separately from formal accounts.','Historical share revision/PIT assumption remains a limitation.']});print('RUNTIME_AUDIT_PASS',flush=True)
if __name__=='__main__':
    p,f=sources();train_audit(p,f);runtime_audit(p,f)
