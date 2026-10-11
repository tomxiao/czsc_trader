"""EX070 finite centre-only native contradiction check, no automatic rescue."""
from __future__ import annotations
from dataclasses import replace
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import shutil
import argparse
import numpy as np
import pandas as pd
from strategy_runtime import StrategyCandidate,implementation_sha256,canonical_sha256,ParameterSet
from strategy_manager import CandidateDerivation,CandidateDerivationKind,CandidateEvidence,CandidateKey
from czsc_trader.application import create_experiment,ExperimentRequest,publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite,EvaluationEvidenceWrite,EvaluationLineage
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-overnight-filter'
OLD=ROOT/'research/S013/experiments/EX058_20261011'
NEW_ID='C9072'
EXPECTED='EX072_20261011'
ORIGINAL='RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def digest(p):return sha256(Path(p).read_bytes()).hexdigest()
def write(p,value):
    p=Path(p)
    if p.exists():raise RuntimeError('Immutable output exists: '+str(p))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
def load(name,path):
    if name in sys.modules:
        assert Path(sys.modules[name].__file__).resolve()==path.resolve()
        return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m; spec.loader.exec_module(m); return m
def oldcommon():return load('common',OLD/'src/common.py')
def public(q):
    ref=EvidenceRef.from_dict(q); assert ref.experiment.strategy_id=='S013'; return ref.resolve(ROOT)
def put(ctx,exp,path,name=None):
    path=Path(path); media={'.py':'text/x-python','.csv':'text/csv','.md':'text/markdown'}.get(path.suffix,'application/json')
    return publish_evidence(ctx,MaterialEvidenceWrite(exp,name or path.stem.replace('_','-'),path.read_bytes(),media,path.suffix[1:])).to_dict()
def runtime_config(source,p):
    files=['strategies/'+q.name for q in sorted((source/'strategies').glob('*.py'))]
    return {'parameters':p,'runtime':{'contract_version':1,'module':'strategy_runtime.strategies.overnight_pressure_range',
        'qualname':'OvernightPressureFilteredRange','source_files':files,'source_sha256':implementation_sha256(files,source_root=source)}}
def native():
    common=oldcommon(); pair=common.cache_read(common.CACHE/'N0.pkl.gz')
    ref=common.read(common.RUNS/'account_references.json')['N0']
    assert serialize_evaluation_evidence(*pair)==read(public(ref))
    assert pair[0].strategy.candidate_id=='C8880'
    return pair,ref
def stage():
    exp=ExperimentRef.from_dict(read(WORK/'experiment.json'))
    name=next((n for n in ('effective_plan3','effective_plan2','effective_plan','plan') if (exp.resolve(ROOT)/'protocols'/(n+'.json')).exists()))
    plan=read(exp.resolve(ROOT)/'protocols'/(name+'.json'))
    for path,value in plan['source_files'].items():assert digest(ROOT/path)==value,path
    assert read(public(read(exp.resolve(ROOT)/'protocols'/(name+'_reference.json'))))==plan
    return exp,plan,exp.resolve(ROOT)
