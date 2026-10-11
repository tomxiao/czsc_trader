"""EX088 final quota slot: causal entry strength vs exact/matched controls."""
from datetime import date
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from czsc_trader.application import create_experiment,ExperimentRequest
from czsc_trader.research_tools.context import ExperimentRef

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp'))
import s013_confirm_execution as base

WORK,OUT=ROOT/'.tmp/s013-entry-strength',ROOT/'.tmp/s013-entry-strength-result'
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
    if (quota['started'],quota['completed'],quota['next_allowed'])!=(9,9,'EX088'):
        raise ValueError('Exact final quota slot')


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
    labels,prices,all_scores=frame('labels.csv'),frame('prices.csv'),frame('scores.csv')
    labels['label_end_return_4']=pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    expected=tuple(f'{family}_{bits:03b}' for family in ('confirmation','original14') for bits in range(8))
    if tuple(all_scores.columns)!=expected:
        raise ValueError('Exact EX087 source16 columns')
    scores=all_scores.loc[:,['confirmation_110','original14_110']].copy()
    axis=scores.index
    if len(axis)!=1635 or axis[0]!=pd.Timestamp('2020-01-02') or axis[-1]!=pd.Timestamp('2026-09-29') or not axis.equals(prices.index[1:-1]):
        raise ValueError('Original1635T and native price axis')
    raw_y=prices['open'].shift(-5)/prices['open'].shift(-1)*(.999/1.001)-1
    maturity=pd.Series(prices.index,index=prices.index).shift(-5)
    np.testing.assert_allclose(labels.return_4,raw_y.reindex(axis),atol=2e-13,rtol=2e-11,equal_nan=True)
    np.testing.assert_array_equal(labels.label_end_return_4.to_numpy(),maturity.reindex(axis).to_numpy())
    old_audit=read(public(plan['input_references']['prior_verification.json']))
    old_plan=read(public(plan['input_references']['prior_plan.json']))
    if old_audit['status']!='PASS' or old_audit['new_annual_models']!=0 or old_audit['EX084_EX086_controls']!='EXACT':
        raise ValueError('EX087 audit unavailable')
    if old_audit['result_references']['forecasts.csv']!=plan['input_references']['scores.csv'] or old_plan['input_references']['labels.csv']!=plan['input_references']['labels.csv']:
        raise ValueError('Exact audited EX087 score/label lineage differs')
    return scores,labels


def declare():
    plan=read(WORK/'prospective.json')
    check(plan)
    if read(WORK/'focused_checks.json')['status']!='PASS':
        raise ValueError('Synthetic checks first')
    c=base.common()
    ctx=c.context(1)
    exp=create_experiment(ctx,ExperimentRequest('净预测强度与四日机会占用因果对照','当前正净预测超过此前四个交易日实际发布预测，能否减少弱入场占用后续机会并改善净经济余量？',date(2026,10,12)))
    if exp.experiment_id!='EX088_20261012':
        raise ValueError('Exact final slot; never allocate again')
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
    print({'experiment':exp.experiment_id,'slot':10,'new_annual_models':0,'component_accounts':0},flush=True)


def study():
    exp,plan=stage()
    write(OUT/'study_attempt.json',{'status':'STARTED','analyze_calls_maximum':1,'new_annual_models':0,'component_accounts':0})
    scores,labels=inputs(plan)
    kernel=base.load('strength_primary_kernel',WORK/'kernel.py')
    clock=base.load('strength_frozen_clock',ROOT/plan['clock_source'])
    states,signals,result=kernel.analyze(scores,labels,clock)
    prior=read(public(plan['input_references']['prior_statistics.json']))
    for family in kernel.FAMILIES:
        assert result['schedules'][family+'_historical_control']==prior['schedules'][family+'_110']
    for name,f in (('record_states.csv',states),('decision_scores.csv',signals)):
        with (OUT/name).open('x',encoding='utf-8',newline='\n') as stream:
            f.to_csv(stream,index_label='signal_date',float_format='%.17g')
    write(OUT/'statistics.json',result)
    write(OUT/'input_checks.json',{'status':'PASS','signals':len(scores),'original_native_HFQ_OPEN_labels':'PASS',
          'historical_controls':'EX087_EXACT','new_models':0,'new_accounts':0,'provider_calls':0,
          'model_year_boundaries':'issued predictions remain comparable net units; no refit or yearly reset',
          'decision_scores':'eligibility adapter only;zero rejection marker not return forecast',
          'numpy_version':np.__version__,'pandas_version':pd.__version__})
    write(OUT/'study_complete.json',{'status':'COMPLETE','analyze_calls':1,'new_annual_models':0,
          'statistics_sha256':digest(OUT/'statistics.json'),'component_accounts':0})
    c=base.common()
    ctx=c.context(1)
    refs={name:put(ctx,exp,OUT/name) for name in ('record_states.csv','decision_scores.csv','statistics.json','input_checks.json','study_complete.json')}
    write(exp.resolve(ROOT)/'protocols/result_references.json',refs)
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'status':'STUDY_COMPLETE','new_annual_models':0,'component_accounts':0},flush=True)


def audit():
    exp,plan=stage()
    refs=read(exp.resolve(ROOT)/'protocols/result_references.json')
    scores,labels=inputs(plan)
    def frame(key):
        f=pd.read_csv(public(refs[key]),index_col='signal_date',float_precision='round_trip')
        f.index=pd.to_datetime(f.index).as_unit('ns')
        return f
    states,signals=frame('record_states.csv'),frame('decision_scores.csv')
    report=read(public(refs['statistics.json']))
    oracle=base.load('strength_independent_audit',WORK/'audit.py')
    clock=base.load('strength_frozen_clock_audit',ROOT/plan['clock_audit_source'])
    proof=oracle.verify(scores,labels,states,signals,report,clock)
    proof['result_references']=refs
    proof['plan_reference']=read(exp.resolve(ROOT)/'protocols/method_references.json')['plan.json']
    write(OUT/'verification.json',proof)
    c=base.common()
    ref=put(c.context(1),exp,OUT/'verification.json')
    write(exp.resolve(ROOT)/'protocols/audit_reference.json',ref)
    assert not c.SOURCE_CALLS
    print({'status':proof['status'],'new_annual_models':0,'bootstrap_checks':5000,'component_accounts':0},flush=True)


if __name__=='__main__':
    {'declare':declare,'study':study,'audit':audit}[sys.argv[1]]()
