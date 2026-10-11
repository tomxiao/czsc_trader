"""EX086 causal conditional payoff contrast; exact EX084 probability/control reuse."""
from datetime import date
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from czsc_trader.application import create_experiment, ExperimentRequest
from czsc_trader.research_tools.context import ExperimentRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_confirm_execution as base

WORK,OUT=ROOT/'.tmp/s013-conditional-payoff',ROOT/'.tmp/s013-conditional-payoff-result'
read,digest,write,public,put=base.read,base.digest,base.write,base.public,base.put


def check(plan):
    for name,expected in plan['source_files'].items():
        if digest(ROOT/name)!=expected:
            raise ValueError('Frozen source drift: '+name)
    for ref in (*plan['input_references'].values(),plan['continuation_budget_reference']):
        public(ref)
    authority=read(public(plan['continuation_budget_reference']))
    if authority['reserved_experiment_sequence']!=[f'EX{i:03}' for i in range(79,89)]:
        raise ValueError('Exact10round authority')
    quota=read(public(plan['input_references']['prior_budget.json']))
    if (quota['started'],quota['completed'],quota['next_allowed'])!=(7,7,'EX086'):
        raise ValueError('Exact eighth quota slot')


def stage():
    plan=read(OUT/'plan.json')
    check(plan)
    exp=ExperimentRef.from_dict(plan['experiment'])
    refs=read(exp.resolve(ROOT)/'protocols/method_references.json')
    if read(public(refs['plan.json']))!=plan:
        raise ValueError('Published prospective differs')
    return exp,plan


def inputs(plan):
    def frame(key):
        f=pd.read_csv(public(plan['input_references'][key]),index_col='signal_date',float_precision='round_trip')
        f.index=pd.to_datetime(f.index).as_unit('ns')
        return f
    features,labels,prices=frame('features.csv'),frame('labels.csv'),frame('prices.csv')
    labels['label_end_return_4']=pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    axis=features.index
    if len(axis)!=1635 or axis[0]!=pd.Timestamp('2020-01-02') or axis[-1]!=pd.Timestamp('2026-09-29') or not axis.equals(prices.index[1:-1]):
        raise ValueError('Original1635T and native price axis')
    raw_y=prices['open'].shift(-5)/prices['open'].shift(-1)*(.999/1.001)-1
    maturity=pd.Series(prices.index,index=prices.index).shift(-5)
    np.testing.assert_allclose(labels.return_4,raw_y.reindex(axis),atol=2e-13,rtol=2e-11,equal_nan=True)
    np.testing.assert_array_equal(labels.label_end_return_4.to_numpy(),maturity.reindex(axis).to_numpy())
    probabilities,prior=frame('prior_probabilities.csv'),frame('prior_forecasts.csv')
    previous=read(public(plan['input_references']['prior_statistics.json']))
    verification=read(public(plan['input_references']['prior_verification.json']))
    if verification['status']!='PASS' or verification['new_annual_models']!=12:
        raise ValueError('Authenticated EX084 audit unavailable')
    kernel=base.load('payoff_input_definition',WORK/'kernel.py')
    kernel.validate(features,labels,probabilities,prior)
    return features,labels,probabilities,prior,previous


def declare():
    plan=read(WORK/'prospective.json')
    check(plan)
    if read(WORK/'focused_checks.json')['status']!='PASS':
        raise ValueError('Synthetic checks first')
    c=base.common()
    ctx=c.context(1)
    exp=create_experiment(ctx,ExperimentRequest('条件盈亏幅度最小职责对照','保留EX084盈利概率，预测盈利/非盈利幅度而不是使用固定历史均值，是否改善净收益选择及下跌年份余量？',date(2026,10,12)))
    if exp.experiment_id!='EX086_20261012':
        raise ValueError('Exact eighth slot; never allocate again')
    plan={**plan,'experiment':exp.to_dict()}
    OUT.mkdir(parents=True,exist_ok=True)
    write(OUT/'plan.json',plan)
    path=exp.resolve(ROOT)
    write(path/'protocols/plan.json',plan)
    refs={'plan.json':put(ctx,exp,OUT/'plan.json'),'focused_checks.json':put(ctx,exp,WORK/'focused_checks.json')}
    for name in plan['source_files']:
        refs[name]=put(ctx,exp,ROOT/name)
        if (ROOT/name).is_relative_to(ROOT/'.tmp'):
            with (path/'src'/Path(name).name).open('xb') as stream:
                stream.write((ROOT/name).read_bytes())
    write(path/'protocols/method_references.json',refs)
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'slot':8,'new_annual_models_maximum':24,'accounts':0},flush=True)


