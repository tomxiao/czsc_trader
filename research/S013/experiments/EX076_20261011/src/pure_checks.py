"""Focused synthetic causal/formula/contracts checks; no actual data or study."""
# ruff: noqa: E402 -- native thread limits before numeric imports.
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import component as c
import curvature_statistics as s
import labels as l

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
checks=[]
def check(name,passed):
    assert passed,name
    checks.append(name)
def reject(name,fn):
    try:
        fn()
    except (ValueError,TypeError):
        checks.append(name)
    else:
        raise AssertionError(name)
def load(path):
    spec=importlib.util.spec_from_file_location('_curvature_pure_prior',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
def function(source,name):
    return next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)

def main():
    rng=np.random.default_rng(13)
    index=pd.bdate_range('2000-01-03',periods=90)
    daily=pd.DataFrame({'Close':10*np.exp(np.cumsum(rng.normal(0,.015,90)))},index=index)
    actual=c.build_features(daily)
    original=load(ROOT/'research/S013/experiments/EX069_20261011/src/pressure_component.py')
    old=original.build_features(daily.assign(Open=daily.Close))
    check('Exact EX069 positive short_stretch4 and original20volatility',np.allclose(actual.short_stretch4,old.short_stretch4,equal_nan=True,rtol=0,atol=0) and np.allclose(actual.volatility20,old.volatility20,equal_nan=True,rtol=0,atol=0))
    # Same multiset of last4 simple/log returns: total/stretch/std identical;
    # halves reverse, changing only the declared temporal-shape numerator.
    prefix=daily.iloc[:60].copy()
    vectors=([-.03,-.01,.01,.03],[.01,.03,-.03,-.01])
    outcomes=[]
    for vector in vectors:
        closes=np.r_[prefix.Close.to_numpy(),prefix.Close.iloc[-1]*np.exp(np.cumsum(vector))]
        outcomes.append(c.build_features(pd.DataFrame({'Close':closes},index=index[:64])).iloc[-1])
    check('Same fourdaytotal/volatility different temporal order opposite curvature',np.isclose(outcomes[0].short_stretch4,outcomes[1].short_stretch4,atol=1e-12) and np.isclose(outcomes[0].volatility20,outcomes[1].volatility20,atol=1e-12) and outcomes[0].curvature4>0>outcomes[1].curvature4)
    check('Allprefix causality',all(c.build_features(daily.iloc[:i]).equals(actual.iloc[:i]) for i in range(1,len(daily)+1)))
    future=daily.copy()
    future.iloc[61:]=future.iloc[61:]*np.linspace(.7,1.3,len(future)-61)[:,None]
    check('Future mutation cannot change available prefix',c.build_features(future).iloc[:61].equals(actual.iloc[:61]))
    scaled=c.build_features(daily*37.13)
    check('HFQ positiveproportional scale invariant',np.allclose(scaled[['curvature4','short_stretch4','volatility20']],actual[['curvature4','short_stretch4','volatility20']],equal_nan=True,rtol=1e-10,atol=1e-11))
    check('No warmup becomes explicit null',actual.curvature4.iloc[:20].isna().all() and actual.curvature_unavailable_reason.iloc[:20].notna().all())
    flat=c.build_features(pd.DataFrame({'Close':np.ones(40)},index=index[:40]))
    check('Zero denominator refused as signal not epsilon/fill',flat.curvature4.isna().all() and flat.curvature_unavailable_reason.iloc[20:].eq('ZERO_VOLATILITY').all())
    missing=daily.copy()
    missing.iloc[30,0]=np.nan
    check('Missing Close never forwardfilled',c.build_features(missing).curvature4.iloc[30:51].isna().all())
    reject('Zero Close invalid',lambda:c.build_features(daily.assign(Close=0)))
    reject('Infinite Close invalid',lambda:c.build_features(daily.assign(Close=np.inf)))
    reject('Duplicate dates invalid',lambda:c.build_features(pd.concat([daily,daily.iloc[-1:]])))
    eligible=pd.Series([True,True,True,False],index=index[:4])
    target=pd.Series([1.,0.,1.,0.],index=index[:4])
    scope=c.causal_flat_eligible(eligible,target,initial_target_position=0)
    check('Original prior policy target predicate excludes policy-alreadyheld eligible',scope.tolist()==[True,False,True,False])
    reject('Missing target cannot be filled',lambda:c.causal_flat_eligible(eligible,target.mask(target.index==index[1]),initial_target_position=0))
    label_parent=(ROOT/'.tmp/s013-volume-body-interaction/component_draft.py').read_text(encoding='utf-8')
    check('Frozen EX075 fee/OCrisk label exact AST',ast.dump(function(label_parent,'fee_labels4'),include_attributes=False)==ast.dump(function((HERE/'labels.py').read_text(encoding='utf-8'),'fee_labels4'),include_attributes=False))
    prices=pd.DataFrame({'Open':[10.,8.,9.,10.,12.,11.,13.],'Close':[10.,7.,8.,9.,11.,12.,14.]},index=index[:7])
    lab=l.fee_labels4(prices,index[:3])
    check('h4 fee andOC endpoints exact independent numericfixture',np.isclose(lab.iloc[0].return4_net,.999*11/(1.001*8)-1) and np.isclose(lab.iloc[0].downside4_oc,1-7/8) and lab.iloc[0].label_end4==index[5] and lab.iloc[2].isna().all())
    check('Fixed17 controls do not negate stretch or include newcomponent',len(s.CONTROLS)==17 and s.CONTROLS[-1]=='short_stretch4' and s.COMPONENT=='curvature4' and s.COMPONENT not in s.CONTROLS)
    parent=(ROOT/'.tmp/s013-volume-body-interaction/statistics_draft_v2.py').read_text(encoding='utf-8')
    own=(HERE/'curvature_statistics.py').read_text(encoding='utf-8')
    for name in ('finite','correlation','block_indices','bootstrap','ecdf','ridge','metrics'):
        check(name+' frozen numericalkernel AST exact',ast.dump(function(parent,name),include_attributes=False)==ast.dump(function(own,name),include_attributes=False))
    grid=pd.DatetimeIndex(np.r_[pd.bdate_range('2020-01-02',periods=100).to_numpy(),pd.bdate_range('2021-01-04',periods=80).to_numpy(),pd.bdate_range('2022-01-03',periods=80).to_numpy()])
    calendar=grid.append(pd.bdate_range(grid[-1]+pd.Timedelta(days=1),periods=6))
    feats=pd.DataFrame(rng.normal(size=(len(grid),18)),index=grid,columns=[*s.CONTROLS,s.COMPONENT])
    p=pd.DataFrame({'Open':10*np.exp(np.cumsum(rng.normal(0,.01,len(calendar))))},index=calendar)
    p['Close']=p.Open*np.exp(rng.normal(0,.005,len(p)))
    labs=l.fee_labels4(p,grid)
    subset=pd.Series(np.arange(len(grid))%3!=1,index=grid)
    # Only the repeated bootstrap is spied: no500rep syntheticstudy. Preserve
    # real source sampler; independently inspect full axis and excluded targets.
    sampled=[]
    def fakebootstrap(x,y,controls,positions):
        sampled.append((len(x),y.copy(),positions.copy()))
        return {'PURE_SPY_NOT_CI':True}
    with patch.object(s,'bootstrap',fakebootstrap):
        result=s.analyze(feats,labs,calendar,flat_eligible=subset)
    check('Both fixedscopes positive return/riskdiagnostic only',set(result['scopes'])=={'all','causal_original_policy_flat_eligible'} and result['return_direction']=='positive' and 'diagnostic' in result['risk_role'])
    check('Bootstrap500x40 uses original complete axis before scope filter',all(n==len(grid) and positions.shape==(500,len(grid)) for n,y,positions in sampled) and all(np.isnan(y[~subset]).all() for n,y,positions in sampled[4:]))
    for scope_name,panel in result['scopes'].items():
        for name,row in panel['labels'].items():
            check(scope_name+'/'+name+' all5phases retained',set(row['phases'])=={'0','1','2','3','4'})
            check(scope_name+'/'+name+' allfixedtestyears retained',set(row['walk_forward']['yearly'])=={str(y) for y in s.YEARS})
            for year,annual in row['walk_forward']['yearly'].items():
                if annual['latest_train_label_end']:
                    assert pd.Timestamp(annual['latest_train_label_end'])<pd.Timestamp(annual['first_actual_signaldate'])
    checks.append('Every nonempty annualtrain label matures strictlybefore actualtestfirstsignal')
    # Mature train/model accepts only history. Mutation offuture2022 predictors
    # and labels cannot alter2021fit,predictions or pastmean baseline.
    allx=feats.to_numpy()
    first=s.walk_forward(grid,allx,labs.return4_net.to_numpy(),labs.label_end4)
    altered=allx.copy()
    altered[grid.year==2022]*=100
    y=labs.return4_net.to_numpy().copy()
    y[grid.year==2022]+=2
    second=s.walk_forward(grid,altered,y,labs.label_end4)
    check('Futureyearmutation cannot alter priorOOS fit/pastmean',first['yearly']['2021']==second['yearly']['2021'] and [r for r in first['records'] if pd.Timestamp(r['signaldate']).year==2021]==[r for r in second['records'] if pd.Timestamp(r['signaldate']).year==2021])
    reject('Target columns cannot leak into features',lambda:s.validate(feats.assign(return4_net=0),labs,calendar))
    wrong=labs.copy()
    wrong['label_end4']=grid
    reject('Wrong maturity rejects before models',lambda:s.validate(feats,wrong,calendar))
    reject('Scope cannot be nonBoolean/future missingness',lambda:s.analyze(feats,labs,calendar,flat_eligible=subset.astype(float)))
    check('Thinpartial explicitly null',s.correlation(np.arange(20),np.arange(20),rng.normal(size=(20,17)))['reason']=='INSUFFICIENT_RESIDUAL_DF')
    payload={'status':'SOURCE_ONLY_PURE_READY','check_count':len(checks),'checks':checks,
        'no_real_data_or_account_reads':True,'new_experiments':0,'publications':0,
        'actual_statistics_runs':0,'synthetic_bootstrap':'shape inspected via spy only, no diagnostic CI or500rep study',
        'synthetic_ridge':'maturity/futuremutation only, not realmarketfit',
        'blas_threads':{name:os.environ[name] for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS','NUMEXPR_NUM_THREADS')},
        'source_files':{n:sha256((HERE/n).read_bytes()).hexdigest() for n in ('component.py','labels.py','curvature_statistics.py','build_source.py','pure_checks.py')}}
    target=HERE/'pureproof.json'
    if target.exists():
        raise ValueError('Immutable pureproof already exists')
    target.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(payload['status'],len(checks))

if __name__=='__main__':
    main()