def declare():
    assert not (WORK/'experiment.json').exists()
    design=ROOT/'.tmp/s013-entry-risk-budget'
    feasible=read(design/'feasibility_plan.json');proof=read(design/'filter_checks.json')
    assert proof['status']=='PASS' and proof['account_runs']==0
    for rel,h in feasible['source_files_sha256'].items():assert digest(design/rel)==h,rel
    base=read(OLD/'protocols/plan.json')['configurations'][0]['payload']['parameters']
    p=feasible['executable_alternative']['parameters'];assert {k:v for k,v in p.items() if k!='risk_filter'}==base
    assert p['risk_filter']=={'enabled':True,'lookback':4}
    assert not (ROOT/'research/S013/assets/candidates'/NEW_ID).exists()
    assert not (ROOT/'research/registrations/S013/candidates'/(NEW_ID+'.json')).exists()
    (old,_),oldref=native();common=oldcommon();ctx=common.context(1)
    assert implementation_sha256(feasible['executable_alternative']['source_files'],source_root=WORK/'strategy_runtime')==feasible['executable_alternative']['source_sha256']
    for q in (OLD/'src/strategy_runtime').rglob('*.py'):
        assert q.read_bytes()==(WORK/'strategy_runtime'/q.relative_to(OLD/'src/strategy_runtime')).read_bytes()
    for ref in feasible['public_evidence_references'].values():public(ref)
    exp=create_experiment(ctx,ExperimentRequest('隔夜下跌压力主导时拒绝熊市买入的固定账户反证','仅原C8880自身空仓且熊市资格与确认均通过时，此前4完整日隔夜负收益压力大于日内负收益压力便拒绝本次买入，其余规则及退出记忆不变。',date(2026,10,11)))
    write(WORK/'allocated_experiment.json',exp.to_dict())
    assert exp.experiment_id==EXPECTED,'Keep allocation on mismatch; do not reallocate'
    target=exp.resolve(ROOT)/'src';target.mkdir(exist_ok=True)
    shutil.copytree(WORK/'strategy_runtime',target/'strategy_runtime',dirs_exist_ok=True)
    for name in ('driver.py','native_audit.py','feature_certificate.py','oracle.py','economics_reference.py','account_reference.py','build_ex072.py'):
        shutil.copyfile(WORK/name,target/name)
    source=target/'strategy_runtime';candidate=StrategyCandidate('S013',NEW_ID,runtime_config(source,p),source)
    identity=ctx.runtime.identify(candidate,dependencies=old.dependencies)
    plan={'experiment':exp.to_dict(),'role':'RSCH','stage':3,'policies':['B0','N_OVERNIGHT_FILTER'],
      'authorization':'用户自主研究授权；root已科学评审并批准EX072固定中心。中心通过再向root报告，不自动运行32/费用。',
      'scope':'Only S013 original public510500 HFQ development pool/warmup; no provider/new data/DEV/PTE/prod/sealed/merge/push/tag',
      'objective':'原四门保持；提高扰动绝对收益Q10、降低DDQ90，报告32逐项/联合达标率；本阶段只中心。',
      'original_four_gates':['return','annual_drawdown','frequency','negative_buyhold_year_profit'],'new_hard_gates':False,
      'rule':feasible['executable_alternative']['rule'],'memory':feasible['executable_alternative']['memory'],
      'hypothesis':'熊市做多入场的隔夜下跌压力可能提示收益之外的持仓风险，最小职责只是过滤原买入；全池统计不保证实际入场组有效。',
      'strong_counterevidence':feasible['evidence_and_counterarguments'],'observed_evidence':feasible['public_evidence_references'],
      'feasibility_snapshot':feasible,'synthetic_precheck':proof,
      'effective_numeric_parameter_count':14,'new_numeric_parameter':{'name':'risk_filter.lookback','center':4,'whole_domain':[1,20],'type':'INTEGER'},
      'original13_full_domains':read(OLD/'protocols/geometry.json')['coordinates'],
      'if_centre_passes':'Root confirms continuation before freezing actual complete14D standard32/.05/seed13/PCG64/HALF_EVEN and fee. New14D vs old13D not paired or equal per-coordinate intensity. Report integer coverage; no silent neighbours.',
      'stop':'Any original4 FAIL: stop before32/fee/neighbours/optimisation; preserve economic negative result. No threshold/direction/window rescue.',
      'budget':{'maximum_new_financial':34,'centre_current':1,'conditional_standard32':32,'conditional_independent_fee':1,'technical_financial_repeats':0,'neighbours_authorized':0,'baseline_centre_reuse':1},
      'latest_fivechecks':'S013-EX062-five-independent-checks-v1; rolling126/step21; block20 bootstrap2000 seed13; PBO/DSR unavailable not0. No new economic veto.',
      'candidate_id':NEW_ID,'content_sha256':identity.content_sha256,'payload':json.loads(json.dumps(dict(candidate.payload),default=dict)),
      'baseline_parameters':base,'baseline_reuse':oldref,'baseline_native_cache':(common.CACHE/'N0.pkl.gz').relative_to(ROOT).as_posix(),'baseline_cache_sha256':digest(common.CACHE/'N0.pkl.gz'),
      'input_bindings':{k:v.to_dict() for k,v in old.input_bindings.items()},'execution_data_fingerprint':old.execution_data.fingerprint,
      'price_basis':'HFQ_RESEARCH','initial_cash':1000000,'one_way_fee':.001,'pricing':old.execution_data.pricing.to_dict(),'benchmark':old.benchmark.to_dict(),
      'source_files':{q.relative_to(ROOT).as_posix():digest(q) for q in target.rglob('*.py')},
      'external_source_files':{(OLD/'src/common.py').relative_to(ROOT).as_posix():digest(OLD/'src/common.py')},
      'data_provider_revision':'S013-EX058-existing-only','preflight':'maxworkers1; disabled historical every old source/native column exact; enabled causal prefix and independent pressure/state/cash/native audit'}
    write(exp.resolve(ROOT)/'protocols/plan.json',plan)
    ref=put(ctx,exp,exp.resolve(ROOT)/'protocols/plan.json','prospective-fixed-overnight-filter-centre')
    refs={'plan':ref,'baseline_native':oldref}
    for q in target.rglob('*.py'):refs[q.relative_to(target).as_posix()]=put(ctx,exp,q)
    for name in ('feasibility_plan.json','filter_checks.json','filter_checks.py','trigger_audit.json','focused_checks.json'):
        refs[name]=put(ctx,exp,design/name,'preaccount-design-'+name.replace('_','-').replace('.','-'))
    write(exp.resolve(ROOT)/'protocols/plan_reference.json',ref);write(exp.resolve(ROOT)/'protocols/prospective_references.json',refs)
    write(WORK/'experiment.json',exp.to_dict());assert not common.SOURCE_CALLS
    return {'status':'DECLARED','experiment':exp.experiment_id,'content_sha256':identity.content_sha256,'accounts':0}