def study():
    exp,plan=stage()
    write(OUT/'study_attempt.json',{'status':'STARTED','analyze_calls_maximum':1,'new_accounts':0})
    features,labels,probabilities,prior,previous=inputs(plan)
    kernel=base.load('payoff_primary_kernel',WORK/'kernel.py')
    clock=base.load('payoff_frozen_clock',ROOT/plan['clock_source'])
    mag,constants,nets,result=kernel.analyze(features,labels,probabilities,prior,previous,clock)
    for name,f in (('magnitudes.csv',mag),('constant_magnitudes.csv',constants),('forecasts.csv',nets)):
        with (OUT/name).open('x',encoding='utf-8',newline='\n') as stream:
            f.to_csv(stream,index_label='signal_date',float_format='%.17g')
    write(OUT/'statistics.json',result)
    write(OUT/'input_checks.json',{'status':'PASS','signals':len(features),'original14':list(features.columns),
          'original_native_HFQ_OPEN_labels':'PASS','probabilities':'EX084_EXACT','net_controls':'EX084_EXACT',
          'same_annual_train_rows':'EX084_EXACT','numpy_version':np.__version__,'pandas_version':pd.__version__,
          'new_accounts':0,'provider_calls':0,'future_test_count_gate':False})
    write(OUT/'study_complete.json',{'status':'COMPLETE','analyze_calls':1,'new_annual_models':result['new_annual_models'],
          'statistics_sha256':digest(OUT/'statistics.json'),'new_accounts':0})
    c=base.common()
    ctx=c.context(1)
    refs={name:put(ctx,exp,OUT/name) for name in ('magnitudes.csv','constant_magnitudes.csv','forecasts.csv','statistics.json','input_checks.json','study_complete.json')}
    write(exp.resolve(ROOT)/'protocols/result_references.json',refs)
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'status':'STUDY_COMPLETE','new_annual_models':result['new_annual_models'],'accounts':0},flush=True)


def audit():
    exp,plan=stage()
    refs=read(exp.resolve(ROOT)/'protocols/result_references.json')
    features,labels,probabilities,prior,previous=inputs(plan)
    def frame(name):
        f=pd.read_csv(public(refs[name]),index_col='signal_date',float_precision='round_trip')
        f.index=pd.to_datetime(f.index).as_unit('ns')
        return f
    mag,constants,nets=frame('magnitudes.csv'),frame('constant_magnitudes.csv'),frame('forecasts.csv')
    report=read(public(refs['statistics.json']))
    oracle=base.load('payoff_independent_audit',WORK/'audit.py')
    clock=base.load('payoff_frozen_clock_audit',ROOT/plan['clock_audit_source'])
    proof=oracle.verify(features,labels,probabilities,prior,previous,mag,constants,nets,report,clock)
    proof['result_references']=refs
    proof['plan_reference']=read(exp.resolve(ROOT)/'protocols/method_references.json')['plan.json']
    write(OUT/'verification.json',proof)
    c=base.common()
    ref=put(c.context(1),exp,OUT/'verification.json')
    write(exp.resolve(ROOT)/'protocols/audit_reference.json',ref)
    assert not c.SOURCE_CALLS
    print({'status':proof['status'],'annual_models':proof['new_annual_models'],'bootstrap_checks':5000,'accounts':0},flush=True)


if __name__=='__main__':
    {'declare':declare,'study':study,'audit':audit}[sys.argv[1]]()
