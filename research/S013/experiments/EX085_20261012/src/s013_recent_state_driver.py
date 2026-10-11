"""EX085 fixed matched current payoff-state component study and scalar audit."""
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

WORK,OUT=ROOT/'.tmp/s013-recent-payoff-state',ROOT/'.tmp/s013-recent-payoff-state-result'
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
    if (quota['started'],quota['completed'],quota['next_allowed'])!=(6,6,'EX085'):
        raise ValueError('Exact seventh quota slot')


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
    kernel=base.load('recent_state_input_definition',WORK/'kernel.py')
    kernel.validate(features,labels)
    return features,labels


def declare():
    plan=read(WORK/'prospective.json')
    check(plan)
    if read(WORK/'focused_checks.json')['status']!='PASS':
        raise ValueError('Synthetic checks first')
    c=base.common()
    ctx=c.context(1)
    exp=create_experiment(ctx,ExperimentRequest('已成熟近期净机会状态增量检验','近期已结束四日机会的盈利比例和平均净收益，能否增加超出原14项的当前状态信息及净盈利余量？',date(2026,10,12)))
    if exp.experiment_id!='EX085_20261012':
        raise ValueError('Exact seventh slot; never allocate again')
    plan={**plan,'experiment':exp.to_dict()}
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
    print({'experiment':exp.experiment_id,'slot':7,'annual_models_maximum':24,'accounts':0},flush=True)


def study():
    exp,plan=stage()
    write(OUT/'study_attempt.json',{'status':'STARTED','analyze_calls_maximum':1,'new_accounts':0})
    features,labels=inputs(plan)
    kernel=base.load('recent_state_primary_kernel',WORK/'kernel.py')
    logit=base.load('recent_state_frozen_logit',ROOT/plan['logit_source'])
    clock=base.load('recent_state_frozen_clock',ROOT/plan['clock_source'])
    state,probs,nets,result=kernel.analyze(features,labels,logit,clock)
    for name,frame in (('state_features.csv',state),('probabilities.csv',probs),('forecasts.csv',nets)):
        with (OUT/name).open('x',encoding='utf-8',newline='\n') as stream:
            frame.to_csv(stream,index_label='signal_date',float_format='%.17g')
    write(OUT/'statistics.json',result)
    write(OUT/'input_checks.json',{'status':'PASS','signals':len(features),'original14':list(features.columns),
          'state_columns':list(state.columns),'original_native_HFQ_OPEN_labels':'PASS',
          'matured_information_only':'ALL_EXPLICIT_WINDOWS','same_train_rows_in_pairs':True,
          'numpy_version':np.__version__,'pandas_version':pd.__version__,
          'new_accounts':0,'provider_calls':0,'future_test_count_gate':False})
    write(OUT/'study_complete.json',{'status':'COMPLETE','analyze_calls':1,'new_annual_models':result['new_annual_models'],
          'statistics_sha256':digest(OUT/'statistics.json'),'new_accounts':0})
    c=base.common()
    ctx=c.context(1)
    refs={name:put(ctx,exp,OUT/name) for name in ('state_features.csv','probabilities.csv','forecasts.csv','statistics.json','input_checks.json','study_complete.json')}
    write(exp.resolve(ROOT)/'protocols/result_references.json',refs)
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'status':'STUDY_COMPLETE','new_annual_models':result['new_annual_models'],'accounts':0},flush=True)


def audit():
    exp,plan=stage()
    refs=read(exp.resolve(ROOT)/'protocols/result_references.json')
    features,labels=inputs(plan)
    def frame(name):
        f=pd.read_csv(public(refs[name]),index_col='signal_date',float_precision='round_trip')
        f.index=pd.to_datetime(f.index).as_unit('ns')
        return f
    state,probs,nets=frame('state_features.csv'),frame('probabilities.csv'),frame('forecasts.csv')
    report=read(public(refs['statistics.json']))
    oracle=base.load('recent_state_independent_audit',WORK/'audit.py')
    clock=base.load('recent_state_frozen_clock_audit',ROOT/plan['clock_audit_source'])
    proof=oracle.verify(features,labels,state,probs,nets,report,clock)
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
