"""Author and publish ASSESSMENT/1; contains no candidate freeze or activation."""
import math
from collections import defaultdict
from hashlib import sha256
from importlib.metadata import version
from strategy_evaluator import (
    CandidateAssessmentRequest, AssessmentPanel, CandidateComparisonRequest,
    CandidateComparison, ResearchMetric,
)
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.application import assemble_delivery, validate_delivery
from phase4_common import RESULTS, ROOT, read, save, source, reference, material, context, d, CODE, PLANS, REPORTS


def percent(value):
    return f'{100*value:.4f}%'


def main():
    research = context(4)
    request = CandidateAssessmentRequest.from_dict(read(RESULTS/'assessment_request.json'))
    panel = AssessmentPanel.from_dict(read(RESULTS/'assessment.json'))
    comparison_request = CandidateComparisonRequest.from_dict(read(RESULTS/'comparison_request.json'))
    comparison = CandidateComparison.from_dict(read(RESULTS/'comparison.json'))
    plan = read(PLANS/'plan.json')
    annual = read(RESULTS/'annual_four_gates.json')['standard_and_stress']
    neighborhood = read(RESULTS/'neighborhood_four_gates.json')
    audit = read(RESULTS/'independent_verification.json')
    assert audit['status'] == 'PASS' and len(request.perturbations) == 80
    refs = {}
    for name, filename in (
        ('stage-four-authorization', PLANS / 'authorization.json'),
        ('stage-four-predeclared-plan', PLANS / 'plan.json'),
        ('stage-four-parameter-lineages', 'lineages.json'), ('stage-four-annual-four-gates', 'annual_four_gates.json'),
        ('stage-four-neighborhood-gates', 'neighborhood_four_gates.json'),
        ('stage-four-independent-verification', 'independent_verification.json'),
        ('stage-four-quality-impact', 'quality_impact.json'),
        ('stage-four-sensitivity', 'sensitivity.json'),
        ('stage-four-se-precheck', 'se_precheck.json'),
    ):
        refs[name] = material(research, name, filename)
    batches = [read(RESULTS/f'batch_{n:02}.json') for n in range(math.ceil(len(plan['cases'])/4))]
    rows = [r for b in batches for r in b['rows']]
    assert len(rows) == 90 and all(r['status'] == 'SUCCEEDED' for r in rows)
    save('coverage.json', {'status': 'COMPLETE', 'requests': 90,
        'parameter_requests': 80, 'stress_requests': 10, 'stress_scenarios': 20,
        'declared_plan_sha256': sha256((PLANS/'plan.json').read_bytes()).hexdigest(),
        'actual_raw_trial_count': 590, 'new_parameter_registrations': 0,
        'records': rows, 'elapsed_evaluation_seconds': sum(b['elapsed_seconds'] for b in batches),
        'infrastructure_precheck': {'result': 'SANDBOX_PIPE_PERMISSION_DENIED',
            'exception': 'PermissionError: [WinError 5] 拒绝访问。',
            'stage': 'ProcessPoolExecutor初始化，计算尚未启动，没有账户结果或evaluation_id',
            'resolution': '获准在沙箱外创建本地研究spawn进程后，首批4点成功；不作为策略评价失败计入族收益。'},
    })
    refs['stage-four-coverage'] = material(research, 'stage-four-coverage', 'coverage.json')
    for row in rows:
        ref = EvidenceRef.from_dict(row['reference'])
        ref.resolve(ROOT)
        refs[ref.name] = ref
    # Source facts remain supplied by the predecessor, avoiding duplicate center publications.
    previous = source('CANDIDATES', 3)
    for name in ('four-gate-loss-diagnostics', 'four-gate-quality-impact',
                 'four-gate-adaptive-attribution', 'four-gate-adaptive-input-control', 'stage-two-data'):
        ref = next(r for r in previous.evidence if r.name == name)
        refs[name] = ref
    sources = {p.name: {'sha256': sha256(p.read_bytes()).hexdigest(),
                        'source': p.read_text(encoding='utf-8')} for p in CODE.glob('*.py')}
    save('reproduction_sources.json', {'files': sources,
        'supporting_source': 'CANDIDATES/3已关联common/economics与AdaptiveRange真实源码、依赖及原数据准备引用',
        'versions': {name: version(name) for name in ('numpy', 'pandas', 'optuna', 'czsc-strategy-evaluator', 'czsc-strategy-runtime')},
        'platform_commit': '24331739', 'platform_changes': '无',
        'resources': plan['resources'], 'data': '仅S013原DFLS资产；无新源、依赖或行情范围',
        'restoration': '保留research/S013/assets/data、准备引用、注册源快照、实验发布证据与交付；缓存不是唯一正式输入',
    })
    refs['stage-four-reproduction-sources'] = material(research, 'stage-four-reproduction-sources', 'reproduction_sources.json')
    metrics = {row.candidate.candidate_id: {x.metric: x.value for x in row.diagnostics} for row in panel.rows}
    ranked = sorted(comparison.rows, key=lambda x: (x.pareto_layer or 999, x.rank_min or 999, x.candidate.candidate_id))
    first = ranked[0]
    first_candidates = [r.candidate.candidate_id for r in ranked
                        if (r.pareto_layer, r.rank_min) == (first.pareto_layer, first.rank_min)]
    risk = {
        'neighborhood_qualified': sum(n['qualified'] for n in neighborhood.values()),
        'neighborhood_count': sum(n['count'] for n in neighborhood.values()),
        'stress20_negative_2023': sum(v['stress_20bp_per_side']['annual']['2023']['return'] <= 0 for v in annual.values()),
        'stress30_negative_2023': sum(v['stress_30bp_per_side']['annual']['2023']['return'] <= 0 for v in annual.values()),
        'bootstrap_crosses_zero': sum(r.uncertainty.lower_95 <= 0 <= r.uncertainty.upper_95 for r in panel.rows),
        'centers': len(panel.rows),
    }
    # This is an explicit RSCH judgment, not an eligibility rule or new economic gate.
    fragile = risk['neighborhood_qualified'] == 0 and risk['stress20_negative_2023'] == risk['centers']
    recommendation = (
        f'建议暂缓进入阶段五，优先回阶段三研究年度盈利余量与成本脆弱性的机制；主政策首位{", ".join(first_candidates)}仍保留原四门资格。'
        if fragile else
        f'主政策首位为{", ".join(first_candidates)}；结合邻域、成本和不确定性证据，请用户选择是否及对哪个精确候选进入阶段五。')
    report = '# S013阶段四：全候选自检与比较\n\n'
    report += (f'已完成全部10个原四门达标候选的标准自检，80个参数联合扰动及10个双成本压力请求全部成功。'
        f'主政策首位为{", ".join(first_candidates)}（帕累托层{first.pareto_layer}，层内位置{first.rank_min}）。'
        '主政策位置来自现有证据和事前比较规则；RSCH对研究充分性与建议负责，平台FULL校验确认交付完整性及确定性复算。\n\n')
    report += (f'研究员建议：{recommendation} 联合扰动四门通过{risk["neighborhood_qualified"]}/{risk["neighborhood_count"]}，'
        f'20bp下2023年失去严格盈利{risk["stress20_negative_2023"]}/10个，30bp下{risk["stress30_negative_2023"]}/10个，'
        f'策略相对基准CAGR差95%区间跨零{risk["bootstrap_crosses_zero"]}/10个。'
        '这些诊断揭示达标余量与证据不确定性，标准场景原四门资格保持；后续阶段由用户决定。\n\n')
    report += '## 原四项资格与价格边界\n\n'
    report += ('全部10个标准中心仍通过整体年化、逐年回撤、平均闭合交易频率及负BuyHold年份严格盈利。'
        '整体年化按252/1636计算，年度收益按实际连续账户计算，年度回撤从初始现金或上一年末权益锚定。'
        '2026仅截至9月30日。压力与邻域通过率用于诊断，不改变标准中心的资格，也不新增硬门。\n\n'
        'MANDATE/5补全已确认的60交易日精确表示，并保留逐年回撤及负基准年盈利原文字硬约束；'
        'SE类型检查覆盖整体CAGR与平均频率，两项年度硬门由关联完整账户独立核验。全窗最大回撤用于排序。'
        '旧MANDATE/4、CANDIDATES/3及原账户保持原件。\n\n'
        '510500.SH，2020-01-02至2026-09-30共1636交易日，初始100万元、100个研究单位整手、基线单侧10bp。'
        '后复权研究价格锚点2019-12-31、因子0.2803，原始0.001网格限价通过每日price_scale转换。'
        'T日信息在T+1执行，基准NextOpenBuyHold(100)共用价格、费用、日历及资本。PTE/SRT执行仍使用未复权价格和真实份额，研究收益不等同真实份额账户收益。\n\n')
    report += '## 主比较与五项自检\n\n'
    report += ('先按净年化收益及全窗回撤两项原始指标做帕累托分层（另一配置两项不差且至少一项更好才构成支配），'
        '再在每层按净年化、全窗回撤、参数收益退化、参数回撤恶化、滚动超额Q10、成本压力损失、收益集中度顺序比较。'
        '收益及退化指标事前精度0.1个百分点，集中度1个百分点，原点0、half-even舍入；频率仅作为门槛。\n\n')
    report += '|候选|帕累托层/层内位|净年化|全窗回撤幅度|参数收益退化|参数回撤恶化|126日超额Q10|20bp年化损失|盈利集中度|邻域四门通过|\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n'
    for r in ranked:
        c = r.candidate.candidate_id
        m = metrics[c]
        interval = str(r.rank_min) if r.rank_min == r.rank_max else f'{r.rank_min}—{r.rank_max}'
        values = [percent(m[k]) for k in (
            ResearchMetric.NET_ANNUAL_RETURN, ResearchMetric.DRAWDOWN_MAGNITUDE,
            ResearchMetric.PARAMETER_RETURN_DEGRADATION, ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
            ResearchMetric.ROLLING_EXCESS_Q10, ResearchMetric.STRESS_ANNUAL_LOSS,
            ResearchMetric.PROFIT_CONCENTRATION)]
        report += f'|{c[5:]}|{r.pareto_layer}/{interval}|'+'|'.join(values)+f'|{neighborhood[c]["qualified"]}/8|\n'
    report += ('\n参数检验每中心8个联合点为种子13产生的4组正反向组合，同时改变11项数值参数；'
        '源码、开关、无值过滤项、限价执行规则与费用固定。收益退化=max(0,中心CAGR−邻域CAGR Q10)，'
        '回撤恶化=max(0,邻域回撤Q90−中心回撤)。8点是有限局部诊断，不能识别单参数因果或代表完整邻域。\n\n'
        '时间稳定性为126交易日配对累计收益差，每21日取窗，共72窗，展示Q10。'
        '盈利集中度为正净损益闭合周期中前ceil(10%)笔的净利润占全部正净利润比例，开放周期单独对账。'
        '成本损失=原单侧10bp CAGR−单侧20bp CAGR，保留负值，实际扣费账本与基准成本同步重算。\n\n')
    report += '## 年度余量与成本压力\n\n'
    report += '|候选|2022实际净收益|2023实际净收益|20bp净年化|20bp的2023收益|30bp净年化|30bp的2023收益|\n|---|---:|---:|---:|---:|---:|---:|\n'
    for r in ranked:
        c = r.candidate.candidate_id
        records = annual[c]
        b, s, t = (records[key] for key in ('baseline', 'stress_20bp_per_side', 'stress_30bp_per_side'))
        report += f'|{c[5:]}|'+ '|'.join(percent(v) for v in (
            b['annual']['2022']['return'], b['annual']['2023']['return'], s['net_cagr'],
            s['annual']['2023']['return'], t['net_cagr'], t['annual']['2023']['return']))+'|\n'
    report += '\n## 统计不确定性、行为分组及排序敏感性\n\n'
    report += '|候选|策略−基准CAGR差95%区间（百分点）|\n|---|---:|\n'
    for row in panel.rows:
        report += f'|{row.candidate.candidate_id[5:]}|{100*row.uncertainty.lower_95:.4f} 至 {100*row.uncertainty.upper_95:.4f}|\n'
    report += ('\n配对平稳区块Bootstrap使用2000次、平均连续块长20日、种子13，策略与基准按同一抽样位置取值。'
        '区间针对CAGR差，保留开发池路径的部分相邻依赖；不是未来收益区间或独立样本外证明。\n\n')
    for diagnostic in panel.family_diagnostics:
        report += f'- {diagnostic.name}：{diagnostic.value if diagnostic.value is not None else diagnostic.reason}；状态{diagnostic.status.value}。\n'
    report += ('\nPBO表示区块组合中，按Sharpe在一半样本选优后，在另一半样本落入后半排名的比例。'
        'DSR衡量考虑试验机会后Sharpe表现的统计证据，原始版按590次计数，有效版按这17列收益的相关性调整。'
        '这些数值不是未来亏损概率或实盘成功率；有效版也不能弥补缺失搜索成员。\n\n')
    report += ('\n族矩阵仅包含阶段三17个正式保留成员，缺少477个其他成功配置、16个UNKNOWN路径及本次80个扰动收益。'
        '原始DSR计数为590=历史510尝试+本次80个扰动，包含未知尝试；仅增加计数不能补足Sharpe分布与相关性。'
        'PBO及有效DSR条件于这个选择后的子集，原始DSR的试验离散度也来自该子集，均不能解释为完整搜索校正或未来成功概率。'
        '族选定成员事前为C0494，PBO内部按Sharpe选择，与最终七项排序不同。\n\n')
    all_groups = defaultdict(list)
    for row in panel.rows:
        assert row.behavior_sha256 is not None
        all_groups[row.behavior_sha256].append(row.candidate.candidate_id)
    report += (f'全部10个配置按公共SE经济哈希对应{len(all_groups)}种标准场景行为，'
               f'其中{len(comparison.behavior_groups)}组含多个配置；保留所有成员身份：\n\n')
    for digest, members in sorted(all_groups.items()):
        report += '- '+ ', '.join(c[5:] for c in sorted(members))+f'；哈希`{digest}`。\n'
    report += ('\n该分组只表示标准场景经济行为相同；各中心的参数邻域仍分别评价，不跨成员补证。'
        '例如同组成员可因实际邻域表现不同而得到不同层内位置。共同机制和重复行为不构成多个独立发现。\n')
    report += '\n精度变化和六个相邻优先级交换均事前声明；下表展示每个敏感性规则首层首位，原主比较不改写：\n\n'
    report += '|规则|首层首位|\n|---|---|\n'
    for variant in comparison.sensitivities:
        ordered = sorted(variant.rows, key=lambda r: (r.pareto_layer or 999, r.rank_min or 999))
        head = ordered[0]
        members = [r.candidate.candidate_id[5:] for r in ordered if (r.pareto_layer, r.rank_min) == (head.pareto_layer, head.rank_min)]
        report += f'|{variant.name}|{", ".join(members)}|\n'
    report += '\n## 研究员判断与下一步\n\n'
    report += ('原四门达标说明这些配置在当前扣费后开发池满足用户要求；阶段四需要结合盈利余量、联合扰动与压力结果判断证据强度。'
        '2023标准盈利仅约0.3%—0.55%，2024利润集中、2025明显落后基准及2026前九个月亏损的反证继续保留。'
        '整个开发池已被反复研究和选择；供应商复权因子历史可得性、未知分钟路径、目标持有起点与实际成交起点差异仍有限制。\n\n')
    quality = read(RESULTS/'quality_impact.json')
    report += (f'对已声明的分钟聚合High/Low残余偏差，逐项检查本次及原中心共{quality["evaluation_coordinates"]}个评价坐标的实际订单；'
        f'发现可能改变成交金额的订单{quality["potential_economic_change_count"]}项。'
        'High偏差不进入可信日线特征，也不被当前BUY LIMIT/SELL MARKET撮合消费。'
        '检验仅覆盖已声明异常，不推断未知分钟轨迹或供应商因子历史发布记录。\n\n')
    report += (recommendation + ' 目前没有回退研究或暂停的执行授权，等待用户决定。'
        '阶段五用于因果/等价/重复性等技术核验，不能消除样本选择偏差或经济脆弱性。用户须明确选择候选；冻结还须另批准精确计划。\n\n')
    report += '## 正式证据与复现\n\n'
    for name in ('stage-four-predeclared-plan', 'stage-four-coverage', 'stage-four-annual-four-gates',
                 'stage-four-neighborhood-gates', 'stage-four-independent-verification',
                 'stage-four-quality-impact',
                 'stage-four-reproduction-sources', 'four-gate-loss-diagnostics', 'four-gate-quality-impact'):
        ref = refs[name]
        report += f'- [{name}](../../../assets/deliveries/ASSESSMENT/1/{ref.path})，SHA256 `{ref.sha256}`。\n'
    report += ('\n新增所有账户通过公开TDR FULL评价及完整事实适配，五项自检/七项比较使用公开SE；'
        '独立复核标准中心四门、七项指标和逐日资金/仓位对账。无需全仓回归；本轮未改变平台代码、数据源、依赖或生产。'
        '没有执行冻结、合并、打tag、推送、同步或部署。正式DFLS资产须与交付一同保留。\n')
    (REPORTS/'report.md').write_text(report, encoding='utf-8', newline='\n')
    bindings = tuple(d.TargetMandateBinding(t.target_id, item.item_id)
        for item in source('MANDATE', 5).payload.items if isinstance(item.requirement, d.PerformanceRequirement)
        for t in item.requirement.targets)
    payload = d.CandidateAssessmentDelivery(reference('CANDIDATES', 3), reference('MANDATE', 5),
        request, panel, comparison_request, comparison, bindings, 'frequency_window_days', 'benchmark',
        recommendation, (refs['stage-four-neighborhood-gates'], refs['stage-four-annual-four-gates'],
                         refs['four-gate-loss-diagnostics'], refs['four-gate-quality-impact']),
        ('用户是否批准进入阶段五并选择精确候选；当前未冻结',
         '若选择后的经济脆弱性不可接受，用户决定回退研究或暂停；不自动新增门槛'))
    receipt = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.ASSESSMENT, 1,
                             (reference('CANDIDATES', 3), reference('MANDATE', 5))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report,
                          evidence=tuple(dict.fromkeys(refs.values()))))
    validation = validate_delivery(research.repository, receipt.reference)
    assert validation.status is d.ValidationStatus.PASS, validation.to_dict()
    save('assessment_reference.json', receipt.reference.to_dict())
    save('assessment_validation.json', validation.to_dict())
    for label, value in (('reference', receipt.reference.to_dict()), ('validation', validation.to_dict())):
        target = ROOT/f'research/S013/materials/stage4_assessment_{label}_20261008.json'
        target.write_text(__import__('json').dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    save('recommendation.json', {'primary_first': first_candidates,
        'recommendation': recommendation, 'risk': risk, 'decision': 'AWAITING_USER_SELECTION'})
    print({'delivery': receipt.reference.to_dict(), 'validation': validation.to_dict(),
           'recommendation': recommendation}, flush=True)


if __name__ == '__main__':
    main()
