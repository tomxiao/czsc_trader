"""Complete the approved C9380 stage-four review from immutable accounts; no replay."""
from pathlib import Path
import sys
import os
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
SCRATCH=ROOT/'.tmp/s018-c9380-stage4-completion'
SCRATCH.mkdir(parents=True,exist_ok=True)
sys.pycache_prefix=str(SCRATCH/'pycache')
os.environ['TMP']=os.environ['TEMP']=str(SCRATCH)
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'

import argparse
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
import math
from time import perf_counter
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext,create_research_context,load_candidate,get_research_overview,
    create_experiment,ExperimentRequest,publish_evidence,assemble_delivery,validate_experiment)
from czsc_trader.research_tools.equity_replay import materialize_equity,build_equity_assessment
from dataflows import ProviderConfig
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources,canonical_sha256
from strategy_evaluator import (CandidatePerformanceAssessmentRequest,ParameterPerformanceEvidence,
    assessment_benchmark_fingerprint,assess_candidates,compare_candidates)
from strategy_evaluator import research_models as m
from strategy_evaluator.models import ValidationError

MATERIAL=ROOT/'research/S018/materials/c9380_stage4_completion'
OLD=ROOT/'research/S018/experiments/EX064_20261104'
EXP=d.ExperimentRef('S018','EX065_20261104')
WORK=EXP.resolve(ROOT)
OUT=WORK/'others'


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def save(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')


def source(row):
    ref=d.EvidenceRef.from_dict(row['account_ref'])
    path=ref.resolve(ROOT)
    data=path.read_bytes()
    assert sha256(data).hexdigest()==ref.sha256
    envelope=json.loads(data)
    assert envelope['request']['content_sha256']==row['content_hash']
    assert envelope['request']['candidate_id']==row['candidate_id']
    return ref,path,envelope


def fact(row):
    ref,path,envelope=source(row)
    value,=build_equity_assessment(materialize_equity(path.read_bytes(),
        lambda item:(path.parent/(item['sha256']+'.json')).read_bytes()))
    return value,envelope,ref


def setup():
    repo=RepositoryContext.discover(ROOT)
    overview=get_research_overview(repo,d.ResearchBatchRef('S018'))
    print('OVERVIEW',len(overview.experiments),[(x.stage.value,x.revision) for x in overview.deliveries],flush=True)
    center=load_candidate(repo,CandidateKey('S018','C9380'))
    assert center.content_identity.content_sha256=='186dffc6fe4df3aec1638030d7c0f65d594b6c9578593c39b5676796fe3c5d4a'
    context=create_research_context(repo,d.ResearchBatchRef('S018'),providers=ProviderConfig(bindings={},equity_bindings={}),
        execution_spec=center.definition.execution_spec,resources=ExecutionResources(1,1,9380))
    return repo,center,context


def prepare():
    repo,center,context=setup()
    assert not WORK.exists(), 'Existing preparation must be reused, not overwritten.'
    assert create_experiment(context,ExperimentRequest('C9380 stage-four completion',
        'Assess temporal stability, profit concentration, paired uncertainty and research selection bias without new account replays.',date(2026,11,4)))==EXP
    template=read(ROOT/'research/S017/experiments/EX076_20261102/protocols/confirmed_bounded_stage4_v3.json')
    protocol=template['protocol']
    protocol.update(version='s018-c9380-calmar-stage4-v1',baseline_window='MU_DEVELOPMENT',bootstrap_repetitions=10000,
        bootstrap_block_length=21,seed=9380)
    policy=template['policy']
    policy['version']='s018-c9380-stage4-v1'
    targets=template['targets']
    targets['requirements'][0]['lower']['inclusive']=True
    assert targets['requirements'][0]['target_id']=='center-net-calmar'
    value={'scope':['S018-C9380'],'source_candidate_delivery':'CANDIDATES/3','other_492_centers_not_assessed':True,
        'protocol':protocol,'policy':policy,'targets':targets,
        'parameter_plan_ref':read(OLD/'others/recovery_01/parameter_plan_ref.json'),
        'new_account_replays':0,'new_search_points':0,'stage5_authorized':False,
        'method':'Annual and 252-session step21 slices inherit continuous positions and starting NAV. Paired bootstrap10000/block21/seed9380. Family selection diagnostics use all comparable prior search members, never winners only.',
        'incomplete_years':'Show observed partial-year return and annualized rate with explicit YTD label; no full-year extrapolation claim.',
        'underperformance':'Negative paired rolling Calmar difference; consecutive negative windows form a diagnostic run, not independent periods.',
        'known_bias':'Repeated development sample; changing parameter design after research does not restore independence.',
        'user_authorization':['切换RSCH，批准C9380进入阶段四，请你推进','沿用净卡玛（建议）','开始吧','继续'],
        'authorization_context':'The latest continue authorizes the remaining time/concentration/statistical checks after EX064; no stage-five or production action.'}
    save(OUT/'protocol.json',value)
    (WORK/'src/finalize.py').write_bytes(Path(__file__).read_bytes())
    confirmation=publish_evidence(context,d.MaterialEvidenceWrite(EXP,'confirmed-stage4-protocol',
        (OUT/'protocol.json').read_bytes(),'application/json','json'))
    confirmed=d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED,confirmation)
    target_set=m.ResearchTargets.from_dict(targets)
    mandate=d.ResearchMandate((
        d.MandateItem('object',d.MandateItemKind.TRADABLE_SYMBOL,'仅评价用户选定C9380；MU唯一交易标的，SOXX仅观察。',confirmed),
        d.MandateItem('targets',d.MandateItemKind.OBJECTIVE,'沿用S018净卡玛、回撤及双频率门；79点至少65点联合通过，全点绝对风险及费用压力门不变。',confirmed,d.PerformanceRequirement(target_set.requirements)),
        d.MandateItem('frequency_days',d.MandateItemKind.EXECUTION,'实际60交易日闭合交易频率窗口。',confirmed,d.NumericRequirement('frequency_window_days','sessions',60.,60.)),
        d.MandateItem('benchmark',d.MandateItemKind.BENCHMARK,'同数据、窗口、资金、报价及成交规则买持；标准和压力分别匹配成本。',confirmed,d.BenchmarkRequirement(d.EvaluationBenchmark(d.EquityBuyHold(center.definition.execution_spec)))),
        d.MandateItem('data',d.MandateItemKind.DATA_PERMISSION,'2023-01-03至2026-10-30已见开发池，2022预热；MU/SOXX既有数据，无新行情。',confirmed),
        d.MandateItem('resources',d.MandateItemKind.RESOURCE,'本次只复用账户做统计、汇总及发布；0新增账户、0搜索点。',confirmed),
        d.MandateItem('method',d.MandateItemKind.EXECUTION,'参数沿用批准79点；时间、集中性、统计不确定性只报告不另设硬门。单候选不宣称优于其他492候选。',confirmed)))
    report='本约定记录用户已确认的C9380阶段四范围和净卡玛目标；不重设研究目标。参数及压力已有EX064证据，本轮补完其余检查。阶段五、冻结与生产未获授权。'
    assembled=assemble_delivery(repo,d.DeliveryDefinition(d.ResearchBatchRef('S018'),d.DeliveryStage.MANDATE,1),
        d.DeliveryContent(mandate,d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=(confirmation,)))
    assert assembled.validation.status is d.ValidationStatus.PASS
    save(OUT/'mandate_reference.json',assembled.receipt.reference.to_dict())
    save(OUT/'mandate_receipt.json',{'reference':assembled.receipt.reference.to_dict(),'validation':assembled.validation.to_dict(),'confirmation':confirmation.to_dict()})
    print('PREPARED_MANDATE',assembled.receipt.reference.content_sha256,flush=True)


