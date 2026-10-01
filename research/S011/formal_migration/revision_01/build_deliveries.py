"""Publish S011 stage contracts from authenticated historical and current evidence."""
from dataclasses import replace
from hashlib import sha256
import argparse
import json
from pathlib import Path

import pandas as pd
from research_experiment import load_experiment_input
from strategy_manager import CandidateKey
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m
from czsc_trader.application import RepositoryContext, assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[3]
EX='20261001_S011_EX29'
EXP=REPO/'experiments/S011'/EX
CTX=RepositoryContext.discover(REPO)
HIST=REPO/'research/S011/historical_deliveries/revision_01'

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')

def attach(path, name=None):
    path=Path(path)
    media='application/json' if path.suffix=='.json' else 'text/plain'
    return d.EvidenceFile(path.relative_to(REPO).as_posix(),
        d.EvidenceRef('attachments/'+(name or path.name),sha256(path.read_bytes()).hexdigest(),media))

def closure(ids):
    found={}
    def visit(ex):
        if ex in found:
            return
        root=REPO/'experiments/S011'/ex/'artifacts'
        receipt=read(root/'execution_receipt.json')
        load_experiment_input(root,expected_receipt_sha256=receipt['receipt_sha256'])
        found[ex]=d.ExperimentEvidenceRef(ex,root.relative_to(REPO).as_posix(),receipt['receipt_sha256'],
            d.ExperimentEvidenceUse.CURRENT_EVALUATION if ex==EX else d.ExperimentEvidenceUse.HISTORICAL_REFERENCE)
        for previous,digest in receipt['predecessor_receipts'].items():
            visit(previous)
            assert found[previous].receipt_sha256==digest
    for ex in ids:
        visit(ex)
    return tuple(found[k] for k in sorted(found))

class Deliverable(d.ResearchDeliverable):
    def __init__(self,definition,content):
        self._definition,self.content=definition,content
    @property
    def definition(self):
        return self._definition
    def build(self):
        return self.content

def publish(stage,payload,*,attachments=(),experiments=(),predecessors=(),gaps=(),facts=(),explanations=()):
    definition=d.DeliveryDefinition('S011',stage,1,predecessors,experiments)
    content=d.DeliveryContent(payload,d.DeliveryStatus.PARTIAL if gaps else d.DeliveryStatus.COMPLETE,
        facts,explanations,d.ReproductionSpec(
            '用当前公共validate_delivery验证；复算使用新的实验编号，不覆盖已封存EX29。迁移构建脚本见research/S011/formal_migration/revision_01/build_deliveries.py。',
            (), '原S011权限范围；当前复算经DFLS，历史引用按原回执认证。',
            '原输入逐字节封存；身份和浮点公式版本显式记录。所有研究结果属于已见开发池。'),gaps,attachments)
    receipt=assemble_delivery(CTX,Deliverable(definition,content))
    validation=validate_delivery(CTX,receipt.reference)
    assert validation.status is d.ValidationStatus.PASS,validation
    write(ROOT/(stage.value.lower()+'_receipt.json'),receipt.to_dict())
    print(json.dumps({'stage':stage.value,'status':content.status.value,'validation':validation.status.value,
        'reference':receipt.reference.to_dict()}),flush=True)
    return receipt

def targets():
    return (
        m.ResearchTarget('return_multiple',m.ResearchMetric.NET_ANNUAL_RETURN,lower=m.BenchmarkBound(1.5,True)),
        m.ResearchTarget('positive_if_nonpositive_benchmark',m.ResearchMetric.NET_ANNUAL_RETURN,
            lower=m.ConstantBound(0.,False),when=m.BenchmarkCondition(m.ResearchMetric.NET_ANNUAL_RETURN,m.ComparisonOperator.LE,0.)),
        m.ResearchTarget('excess_if_nonpositive_benchmark',m.ResearchMetric.NET_ANNUAL_RETURN,
            lower=m.BenchmarkBound(1.,False),when=m.BenchmarkCondition(m.ResearchMetric.NET_ANNUAL_RETURN,m.ComparisonOperator.LE,0.)),
        m.ResearchTarget('strict_drawdown',m.ResearchMetric.DRAWDOWN_MAGNITUDE,upper=m.BenchmarkBound(1.,False)),
        m.ResearchTarget('full_frequency',m.ResearchMetric.FULL_SAMPLE_FREQUENCY,lower=m.ConstantBound(4.,True),upper=m.ConstantBound(6.,True)))

