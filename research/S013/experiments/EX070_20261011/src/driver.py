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
WORK=ROOT/'.tmp/s013-short-alt'
OLD=ROOT/'research/S013/experiments/EX058_20261011'
NEW_ID='C9070'
EXPECTED='EX070_20261011'
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
    return {'parameters':p,'runtime':{'contract_version':1,'module':'strategy_runtime.strategies.short_alternative_range',
        'qualname':'ShortAlternativeRange','source_files':files,'source_sha256':implementation_sha256(files,source_root=source)}}
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
    assert read(WORK/'synthetic.json')['status']=='PASS'
    assert not (ROOT/'research/S013/assets/candidates'/NEW_ID).exists()
    # Exact source metadata number comparisons, no broad result search.
    base=read(OLD/'protocols/plan.json')['configurations'][0]['payload']['parameters']
    p=base|{'mechanism':ORIGINAL+'_SHORT_ALT','short_confirmation_lookback4':4}
    (old,_),oldref=native(); assert dict(old.strategy.payload['parameters'])==base
    common=oldcommon(); ctx=common.context(1)
    assert read(ROOT/'research/S013/experiments/EX065_20261011/protocols/delivery_validation.json')['status']=='PASS'
    prior=read(ROOT/'research/S013/experiments/EX069_20261011/protocols/verification_references.json')
    for value in prior.values():public(value)
    exp=create_experiment(ctx,ExperimentRequest('四日未上涨替代买入确认的最小完整账户反证',
        '保留C8880原规则，在原空仓资格下OR允许完整历史且正波动的四日未上涨入场，是否改善扣费收益并满足原四门？',date(2026,10,11)))
    write(WORK/'allocated_experiment.json',exp.to_dict())
    if exp.experiment_id!=EXPECTED:raise ValueError('Allocation differs; preserve allocation and stop')
    target=exp.resolve(ROOT)/'src'
    for path in (WORK/'strategy_runtime').rglob('*.py'):
        dest=target/'strategy_runtime'/path.relative_to(WORK/'strategy_runtime'); dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,dest)
    for name in ('driver.py','native_audit.py','synthetic.py','build_source.py','feature_certificate.py','oracle.py','economics_reference.py','account_reference.py'):
        shutil.copyfile(WORK/name,target/name)
    source=target/'strategy_runtime'
    candidate=StrategyCandidate('S013',NEW_ID,runtime_config(source,p),source)
    content=ctx.runtime.identify(candidate,dependencies=old.dependencies).content_sha256
    plan={'experiment':exp.to_dict(),'role':'RSCH','stage':3,'policies':['B0','N_SHORT_ALT'],
        'authorization':'用户2026-10-11认同三约束分析，要求重新设定研究目标并自主研究；root授权单一固定centre反证',
        'objective':'保持原四门，寻求足够且扣费盈利的做多机会，提高收益Q10、降低DDQ90并报告32点逐项/联合达标率；本轮只检验固定中心',
        'economic_targets_unchanged':True,'new_economic_hard_gates':False,
        'hypothesis':'原C8880当前state空仓且原eligible，保留原BODY边界和全部退出优先级；原confirmation_pass OR short_confirmation可入场',
        'short_confirmation':'完整20单日收益和4日端点，volatility20>0，(log(C_T)-log(C_T-4))/(volatility20_T*sqrt(4))<=0；包含持平；无EPS兜底',
        'effective_numeric_parameter_count':14,'original13_numeric_parameters_unchanged':True,
        'new_numeric_parameter':{'name':'short_confirmation_lookback4','center':4,'contract_bounds':[1,20],
            'meaning':'New effective lookback; no perturbation domain or14D design declared in centre-only study'},
        'zero_threshold':'Natural nonpositive prior-return event chosen by hypothesis; no sample quantile or threshold optimization',
        'selection_history':'Seen S013 EX066-069 development evidence; EX069 conditional partial correlation positive clue, augmented models/downside/broad-downmarket yearly returns strong counterevidence; not independent validation',
        'non_claim':'Same current state original-pass branch retained; added entries can change later paths, no guarantee all baseline trades remain',
        'stop':'No threshold/direction/window rescue. If centre fails original four gates, stop without32/stress/new candidate registration. If centre passes, root must prospectively declare all14D perturbation including new4-day parameter before proceeding.',
        'new_account_budget':1,'baseline_reuse':oldref,'baseline_native_cache':str((common.CACHE/'N0.pkl.gz').relative_to(ROOT)).replace('\\','/'),
        'baseline_cache_sha256':digest(common.CACHE/'N0.pkl.gz'),
        'baseline_fivechecks_reuse_reference':read(ROOT/'research/S013/experiments/EX065_20261011/protocols/delivery_reference.json'),
        'observed_component_evidence':prior,'candidate_id':NEW_ID,'content_sha256':content,'payload':candidate.payload,
        'baseline_parameters':base,'input_bindings':{k:v.to_dict() for k,v in old.input_bindings.items()},
        'execution_data_fingerprint':old.execution_data.fingerprint,'provider_revision':'S013-EX058-existing-only',
        'price_basis':'HFQ_RESEARCH','pricing':old.execution_data.pricing.to_dict(),'benchmark':old.benchmark.to_dict(),
        'source_files':{q.relative_to(ROOT).as_posix():digest(q) for q in target.rglob('*.py')},
        'external_source_files':{(OLD/'src/common.py').relative_to(ROOT).as_posix():digest(OLD/'src/common.py')},
        'preflight':'Pure proof then prepare at max_workers1 plus authenticated-source real-prefix/state checks, no account before prospective publication',
        'boundaries':'S013510500.SH original devpool/warmup, no new providers/sealed data/platform/PTE/production/merge/push/tag'}
    # Mapping proxies become a plain frozen payload, never repr.
    plan['payload']=json.loads(json.dumps(dict(candidate.payload),default=dict))
    write(exp.resolve(ROOT)/'protocols/plan.json',plan)
    ref=put(ctx,exp,exp.resolve(ROOT)/'protocols/plan.json','prospective-fixed-centre-method')
    refs={'plan.json':ref,'baseline_native':oldref}
    for path in target.rglob('*.py'):refs[path.relative_to(target).as_posix()]=put(ctx,exp,path)
    refs['synthetic.json']=put(ctx,exp,WORK/'synthetic.json')
    write(exp.resolve(ROOT)/'protocols/plan_reference.json',ref)
    write(exp.resolve(ROOT)/'protocols/prospective_references.json',refs)
    write(WORK/'experiment.json',exp.to_dict())
    assert not common.SOURCE_CALLS
    return {'status':'DECLARED','experiment':exp.experiment_id,'content_sha256':content,'accounts':0}
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
        CandidateDerivationKind.IMPLEMENTATION,{'mechanism':{'before':ORIGINAL,'after':ORIGINAL+'_SHORT_ALT'},
        'short_confirmation_lookback4':{'before':None,'after':4}},read(path/'protocols/plan_reference.json')['sha256'],
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
    ctx,exp,plan,path,request,oldpair=prepared()
    common=oldcommon()
    assert not (WORK/'preflight.json').exists()
    audit=audits()
    baseline=audit.audit(ctx,*oldpair,read(public(plan['baseline_reuse'])),new=False)
    # Disable alternative only in in-memory test to prove exact original-source
    # signals on original real input, never an unreported financial variant.
    pure=load('short_pure_synthetic',path/'src/synthetic.py')
    mod=pure.load_strategy(path/'src/strategy_runtime')
    binding=request.input_bindings['full']
    fetched=ctx.data.fetch(binding.plan.requests['daily'],prepared=binding.prepared)
    assert fetched.ready
    daily=fetched.dataframe.copy()
    sessions=pd.DatetimeIndex(pd.to_datetime(oldpair[1].runs[0].execution.decisions.signal_date)).normalize()
    parameters=ParameterSet(plan['payload']['parameters'])
    model=mod.ShortAlternativeRange(parameters)
    original_short=mod.short_confirmation
    def disabled(c,w):
        val,passed,reason=original_short(c,w)
        return val,pd.Series(False,index=c.index),reason
    mod.short_confirmation=disabled
    disabledhist=model.calculate_history({'daily':daily},sessions)
    oldmod=__import__('_s013_short_prototype.strategies.boundary_bear_recovery_range',fromlist=['BoundaryBearRecoveryRange'])
    oldhist=oldmod.BoundaryBearRecoveryRange(ParameterSet(plan['baseline_parameters'])).calculate_history({'daily':daily},sessions)
    pd.testing.assert_frame_equal(disabledhist[oldhist.columns],oldhist,check_exact=True)
    mod.short_confirmation=original_short
    newhistory=model.calculate_history({'daily':daily},sessions)
    prefix=model.calculate_history({'daily':daily.iloc[:-10]},sessions[sessions<=pd.Timestamp(daily.Date.iloc[-11])])
    pd.testing.assert_frame_equal(prefix,newhistory.loc[prefix.index],check_exact=True)
    # Existing native source reproduction: all stored feature/state fields match.
    olddec=oldpair[1].runs[0].execution.decisions.copy(); olddec.index=sessions
    comparable=[n for n in oldhist.columns if n in olddec]
    for n in comparable:
        left,right=oldhist[n],olddec[n]
        if pd.api.types.is_numeric_dtype(left):
            assert np.array_equal(left.to_numpy(),right.to_numpy(),equal_nan=True),n
        else:
            assert all((a==b) or (pd.isna(a) and pd.isna(b)) for a,b in zip(left,right)),n
    doc={'status':'PASS','max_workers':1,'financial_accounts':0,'prepared_input_requests_calendar_data_original_exact':True,
        'new_prepared_input_bindings':{k:v.to_dict() for k,v in request.input_bindings.items()},
        'baseline_complete_native_audit':baseline,'disabled_short_alt_real_history':'EXACT_EQUAL original C8880 and native original stored columns',
        'real_prefix_causality':'EXACT_EQUAL','baseline_serialization':'EXACT_EQUAL','new_signal_only_differences':int((newhistory.target_position!=oldhist.target_position).sum()),
        'prepared_request_identity':request.strategy.runtime_identity_sha256,'new_content_sha256':plan['content_sha256'],
        'new_parameter_count':14,'new_parameter_plan_status':'NOT_DECLARED_CENTER_ONLY','provider_calls':common.SOURCE_CALLS}
    write(WORK/'preflight.json',doc)
    common.cache_write(WORK/'prepared.pkl.gz',(request,oldpair))
    ref=put(ctx,exp,WORK/'preflight.json'); write(path/'protocols/preflight_reference.json',ref)
    return {'status':'PREFLIGHT_PASS','new_signal_only_differences':doc['new_signal_only_differences'],'new_accounts':0}
