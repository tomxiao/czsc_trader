"""S011 broad, role-aware component evidence census. No strategy or promotion."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import json
import warnings
import numpy as np
import pandas as pd
import scipy
from scipy.stats import spearmanr
import statsmodels
import statsmodels.api as sm
import tsfresh
from tsfresh.feature_extraction import MinimalFCParameters, feature_calculators as fc
from dataflows import DataRequest, Dataset
from research_experiment import (ExperimentDefinition, ExperimentMode, ExperimentProtocol,
    ExperimentStage, ExperimentDependency, ExperimentCapabilities, ExperimentCapability,
    ExperimentResult, ExperimentOutcome, ResearchExperiment)

ID='20260929_S011_EX10'
START,END='2024-09-09','2026-09-28'
SEED=2026092910
PREDECESSORS={
 '20260929_S011_EX01':'2cfdb869fe0c2b41b1048b58655e423c53cf2e7618d154a26491db9d42633473',
 '20260929_S011_EX02':'d3bb256adbcb32cd09cdc7eca5a03c813c7741de2b9c2d49a71d7018c497c96e',
 '20260929_S011_EX04':'23c60187b0f7d94f0c54f513d6942e94b55f9a37d55db6443f0b8d2e7f072985',
 '20260929_S011_EX06':'b4b23abbca57b32e33be1f3de4111b0e31215c0caefc651e4ffb9323f3ff1b27',
 '20260929_S011_EX07':'18f9ba9232e5a8379573151ff151ba7fd2427ee98cd5c77c88d9a8f36018c395',
 '20260929_S011_EX08':'a71f701ef6a7a418081f91067d9f826315bbcf70ebc23961631b365c8932b6bb'}
WINDOWS=(('2025-07-01','2026-01-01'),('2026-01-01','2026-07-01'),('2026-07-01','2026-10-01'))
REQUESTS=(('etf',Dataset.ETF_OHLCV,'159326.SZ',START),
 ('large',Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000300.SH','2024-06-01'),
 ('small',Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'000905.SH','2024-06-01'),
 ('growth',Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,'399006.SZ','2024-06-01'),
 ('spx',Dataset.GLOBAL_INDEX_DAILY,'SPX','2024-06-01'),
 ('ixic',Dataset.GLOBAL_INDEX_DAILY,'IXIC','2024-06-01'),
 ('shibor',Dataset.SHIBOR_DAILY,None,'2024-06-01'),
 ('calendar',Dataset.TRADING_CALENDAR,'SSE',START))

def indexed(frame):
    f=frame.copy(); f['Date']=pd.to_datetime(f.Date).dt.normalize()
    if f.Date.duplicated().any() or not f.Date.is_monotonic_increasing: raise ValueError('dates invalid')
    return f.set_index('Date')

def prior(s,dates):
    a=pd.DataFrame({'DecisionDate':dates})
    b=pd.DataFrame({'SourceDate':s.index,'Value':s.to_numpy()})
    z=pd.merge_asof(a,b,left_on='DecisionDate',right_on='SourceDate',direction='backward',allow_exact_matches=False)
    bad=(z.DecisionDate-z.SourceDate).dt.days.gt(10)
    z.loc[bad,'Value']=np.nan; z.loc[bad,'SourceDate']=pd.NaT
    return pd.Series(z.Value.to_numpy(),index=dates),pd.Series(z.SourceDate.to_numpy(),index=dates)

def daily_features(etf):
    c=etf.Close.astype(float); a=etf.Amount.astype(float); r=c.pct_change(fill_method=None)
    span=(etf.High-etf.Low)/c; delta=np.log(a).diff()
    d={}
    for h in (1,3,5,10,20,60): d[f'daily__return_{h}']=c.pct_change(h,fill_method=None)
    for h in (5,20,60): d[f'daily__vol_{h}']=r.rolling(h).std()
    d['daily__range']=span
    for h in (5,20): d[f'daily__range_mean_{h}']=span.rolling(h).mean()
    d.update({'daily__body':c/etf.Open-1,'daily__gap':etf.Open/c.shift(1)-1,
        'daily__close_location':(c-etf.Low)/(etf.High-etf.Low).replace(0,np.nan),
        'daily__distance_mean_20':c/c.rolling(20).mean()-1,
        'daily__amount_activity':np.log(a/a.rolling(20).median()),'daily__log_amount_change':delta})
    for h in (5,20): d[f'daily__log_amount_change_mean_{h}']=delta.rolling(h).mean()
    for series_name,s in [('return',r),('range',span),('log_amount_change',delta)]:
        for h in (20,60):
            for calculator in MinimalFCParameters():
                d[f'tsf__{series_name}__{calculator}__{h}']=s.rolling(h,min_periods=h).apply(getattr(fc,calculator),raw=True)
    return pd.DataFrame(d,index=etf.index).replace([np.inf,-np.inf],np.nan)

def labels(etf):
    out={}; entry=etf.Open.shift(-1)
    for h in (1,3,5,10): out[f'return_{h}']=etf.Close.shift(-h)/entry-1
    low=pd.concat([etf.Low.shift(-i) for i in range(1,6)],axis=1).min(axis=1)
    out['adverse_5']=(1-low/entry).where(etf.Close.shift(-5).notna())
    ranges=(etf.High-etf.Low)/etf.Open
    out['range_5']=pd.concat([ranges.shift(-i) for i in range(1,6)],axis=1).mean(axis=1).where(etf.Close.shift(-5).notna())
    out['persistence_3']=pd.concat([(etf.Close.shift(-i)>entry).astype(float) for i in range(1,4)],axis=1).mean(axis=1).where(etf.Close.shift(-3).notna())
    return pd.DataFrame(out,index=etf.index)

def rho(a,b):
    z=pd.concat([a,b],axis=1).dropna()
    return float(spearmanr(z.iloc[:,0],z.iloc[:,1]).statistic) if len(z)>=3 and z.iloc[:,0].nunique()>1 and z.iloc[:,1].nunique()>1 else np.nan

def mapping(train,values):
    lo,hi=train.quantile([.01,.99]); ref=np.sort(train.clip(lo,hi).to_numpy(float))
    if not len(ref) or np.unique(ref).size<2: return pd.Series(np.nan,index=values.index)
    out=pd.Series(np.searchsorted(ref,values.clip(lo,hi).to_numpy(float),side='right')/len(ref)-.5,index=values.index)
    out.loc[values.isna()]=np.nan
    return out

def ridge(tr,te,cols,label):
    y=tr[label].to_numpy(float); mu=y.mean()
    if not cols: return np.full(len(te),mu)
    x=tr[cols].to_numpy(float); q=te[cols].to_numpy(float)
    center=x.mean(0); scale=x.std(0); scale[scale==0]=1
    x=(x-center)/scale; q=(q-center)/scale
    w=np.linalg.solve(x.T@x+10*np.eye(len(cols)),x.T@(y-mu))
    return mu+q@w

def bootstrap(x,y,seed):
    z=pd.DataFrame({'x':x,'y':y}).dropna().rank(pct=True).to_numpy(float)
    n=len(z); rng=np.random.default_rng(seed)
    dates=pd.DataFrame({'x':x,'y':y}).dropna().index
    pieces=[]
    for start,end in WINDOWS:
        positions=np.flatnonzero((dates>=start)&(dates<end)); count=len(positions)
        if not count: continue
        starts=rng.integers(0,count,size=(1000,int(np.ceil(count/20))))
        local=((starts[:,:,None]+np.arange(20))%count).reshape(1000,-1)[:,:count]
        pieces.append(positions[local])
    if not pieces: return np.nan,np.nan,np.nan
    ix=np.concatenate(pieces,axis=1)
    sample=z[ix]; sample-=sample.mean(1,keepdims=True)
    den=np.sqrt(np.sum(sample[:,:,0]**2,axis=1)*np.sum(sample[:,:,1]**2,axis=1))
    valid=den>0
    rr=np.sum(sample[valid,:,0]*sample[valid,:,1],axis=1)/den[valid]
    if len(rr)<950: return np.nan,np.nan,np.nan
    return float((rr>0).mean()),float(np.quantile(rr,.05)),float(np.quantile(rr,.95))

def bh(values):
    out=pd.Series(np.nan,index=values.index); v=values.dropna().sort_values(); n=len(v)
    if n: out.loc[v.index]=np.minimum(1,np.minimum.accumulate((v.to_numpy()*n/np.arange(1,n+1))[::-1])[::-1])
    return out

def survey(x,y):
    data=x.join(y); pos=np.arange(len(data)); dates=data.index
    controls=['daily__return_5','daily__vol_20']
    first=np.flatnonzero(dates>='2025-07-01')[0]
    rows=[]; folds=[]
    for no,factor in enumerate(x.columns):
        for label in y.columns:
            h=int(label.rsplit('_',1)[1]); role='RISK_CONTEXT' if label.startswith(('adverse','range')) else ('CONFIRMATION' if label.startswith('persistence') else 'OPPORTUNITY_ENTRY')
            tr=data.iloc[pos+h<first][[factor,label]].dropna()
            validtests=[]; segments=[]
            for start,end in WINDOWS:
                ii=np.flatnonzero((dates>=start)&(dates<end)); last=ii[-1]
                ii=ii[ii+h<=last]
                z=data.iloc[ii][[factor,label]].dropna(); segments.append((start,end,ii,z)); validtests.append(z)
            te=pd.concat(validtests)
            rec={'Factor':factor,'Label':label,'ProposedRole':role,'DiscoveryN':len(tr),'ReviewN':len(te)}
            if len(tr)<60 or len(te)<120 or tr[factor].nunique()<3 or te[factor].nunique()<3 or tr[label].nunique()<2 or te[label].nunique()<2:
                rows.append({**rec,'Status':'INSUFFICIENT_OR_CONSTANT'}); continue
            orientation=1 if rho(tr[factor],tr[label])>=0 else -1
            score=mapping(tr[factor],te[factor])*orientation
            if score.nunique()<2:
                rows.append({**rec,'Status':'SATURATED_DISCOVERY_MAPPING'}); continue
            prob,lo,hi=bootstrap(score,te[label],SEED+no*10+h)
            sd=score.std(ddof=0)
            fit=sm.OLS(te[label].to_numpy(float),sm.add_constant(((score-score.mean())/sd).to_numpy(float))).fit(cov_type='HAC',cov_kwds={'maxlags':10})
            p=float(fit.pvalues[1]/2 if fit.params[1]>=0 else 1-fit.pvalues[1]/2)
            z=data.loc[te.index,[label,*controls]].dropna()
            ols=sm.OLS(z[label].to_numpy(float),sm.add_constant(z[controls].to_numpy(float))).fit()
            residual=pd.Series(ols.resid,index=z.index)
            scorefit=sm.OLS(score.loc[z.index].to_numpy(float),sm.add_constant(z[controls].to_numpy(float))).fit()
            residualscore=pd.Series(scorefit.resid,index=z.index)
            signed_train=mapping(tr[factor],tr[factor])*orientation
            qlo,qhi=signed_train.quantile([.2,.8])
            strong=te.loc[score>=qhi,label]; weak=te.loc[score<=qlo,label]
            rec.update(Status='DESCRIBED',Orientation=orientation,DiscoveryIC=abs(rho(tr[factor],tr[label])),
                ReviewIC=rho(score,te[label]),ResidualIC=rho(residualscore,residual),
                HacP=p,BootstrapPositive=prob,IcLo90=lo,IcHi90=hi,
                StrongN=len(strong),WeakN=len(weak),TailDifference=float(strong.mean()-weak.mean()))
            err={k:[] for k in ('mean','factor','base','plus')}
            for j,(start,end,ii,zseg) in enumerate(segments):
                sseg=score.reindex(zseg.index)
                strongseg=zseg.loc[sseg>=qhi,label]; weakseg=zseg.loc[sseg<=qlo,label]
                rec[f'FoldIC{j}']=rho(sseg,zseg[label]); rec[f'FoldTail{j}']=float(strongseg.mean()-weakseg.mean())
                rec[f'FoldStrongN{j}']=len(strongseg);rec[f'FoldWeakN{j}']=len(weakseg)
                teststart=np.flatnonzero(dates>=start)[0]
                cols=list(dict.fromkeys([factor,label,*controls]))
                train=data.iloc[pos+h<teststart][cols].dropna(); test=data.iloc[ii][cols].dropna()
                if len(train)<60 or len(test)<15: continue
                rr={'Factor':factor,'Label':label,'TestStart':start,'TrainN':len(train),'TestN':len(test)}
                for kind,cc in [('mean',[]),('factor',[factor]),('base',controls),('plus',list(dict.fromkeys([*controls,factor])))]:
                    loss=(test[label].to_numpy(float)-ridge(train,test,cc,label))**2
                    err[kind].extend(loss.tolist());rr[kind+'Mse']=float(loss.mean())
                folds.append(rr)
            if err['mean']:
                rec['FactorVsMean']=1-np.mean(err['factor'])/np.mean(err['mean'])
                rec['BaseVsMean']=1-np.mean(err['base'])/np.mean(err['mean'])
                rec['IncrementVsBase']=1-np.mean(err['plus'])/np.mean(err['base'])
            rows.append(rec)
        if (no+1)%20==0: print(f'EX10 evidence {no+1}/{len(x.columns)} factors',flush=True)
    result=pd.DataFrame(rows); result['GlobalBH']=bh(result.get('HacP',pd.Series(np.nan,index=result.index)))
    return result,pd.DataFrame(folds)

def synthetic():
    rng=np.random.default_rng(SEED); idx=pd.bdate_range('2025-01-01',periods=300)
    close=np.exp(np.cumsum(rng.normal(0,.01,len(idx))))*100
    etf=pd.DataFrame({'Open':close*.999,'High':close*1.01,'Low':close*.99,'Close':close,'Amount':np.exp(rng.normal(18,.1,len(idx)))},index=idx)
    a=daily_features(etf); mutated=etf.copy();mutated.iloc[200:]*=1.2
    b=daily_features(mutated)
    pd.testing.assert_frame_equal(a.iloc[:200],b.iloc[:200])
    yy=labels(etf); assert yy.return_10.iloc[-10:].isna().all()
    assert yy.persistence_3.iloc[-3:].isna().all()
    assert np.isclose(yy.adverse_5.iloc[0],1-etf.Low.iloc[1:6].min()/etf.Open.iloc[1])
    assert np.isclose(yy.return_3.iloc[0],etf.Close.iloc[3]/etf.Open.iloc[1]-1)
    priorvalues,sourcedate=prior(pd.Series([1.,2.],index=idx[:2]),idx[:3])
    assert pd.isna(priorvalues.iloc[0]) and priorvalues.iloc[1]==1 and priorvalues.iloc[2]==2
    train=pd.Series([0.,1.,2.,3.]); assert mapping(train,pd.Series([100.])).iloc[0]==.5
    assert mapping(pd.Series([1.,1.]),pd.Series([2.])).isna().all()
    tr=pd.DataFrame({'x':[1.,2.,3.],'y':[2.,4.,6.]});te=pd.DataFrame({'x':[7.,8.]})
    assert np.allclose(ridge(tr,te,[],'y'),4.)
    assert np.allclose(bh(pd.Series([.01,.04,.03])).to_numpy(),[.03,.04,.04])
    assert np.isnan(rho(pd.Series([1.,1.,1.]),pd.Series([1.,2.,3.])))
    bx=pd.Series(np.arange(100,dtype=float),index=pd.bdate_range('2025-07-01',periods=100))
    probability,lo,hi=bootstrap(bx,bx,SEED)
    assert probability==1 and np.isclose(lo,1) and np.isclose(hi,1)
    assert len(MinimalFCParameters())==10 and len(a.columns)==80

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(schema_version=1,experiment_id=ID,strategy_id='S011',mode=ExperimentMode.FORMAL,
            research_question='Which causal information supports opportunity, persistence or risk roles on the ETF?',
            hypothesis='Role-specific ranking and path evidence can differ from conditional magnitude-prediction error.',
            falsification_conditions=('No meaningful temporal association for a proposed role','Evidence reverses or duplicates another input','Causal input contract fails'),
            development_cutoff=date(2026,9,28),validation_cutoff=date(2026,9,29),random_seed=SEED,
            allowed_datasets=tuple(dict.fromkeys(r[1].value for r in REQUESTS)),subjects=('159326.SZ',),
            protocol=ExperimentProtocol(stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=('Temporary trading pressure competes with persistent information','Volatility persistence may identify risk independently of returns'),
                information_paths=('Completed prices and earlier external sources at T20:30 to subsequent ETF paths',),
                stage_objectives=('Unified basic and proposed factors','Evidence for separate roles before component review'),
                observation_metrics=('Rank and fixed-tail effect','HAC and block uncertainty','Simple and conditional prediction loss'),
                methodology=('Complete fixed feature ledger and seven labels','Frozen discovery orientation and boundaries','No strategy selection'),
                predecessor_experiment_ids=tuple(PREDECESSORS)),
            dependencies=tuple(ExperimentDependency(k,v) for k,v in [('numpy',np.__version__),('pandas',pd.__version__),('scipy',scipy.__version__),('statsmodels',statsmodels.__version__),('tsfresh',tsfresh.__version__)]),
            capabilities=ExperimentCapabilities(reads_real_returns=True,reads_sealed_validation=True))

    def synthetic_precheck(self): synthetic()

    def execute(self,context):
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        repo=Path(__file__).resolve().parents[3]; artifacts=[]; frames={}; identities={}
        def save(name,frame):
            frame.to_csv(context.workspace.path(name),index=False,compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None,lineterminator='\n')
            artifacts.append(context.workspace.register_artifact(name,'S011-EX10-'+name.split('.')[0]))
        for name,dataset,symbol,start in REQUESTS:
            r=context.data.fetch(DataRequest(dataset,symbol,start,END,None,'daily',{'env_file':str(repo/'.env')}))
            if not r.ready or r.identity is None: raise ValueError(f'{name}: {r.status.value}; {r.error}')
            identities[name]={'dataset':dataset.value,'symbol':symbol,'rows':len(r.dataframe),'content_sha256':r.identity.content_sha256,'metadata':dict(r.identity.metadata)}
            save('source_'+name+'.csv.gz',r.dataframe); frames[name]=indexed(r.dataframe)
            print('EX10 source',name,len(r.dataframe),flush=True)
        etf=frames['etf']; cal=frames['calendar']; sessions=cal.index[cal.IsOpen.eq(1)]
        if len(etf)!=497 or not etf.index.equals(sessions): raise ValueError('ETF calendar differs')
        if identities['etf']['metadata'].get('adjustment')!='hfq': raise ValueError('ETF not hfq')
        if not pd.to_datetime(etf.AvailableDate).dt.strftime('%H:%M:%S').eq('17:00:00').all(): raise ValueError('ETF availability differs')
        if not np.isfinite(etf[['Open','High','Low','Close','Amount']].to_numpy(float)).all() or (etf[['Open','High','Low','Close','Amount']]<=0).any().any(): raise ValueError('invalid ETF values')
        parts=[]; meta=[]
        for ex,receipt in PREDECESSORS.items():
            if context.predecessors[ex].receipt_sha256!=receipt: raise ValueError('predecessor receipt differs')
            path=repo/'experiments/S011'/ex/'artifacts/factor_matrix.csv.gz'
            f=indexed(pd.read_csv(path)).reindex(etf.index)
            for c in f.columns: meta.append({'Factor':ex[-4:]+'__'+c,'Source':ex,'Definition':c,'Availability':'T20:30, after source contract','EvidenceScope':'SEEN_DEVELOPMENT_POOL','PotentialRoles':'OPPORTUNITY_ENTRY;CONFIRMATION;RISK_CONTEXT'})
            parts.append(f.add_prefix(ex[-4:]+'__'))
        d=daily_features(etf);parts.append(d)
        for c in d:meta.append({'Factor':c,'Source':'DFLS ETF HFQ daily','Definition':c,'Availability':'T20:30','EvidenceScope':'SEEN_DEVELOPMENT_POOL','PotentialRoles':'OPPORTUNITY_ENTRY;CONFIRMATION;RISK_CONTEXT'})
        ext={}; times={}
        for name in ('large','small','growth'):
            f=frames[name]; close=f.Close; amount=f.Amount
            for h in (1,5,20): ext[f'market__{name}_return_{h}']=close.pct_change(h,fill_method=None).reindex(etf.index)
            loga=np.log(amount.where(amount>0))
            ext[f'market__{name}_amount_z20']=((loga-loga.rolling(20).mean())/loga.rolling(20).std()).reindex(etf.index)
            ext[f'market__{name}_amount_ratio20']=np.log(amount/amount.rolling(20).median()).reindex(etf.index)
        for name in ('small','growth'):ext[f'market__{name}_relative5']=ext[f'market__{name}_return_5']-ext['market__large_return_5']
        for name in ('spx','ixic'):
            if identities[name]['metadata'].get('unit')!='decimal_return':raise ValueError('US return unit')
            r=frames[name].PercentChange
            for h in (1,5):
                series=(1+r).rolling(h).apply(np.prod,raw=True)-1
                ext[f'external__{name}_{h}'],times[f'{name}_{h}']=prior(series,etf.index)
        r=frames['shibor'].OvernightRate
        for h in (0,1,5):ext[f'external__rate_{h}'],times[f'rate_{h}']=prior(r if h==0 else r.diff(h),etf.index)
        parts.append(pd.DataFrame(ext,index=etf.index))
        for c in ext:meta.append({'Factor':c,'Source':'DFLS existing Tushare index/rate','Definition':c,'Availability':'T20:30; US/rate strictly earlier source date','EvidenceScope':'SEEN_DEVELOPMENT_POOL','PotentialRoles':'OPPORTUNITY_ENTRY;CONFIRMATION;RISK_CONTEXT'})
        x=pd.concat(parts,axis=1).replace([np.inf,-np.inf],np.nan); y=labels(etf)
        if x.columns.duplicated().any():raise ValueError('duplicate feature identity')
        coverage=pd.DataFrame([{'Factor':c,'FiniteN':x[c].notna().sum(),'UniqueN':x[c].nunique(),'FirstFinite':str(x[c].first_valid_index())} for c in x])
        save('factor_matrix.csv.gz',x.reset_index(names='Date'));save('future_labels.csv.gz',y.reset_index(names='Date'))
        save('feature_catalog.csv',pd.DataFrame(meta));save('feature_coverage.csv',coverage)
        save('source_dates.csv',pd.DataFrame(times,index=etf.index).reset_index(names='Date'))
        scores,folds=survey(x,y)
        save('information_ledger.csv',scores);save('forecast_folds.csv',folds)
        corr=x.corr(method='spearman',min_periods=120);save('absolute_spearman.csv',corr.abs().reset_index(names='Factor'))
        summary={'decision':'ROLE_EVIDENCE_REVIEW_REQUIRED','feature_count':len(x.columns),'label_count':len(y.columns),
            'comparison_count':len(scores),'described_paths':int(scores.Status.eq('DESCRIBED').sum()),
            'insufficient_paths':int(scores.Status.ne('DESCRIBED').sum()),'forecast_folds':len(folds),
            'tsfresh_new_features':60,'source_identities':identities,'predecessor_receipts':PREDECESSORS,
            'component_promotion_performed':False,'account_replay_performed':False}
        context.workspace.path('summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        artifacts.append(context.workspace.register_artifact('summary.json','S011-EX10-summary'))
        return ExperimentResult(outcome=ExperimentOutcome.PASS,facts={k:summary[k] for k in ('decision','feature_count','comparison_count','described_paths','component_promotion_performed','account_replay_performed')},diagnostics={'insufficient_paths':summary['insufficient_paths']},artifacts=tuple(artifacts))