def mandate():
    source=ROOT/'confirmed_mandate_source.json'
    if not source.exists():
        handoff=REPO/'research/S011/HANDOFF.md'
        write(source,{'kind':'HISTORICAL_CONFIRMED_MANDATE_TRANSCRIPTION','authority':'USER',
            'source':'research/S011/HANDOFF.md','source_sha256':sha256(handoff.read_bytes()).hexdigest(),
            'source_text':handoff.read_text(encoding='utf-8'),
            'migration_approval':'本会话用户已批准保持原研究目标补齐阶段二、三、四正式交付；本文件为原契约转录，不伪造新的逐项用户引语。',
            'new_economic_gates':False})
    evidence=attach(source)
    confirmation=d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED,evidence.reference)
    t=targets()
    items=(
        d.MandateItem('symbol',d.MandateItemKind.TRADABLE_SYMBOL,'159326.SZ；000300.SH和SPX为输入，不扩大交易标的。',confirmation),
        d.MandateItem('benchmark',d.MandateItemKind.BENCHMARK,'同标的、窗口、资金、执行口径和成本的可执行BuyHold。',confirmation),
        d.MandateItem('horizon',d.MandateItemKind.HORIZON,'完整开发池2025-02-06至2026-09-28；403交易日。',confirmation),
        d.MandateItem('return',d.MandateItemKind.OBJECTIVE,'CAGR≥1.5×基准；基准非正时还须策略为正且高于基准。',confirmation,d.PerformanceRequirement(t[:3])),
        d.MandateItem('drawdown',d.MandateItemKind.CONSTRAINT,'最大回撤幅度严格小于同口径基准。',confirmation,d.PerformanceRequirement((t[3],))),
        d.MandateItem('frequency',d.MandateItemKind.CONSTRAINT,'60×全部闭合交易笔数÷完整样本交易日数在[4,6]内。',confirmation,d.PerformanceRequirement((t[4],))),
        d.MandateItem('frequency_window',d.MandateItemKind.EXECUTION,'全样本交易频率折算为60交易日。',confirmation,d.NumericRequirement('frequency_window_days','sessions',60.,60.)),
        d.MandateItem('execution',d.MandateItemKind.EXECUTION,'初始100万元；lot_size=100；只多不杠杆；LIMIT买、MARKET卖；标准每侧10bp，压力20bp为诊断。',confirmation),
        d.MandateItem('permission',d.MandateItemKind.DATA_PERMISSION,'现有S011数据权限；所有复算均为已见开发池；阶段五、冻结及部署另行推进。',confirmation))
    return publish(d.DeliveryStage.MANDATE,d.ResearchMandate(items),attachments=(evidence,))

