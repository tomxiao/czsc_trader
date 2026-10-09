"""Publish all-center assessment revision; selection and freezing remain human gates."""
from collections import defaultdict
from hashlib import sha256
from importlib.metadata import version
import argparse
from strategy_evaluator import CandidateAssessmentRequest, AssessmentPanel, CandidateComparisonRequest, CandidateComparison, ResearchMetric
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import EvidenceRef
from common import ROOT, RUNS, PROTOCOLS, REPORTS, SRC, d, read, write, material, source, reference, context
from package_controls import control_materials

METRICS = (ResearchMetric.NET_ANNUAL_RETURN, ResearchMetric.DRAWDOWN_MAGNITUDE,
    ResearchMetric.PARAMETER_RETURN_DEGRADATION, ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
    ResearchMetric.ROLLING_EXCESS_Q10, ResearchMetric.STRESS_ANNUAL_LOSS, ResearchMetric.PROFIT_CONCENTRATION)

def pct(value):
    return f'{100*value:.4f}%'

def positions(rows):
    return sorted(rows,key=lambda r:(r.pareto_layer or 999,r.rank_min or 999,r.candidate.candidate_id))

def leaders(rows):
    ordered=positions(rows)
    head=ordered[0]
    return [r.candidate.candidate_id for r in ordered if (r.pareto_layer,r.rank_min)==(head.pareto_layer,head.rank_min)]