def audits():
    # Use immutable formal helper code; cache common reducer remains original.
    exp,plan,path=stage()
    sys.path.insert(0,str(path/'src'))
    for n in ('feature_certificate','oracle','economics_reference','account_reference'):
        load(n,path/'src'/f'{n}.py')
    return load('short_native_audit',path/'src/native_audit.py')
def prepared():
    exp,plan,path=stage(); common=oldcommon(); ctx=common.context(1)
    oldpair,ref=native(); old=oldpair[0]
    assert digest(ROOT/plan['baseline_native_cache'])==plan['baseline_cache_sha256']
    source=path/'src/strategy_runtime'
    candidate=StrategyCandidate('S013',plan['candidate_id'],plan['payload'],source)
    identity=ctx.runtime.identify(candidate,dependencies=old.dependencies)
    assert identity.content_sha256==plan['content_sha256']
    parent=ctx.runtime.identify(old.strategy,dependencies=old.dependencies)
    lineage=CandidateDerivation(CandidateKey('S013','C8880'),parent.content_sha256,CandidateKey('S013',NEW_ID),identity.content_sha256,
        CandidateDerivationKind.IMPLEMENTATION,{'risk_filter':{'before':None,'after':{'enabled':True,'lookback':4}}},read(path/'protocols/plan_reference.json')['sha256'],
        CandidateEvidence(EvidenceRef.from_dict(ref).repository_path,ref['sha256']))
    request=replace(old,experiment_id=exp.experiment_id,strategy=candidate,
        runtime_binding={'candidate_id':candidate.reference_id,'source_files':list(candidate.payload['runtime']['source_files']),
        'implementation_sha256':candidate.payload['runtime']['source_sha256']},input_bindings={},lineage=EvaluationLineage(lineage))
    request=ctx.evaluation.prepare(request)
    assert request.execution_data is old.execution_data
    actual={k:v.to_dict() for k,v in request.input_bindings.items()}
    for k,v in actual.items():
        original=plan['input_bindings'][k]
        assert {n:q for n,q in v.items() if n!='plan'}=={n:q for n,q in original.items() if n!='plan'}
        assert {n:q for n,q in v['plan'].items() if n!='strategy'}=={n:q for n,q in original['plan'].items() if n!='strategy'}
        assert v['plan']['strategy']['reference_id']==candidate.reference_id
        definition=ctx.runtime.describe(candidate)
        assert v['plan']['strategy']['runtime_sha256']==definition.runtime_sha256
        assert v['plan']['strategy']['release_hash']==definition.release_hash
    assert not common.SOURCE_CALLS
    return ctx,exp,plan,path,request,oldpair