def components(mandate_ref):
    ex='20260929_S011_EX12'
    directory=REPO/'experiments/S011'/ex
    receipt=read(directory/'artifacts/execution_receipt.json')
    panel=read(directory/'component_panel.json')
    original=attach(directory/'component_panel.json')
    protocol=attach(directory/'02_design.md','EX12_protocol.md')
    source=attach(directory/'experiment.py','EX12_experiment.py')
    history=attach(HIST/'stage2/delivery.json','historical_stage2.json')
    findings=attach(HIST/'focused_validation.json','historical_validation.json')
    refs=tuple(d.EvidenceRef(f'experiments/{ex}/{name}',receipt['artifact_sha256'][name],'text/csv') for name in
        ('role_evidence.csv','role_folds.csv','definition_checks.csv','full_screening_ledger.csv'))
    entries=[]
    for c in panel['components']:
        entries.append(d.ComponentEntry(c['component_id'],
            d.ExperimentDefinitionRef(ex,receipt['definition_sha256'],receipt['source_sha256'],'experiment.calculate'),
            c['role'],c['primary_evidence']['label'],str(c['horizons_sessions'])+'个交易日',
            '原EX12三段复核、训练均值、固定分组和其他组件控制；完整方法见协议。',
            c['availability'],'信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。',
            '已见开发池内职责限定组件；'+ '; '.join(c['limitations']),
            c['name']+'；'+c['formula']+'；'+ '; '.join(c['supports']),
            (d.ComponentTestResult(c['component_id']+'-ROLE',ex,protocol.reference,d.ComponentTestStatus.SUPPORTED,
                '继承原职责判断，不宣称重新执行组件检验；原无效路线和失败实验见历史台账。',refs),)))
    return publish(d.DeliveryStage.COMPONENTS,d.ComponentPanel(tuple(entries),
        '4个原职责组件完成正式引用迁移。历史执行和当前正式引用分别标识；不增加独立样本，不等于完整策略。'),
        attachments=(original,protocol,source,history,findings),experiments=closure((ex,)),predecessors=(mandate_ref,),
        gaps=('EX12引用的EX01 manifest指纹差异仍未解释；原件和失败验证结果完整保留。',))

def historical_searches():
    table=pd.read_csv(REPO/'research/S011/stage3/iteration_02/all_evaluations.csv')
    assert len(table)==573
    records=[]
    fields=('tail_weight','spx_weight','entry','exit','max_days','lookback','premium')
    failures=read(REPO/'research/S011/stage4/iteration_02/historical_failures.json')
    for ex in ('EX15','EX23','EX22','EX24','EX25'):
        group=table[table.experiment==ex]
        trials=[]
        for row in group.to_dict('records'):
            values=tuple(d.ParameterValue(k,int(row[k]) if k in ('lookback','max_days') else float(row[k])) for k in fields)
            predecessor=None
            if ex=='EX23' and int(row['trial']) in (368,380):
                source_ex='20260930_S011_EX19' if int(row['trial'])==368 else '20260930_S011_EX21'
                failure=next(x for x in failures if x['experiment']==source_ex)
                detail=failure['detail']
                predecessor=source_ex+'-FAILED-T'+str(int(row['trial']))
                old_values=tuple(d.ParameterValue(k,detail['parameters'][k]) for k in fields)
                trials.append(d.SearchTrial(predecessor,old_values,d.SearchTrialStatus.FAILED,detail['error']))
            trials.append(d.SearchTrial(row['reference'],values,d.SearchTrialStatus.COMPLETE,
                '历史账户评价，非本轮新试验；原达标='+str(row['qualified'])+'；参数键和账户去重键见完整573行附件。',
                predecessor_proposal_id=predecessor))
        if ex=='EX23':
            contract=read(REPO/'experiments/S011/20260930_S011_EX23/artifacts/search_contract.json')
            domains=tuple(d.NumericParameterDomain(k,float(v[0]),float(v[1]),step=float(v[2]),integer=k in ('lookback','max_days')) for k,v in contract['space'].items())
            method='Optuna TPESampler多目标；EX19→EX21→EX23继承380条后续完4条，总计384条去重提议'
            version=contract['optuna'];seed=contract['seed'];budget=384
        else:
            # Fixed historical proposal lists are categorical feasible sets, not an inferred continuous search domain.
            values={k:sorted({x.value for t in trials for x in t.parameters if x.name==k}) for k in fields}
            if ex=='EX15':
                values=dict(tail_weight=[.25,.5,.75],spx_weight=[0.,.15,.3],entry=[.1,.2,.3,.4],exit=[-.2,0.,.05],
                    max_days=[1,2,3],lookback=[20,60,120],premium=[0.,.003,.01])
            domains=tuple(d.CategoricalParameterDomain(k,tuple(values[k])) for k in fields)
            method='预登记有限提议集合（含原锚点）；可行联合点以trials及原源码为准，不把笛卡尔积冒称已执行'
            version='archived-source-v1';seed=2026093013 if ex=='EX15' else 2026093000+int(ex[2:]);budget=len(trials)
        records.append(d.SearchRecord(ex,domains,method,version,seed,
            '继承历史单进程执行与检查点；当前迁移不调用Optuna、不再提议参数。',budget,tuple(trials),
            '历史收口：联合搜索后期无新前沿，扩边及入场成交归因闭环；有限空间不证明穷尽。'))
    failure=next(x for x in failures if x['experiment']=='20260930_S011_EX18')
    params=failure['detail']['parameters']
    records.append(d.SearchRecord('EX18_FAILED_PATH',tuple(d.CategoricalParameterDomain(k,(v,)) for k,v in params.items()),
        '历史失败提议的精确参数快照；完整搜索域见原EX18档案','archived-source-v1',None,'原实验停止，当前不重试',None,
        (d.SearchTrial('EX18T001',tuple(d.ParameterValue(k,v) for k,v in params.items()),d.SearchTrialStatus.FAILED,failure['detail']['error']),),
        '技术失败；已完成路径和实验级EX13/EX17启动失败另外附原件，未凭空补写参数提议。'))
    return tuple(records)