def evidence_link(ref):
    assert ref.repository_path.startswith('research/S013/assets/')
    return '../../../assets/'+ref.repository_path.removeprefix('research/S013/assets/')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args()
    research=context(4)
    if args.validate_only:
        receipt_ref=d.DeliveryReference.from_dict(read(RUNS/'assessment_reference.json'))
        validation=validate_delivery(research.repository,receipt_ref)
        write(RUNS/'assessment_validation.json',validation.to_dict())
        assert validation.status is d.ValidationStatus.PASS,validation.to_dict()
        write(ROOT/'research/S013/materials/stage4_assessment_20261010.json',
            {'status':'PASS','reference':receipt_ref.to_dict(),'validation':validation.to_dict(),
             'coverage':{'centers':79,'perturbations':632,'stress_requests':79,'new_coordinates':790,'total_coordinates':869},
             'next_step':'等待用户选择阶段五精确候选；尚未冻结'})
        print({'validation':validation.to_dict(),'reference':receipt_ref.to_dict()},flush=True)
        return
    plan=read(PROTOCOLS/'plan.json')
    requests=read(RUNS/'rows.json')['rows']
    assert len(requests)==711 and all(r['status']=='SUCCEEDED' for r in requests)
    audit=read(RUNS/'independent_verification.json')
    quality=read(RUNS/'quality_impact.json')
    binding_controls=read(RUNS/'binding_controls.json')
    assert audit['status']=='PASS' and quality['evaluation_coordinates']==869 and binding_controls['status']=='PASS'
    req=CandidateAssessmentRequest.from_dict(read(RUNS/'assessment_request.json'))
    panel=AssessmentPanel.from_dict(read(RUNS/'assessment.json'))
    compare_req=CandidateComparisonRequest.from_dict(read(RUNS/'comparison_request.json'))
    comparison=CandidateComparison.from_dict(read(RUNS/'comparison.json'))
    assert len(req.centers)==len(panel.rows)==79 and len(req.perturbations)==632
    annual=read(RUNS/'annual_four_gates.json')['standard_and_stress']
    neighborhoods=read(RUNS/'neighborhood_four_gates.json')
    ranked=positions(comparison.rows)
    primary=leaders(comparison.rows)
    metrics={r.candidate.candidate_id:{x.metric:x.value for x in r.diagnostics} for r in panel.rows}
    groups=defaultdict(list)
    for row in panel.rows:
        assert row.behavior_sha256 is not None
        groups[row.behavior_sha256].append(row.candidate.candidate_id)
    risk={
        'centers':79,'behavior_groups':len(groups),
        'neighborhood_qualified':sum(x['qualified'] for x in neighborhoods.values()),'neighborhood_count':632,
        'stress20_four_gate_qualified':sum(x['stress_20bp_per_side']['qualified'] for x in annual.values()),
        'stress30_four_gate_qualified':sum(x['stress_30bp_per_side']['qualified'] for x in annual.values()),
        'stress20_positive_negative_benchmark_years':sum(x['stress_20bp_per_side']['gates']['negative_buyhold_year_profit'] for x in annual.values()),
        'bootstrap_crosses_zero':sum(r.uncertainty.lower_95<=0<=r.uncertainty.upper_95 for r in panel.rows),
        'quality_potentially_affected_coordinates':quality['potential_economic_change_count']}
    recommendation=(f'按事前主政策，优先候选为{", ".join(c[5:] for c in primary)}；如用户决定继续技术核验，'
        '建议选择C2132与C3107作为整体收益和2023防守两种取舍的对照，或明确选择其中一个。'
        '632个联合扰动和20bp压力下均没有四门全过，尚无参数稳健性或独立样本外优势的充分证据，现阶段不建议据此冻结。'
        '这项研究判断不新增资格门：79个标准中心仍全部达标。阶段五及冻结分别等待用户对精确候选和计划的批准。')
    elapsed=sum(read(p)['elapsed_seconds'] for p in [RUNS/'precheck_cases.json',*sorted(RUNS.glob('batch_*.json'))])
    write(RUNS/'coverage.json',{'status':'COMPLETE','source_candidates':plan['source_candidates'],
        'centers':79,'parameter_requests':632,'stress_requests':79,'requests':711,
        'new_evaluation_coordinates':790,'total_evaluation_coordinates':869,'new_parameter_registrations':0,
        'plan_sha256':sha256((PROTOCOLS/'plan.json').read_bytes()).hexdigest(),'records':requests,
        'initial_batch_evaluation_and_publication_seconds':elapsed,
        'parallel_scheduler_wall_seconds_after_serial_control':read(RUNS/'parallel_scheduler.json')['wall_seconds'],'trial_count':1536,
        'supplemental_same_parameter_controls':8,'supplemental_control_status':binding_controls['status'],
        'basis':plan['trial_count_basis'],'source_identity':'every center independently; five exact implementations; no borrowed perturbation'})
    write(RUNS/'reproduction_sources.json',{'files':{p.name:{'sha256':sha256(p.read_bytes()).hexdigest(),
        'source':p.read_text(encoding='utf-8')} for p in SRC.glob('*.py')},
        'versions':{n:version(n) for n in ('numpy','pandas','optuna','czsc-strategy-runtime','czsc-strategy-evaluator')},
        'platform_commit':'3f1feb465524b8f77fa965f2de8096c6a2a5e401','resources':plan['resources'],
        'restoration':'Keep S013 formal data assets, source snapshots, original evidence and linked delivery packages. Temporary pickle caches are reproducible accelerators, not the sole formal input.',
        'scope':'Existing S013 510500.SH pool only; no new acquisition, dependency, platform or production change.'})
    refs={}
    for name,path in (
        ('authorization',PROTOCOLS/'authorization.json'),('plan',PROTOCOLS/'plan.json'),
        ('center-authentication',RUNS/'center_authentication.json'),('lineages',RUNS/'lineages.json'),
        ('coverage',RUNS/'coverage.json'),('annual-four-gates',RUNS/'annual_four_gates.json'),
        ('neighborhood-four-gates',RUNS/'neighborhood_four_gates.json'),('independent-verification',RUNS/'independent_verification.json'),
        ('quality-impact',RUNS/'quality_impact.json'),('sensitivity',RUNS/'sensitivity.json'),
        ('execution-precheck',RUNS/'execution_precheck.json'),('se-precheck',RUNS/'se_precheck.json'),
        ('scheduler-supplement',PROTOCOLS/'scheduler_supplement.json'),('scheduler-precheck',RUNS/'scheduler_precheck.json'),
        ('parallel-scheduler',RUNS/'parallel_scheduler.json'),
        ('binding-control-plan',PROTOCOLS/'binding_control_plan.json'),('binding-controls',RUNS/'binding_controls.json'),
        ('assembly-failure',RUNS/'assembly_failure.json'),
        ('reproduction-sources',RUNS/'reproduction_sources.json')):
        ref=material('stage4-'+name,path)
        refs[ref.name]=ref
    for row in requests:
        ref=EvidenceRef.from_dict(row['reference'])
        refs[ref.name]=ref
    for ref in control_materials():
        refs[ref.name]=ref
    old_quality=EvidenceRef.from_dict(quality['source'])
    refs[old_quality.name]=old_quality
    report='# S013阶段四：79个达标候选的自检与比较\n\n'
    report+=(f'阶段四已完成。CANDIDATES/6交接的全部79个身份均独立核验，标准场景仍通过原四门，'
        f'632个联合参数扰动与79个双费用压力请求全部成功；790个新评价坐标连同79原基线共869个完整账户。'
        f'七项排序证据齐备，主政策首层首位为{", ".join(c[5:] for c in primary)}。\n\n'
        f'{recommendation}\n\n'
        f'全部身份按标准经济行为对应{len(groups)}组；每个身份先独立自检，再分组展示。'
        '同组不是多次独立发现，也没有共享或代借参数邻域。\n\n')
    report+='## 目标和执行口径\n\n'
    report+=('来源为CANDIDATES/6与MANDATE/5，保持整体净年化至少基准1.5倍、每自然年回撤严格较小、'
        '每60交易日平均至少4笔闭合交易、负基准年份2022/2023实际净收益严格为正四项要求。'
        'SE类型绑定整体年化及60日平均频率，两项年度硬门使用连续账户独立核验。全窗最大回撤用于标准排序，不能替代逐年门。\n\n'
        '510500.SH，2020-01-02至2026-09-30共1636交易日，初始100万元、100个后复权研究单位整手。'
        'T日已知信息在T+1限价买入/市价卖出，只做多、不加杠杆；基线买卖每侧10bp（千分之一）。'
        '基准NextOpenBuyHold(100)共用资本、价格、日历及费用。后复权因子锚点2019-12-31为0.2803；'
        '原始0.001价格网格按每日price_scale映射，2026只计至9月30日。收益是研究单位账户事实。\n\n'
        '年度收益及回撤从初始现金或上一年末权益衔接，频率=闭合笔数×60/1636。'
        '费用压力、扰动通过比例、集中度和统计诊断均不新增经济硬门。\n\n')
    report+='## 主政策结果及选择代价\n\n'
    report+=('先按原始净年化、全窗回撤做帕累托分层：其他配置两项不差且至少一项更好才构成支配。'
        '每层按净年化高、回撤小、参数收益退化小、参数回撤恶化小、滚动超额Q10高、费用损失小、盈利集中度低依次分箱比较。'
        '前项同档才比较后项；频率只作资格门。前六项分箱0.1个百分点，集中度1个百分点，原点0、half-even。'
        'RAW分层与REQUIRE_COMPLETE沿用标准政策；没有加权总分或费用否决。\n\n')
    report+='|候选|层/层内位置|净年化|全窗回撤|参数年化退化|参数回撤恶化|126日超额Q10|20bp年化损失|盈利集中度|邻域四门通过|\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n'
    for r in ranked:
        cid=r.candidate.candidate_id
        pos=str(r.rank_min) if r.rank_min==r.rank_max else f'{r.rank_min}—{r.rank_max}'
        report+=f'|{cid[5:]}|{r.pareto_layer}/{pos}|'+ '|'.join(pct(metrics[cid][k]) for k in METRICS)+f'|{neighborhoods[cid]["qualified"]}/8|\n'
    report+=('\n帕累托层揭示收益与回撤之间的取舍；同层顺序反映事前政策。七指标全部同档则并列，ID仅稳定展示。'
        '全79中心保留，不只送C3107与C2308；全窗高收益的C2132亦获得同样自检。\n\n')
    report+='## 五项自检的含义和覆盖\n\n'
    report+=(f'联合扰动原四门通过{risk["neighborhood_qualified"]}/632。每中心8点为4组正反向、种子13，'
        '基础11维联合尺度：bull/bear区间窗口±15/10日、bull入出阈值±0.025、bear入出阈值±0.002、'
        '两路最大持有±1日、bear ACF±0.025、状态窗±2日、状态阈值±0.0025；'
        'bull ACF非空者另±0.025，启用的基础及机会确认阈值各±0.01。每个实际维度、符号和父子哈希保存在计划中。\n\n'
        '源码、整数状态确认、结构开关、方向、配置、权重、None项与限价溢价保持；固定冷却为0。'
        '确认窗口40..120及RAW固定40的合法域不对称，故窗口固定并披露未覆盖；stable状态带=0保持。'
        '八点是有限局部诊断，不能当成完整参数空间证明或单参数归因。收益退化=max(0,中心CAGR−邻域CAGR Q10)，'
        '回撤恶化=max(0,邻域回撤Q90−中心回撤)，分位数使用LINEAR。\n\n'
        '时间稳定性：126交易日累计收益与同期基准相减，每21日取窗，共72窗，报告10%分位数；低值说明较差时段的相对表现。'
        '盈利集中度：盈利闭合周期中前ceil(10%)笔净利润占全部正净利润的比例，按实际成交及费用计算；不是单笔最大交易占比。'
        '执行敏感性：标准10bp CAGR减去主压力20bp CAGR，保留可能负值；30bp作为补充，基准同场景同步扣费。\n\n')
    report+=('本轮632个扰动中，整体年化门通过0个、年度回撤门通过614个、平均频率门通过484个、负基准年份盈利门通过25个。'
        '全体未能复制四门全过，主要体现整体收益与弱年份盈利对这组联合变化敏感。'
        'C2132邻域CAGR Q10约1.3240%，C3107约1.0944%，较中心明显下降；不能把主榜第一解释为稳健性已得到证明。\n\n'
        '因此另立事前补充协议，保持参数、源码、费用及数据不变，对五种实现和三个重点候选共8点重新绑定输入。'
        '信号及全部经济表、dtype和关系ID结构与原正式基线精确一致，排除了输入重新绑定造成的退化。'
        '控制账户均已成功并发布；首次脚本仅在提取元数据时误把顶层input_bindings放到request_identity下，'
        '随后从同8个已发布原件认证恢复证明，没有重新计算或改写原件。这8点是技术复算，不增加参数试验计数。\n\n')
    report+=('首次正式封装在发布前发现：控制账户与原基线共享经济评价编号，但实验、请求、结果及尝试四个来源字段不同，'
        '不能把控制账户作为同编号的原始基线事实覆盖。其余全部Assessment字段精确相同。'
        '交付保留原基线作为自检输入，将8个已认证控制账户的完整原件和差异证明单独封装为补充材料；'
        '没有修改原账户、排序输入或试验计数。失败及修正明细关联assembly-repair证据。\n\n')
    report+='## 年度盈利与成本压力\n\n'
    report+=(f'20bp下全部原四门通过{risk["stress20_four_gate_qualified"]}/79，2022/2023两年严格盈利仍有'
        f'{risk["stress20_positive_negative_benchmark_years"]}/79；30bp下四门通过{risk["stress30_four_gate_qualified"]}/79。'
        '维持两年正收益是有价值的防守表现，但两年盈利不等于整体年化同时达标；两种事实分别保留。\n\n')
    report+='|候选|基线2022|基线2023|20bp年化|20bp2022|20bp2023|20bp四门通过|30bp年化|30bp2023|\n|---|---:|---:|---:|---:|---:|---|---:|---:|\n'
    for r in ranked:
        cid=r.candidate.candidate_id
        b,s,t=(annual[cid][key] for key in ('baseline','stress_20bp_per_side','stress_30bp_per_side'))
        vals=[b['annual']['2022']['return'],b['annual']['2023']['return'],s['net_cagr'],s['annual']['2022']['return'],s['annual']['2023']['return']]
        report+=f'|{cid[5:]}|'+ '|'.join(pct(v) for v in vals)+f'|{"是" if s["qualified"] else "否"}|{pct(t["net_cagr"])}|{pct(t["annual"]["2023"]["return"])}|\n'
    report+='\n压力下每项通过/失败原因、逐年回撤差额及邻域四门明细都保存在关联证据；没有因压力失败删除标准达标候选。\n\n'
    report+=('关键取舍：C2132标准净年化16.1572%、全窗回撤14.1599%，2023净收益0.2841%；'
        'C3107对应12.7130%、13.6107%和3.6875%。20bp时，C2132整体年化仍有12.2417%并通过整体年化门，'
        '但2023转为−3.7959%；C3107在2022/2023仍为+0.9829%/+0.0636%，是有价值的防守表现，'
        '同时其整体年化8.9963%未到同期基准1.5倍要求，因此不能称压力下四门全过。\n\n')
    report+='## 统计不确定性与选择历史\n\n'
    report+=f'策略相对基准CAGR差的95%区间跨零{risk["bootstrap_crosses_zero"]}/79。配对平稳区块Bootstrap为2000次、平均块长20日、种子13，策略和基准用同一抽样位置。开发池路径区间不是未来收益区间。\n\n'
    report+='|候选|策略−基准CAGR差95%区间（百分点）|\n|---|---:|\n'
    for row in panel.rows:
        report+=f'|{row.candidate.candidate_id[5:]}|{100*row.uncertainty.lower_95:.4f} 至 {100*row.uncertainty.upper_95:.4f}|\n'
    report+='\n'
    for diagnostic in panel.family_diagnostics:
        report+=f'- {diagnostic.name}：{diagnostic.value if diagnostic.value is not None else diagnostic.reason}；{diagnostic.status.value}。\n'
    report+=(f'\n族矩阵仅包含79个交接后达标中心，事前选定上阶段最高CAGR的{plan["family_selected"]}。'
        'PBO在分块的一半按Sharpe选优，观察另一半跌入后半排名的比例；DSR描述考虑试验机会后的Sharpe证据。'
        '二者均不是实盘亏损概率或成功率。\n\n'
        f'{plan["trial_count_basis"]} 原始DSR使用1536计数，有效版本按79列收益相关性修正；'
        '缺少其余成功/失败/未知及632扰动收益路径，样本又经达标选择，增加计数不能补回完整搜索分布。'
        '共同族诊断不参与候选排序。整个原开发池反复用于研究，无独立样本外验证。\n\n')
    report+='## 行为分组与排序敏感性\n\n'
    for digest,members in sorted(groups.items()):
        report+='- '+', '.join(c[5:] for c in sorted(members))+f'；标准行为哈希`{digest}`。\n'
    report+='\n分组保留全部原身份。参数扰动仍各自独立；同经济路径、不同确认字段或源码不证明邻域等价。\n\n'
    report+='|事前敏感性规则|首层首位|\n|---|---|\n'
    for variant in comparison.sensitivities:
        report+=f'|{variant.name}|{", ".join(c[5:] for c in leaders(variant.rows))}|\n'
    report+='\n半/双分箱精度及六个相邻优先级交换只说明政策敏感性，主政策保持原件。\n\n'
    report+='## 验证、限制和下一步\n\n'
    report+=(f'通过公开TDR完整账户评价与SE自检/比较。五类实现传输预检、首完整中心七指标预检通过，'
        '全869账户独立资金/仓位及开放周期对账，79中心七项公式及年度四门独立复核。'
        f'已知分钟聚合High/Low异常的实际订单审计覆盖869坐标，潜在成交影响订单{quality["potential_economic_change_count"]}项；'
        '该检查只覆盖已声明五个异常，不代表未知分钟轨迹或供应商调整因子的历史发布记录已解决。\n\n'
        '高集中度、薄年度余量、费用敏感性及重复使用开发池是选择代价，不是新增资格门。'
        '阶段五只能进一步核验因果可得、执行等价和复现可靠性，不能消除已见样本的选择偏差。'
        f'{recommendation} 当前等待用户选择具体候选；冻结需另审精确计划。\n\n'
        '本轮未修改平台、依赖、数据范围或生产。未执行阶段五、冻结、合并、tag、推送或部署。原交付及登记快照保持。\n\n')
    report+='## 正式关联证据\n\n'
    for name,ref in refs.items():
        if name.startswith('stage4-') and not name.startswith(('stage4-parameters-','stage4-stress-')):
            report+=f'- [{name}]({evidence_link(ref)})，SHA256 `{ref.sha256}`。\n'
    report+='\n完整711请求引用在coverage证据及本交付中。复现须一并保留S013正式数据资产、绑定、候选源码快照、交付和证据，Git及临时pickle缓存不能替代这些资产。\n'
    REPORTS.mkdir(parents=True,exist_ok=True)
    (REPORTS/'report.md').write_text(report,encoding='utf-8',newline='\n')
    write(RUNS/'recommendation.json',{'primary_first':primary,'recommendation':recommendation,'risk':risk,'decision':'AWAITING_USER_SELECTION'})
    bindings=tuple(d.TargetMandateBinding(t.target_id,item.item_id) for item in source('MANDATE',5).payload.items
        if isinstance(item.requirement,d.PerformanceRequirement) for t in item.requirement.targets)
    payload=d.CandidateAssessmentDelivery(reference('CANDIDATES',6),reference('MANDATE',5),req,panel,compare_req,comparison,
        bindings,'frequency_window_days','benchmark',recommendation,
        tuple(refs['stage4-'+n] for n in ('neighborhood-four-gates','annual-four-gates','quality-impact')),
        ('用户选择阶段五精确候选或补证/暂不推进；当前未冻结','冻结须另获对精确版本及计划的批准'))
    print({'assembly':'START','centers':79,'requests':711},flush=True)
    receipt=assemble_delivery(research.repository,d.DeliveryDefinition(research.batch,d.DeliveryStage.ASSESSMENT,2,
        (reference('CANDIDATES',6),reference('MANDATE',5))),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(refs.values())))
    write(RUNS/'assessment_reference.json',receipt.reference.to_dict())
    print({'assembly':'COMPLETE','reference':receipt.reference.to_dict(),'next':'FULL validation'},flush=True)

if __name__=='__main__':
    main()