def execute():
    exp,plan,path=stage(); common=oldcommon(); ctx=common.context(1)
    assert read(public(read(path/'protocols/preflight_reference.json')))['status']=='PASS'
    assert not (WORK/'execution_started.json').exists()
    request,_=common.cache_read(WORK/'prepared.pkl.gz')
    assert ctx.runtime.identify(request.strategy,dependencies=request.dependencies).content_sha256==plan['content_sha256']
    write(WORK/'execution_started.json',{'status':'INFLIGHT','account_budget':1,'plan_reference':read(path/'protocols/plan_reference.json')})
    result=ctx.evaluation.evaluate(request)
    common.cache_write(WORK/'centre.pkl.gz',(request,result))
    ref=publish_evidence(ctx,EvaluationEvidenceWrite(exp,'short-alternative-full-centre-native',request,result)).to_dict()
    assert serialize_evaluation_evidence(request,result)==read(public(ref))
    write(path/'protocols/centre_reference.json',ref)
    write(WORK/'execution_complete.json',{'status':'COMPLETE','actual_new_accounts':1,'new_32':0,'new_fee':0,'reference':ref,
        'request_hash':result.request_hash,'result_hash':result.result_hash,'cache_sha256':digest(WORK/'centre.pkl.gz')})
    assert not common.SOURCE_CALLS
    return {'status':'NATIVE_FULL_COMPLETE','actual_new_accounts':1,'request_hash':result.request_hash,'result_hash':result.result_hash}
