"""Current managed rerun of the fixed S011 component role tests."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
from dataflows import DataRequest, Dataset
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentProtocol, ExperimentStage, ExperimentDependency, ExperimentCapabilities,
    ExperimentPrecheckResult, ExperimentPreflightCheck, ExperimentPreflightStatus,
    ExperimentResult, ExperimentOutcome,
)
"""Frozen EX12 numeric methods; binary historical diagnostic excluded from this rerun."""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
SEED=2026092911
WINDOWS=(('2025-07-01','2026-01-01'),('2026-01-01','2026-07-01'),('2026-07-01','2026-09-29'))
PRIMARY={'market__large_return_1':-1,'EX01__tail_return_90':-1,'external__spx_1':1,'daily__range_mean_5':1}
REVIEW={**PRIMARY,'daily__close_location':-1,'market__small_relative5':1,
    'daily__range':1,'daily__range_mean_20':1,'EX01__tail_return_60':-1}
CONTROLS=['daily__return_5','daily__vol_20']

def indexed(f):
    f=f.copy();f['Date']=pd.to_datetime(f.Date)
    if f.Date.duplicated().any() or not f.Date.is_monotonic_increasing:raise ValueError('invalid dates')
    return f.set_index('Date')

def rho(x,y):
    z=pd.concat([x,y],axis=1).dropna()
    return float(spearmanr(z.iloc[:,0],z.iloc[:,1]).statistic) if len(z)>2 and (z.nunique()>1).all() else np.nan

def prior(s,dates):
    z=pd.merge_asof(pd.DataFrame({'Date':dates}),pd.DataFrame({'SourceDate':s.index,'Value':s.to_numpy()}),left_on='Date',right_on='SourceDate',direction='backward',allow_exact_matches=False)
    z.loc[(z.Date-z.SourceDate).dt.days.gt(10),'Value']=np.nan
    return pd.Series(z.Value.to_numpy(),index=dates)

def calculate(etf,bars,large,small,spx):
    """Raw information only; no thresholds, position, order or strategy."""
    b=bars.copy();b['Date']=pd.to_datetime(b.Date);b['Day']=b.Date.dt.normalize();b['Clock']=b.Date.dt.strftime('%H:%M')
    if b.duplicated(['Day','Clock']).any():raise ValueError('duplicate minute bar')
    close=b.pivot(index='Day',columns='Clock',values='Close')
    if close.isna().any().any() or len(close.columns)!=8:raise ValueError('incomplete intraday session')
    span=(etf.High-etf.Low)/etf.Close
    return pd.DataFrame({
        'EX01__tail_return_90':(close['15:00']/close['13:30']-1).reindex(etf.index),
        'EX01__tail_return_60':(close['15:00']/close['14:00']-1).reindex(etf.index),
        'daily__range':span,'daily__range_mean_5':span.rolling(5).mean(),
        'daily__range_mean_20':span.rolling(20).mean(),
        'daily__close_location':(etf.Close-etf.Low)/(etf.High-etf.Low).replace(0,np.nan),
        'market__large_return_1':large.Close.pct_change(fill_method=None).reindex(etf.index),
        'market__small_relative5':(small.Close.pct_change(5,fill_method=None)-large.Close.pct_change(5,fill_method=None)).reindex(etf.index),
        'external__spx_1':prior(spx.PercentChange,etf.index)},index=etf.index)

def partial(frame,factor,label,controls,orientation):
    z=frame[list(dict.fromkeys([factor,label,*controls]))].dropna().rank(pct=True)
    if len(z)<10:return np.nan
    a=z[factor].to_numpy()*orientation;b=z[label].to_numpy()
    xx=np.column_stack([np.ones(len(z)),z[controls].to_numpy()])
    a=a-xx@np.linalg.lstsq(xx,a,rcond=None)[0];b=b-xx@np.linalg.lstsq(xx,b,rcond=None)[0]
    return float(np.corrcoef(a,b)[0,1]) if a.std()>1e-12 and b.std()>1e-12 else np.nan

def ridge(tr,te,cols,label):
    y=tr[label].to_numpy(float);center=y.mean()
    if not cols:return np.full(len(te),center),np.nan
    x=tr[cols].to_numpy(float);q=te[cols].to_numpy(float);mu=x.mean(0);sd=x.std(0);sd[sd==0]=1
    x=(x-mu)/sd;q=(q-mu)/sd
    w=np.linalg.solve(x.T@x+10*np.eye(len(cols)),x.T@(y-center))
    return center+q@w,float(w[-1])

def resample_indices(lengths,seed):
    rng=np.random.default_rng(seed);parts=[];offset=0
    for n in lengths:
        starts=rng.integers(0,n,size=(2000,int(np.ceil(n/20))))
        parts.append(((starts[:,:,None]+np.arange(20))%n).reshape(2000,-1)[:,:n]+offset);offset+=n
    return np.concatenate(parts,axis=1)

def audit(x,y,ledger):
    data=x.join(y);dates=data.index;pos=np.arange(len(data));rows=[];folds=[];months=[];binary=[]
    for no,(factor,orientation) in enumerate(REVIEW.items()):
        other=[c for c in PRIMARY if c!=factor]
        for label in y:
            h=int(label.rsplit('_',1)[1]);parts=[];losses=[];increments=[]
            for start,end in WINDOWS:
                ii=np.flatnonzero((dates>=start)&(dates<end));last=ii[-1];ii=ii[ii+h<=last]
                z=data.iloc[ii].dropna(subset=[factor,label]);parts.append(z)
                cc=list(dict.fromkeys([factor,label,*CONTROLS]));tr=data.iloc[pos+h<np.flatnonzero(dates>=start)[0]][cc].dropna();te=data.iloc[ii][cc].dropna()
                first=data.iloc[pos+h<np.flatnonzero(dates>='2025-07-01')[0]][[factor,label]].dropna()
                low,high=(first[factor]*orientation).quantile([.2,.8])
                score=z[factor]*orientation;strong=z.loc[score>=high,label];weak=z.loc[score<=low,label]
                rec={'Factor':factor,'Label':label,'Start':start,'N':len(z),'RawIC':orientation*rho(z[factor],z[label]),
                    'SimplePartialIC':partial(z,factor,label,CONTROLS,orientation),
                    'PanelPartialIC':partial(z,factor,label,[*CONTROLS,*other],orientation),
                    'RawMin':z[factor].min(),'RawMax':z[factor].max(),'StrongN':len(strong),'WeakN':len(weak),
                    'FixedTailDifference':strong.mean()-weak.mean(),'TrainN':len(tr),'PredictN':len(te)}
                errors={}
                for kind,cols in [('mean',[]),('factor',[factor]),('base',CONTROLS),('plus',list(dict.fromkeys([*CONTROLS,factor])))]:
                    pred,w=ridge(tr,te,cols,label);errors[kind]=(te[label].to_numpy()-pred)**2
                    rec[kind+'Mse']=float(errors[kind].mean());rec[kind+'PredictionMean']=float(pred.mean())
                    if kind=='factor':rec['OrientedCoefficient']=orientation*w
                rec['ActualMean']=float(te[label].mean());folds.append(rec)
                losses.append(errors['mean']-errors['factor']);increments.append(errors['base']-errors['plus'])
            review=pd.concat(parts);raw=review[[factor,label]].rank(pct=True).to_numpy(copy=True);raw[:,0]*=orientation
            ix=resample_indices([len(z) for z in parts],SEED+no*10+h);sample=raw[ix];sample-=sample.mean(1,keepdims=True)
            den=np.sqrt((sample[:,:,0]**2).sum(1)*(sample[:,:,1]**2).sum(1));valid=den>0
            rr=(sample[valid,:,0]*sample[valid,:,1]).sum(1)/den[valid]
            li=resample_indices([len(a) for a in losses],SEED+no*10+h)
            diffs=np.concatenate(losses)[li].mean(1);inc=np.concatenate(increments)[li].mean(1)
            monthly=[]
            for month in sorted(set(review.index.to_period('M'))):
                z=review.loc[review.index.to_period('M')!=month];v=orientation*rho(z[factor],z[label]);monthly.append(v)
                months.append({'Factor':factor,'Label':label,'ExcludedMonth':str(month),'N':len(z),'RawIC':v})
            old=ledger.loc[ledger.Factor.eq(factor)&ledger.Label.eq(label)].iloc[0]
            rows.append({'Factor':factor,'Label':label,'Orientation':orientation,'N':len(review),
                'RawIC':orientation*rho(review[factor],review[label]),'SimplePartialIC':partial(review,factor,label,CONTROLS,orientation),
                'PanelPartialIC':partial(review,factor,label,[*CONTROLS,*other],orientation),
                'BootstrapPositive':float((rr>0).mean()),'IcLo90':float(np.quantile(rr,.05)),'IcHi90':float(np.quantile(rr,.95)),
                'LossDeltaLo90':float(np.quantile(diffs,.05)),'LossDeltaHi90':float(np.quantile(diffs,.95)),
                'IncrementDeltaLo90':float(np.quantile(inc,.05)),'IncrementDeltaHi90':float(np.quantile(inc,.95)),
                'LeaveMonthMinIC':min(monthly),'LeaveMonthMaxIC':max(monthly),
                'EX10MappedIC':old.ReviewIC,'EX10Orientation':old.Orientation,'EX10GlobalBH':old.GlobalBH})
    return pd.DataFrame(rows),pd.DataFrame(folds),pd.DataFrame(months)

def synthetic():
    idx=pd.bdate_range('2025-01-01',periods=40);v=np.arange(100.,140.)
    e=pd.DataFrame({'Open':v,'Close':v+.2,'High':v+1,'Low':v-1},index=idx)
    bars=pd.DataFrame([{'Date':d+pd.Timedelta(hours=h,minutes=m),'Close':float(v[i]+j/10)} for i,d in enumerate(idx) for j,(h,m) in enumerate([(10,0),(10,30),(11,0),(11,30),(13,30),(14,0),(14,30),(15,0)])])
    market=pd.DataFrame({'Close':v},index=idx);spx=pd.DataFrame({'PercentChange':np.arange(40)/1000},index=idx)
    a=calculate(e,bars,market,market,spx)
    ee=e.copy();ee.iloc[30:]*=2;bb=bars.copy();bb.loc[bb.Date.dt.normalize()>=idx[30],'Close']*=2
    b=calculate(ee,bb,market,market,spx);pd.testing.assert_frame_equal(a.iloc[:30],b.iloc[:30])
    scale=pd.Series(np.arange(1.,41.),index=idx);scaled=e.mul(scale,axis=0);bscaled=bars.copy();bscaled['Close']*=bscaled.Date.dt.normalize().map(scale)
    c=calculate(scaled,bscaled,market,market,spx)
    for name in ('EX01__tail_return_90','EX01__tail_return_60','daily__range','daily__range_mean_5'):assert np.allclose(a[name],c[name],equal_nan=True)
    assert pd.isna(a.external__spx_1.iloc[0]) and a.external__spx_1.iloc[2]==spx.PercentChange.iloc[1]
    ix=resample_indices([3,7],1);assert ix.shape==(2000,10) and (ix[:,:3]<3).all() and (ix[:,3:]>=3).all()
    tr=pd.DataFrame({'x':[1.,2.,3.],'y':[1.,2.,3.]});pred,_=ridge(tr,tr,[],'y');assert np.allclose(pred,2)


def synthetic_audit():
    rng=np.random.default_rng(SEED)
    idx=pd.bdate_range('2024-09-09','2026-09-28')
    x=pd.DataFrame({name:rng.normal(size=len(idx)) for name in dict.fromkeys([*REVIEW,*CONTROLS])},index=idx)
    x['EX04__extreme_order']=np.where(np.arange(len(idx))%2,1.,-1.)
    y=pd.DataFrame({'return_1':rng.normal(size=len(idx))},index=idx)
    ledger=pd.DataFrame([{'Factor':name,'Label':'return_1','ReviewIC':0.,'Orientation':direction,'GlobalBH':1.} for name,direction in REVIEW.items()])
    scores,folds,months=audit(x,y,ledger)
    assert len(scores)==9 and len(folds)==27 and len(months)==135
    assert np.isfinite(scores.RawIC).all() and folds.PredictN.min()>15

def labels(etf):
    out={}; entry=etf.Open.shift(-1)
    for h in (1,3,5,10): out[f'return_{h}']=etf.Close.shift(-h)/entry-1
    low=pd.concat([etf.Low.shift(-i) for i in range(1,6)],axis=1).min(axis=1)
    out['adverse_5']=(1-low/entry).where(etf.Close.shift(-5).notna())
    ranges=(etf.High-etf.Low)/etf.Open
    out['range_5']=pd.concat([ranges.shift(-i) for i in range(1,6)],axis=1).mean(axis=1).where(etf.Close.shift(-5).notna())
    out['persistence_3']=pd.concat([(etf.Close.shift(-i)>entry).astype(float) for i in range(1,4)],axis=1).mean(axis=1).where(etf.Close.shift(-3).notna())
    return pd.DataFrame(out,index=etf.index)



ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
ID=ROOT.name
REQUESTS=(
    ('etf',Dataset.ETF_OHLCV,'159326.SZ','2024-09-09','daily'),
    ('bars',Dataset.ETF_OHLCV,'159326.SZ','2024-12-26','30m'),
    ('large',Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000300.SH','2024-06-01','daily'),
    ('small',Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000905.SH','2024-06-01','daily'),
    ('spx',Dataset.GLOBAL_INDEX_DAILY,'SPX','2024-06-01','daily'),
)

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, experiment_id=ID, strategy_id='S011', mode=ExperimentMode.FORMAL,
            data_scope=ExperimentDataScope.DEVELOPMENT, development_cutoff=date(2026,9,28),
            random_seed=2026092911, subjects=('159326.SZ',),
            research_question='Do the fixed four component roles retain their recorded evidence under current APIs?',
            hypothesis='Nine fixed definitions and seven labels reproduce the original role statistics.',
            falsification_conditions=('Fresh managed data changes role evidence beyond tolerance',),
            allowed_datasets=tuple(dict.fromkeys(x[1].value for x in REQUESTS)),
            dependencies=tuple(ExperimentDependency(k,v) for k,v in [('numpy',np.__version__),('pandas',pd.__version__),('scipy',scipy.__version__)]),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(ExperimentStage.FEATURE_DISCOVERY,
                ('Role information is distinct from tradable profitability',),
                ('Managed observations to fixed definitions and future path labels',),
                ('Reproduce the fixed component role evidence',),
                ('Rank, partial rank, forecast error and adverse evidence',),
                ('No new search; historical broad screening attached with original limits',), ()))

    def synthetic_precheck(self):
        synthetic()
        synthetic_audit()
        return ExperimentPrecheckResult((ExperimentPreflightCheck('ROLE_COMPUTATION',ExperimentPreflightStatus.PASS,
            'Causal prefix, adjustment invariance, strict prior alignment and complete numeric audit exercised'),),
            ExperimentResult(ExperimentOutcome.PASS,{'synthetic_only':True},{}))

    def execute(self, context):
        historical=json.loads((ROOT/'historical_sources.json').read_text(encoding='utf-8'))
        for path,digest in historical.items():
            assert sha256((REPO/path).read_bytes()).hexdigest()==digest,path
        frames={}; artifacts=[]; identities={}
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,encoding='utf-8',lineterminator='\n',
                compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None)
            artifacts.append(context.workspace.register_artifact(name,'component-evidence'))
        for name,dataset,symbol,start,frequency in REQUESTS:
            result=context.data.fetch(DataRequest(dataset,symbol,start,'2026-09-28',None,frequency))
            assert result.ready and result.identity is not None, (name,result.status)
            frames[name]=result.dataframe
            identities[name]={'content_sha256':result.identity.content_sha256,'metadata':dict(result.identity.metadata)}
            save('source_'+name+'.csv.gz',result.dataframe)
        assert identities['etf']['metadata'].get('adjustment')=='hfq'
        assert identities['bars']['metadata'].get('adjustment')=='hfq'
        assert identities['spx']['metadata'].get('unit')=='decimal_return'
        for name in ('etf','bars'):
            assert pd.to_datetime(frames[name].AvailableDate).dt.strftime('%H:%M:%S').eq('17:00:00').all()
        etf=indexed(frames['etf'])
        assert len(etf)==497 and len(frames['bars'])==3408
        x=calculate(etf,frames['bars'],indexed(frames['large']),indexed(frames['small']),indexed(frames['spx']))
        x['daily__return_5']=etf.Close.pct_change(5,fill_method=None)
        x['daily__vol_20']=etf.Close.pct_change(fill_method=None).rolling(20).std()
        y=labels(etf)
        prior=REPO/'experiments/S011/20260929_S011_EX10/artifacts'
        old_x=indexed(pd.read_csv(prior/'factor_matrix.csv.gz'))
        old_y=indexed(pd.read_csv(prior/'future_labels.csv.gz'))
        checks=[]
        for name in x:
            np.testing.assert_allclose(x[name],old_x[name],rtol=1e-9,atol=1e-12,equal_nan=True)
            checks.append({'Factor':name,'ComparedRows':len(x),'FiniteN':int(x[name].notna().sum()),'MaxAbsError':float((x[name]-old_x[name]).abs().max())})
        np.testing.assert_allclose(y,old_y,rtol=1e-9,atol=1e-12,equal_nan=True)
        ledger=pd.read_csv(prior/'information_ledger.csv')
        scores,folds,months=audit(x,y,ledger)
        for name,frame in [('role_evidence.csv',scores),('role_folds.csv',folds),('leave_month.csv',months)]:
            old=pd.read_csv(REPO/'experiments/S011/20260929_S011_EX12/artifacts'/name)
            pd.testing.assert_frame_equal(frame,old,check_dtype=False,rtol=1e-8,atol=1e-10)
            save(name,frame)
        save('definition_checks.csv',pd.DataFrame(checks))
        save('review_component_values.csv.gz',x.reset_index(names='Date'))
        save('future_labels.csv.gz',y.reset_index(names='Date'))
        summary={'definition_count':len(REVIEW),'role_tests':len(scores),'folds':len(folds),'leave_month_paths':len(months),
            'data_identities':identities,'comparison':'PASS','independent_evidence':False,
            'historical_screening_rerun':False,'historical_source_count':len(historical)}
        context.workspace.path('summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        artifacts.append(context.workspace.register_artifact('summary.json','component-summary'))
        return ExperimentResult(ExperimentOutcome.PASS,{'role_tests':len(scores),'folds':len(folds),'comparison':'PASS'},
            {'development_only':True,'historical_screening_rerun':False},tuple(artifacts))