def preflight():
    ctx,exp,plan,path,request,oldpair=prepared();common=oldcommon();audit=audits()
    assert not (WORK/'preflight.json').exists()
    baseline=audit.audit(ctx,*oldpair,read(public(plan['baseline_reuse'])),new=False)
    import types,importlib
    namespace=types.ModuleType('s013_overnight_preflight');namespace.__path__=[str(path/'src/strategy_runtime')];sys.modules[namespace.__name__]=namespace
    mod=importlib.import_module(namespace.__name__+'.strategies.overnight_pressure_range')
    oldmod=importlib.import_module(namespace.__name__+'.strategies.boundary_bear_recovery_range')
    binding=request.input_bindings['full'];fetched=ctx.data.fetch(binding.plan.requests['daily'],prepared=binding.prepared);assert fetched.ready
    daily=fetched.dataframe.copy();sessions=pd.DatetimeIndex(pd.to_datetime(oldpair[1].runs[0].execution.decisions.signal_date)).normalize()
    p=plan['payload']['parameters'];disabled=mod.OvernightPressureFilteredRange(ParameterSet(p|{'risk_filter':{'enabled':False,'lookback':4}}))
    hist=disabled.calculate_history({'daily':daily},sessions);oldhist=oldmod.BoundaryBearRecoveryRange(ParameterSet(plan['baseline_parameters'])).calculate_history({'daily':daily},sessions)
    pd.testing.assert_frame_equal(hist[oldhist.columns],oldhist,check_exact=True)
    olddec=oldpair[1].runs[0].execution.decisions.copy();olddec.index=sessions
    comparable=[n for n in oldhist.columns if n in olddec]
    for n in comparable:
        left,right=oldhist[n],olddec[n]
        if pd.api.types.is_numeric_dtype(left):assert np.array_equal(left.to_numpy(),right.to_numpy(),equal_nan=True),n
        else:assert all((a==b) or (pd.isna(a) and pd.isna(b)) for a,b in zip(left,right)),n
    model=mod.OvernightPressureFilteredRange(ParameterSet(p));newhist=model.calculate_history({'daily':daily},sessions)
    prefix=model.calculate_history({'daily':daily.iloc[:-10]},sessions[sessions<=pd.Timestamp(daily.Date.iloc[-11])]);pd.testing.assert_frame_equal(prefix,newhist.loc[prefix.index],check_exact=True)
    doc={'status':'PASS','financial_accounts':0,'max_workers':1,'baseline_complete_native_audit':baseline,'disabled_historical_signal_count':len(hist),'disabled_original_source_old_columns_exact':True,'disabled_native_old_columns_exact':comparable,'enabled_real_prefix_exact':True,'enabled_ownpath_rejections':int(newhist.pressure_gate_rejected.sum()),'new_signal_target_difference_n':int((newhist.target_position!=oldhist.target_position).sum()),'input_bindings':{k:v.to_dict() for k,v in request.input_bindings.items()},'provider_calls':common.SOURCE_CALLS}
    write(WORK/'preflight.json',doc);common.cache_write(WORK/'prepared.pkl.gz',(request,oldpair));ref=put(ctx,exp,WORK/'preflight.json');write(path/'protocols/preflight_reference.json',ref)
    assert not common.SOURCE_CALLS
    return {'status':'PREFLIGHT_PASS','financial_accounts':0,'disabled_original_signal_count':len(hist),'enabled_rejections':doc['enabled_ownpath_rejections']}