def candidates(mandate_ref,component_ref):
    results=read(EXP/'artifacts/migration_results.json')
    inputs=read(EXP/'inputs.json')
    mapping=[];entries=[]
    by_id={x['candidate_id']:x for x in results}
    for spec in inputs['centers']:
        result=by_id['S011-'+spec['candidate_id']]
        identity=d.CandidateIdentityRef(CandidateKey('S011',spec['candidate_id']),result['content_sha256'])
        entries.append(d.CandidateEntry(identity,
            '负向市场/尾盘压力排序与严格前序SPX确认形成短期反转持仓，依据退出阈值或最长持有期限退出；净账户须同时满足原三项目标。',
            '既有阶段四集合迁移；保持参数和实现，对原标准及存在的成本账本作受管复算。',
            (d.EvaluationEvidenceRef(EX,result['attempt_id'],tuple(result['evaluation_ids'])),)))
        mapping.append({'config_id':spec['config_id'],'config_fingerprint':spec['config_fingerprint'],
            'first_reference':spec['first_reference'],'historical_source_root':spec['source_root'],
            'candidate':identity.to_dict(),'attempt_id':result['attempt_id'],'evaluation_ids':result['evaluation_ids']})
    write(ROOT/'identity_mapping.json',mapping)
    attachments=(attach(ROOT/'identity_mapping.json'),attach(HIST/'stage3/delivery.json','historical_stage3.json'),
        attach(REPO/'research/S011/stage3/iteration_02/all_evaluations.csv','historical_573_evaluations.csv'),
        attach(REPO/'research/S011/stage3/iteration_02/summary.json','historical_stage3_summary.json'),
        attach(REPO/'research/S011/stage4/iteration_04/search_ledger.json','historical_search_extension.json'),
        attach(REPO/'research/S011/stage4/iteration_02/historical_failures.json','historical_failures.json'),
        attach(REPO/'research/S011/stage4/iteration_02/trial_events.parquet','historical_trial_events.parquet'),
        attach(REPO/'experiments/S011/20260930_S011_EX23/artifacts/source_trials.json','historical_proposal_inheritance.json'),
        attach(EXP/'inputs.json'),attach(EXP/'registrations.json'),attach(EXP/'artifacts/migration_results.json'))
    payload=d.CandidateSet(tuple(entries),tuple(x.identity.key for x in entries),historical_searches(),
        '完整交接36个已登记配置。原阶段三573评价/559参数/521账户和26达标参数/18达标账户，与后续阶段四36配置范围分列；新135账户仅为复算。历史技术失败及EX14错误预热证据完整保留。')
    return publish(d.DeliveryStage.CANDIDATES,payload,attachments=attachments,experiments=closure((EX,)),
        predecessors=(mandate_ref,component_ref))