def compute():
    begun=perf_counter()
    protocol=read(OUT/'protocol.json')
    assert not (OUT/'panel.json').exists(), 'Do not silently recompute an already retained assessment.'
    rows=read(OLD/'others/recovery_01/results.json')['accounts']
    plan=d.ParameterEvaluationPlan.from_dict(read(OLD/'others/recovery_01/parameter_plan.json'))
    planref=d.EvidenceRef.from_dict(protocol['parameter_plan_ref'])
    assert planref.resolve(ROOT).read_bytes()==(OLD/'others/recovery_01/parameter_plan.json').read_bytes()
    baseline,envelope,base_ref=fact(rows['CENTER'])
    pressure,stress_envelope,pressure_ref=fact(rows['PRESSURE'])
    assert baseline.candidate==pressure.candidate==plan.design.center
    fingerprint=assessment_benchmark_fingerprint(baseline)
    points=read(OLD/'others/approved_point_set.json')['points']
    projections=[]
    refs=[base_ref,pressure_ref]
    for point,child,index in zip(points,plan.children,plan.design.point_indices,strict=True):
        row=rows[point['id']]
        reference,_,header=source(row)
        req=header['request']
        for key in ('window','history_start','instrument','specification','specification_hash','initial_cash',
                    'input_binding','data_manifest','sources','warmup_bars','benchmark','benchmark_sha256',
                    'frequency_window_days','drawdown_basis','concentration_basis','engine_sources','fee_rate','window_id','scenario_id'):
            assert req[key]==envelope['request'][key], (point['id'],key)
        assert header['data']==envelope['data'] and header['benchmark_ref']==envelope['benchmark_ref']
        assert row['config']==point['parameters']
        assert req['content_sha256']==child.candidate.content_sha256
        binding=d.ParameterEvaluationBinding.from_dict(req['lineage']['parameter_binding'])
        assert binding.plan==planref and binding.point==plan.design.bind_point(index)
        v,b=row['candidate'],row['benchmark']
        projection=ParameterPerformanceEvidence(m.PerformanceFacts(child.candidate,header['evaluation_id'],baseline.scenario_context,
            v['annual'],v['dd'],b['annual'],b['dd'],index),EXP.experiment_id,reference.sha256[:32],header['request_hash'],reference.sha256,
            baseline.context_sha256,baseline.window_id,baseline.scenario_id,baseline.metric_version,baseline.initial_cash,
            baseline.frequency_window_days,fingerprint,baseline.candidate,canonical_sha256(req['lineage']['derivation']),
            m.AssessmentDerivationKind.PARAMETERS,binding.point)
        # The source account belongs to EX064, not this derived analysis experiment.
        projection_dict=projection.to_dict()
        projection_dict['experiment_id']=reference.experiment.experiment_id
        projections.append(ParameterPerformanceEvidence.from_dict(projection_dict))
        refs.append(reference)
    # The compact performance contract admits only center journals. A full research
    # family requires matching noncenter journals and cannot be attached here.
    # Run the public selection-statistic interfaces separately; retain their facts
    # and this explicit boundary instead of rewriting SE's family diagnostics.
    family=None
    base=m.CandidateAssessmentRequest((baseline.candidate,),m.CalmarSelfCheckProtocol.from_dict(protocol['protocol']),
        tuple(m.PerturbationLink(x.parent,x.candidate,1.,x.derivation_sha256,x.parameter_point) for x in projections),
        (baseline,pressure),family_returns=family,parameter_designs=(plan.design,))
    request=CandidatePerformanceAssessmentRequest(base,tuple(projections))
    print('ASSESSING',len(projections),'family',family is not None,flush=True)
    panel=assess_candidates(request)
    save(SCRATCH/'request.json',request.to_dict())
    save(OUT/'panel.json',panel.to_dict())
    save(OUT/'account_references.json',[x.to_dict() for x in refs])
    assert panel.rows[0].parameter_context.valid_points==79
    assert not panel.rows[0].coverage_gaps,panel.rows[0].coverage_gaps
    contract=m.DeclaredPointSetComparisonContract(plan.design.construction_sha256,
        m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05),
            (m.ZeroCenterAbsoluteLimit('add_sector_margin',m.AbsoluteChangeLimit(.0005)),)))
    try:
        comparison_request=m.CalmarComparisonRequest(base.centers,m.ResearchTargets.from_dict(protocol['targets']),panel,
            m.ComparisonPolicy.from_dict(protocol['policy']),(plan.design,),contract)
    except ValidationError as error:
        # Retain a real capability failure. Do not coerce integer axes, change the
        # ranking objective, synthesize a comparison, or publish a false PASS.
        if str(error)!='common comparison requires continuous real axes':
            raise
        save(OUT/'comparison_blocker.json',{'status':'UNSUPPORTED_DECLARED_MIXED_PARAMETER_DESIGN',
            'message':str(error),'location':'strategy_evaluator.research_models.CommonNeighborhoodComparisonContract._scale_signature',
            'varying_integer':'beta_window','fixed_integers':['entry_days','earliest_add','review_after','max_hold'],
            'fixed_category':'add_mode','changed_design':False,'comparison_created':False,
            'assessment_delivery_created':False,'platform_modified':False,'action':'Report current numerical evidence and request DEV scope after completing the authorized research.'})
        save(OUT/'assessment_execution.json',{'status':'PANEL_COMPLETE_COMPARISON_BLOCKED','seconds':perf_counter()-begun,
            'new_account_replays':0,'center_accounts_reused':2,'parameter_account_facts_reused':79,
            'selected_centers':1,'family_returns_attached':False,
            'family_interface_boundary':'Compact performance input admits only center journals; full-family public statistics are separate RSCH evidence, not injected into SE panel.',
            'family_limitations':list(panel.family_limitations),'formal_stage4_delivery':'BLOCKED',
            'source_report':read(OLD/'report_ref.json')['report']})
        print('PANEL_COMPLETE_COMPARISON_BLOCKED',str(error),round(perf_counter()-begun,2),flush=True)
        return
    comparison=compare_candidates(comparison_request)
    result,=comparison.rows
    target,=tuple(x for x in result.target_checks if isinstance(x,m.ParameterNeighborhoodCheck))
    assert (target.required_points,target.valid_points,target.minimum_joint_passes,target.joint_passes)==(79,79,65,79)
    assert result.acceptance_status.value=='PASSED',result
    assert not panel.rows[0].coverage_gaps,panel.rows[0].coverage_gaps
    save(SCRATCH/'request.json',request.to_dict())
    save(OUT/'panel.json',panel.to_dict())
    save(OUT/'comparison_request.json',comparison_request.to_dict())
    save(OUT/'comparison.json',comparison.to_dict())
    save(OUT/'account_references.json',[x.to_dict() for x in refs])
    save(OUT/'assessment_execution.json',{'status':'COMPLETED','seconds':perf_counter()-begun,'new_account_replays':0,
        'center_accounts_reused':2,'parameter_account_facts_reused':79,'selected_centers':1,
        'family_returns_attached':family is not None,
        'family_interface_boundary':'Compact performance input admits only center journals; full-family public statistics are supplied as separate RSCH evidence, not injected into the SE panel.',
        'candidate_acceptance':result.acceptance_status.value,
        'candidate_comparison_status':result.status.value,'parameter_points':79,'joint_passes':79,'required_passes':65,
        'family_limitations':list(panel.family_limitations),'source_report':read(OLD/'report_ref.json')['report']})
    print('ASSESSMENT_COMPUTED',result.acceptance_status.value,result.status.value,round(perf_counter()-begun,2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('prepare','compute'))
    args=parser.parse_args()
    prepare() if args.action=='prepare' else compute()