def verify():
    exp,plan,path=stage(); common=oldcommon(); ctx=common.context(1)
    complete=read(WORK/'execution_complete.json')
    assert digest(WORK/'centre.pkl.gz')==complete['cache_sha256']
    pair=common.cache_read(WORK/'centre.pkl.gz')
    report=audits().audit(ctx,*pair,read(public(complete['reference'])),new=True)
    baseline=read(WORK/'preflight.json')['baseline_complete_native_audit']
    report['baseline']=baseline
    run=pair[1].runs[0].execution
    decisions=run.decisions
    altids=set(decisions.loc[decisions.alt_only_entry,'decision_id'])
    altfills=run.fills.loc[run.fills.side.eq('BUY')&run.fills.decision_id.isin(altids)]
    altcycles=set(altfills.cycle_id)
    trade=run.trades.loc[run.trades.cycle_id.isin(altcycles)]
    report['attribution']={'alt_only_opportunity_n':int(decisions.alt_only_opportunity.sum()),'alt_only_signal_entry_n':int(decisions.alt_only_entry.sum()),
        'alt_entry_actual_buy_fill_n':len(altfills),'alt_buy_cycle_n':len(altcycles),'alt_trade_rows':len(trade),
        'fills_columns':list(run.fills.columns),'trades_columns':list(run.trades.columns),
        'meaning':'Group attribution of actual alternative-entry origins, not causal isolated added-trade benefit; later old confirmation entries can change.'}
    # Full ledgers have public identity; simple CSV exports aid readable review.
    for name in ('decisions','orders','fills','account_daily','trades'):
        getattr(run,name).to_csv(WORK/(name+'.csv'),index=False,float_format='%.17g')
    trade.to_csv(WORK/'alternate_origin_trades.csv',index=False,float_format='%.17g')
    report['additional_run_policy']='CENTRE_FAILED_STOP_NO32_NOFEE' if not report['economics']['qualified'] else 'CENTRE_PASSED_WAIT_ROOT14D_PROSPECTIVE_DESIGN'
    report['actual_new_accounts']=1; report['new_perturbations']=0; report['new_fee_accounts']=0
    report['provider_calls']=common.SOURCE_CALLS
    write(WORK/'verification.json',report)
    refs={'centre':complete['reference'],'preflight':read(path/'protocols/preflight_reference.json'),'plan':read(path/'protocols/plan_reference.json')}
    refs['verification.json']=put(ctx,exp,WORK/'verification.json')
    for name in ('decisions','orders','fills','account_daily','trades','alternate_origin_trades'):refs[name+'.csv']=put(ctx,exp,WORK/(name+'.csv'))
    write(path/'protocols/result_references.json',refs)
    print(json.dumps({'status':'INDEPENDENT_NATIVE_PASS','economics':report['economics'],'attribution':report['attribution'],'policy':report['additional_run_policy']},ensure_ascii=False),flush=True)
    return {'status':'INDEPENDENT_NATIVE_PASS','qualified':report['economics']['qualified'],'new_accounts':1}
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=('declare','preflight','execute','verify')); args=parser.parse_args()
    print(json.dumps(globals()[args.action](),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