def comparison_policy():
    historical=read(REPO/'research/S011/stage4/iteration_04/ranking_policy.json')
    bins=tuple(m.MetricBinSpec(metric,float(x['resolution']),float(x['origin']),m.BinRounding.NEAREST_HALF_UP)
        for metric,x in zip(m.RANKING_METRICS,historical['recommendation_order']))
    variants=[]
    for name,factor,shift in [('fine_10dec',None,False),('finer_half_steps',.5,False),('coarser_double_steps',2.,False),('half_cell_shift',1.,True)]:
        variant=tuple(replace(x,resolution=1e-10 if factor is None else x.resolution*factor,
            origin=x.resolution*factor/2 if shift else 0.) for x in bins)
        variants.append(m.ComparisonVariant(name,variant))
    variants.extend(m.ComparisonVariant(f'priority_swap_{i+1}_{i+2}',bins,i) for i in range(6))
    return m.ComparisonPolicy('S011-iteration04-migrated-v1',bins,m.ParetoBasis.BINNED,m.MissingEvidencePolicy.PREFIX_PARTIAL,tuple(variants))

def assessment(mandate_ref,candidate_ref):
    receipt=read(EXP/'artifacts/execution_receipt.json')
    evidence=[]
    for record in receipt['trace']['evaluations']:
        result=read(EXP/'artifacts'/record['result_artifact']['path'])
        evidence.extend(m.AssessmentEvidence.from_dict(x) for x in result['assessment_evidence'])
    inputs=read(EXP/'inputs.json')
    by_id={x.candidate.candidate_id:x.candidate for x in evidence}
    centers=tuple(by_id['S011-'+x['candidate_id']] for x in inputs['centers'])
    links=[]
    for spec in inputs['neighbors']:
        child=by_id['S011-'+spec['candidate_id']]
        item=next(x for x in evidence if x.candidate==child)
        links.append(m.PerturbationLink(item.parent,child,1.,item.derivation_sha256))
    protocol=m.SelfCheckProtocol('S011-migration-selfcheck-v1','full','standard','fee_20bp',60,1,
        m.QuantileMethod.LINEAR,16,1,5000,20,20261001,1e-6)
    request=m.CandidateAssessmentRequest(centers,protocol,tuple(links),tuple(evidence),
        (m.IncompleteEvaluation(by_id['S011-CFG000193'],'full','fee_20bp',m.IncompleteEvaluationStatus.NOT_RUN,
            '保留原同源码20bp账户缺口，本轮不补测。'),))
    panel=assess_candidates(request)
    compare_request=m.CandidateComparisonRequest(centers,m.ResearchTargets(targets(),60),panel,comparison_policy())
    comparison=compare_candidates(compare_request)
    write(ROOT/'assessment_request.json',request.to_dict())
    write(ROOT/'assessment_panel.json',panel.to_dict())
    write(ROOT/'comparison.json',comparison.to_dict())
    mapping={'S011-'+x['candidate_id']:x['config_id'] for x in inputs['centers']}
    old=read(HIST/'stage4/rankings.json')
    old_by_id={x['config_id']:x for x in old}
    for row in comparison.rows:
        historical=old_by_id[mapping[row.candidate.candidate_id]]
        assert (row.pareto_layer,row.rank_min,row.rank_max,row.rank_in_layer)==(
            historical['pareto_layer'],historical['rank_min'],historical['rank_max'],historical['recommendation_rank']), (row.to_dict(),historical)
    old_pairs=read(REPO/'research/S011/stage4/iteration_04/ranking_explanations.json')['pairs']
    metric_map=dict(zip([x['name'] for x in read(REPO/'research/S011/stage4/iteration_04/ranking_policy.json')['recommendation_order']],m.RANKING_METRICS))
    def identity(p):
        return (mapping[p.candidate_a.candidate_id],mapping[p.candidate_b.candidate_id],p.relation.value,
            None if p.decisive_metric is None else next(k for k,v in metric_map.items() if v is p.decisive_metric))
    def check_pairs(actual,expected):
        assert {identity(x) for x in actual}=={(x['config_a'],x['config_b'],x['relation'],x['decisive_metric']) for x in expected}
    check_pairs(comparison.pairs,old_pairs)
    sensitivities=read(REPO/'research/S011/stage4/iteration_04/ranking_sensitivity.json')
    for variant in comparison.sensitivities:
        check_pairs(variant.pairs,sensitivities[variant.name]['pair_comparisons'])
    write(ROOT/'assessment_request.json',request.to_dict())
    write(ROOT/'assessment_panel.json',panel.to_dict())
    write(ROOT/'comparison.json',comparison.to_dict())
    write(ROOT/'comparison_verification.json',{'status':'PASS','centers':36,'accounts':135,
        'layers':max(x.pareto_layer for x in comparison.rows),'incomparable_pairs':sum(x.relation is m.PairwiseRelation.INCOMPARABLE for x in comparison.pairs),
        'partial_candidates':sum(x.status is m.ComparisonStatus.PARTIALLY_ORDERED for x in comparison.rows),
        'sensitivity_variants':len(comparison.sensitivities),'historical_ranks_and_pairs_preserved':True})
    selected=next(x for x in read(ROOT/'identity_mapping.json') if x['config_id']=='S011-CFG-000621')
    write(ROOT/'historical_selection_mapping.json',{'kind':'HISTORICAL_USER_SELECTION_MAPPING','selected':selected,
        'original_decision':'research/S011/stage4/closeout_01/decision.json','original_within_layer_rank':3,
        'new_research_decision_record_created':False,'stage_five_started':False,
        'meaning':'保留621的历史选择；新交付内容身份待用户审阅，不补造一份已审阅新摘要的决定。'})
    decision=attach(REPO/'research/S011/stage4/closeout_01/decision.json','historical_user_decision.json')
    adverse=attach(REPO/'research/S011/stage4/iteration_04/additional_checks.json','historical_coverage_gaps.json')
    attachments=(decision,adverse,attach(ROOT/'historical_selection_mapping.json'),attach(ROOT/'comparison_verification.json'),
        attach(REPO/'research/S011/stage4/iteration_04/ranking_policy.json','historical_ranking_policy.json'),
        attach(HIST/'stage4/delivery.json','historical_stage4.json'),
        attach(REPO/'research/S011/stage4/iteration_02/family_statistics.json','historical_family_statistics.json'),
        attach(REPO/'research/S011/stage4/iteration_02/bootstrap.parquet','historical_bootstrap.parquet'),
        attach(REPO/'research/S011/stage4/iteration_04/search_ledger.json','historical_statistics_scope.json'))
    bindings=tuple(d.TargetMandateBinding(t.target_id, 'return' if i<3 else 'drawdown' if i==3 else 'frequency') for i,t in enumerate(targets()))
    payload=d.CandidateAssessmentDelivery(candidate_ref,mandate_ref,request,panel,compare_request,comparison,bindings,'frequency_window',
        '保留用户对621的选择及原第一层第3位；收益优先顺序仍为618→624→621→628。迁移不改变风险判断。',
        (decision.reference,adverse.reference),('请审阅621新身份与交付摘要后，确认下一步是否进入阶段五技术检验。',))
    return publish(d.DeliveryStage.ASSESSMENT,payload,attachments=attachments,experiments=closure((EX,)),
        predecessors=(mandate_ref,candidate_ref),gaps=(
            '32配置缺少主联合扰动模块；000193缺同源码成本压力；9对不可比和15配置名次区间保留。',
            '旧PBO/DSR与旧重抽样按原搜索范围引用。新SE区间为当前20日块5000次公式诊断，不扩大历史统计覆盖。',
            'EX01历史manifest引用差异仍未解决；已见开发池与反复选择偏差保持披露。'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--components-only',action='store_true');args=parser.parse_args()
    for path,digest in read(HIST/'sources.json').items():
        assert sha256((REPO/path).read_bytes()).hexdigest()==digest,path
    one=mandate();two=components(one.reference)
    if not args.components_only:
        three=candidates(one.reference,two.reference)
        four=assessment(one.reference,three.reference)
        write(ROOT/'delivery_index.json',{'status':'PUBLISHED_WITH_DISCLOSED_LIMITATIONS',
            'references':[x.reference.to_dict() for x in (one,two,three,four)],'historical_sources_unchanged':502})

if __name__=='__main__':
    main()