def execute():
    exp,plan,path=stage(); common=oldcommon(); ctx=common.context(1)
    assert read(public(read(path/'protocols/preflight_reference.json')))['status']=='PASS'
    assert not (WORK/'execution_started.json').exists()
    request,_=common.cache_read(WORK/'prepared.pkl.gz')
    assert ctx.runtime.identify(request.strategy,dependencies=request.dependencies).content_sha256==plan['content_sha256']
    write(WORK/'execution_started.json',{'status':'INFLIGHT','account_budget':1,'plan_reference':read(path/'protocols/plan_reference.json')})
    result=ctx.evaluation.evaluate(request)
    common.cache_write(WORK/'centre.pkl.gz',(request,result))
    ref=publish_evidence(ctx,EvaluationEvidenceWrite(exp,'overnight-filter-full-centre-native',request,result)).to_dict()
    assert serialize_evaluation_evidence(request,result)==read(public(ref))
    write(path/'protocols/centre_reference.json',ref)
    write(WORK/'execution_complete.json',{'status':'COMPLETE','actual_new_accounts':1,'new_32':0,'new_fee':0,'reference':ref,
        'request_hash':result.request_hash,'result_hash':result.result_hash,'cache_sha256':digest(WORK/'centre.pkl.gz')})
    assert not common.SOURCE_CALLS
    return {'status':'NATIVE_FULL_COMPLETE','actual_new_accounts':1,'request_hash':result.request_hash,'result_hash':result.result_hash}
def verify():
    exp,plan,path=stage();common=oldcommon();ctx=common.context(1);complete=read(WORK/'execution_complete.json')
    assert digest(WORK/'centre.pkl.gz')==complete['cache_sha256'];pair=common.cache_read(WORK/'centre.pkl.gz')
    report=audits().audit(ctx,*pair,read(public(complete['reference'])),new=True)
    baseline=read(WORK/'preflight.json')['baseline_complete_native_audit'];report['baseline']=baseline
    run=pair[1].runs[0].execution;d=run.decisions
    report['raw_counts']={'signal_days':len(d),'pressure_dominant_all_days':int(d.pressure_dominant.sum()),'own_flat_bear_pressure_rejected':int(d.pressure_gate_rejected.sum()),'signal_buy_entries':int(d.signal_reason.eq('entry').sum()),'actual_buy_fills':int(run.fills.side.eq('BUY').sum()),'actual_sell_fills':int(run.fills.side.eq('SELL').sum()),'closed_trades':len(run.trades)}
    report['raw_rejection_dates']=[str(x) for x in d.loc[d.pressure_gate_rejected,'signal_date']]
    report['interpretation']='Rejections alter later state/exit memory and actual cash paths. Old15 static triggers do not predict actual trade frequency. No hypothetical future group-profit selection.'
    report['stop_policy']='ANY_ORIGINAL4_FAIL_STOP_NO32_NOFEE_NONEIGHBOUR' if not report['economics']['qualified'] else 'CENTRE_PASS_WAIT_ROOT_CONFIRMATION_BEFORE32_FEE'
    report['counts']={'new_financial':1,'new_standard32':0,'new_fee':0,'new_neighbours':0,'baseline_reuse':1,'technical_financial_repeats':0}
    report['provider_calls']=common.SOURCE_CALLS
    refs={'centre':complete['reference'],'preflight':read(path/'protocols/preflight_reference.json'),'plan':read(path/'protocols/plan_reference.json')}
    for name in ('decisions','orders','fills','account_daily','trades'):
        getattr(run,name).to_csv(WORK/(name+'.csv'),index=False,float_format='%.17g');refs[name+'.csv']=put(ctx,exp,WORK/(name+'.csv'))
    write(WORK/'verification.json',report);refs['verification']=put(ctx,exp,WORK/'verification.json');write(path/'protocols/result_references.json',refs)
    assert not common.SOURCE_CALLS
    return {'status':'NATIVE_INDEPENDENT_AUDIT_PASS','economics':report['economics'],'baseline_economics':baseline['economics'],'raw_counts':report['raw_counts'],'stop_policy':report['stop_policy']}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=('declare','preflight','execute','verify')); args=parser.parse_args()
    print(json.dumps(globals()[args.action](),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
