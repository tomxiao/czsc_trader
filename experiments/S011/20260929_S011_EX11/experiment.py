"""Immutable role evidence review. Component admission remains an explicit judgment."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import json
import numpy as np
import pandas as pd
import scipy
from scipy.stats import spearmanr
from dataflows import DataRequest, Dataset
from research_experiment import (ExperimentDefinition,ExperimentMode,ExperimentProtocol,
    ExperimentStage,ExperimentDependency,ExperimentCapabilities,ExperimentCapability,
    ExperimentResult,ExperimentOutcome,ResearchExperiment)

ID='20260929_S011_EX11'
PREDECESSORS={'20260929_S011_EX10':'e4a532e7cc888cd5d770bb4c0e2cf41ce37cff0a731792197922d2e85bd9e78c'}
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
            review=pd.concat(parts);raw=review[[factor,label]].rank(pct=True).to_numpy();raw[:,0]*=orientation
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
    factor='EX04__extreme_order'
    for label in y:
        h=int(label.rsplit('_',1)[1])
        for start,end in (('2024-09-09','2025-07-01'),*WINDOWS):
            ii=np.flatnonzero((dates>=start)&(dates<end));last=ii[-1];ii=ii[ii+h<=last]
            z=data.iloc[ii][[factor,label]].dropna()
            for value,g in z.groupby(factor):binary.append({'Label':label,'Start':start,'Value':value,'N':len(g),'LabelMean':g[label].mean()})
    return pd.DataFrame(rows),pd.DataFrame(folds),pd.DataFrame(months),pd.DataFrame(binary)

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

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.FORMAL,
            research_question='Does the selected information have distinct and defensible stage-two roles?',
            hypothesis='Short reversal, external confirmation and continuous risk information may support distinct roles.',
            falsification_conditions=('Formula or causal contract differs','Role evidence depends only on pooled regimes','Information is redundant or role evidence is inadequate'),
            development_cutoff=date(2026,9,28),validation_cutoff=date(2026,9,29),random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value,),subjects=('159326.SZ',),
            protocol=ExperimentProtocol(stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=('Temporary pressure competes with persistent price information','Risk magnitude differs from expected direction'),
                information_paths=('Same-day and strictly earlier source observations to subsequent ETF paths',),
                stage_objectives=('Reconstruct definitions','Review distinct roles and adverse evidence','Retain full screening history'),
                observation_metrics=('Raw rank and partial rank','Segment and leave-month diagnostics','Forecast and baseline calibration'),
                methodology=('Nine fixed candidates and seven inherited labels','No parameter or trading combination search',),
                predecessor_experiment_ids=tuple(PREDECESSORS)),
            dependencies=tuple(ExperimentDependency(k,v) for k,v in [('numpy',np.__version__),('pandas',pd.__version__),('scipy',scipy.__version__)]),
            capabilities=ExperimentCapabilities(reads_real_returns=True,reads_sealed_validation=True))

    def synthetic_precheck(self):synthetic()

    def execute(self,context):
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        repo=Path(__file__).resolve().parents[3];p=repo/'experiments/S011/20260929_S011_EX10/artifacts';artifacts=[]
        for ex,sha in PREDECESSORS.items():
            if context.predecessors[ex].receipt_sha256!=sha:raise ValueError('predecessor differs')
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None,lineterminator='\n')
            artifacts.append(context.workspace.register_artifact(name,'S011-EX11-'+name.split('.')[0]))
        x=indexed(pd.read_csv(p/'factor_matrix.csv.gz'));y=indexed(pd.read_csv(p/'future_labels.csv.gz'));ledger=pd.read_csv(p/'information_ledger.csv')
        result=context.data.fetch(DataRequest(Dataset.ETF_OHLCV,'159326.SZ','2024-12-26','2026-09-28',None,'30m',{'env_file':str(repo/'.env')}))
        if not result.ready or result.identity is None:raise ValueError('intraday source unavailable')
        bars=result.dataframe
        save('source_intraday.csv.gz',bars)
        if result.identity.metadata.get('adjustment')!='hfq' or len(bars)!=3408:raise ValueError('intraday price or count differs')
        if not pd.to_datetime(bars.AvailableDate).dt.strftime('%H:%M:%S').eq('17:00:00').all():raise ValueError('intraday clock differs')
        inputs={name:indexed(pd.read_csv(p/f'source_{name}.csv.gz')) for name in ('etf','large','small','spx')}
        rebuilt=calculate(inputs['etf'],bars,inputs['large'],inputs['small'],inputs['spx'])
        checks=[]
        for name in REVIEW:
            if not np.allclose(rebuilt[name],x[name],rtol=1e-9,atol=1e-12,equal_nan=True):raise ValueError('formula differs: '+name)
            checks.append({'Factor':name,'ComparedRows':len(x),'FiniteN':int(x[name].notna().sum()),'MaxAbsError':float((rebuilt[name]-x[name]).abs().max())})
        save('definition_checks.csv',pd.DataFrame(checks));save('review_component_values.csv.gz',rebuilt.reset_index(names='Date'))
        print('EX11 nine definitions matched',flush=True)
        scores,folds,months,binary=audit(x,y,ledger)
        save('role_evidence.csv',scores);save('role_folds.csv',folds);save('leave_month.csv',months);save('binary_diagnostic.csv',binary)
        corr=x.corr(method='spearman',min_periods=120);save('review_correlation.csv',corr.loc[list(REVIEW),list(REVIEW)].reset_index(names='Factor'))
        screen=[]
        for factor in x:
            evidence=ledger.loc[ledger.Factor.eq(factor)];best=corr.loc[factor,list(PRIMARY)].abs().dropna()
            nearest=best.idxmax() if len(best) else '';value=float(best.max()) if len(best) else np.nan
            status='DETAILED_REVIEW' if factor in REVIEW else ('CONSTANT' if x[factor].nunique()<2 else ('BINARY_DESCRIBED_SEPARATELY' if factor=='EX04__extreme_order' else ('CORRELATED_ALTERNATIVE' if value>=.8 else 'SURVEY_ONLY_NO_ROLE_ADMISSION')))
            screen.append({'Factor':factor,'ReviewRoute':status,'NearestPrimary':nearest,'AbsCorrelation':value,'FiniteN':int(x[factor].notna().sum()),'EX10DescribedPaths':int(evidence.Status.eq('DESCRIBED').sum()),'ComponentAdmittedByMachine':False})
        save('full_screening_ledger.csv',pd.DataFrame(screen))
        summary={'decision':'ROLE_REVIEW_READY','review_features':len(REVIEW),'review_paths':len(scores),'forecast_folds':len(folds),'leave_month_paths':len(months),
            'full_screened_fields':len(screen),'intraday_identity':{'content_sha256':result.identity.content_sha256,'metadata':dict(result.identity.metadata)},
            'predecessor_receipts':PREDECESSORS,'component_promotion_performed':False,'account_replay_performed':False}
        context.workspace.path('summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        artifacts.append(context.workspace.register_artifact('summary.json','S011-EX11-summary'))
        return ExperimentResult(outcome=ExperimentOutcome.PASS,facts={k:summary[k] for k in ('decision','review_features','review_paths','full_screened_fields','component_promotion_performed')},diagnostics={'definition_checks':len(checks)},artifacts=tuple(artifacts))
