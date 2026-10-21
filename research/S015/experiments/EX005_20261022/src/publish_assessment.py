"""Preview, then explicitly publish the completed S015 stage-four assessment.

No account evaluation, market-data request, candidate selection or registration
is performed here. ``preview`` requires completed build_assessment outputs;
``publish`` requires the reviewed preview and unchanged underlying inputs.
"""
import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from common import EROOT, EXPERIMENT, ROOT, WORK, read, save

from czsc_trader.application import (
    RepositoryContext, assemble_delivery, create_research_context,
    publish_evidence, validate_delivery, validate_experiment,
)
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentOutcome, ExperimentReportWrite,
    ExperimentValidationRequest, ExperimentValidationScope,
    MaterialEvidenceWrite, ResearchBatchRef,
)
from czsc_trader.research_tools import delivery as d
from strategy_evaluator import research_models as m


BUILD_FILES = (
    'authenticated_sources.json', 'assessment_request.json', 'assessment_panel.json',
    'comparison_request.json', 'comparison.json', 'summary.json', 'centers.json',
)
RANKED = {'RANKED', 'TIED', 'PARTIALLY_ORDERED'}
DEGENERATE = {'C0030', 'C0062'}
LABELS = {
    'PASSED': '通过', 'FAILED': '未通过', 'NOT_APPLICABLE': '不适用',
    'INDETERMINATE': '证据不足', 'TARGET_NOT_MET': '目标未通过',
    'INCOMPARABLE': '不可比', 'RANKED': '可排序', 'TIED': '并列',
    'PARTIALLY_ORDERED': '部分有序', 'AVAILABLE': '可用',
    'INSUFFICIENT_DATA': '证据不足',
}


def short(candidate):
    return candidate.candidate_id.removeprefix('S015-')


def pct(value, digits=3):
    return '—' if value is None else f'{100 * value:.{digits}f}%'


def pp(value):
    return '—' if value is None else f'{100 * value:.3f}'


def clean(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def metric(assessment, name):
    found = [item for item in assessment.diagnostics if item.metric.value == name]
    if len(found) != 1:
        raise ValueError(f'{short(assessment.candidate)}: missing unique metric {name}')
    return found[0]


def value(assessment, name):
    return metric(assessment, name).value


def parameter_check(rank):
    checks = [item for item in rank.target_checks if isinstance(item, m.ParameterGroupCheck)]
    if len(checks) != 1:
        raise ValueError('exactly one complete parameter-group target is required')
    return checks[0]


def stress_status(rank):
    checks = [item for item in rank.target_checks
              if isinstance(item, m.TargetCheck) and item.target.scope.value == 'STRESS']
    if not checks:
        raise ValueError('stress targets are missing')
    statuses = {item.status.value for item in checks}
    if 'FAILED' in statuses:
        return 'FAILED'
    if 'INDETERMINATE' in statuses:
        return 'INDETERMINATE'
    if not statuses.issubset({'PASSED', 'NOT_APPLICABLE'}):
        raise ValueError(f'unexpected stress status: {statuses}')
    return 'PASSED'


def ordered_ranks(comparison):
    return sorted((row for row in comparison.rows if row.status.value in RANKED),
                  key=lambda row: (row.pareto_layer, row.rank_min, row.candidate.candidate_id))


def recommendation(comparison):
    ranked = ordered_ranks(comparison)
    if not ranked:
        return ('本轮没有同时达到完整目标且具备完整可比证据的候选。'
                '建议保留负面与不适用证据，由用户决定补证、调整研究或暂不推进；不进入阶段五。')
    first = ranked[0]
    leading = [short(row.candidate) for row in ranked
               if (row.pareto_layer, row.rank_min) == (first.pareto_layer, first.rank_min)]
    return (f'按事前政策共有{len(ranked)}个候选进入可比排序集合；首层首档为'
            f'{"、".join(leading)}。这是研究建议，不是用户选型；请用户依据收益、回撤和局限'
            '选择进入阶段五的具体候选，或要求补证、暂不推进。'
            '本次优先建议C0031作为首档代表：它与C0200在本池行为和排序上重复，'
            '无需把两者当作两份独立机会。C0204可表达固定减仓的简单选择，'
            'C0307可表达接受较低收益以降低历史回撤的选择；后二者不替换事前排序。')


@dataclass(frozen=True)
class Inputs:
    request: m.CandidateAssessmentRequest
    panel: m.AssessmentPanel
    comparison_request: m.CandidateComparisonRequest
    comparison: m.CandidateComparison
    summary: dict
    sources: dict
    centers: tuple[dict, ...]
    source_candidates: d.DeliveryReference
    source_mandate: d.DeliveryReference
    mandate: d.ResearchMandate


def load_inputs(*, require_final_check=False):
    missing = [name for name in BUILD_FILES if not (WORK / name).is_file()]
    if missing:
        raise RuntimeError(f'Complete run_assessment/build_assessment before publication: {missing}')
    if (read(WORK / 'parallel_tail_state.json')['status'] != 'COMPLETE'
            or not read(WORK / 'parallel_tail_state.json')['boundary_cache_restored']):
        raise RuntimeError('The authorized parallel tail and temporary cache restoration must finish')
    final_check_path = EROOT / 'others/final_checks.json'
    if require_final_check and (not final_check_path.is_file() or read(final_check_path).get('status') != 'PASS'):
        raise RuntimeError('Run independent finalize_checks.py and require final_checks status PASS')
    request = m.CandidateAssessmentRequest.from_dict(read(WORK / 'assessment_request.json'))
    panel = m.AssessmentPanel.from_dict(read(WORK / 'assessment_panel.json'))
    comparison_request = m.CandidateComparisonRequest.from_dict(read(WORK / 'comparison_request.json'))
    comparison = m.CandidateComparison.from_dict(read(WORK / 'comparison.json'))
    summary, sources = read(WORK / 'summary.json'), read(WORK / 'authenticated_sources.json')
    centers = tuple(read(WORK / 'centers.json'))
    if (len(request.centers) != 98 or len(panel.rows) != 98 or len(comparison.rows) != 98
            or len(request.parameter_designs) != 96 or len(request.perturbations) != 3072
            or len(centers) != 98 or set(summary['design_failures']) != DEGENERATE):
        raise ValueError('assessment has not completed the declared 98-center/96-design scope')
    if (summary['assessment_request_sha256'] != request.sha256
            or summary['comparison_request_sha256'] != comparison_request.sha256
            or panel.request_sha256 != request.sha256
            or panel.protocol_sha256 != request.protocol.sha256
            or comparison.request_sha256 != comparison_request.sha256
            or comparison_request.panel != panel
            or set(request.centers) != set(comparison_request.candidates)):
        raise ValueError('saved assessment/comparison identities differ')
    actual_counts = Counter(row.status.value for row in comparison.rows)
    actual_acceptance = Counter(row.acceptance_status.value for row in comparison.rows)
    if dict(actual_counts) != summary['status_counts'] or dict(actual_acceptance) != summary['acceptance_counts']:
        raise ValueError('summary counts differ from typed comparison')
    if (len(sources['accounts']) != len(request.evidence)
            or {row['evaluation_id'] for row in sources['accounts']}
            != {row.evaluation_id for row in request.evidence}
            or len(sources['parameter_plans']) != 96):
        raise ValueError('authenticated source coverage differs from assessment')
    if ({row.candidate for row in panel.rows} != set(request.centers)
            or {row.candidate for row in comparison.rows} != set(request.centers)
            or {row['candidate_id'] for row in centers} != {short(item) for item in request.centers}):
        raise ValueError('center identities differ across saved output tables')
    for row in comparison.rows:
        if short(row.candidate) in DEGENERATE and row.status.value in RANKED:
            raise ValueError('non-applicable center entered recommendation ranking')
    stress = [item for item in request.evidence if item.candidate in request.centers
              and item.scenario_id == 'fee_x2']
    if len(stress) != 98:
        raise ValueError('exactly 98 center pressure accounts required')
    candidates = d.DeliveryReceipt.from_dict(read(
        ROOT / 'research/S015/deliveries/CANDIDATES/2/receipt.json')).reference
    mandate_ref = d.DeliveryReference.from_dict(sources['mandate']['reference'])
    mandate_document = read(ROOT / 'research/S015/assets/deliveries/MANDATE/2/delivery.json')
    mandate = d.ResearchMandate.from_dict(mandate_document['content']['payload'])
    if mandate_ref.stage is not d.DeliveryStage.MANDATE or mandate_ref.revision != 2:
        raise ValueError('unexpected mandate revision')
    return Inputs(request, panel, comparison_request, comparison, summary, sources, centers,
                  candidates, mandate_ref, mandate)


def account_temporal(evidence):
    """Describe a retained continuous account; inherit all historical high watermarks."""
    points = evidence.account
    before, high, records = evidence.initial_cash, evidence.initial_cash, []
    for point in points:
        high = max(high, point.equity)
        records.append({'year': point.session[:4], 'session': point.session,
                        'before': before, 'equity': point.equity,
                        'drawdown': point.equity / high - 1})
        before = point.equity
    annual = []
    for year in sorted({record['year'] for record in records}):
        group = [record for record in records if record['year'] == year]
        annual.append({'year': year, 'return': group[-1]['equity'] / group[0]['before'] - 1,
                       'drawdown': abs(min(record['drawdown'] for record in group))})
    return annual


def report(inputs):
    assessments = {short(row.candidate): row for row in inputs.panel.rows}
    rankings = {short(row.candidate): row for row in inputs.comparison.rows}
    original = {row['candidate_id']: row for row in inputs.centers}
    baseline = {short(item.candidate): item for item in inputs.request.evidence
                if item.candidate in inputs.request.centers and item.scenario_id == 'standard'}
    ranked = ordered_ranks(inputs.comparison)
    accepted = sum(row.acceptance_status.value == 'PASSED' for row in inputs.comparison.rows)
    parameter_passed = sum(parameter_check(row).status.value == 'PASSED' for row in inputs.comparison.rows)
    stress_passed = sum(stress_status(row) == 'PASSED' for row in inputs.comparison.rows)
    ranked_first_layer = [row for row in ranked if row.pareto_layer == 1]
    first_center = inputs.centers[0]
    first_stress = assessments[first_center['candidate_id']].stress_performance
    benchmark_cagr = first_center['benchmark_cagr']
    benchmark_dd = abs(first_center['benchmark_metrics']['max_drawdown'])
    lines = [
        '# S015 阶段四：候选自检、比较与选型建议', '',
        '本阶段已完成全部98个交接候选的自检状态核对；阶段五选型、技术检验及冻结尚未获批。', '',
        f'完整目标通过{accepted}/98个，其中{len(ranked)}个具有完整可比证据并进入排序；'
        f'96个适用中心各完成32点参数检验，{parameter_passed}/96个达到参数目标；'
        f'98个中心均完成费用翻倍压力，{stress_passed}/98个达到压力目标。'
        'C0030、C0062的32点方法不适用，明确保留证据缺口，不按通过处理。', '',
        recommendation(inputs.comparison), '',
        '## 约定、范围和目标', '',
        '[MANDATE/2](../../deliveries/MANDATE/2/report.md)及'
        '[CANDIDATES/2](../../deliveries/CANDIDATES/2/report.md)保持不变。'
        '标的159326.SZ，评价2025-01-02至2026-10-21共434个交易日，'
        '2024-09-09至2024-12-31的75日仅预热。初始10万元、空仓、只做多、无杠杆，'
        '日频T决策、T+1执行；买入限价参考信号收盘上方1%，卖出市价，100份整手、'
        '0.001元价格档位。期末持仓估值，不强制平仓；未闭合尾仓不计交易次数。', '',
        '中心标准费用每侧0.1%。基准正年化时中心年化至少为基准1.5倍，'
        '否则须为正；最大回撤同时不超过基准80%和25%。完整滚动60日共375窗，'
        '闭合交易数中位至少6笔，至少338窗有3笔。闭合周期按真实平仓归属，'
        '补买及部分卖出不拆成额外完整交易。', '',
        f'标准可执行买入持有基准年化{pct(benchmark_cagr, 6)}、回撤{pct(benchmark_dd, 6)}；'
        f'本池中心年化门槛{pct(1.5 * benchmark_cagr, 6)}，相对回撤门{pct(.8 * benchmark_dd, 6)}。'
        f'费用翻倍后的基准年化{pct(None if first_stress is None else first_stress.benchmark_return, 6)}、'
        f'回撤{pct(None if first_stress is None else first_stress.benchmark_drawdown, 6)}，压力条件使用此同场景基准。', '',
        '参数32点至少26点同时满足：基准正年化时策略年化至少1.25倍基准，'
        '否则策略年化为正，且回撤不超过基准90%；全部32点回撤均不超过25%。'
        '参数点不另要求中心交易频率门。压力每侧费用0.2%，中心参数与窗口不变，'
        '策略年化须为正且高于同压力基准，回撤严格小于该基准并不超过25%；'
        '基准回撤为零时策略也须为零。诊断指标没有另设经济硬门。', '',
        '## 参数设计、边界与执行规模', '',
        '事前[协议](protocols/stage4.json)固定种子13、32点、域宽标准化总欧氏距离5%。'
        '不是每个参数各变5%，也不除以维数；边界采用可行域拒绝抽样，不裁剪或按成绩换点。'
        '中心与子点固定源码、结构、窗口、费用、基准及数据身份。', '',
        '参数域为入场[0,0.03]、退出[0,0.02]、整数信号周期[1,20]、相对振幅阈值[0,4]、'
        '绝对振幅阈值[0,2/9]、低仓位[0,1]。相对5日/20日均值比的4为代数上界；'
        '2/9是名义±10%且忽略价格档位取整时的振幅尺度，作为固定研究域，'
        '不声称它是实际价格规则的严格上界。', '',
        '关闭过滤的range_cap=0作为固定类别，不把零附近正值当作同机制微扰；'
        'cycle删除不生效阈值和权重，constant仅保留有效仓位参数；'
        'relative/absolute固定类别和反向标志。entry=0、low_weight=0/1等为单侧边界。'
        '无效参数不加入几何以稀释其他坐标。', '',
        '**持续天数限制：**一个整数日的标准化距离1/19≈5.263%，已经超过5%半径。'
        '所有96个设计中的max_days均保持中心值，本次不能声称验证了±1日稳健性。'
        'C0030、C0062在max_days=1时exit不生效且过滤关闭，仅余entry一个有效连续坐标；'
        '固定半径最多两个不同点，不能形成32点。没有用死坐标、浮点尾差或重复点补足，'
        '也未擅自追加其他半径或离散邻档。两者继续完成压力及其余诊断，但不进入推荐排序。', '',
        '98份中心标准账户经完整身份核对复用；新增参数账户96×32=3072份，'
        '独立中心压力98份，合计3170份。串并行预检查使用其中2份正式账户，'
        '对应3次物理评价，并非额外2个配置；不以正式证据数冒充所有物理重跑次数。'
        f'本次SE请求共关联{len(inputs.request.evidence)}份唯一账户投影，'
        '包含研究族181个原搜索账户与3170份新增账户；不把重叠数据或账户当独立样本。', '',
        '用户在执行中要求增加并行；按[资源补充记录](others/resource_addendum.json)，'
        '在8物理核/16逻辑核上从单组8进程调整为两组各8进程，总评价并发上限16，每进程原生线程仍为1。'
        '初始将前71个中心与后27个中心分开，通过可重建临时请求缓存的边界等待确保范围不重叠。'
        '新增执行器实际完成后段22个中心，余5个因下述系统故障由原执行器续跑。'
        '原研究协议、候选、扰动点、费用及排序不变，'
        '复用全部已发布账户。原始8进程协议保持不可变，资源授权另行留证。', '',
        '前段在C0243首16点的证据发布阶段出现一次Windows WinError6/BrokenProcessPool；'
        '该16点计算成功但没有已发布账户，经完整匹配核对后按原身份明确重试。'
        '错误原件、旧调度源码及[恢复决定](others/recovery_01.json)均已发布留证；'
        '没有替换参数点、改变费用或筛掉失败点。恢复后前段改为每批33个账户以减少进程池启动，'
        '进程上限不变。最终3170份唯一正式场景另含预检查的1次重复计算及本次16次重试，'
        '不能以3170冒充物理评价次数；该系统错误的根因尚未确定。', '',
        '后段在C0400的33项评价请求中再次出现相同句柄错误，首项状态为UNKNOWN，'
        '实际启动或完成数量未留存，不能按33次成功计算计数。经核对没有已发布账户后，'
        '按[第二次恢复决定](others/recovery_02.json)恢复为单组8进程，由原队列复用后段22个已完成中心，'
        '明确重试原C0400请求并完成最后4个中心。没有静默串行或修改平台。'
        '最终结果应同时阅读两次故障原件与恢复记录，不能声称全部账户一次运行成功。', '',
        '## 排序政策与主要对照', '',
        '先核验全部目标与完整证据，只对合格可比集合按原始净年化/回撤做帕累托分层：'
        '收益不低且回撤不大、至少一项更好才支配。层级优先；同层依次比较参数年化Q10、'
        '参数回撤Q90、滚动超额Q10、费用压力年化损失、最大盈利周期贡献，最后比较60日频率中位。'
        '收益/回撤类分箱0.001（0.1个百分点）、集中性0.01、频率1笔，原点0、向下取整。'
        '全部指标同档则并列，候选编号只稳定展示，不破坏并列。', '',
        f'首层有{len(ranked_first_layer)}个候选：'
        + ('、'.join(short(row.candidate) for row in ranked_first_layer) or '无') + '。', '',
        '| 候选 | 层/同层名次 | 中心年化/回撤 | 参数年化Q10/回撤Q90 | 参数收益退化/回撤恶化（百分点） | 滚动超额Q10（百分点） | 压力年化损失（百分点） | 最大盈利周期贡献 | 60日频率中位 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for rank in ranked[:12]:
        row = assessments[short(rank.candidate)]
        lines.append(f'| {short(rank.candidate)} | {rank.pareto_layer}/{rank.rank_min}–{rank.rank_max} | '
                     f'{pct(value(row, "NET_ANNUAL_RETURN"))}/{pct(value(row, "DRAWDOWN_MAGNITUDE"))} | '
                     f'{pct(value(row, "PARAMETER_RETURN_Q10"))}/{pct(value(row, "PARAMETER_DRAWDOWN_Q90"))} | '
                     f'{pp(value(row, "PARAMETER_RETURN_DEGRADATION"))}/{pp(value(row, "PARAMETER_DRAWDOWN_DEGRADATION"))} | '
                     f'{pp(value(row, "ROLLING_EXCESS_Q10"))} | {pp(value(row, "STRESS_ANNUAL_LOSS"))} | '
                     f'{pct(value(row, "PROFIT_CONCENTRATION"))} | {value(row, "FREQUENCY_MEDIAN"):g} |')
    if not ranked:
        lines.append('| 无 | — | — | — | — | — | — | — | — |')
    lines += ['', '上表最多展示前12项；相同层/名次可以并列，完整98项在下表及正式比较证据中。'
              '未通过参数或压力目标的中心不因阶段三收益较高而保留推荐资格。', '',
              '### 选型解释', '',
              'C0031/C0200的中心年化47.933%、回撤15.069%，参数年化Q10为47.700%；'
              'C0201中心年化48.146%虽略高，参数年化Q10为44.076%，因此按事前稳健性优先级位于同层第4。'
              'Q10表示本组32点中偏弱端的年化水平，不是未来收益下限。', '',
              'C0204固定75%目标仓位，中心年化35.182%、回撤11.604%，参数32点全部联合通过，'
              '翻倍费用下年化23.412%；规则简单，但本池收益代价明确。'
              'C0307在50%/100%间按相对振幅调仓，中心年化26.977%、回撤7.845%，'
              '参数31/32联合通过且32/32满足回撤上限，翻倍费用下年化18.385%。'
              '它的中心及压力年化分别仅高于相应最低收益要求约1.57和1.52个百分点，余量较小。', '',
              'C0307相对平均目标仓位匹配的恒定对照C0401，在标准及费用翻倍条件下均保持收益更高、'
              '回撤更低；支持这一已见配置上有限的调仓增量。C0401压力年化17.461%、回撤9.245%，'
              '自身也通过全部目标。该比较没有消除阶段三另一入场锚未复现改善的反证，'
              '也不能推广为振幅普遍有效。', '',
              '## 全部98个中心覆盖', '',
              '参数列为“同一点联合通过数/有效点数”；达标还要求全部点回撤上限通过。'
              '参数NA不是0分或通过。压力数值使用同一中心在0.2%费用下的完整账户；'
              '验收与可比排序状态分别报告。', '',
              '| 候选 | 机制 | 中心年化/回撤 | 60日中位/≥3笔窗口 | 参数联合 | 参数状态 | 压力年化/回撤 | 压力状态 | 总体验收 | 排序层/名次或状态 |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for cid in sorted(rankings):
        rank, row, params = rankings[cid], assessments[cid], original[cid]['parameters']
        group = parameter_check(rank)
        frequency = row.frequency_coverage
        freq_text = f'{value(row, "FREQUENCY_MEDIAN"):g}/' + (
            f'{frequency.covered_windows}/{frequency.total_windows}' if frequency is not None else '—')
        stress = row.stress_performance
        stress_text = '—' if stress is None else f'{pct(stress.annual_return)}/{pct(stress.drawdown)}'
        position = (f'{rank.pareto_layer}/{rank.rank_min}–{rank.rank_max}'
                    if rank.status.value in RANKED else LABELS.get(rank.status.value, rank.status.value))
        mechanism = params['sizing'] if 'sizing' in params else ('旧入口过滤' if params['range_cap'] else '旧无过滤')
        if params.get('reverse'):
            mechanism += '反向'
        lines.append(f'| {cid} | {mechanism} | {pct(value(row, "NET_ANNUAL_RETURN"))}/{pct(value(row, "DRAWDOWN_MAGNITUDE"))} | '
                     f'{freq_text} | {"NA" if cid in DEGENERATE else f"{group.joint_passes}/{group.valid_points}"} | '
                     f'{LABELS.get(group.status.value, group.status.value)} | {stress_text} | '
                     f'{LABELS[stress_status(rank)]} | {LABELS.get(rank.acceptance_status.value, rank.acceptance_status.value)} | {position} |')
    lines += ['', '完整参数、逐点目标、失败原因及缺失原因见正式summary、panel、comparison证据；'
              '未将条件分支不适用（例如基准正收益时的非正分支）误记为失败。', '',
              '## 时间表现、集中性和统计限制', '',
              '全年/片段从原连续账户切片，回撤继承完整账户历史高水位。2025是完整年，'
              '2026仅截至10月21日。252日窗口每21日移动，共9个重叠窗口；'
              '它们不独立，也不能据比例推断未来成功率。收益集中性来自实际完整闭合周期，'
              '包括分次买入和部分卖出；不把盈利周期贡献率当全账户收益占比。', '',
              '| 候选 | 2025收益/继承回撤 | 2026片段收益/继承回撤 | 滚动超额Q10（百分点） | 超额年化95%区间（百分点） |',
              '| --- | --- | --- | --- | --- |']
    representatives = list(dict.fromkeys([short(row.candidate) for row in ranked[:5]]
                                         + ['C0031', 'C0201', 'C0204', 'C0307', 'C0401']))
    for cid in representatives:
        row = assessments[cid]
        annual = account_temporal(baseline[cid])
        interval = row.uncertainty
        if interval.status.value == 'AVAILABLE':
            interval_text = f'[{pp(interval.lower_95)}, {pp(interval.upper_95)}]'
        else:
            interval_text = f'{LABELS.get(interval.status.value, interval.status.value)}：{clean(interval.reason)}'
        years = [f'{pct(item["return"])}/{pct(item["drawdown"])}' for item in annual]
        if len(years) != 2:
            raise ValueError('fixed-window annual slices changed')
        lines.append(f'| {cid} | {years[0]} | {years[1]} | {pp(value(row, "ROLLING_EXCESS_Q10"))} | {interval_text} |')
    family = inputs.summary['family']
    effective = family['effective_trial_count']
    lines += ['', '统计区间采用事前固定的2000次、平均块长10日的配对平稳块重抽样，种子13。'
              '区间描述已见样本和该重抽样假设下的不确定性，不是独立样本证明或投资收益保证；'
              '区间跨零、年度落后或集中度高只作为诊断，本轮未新增否决阈值。', '',
              f'研究族矩阵包含181列×434日，零方差列{family["zero_variance_columns"]}个，'
              f'精确收益路径{family["distinct_exact_return_paths"]}组。有效次数状态'
              f'{effective["status"]}，数值{effective["value"]}；原因{clean(effective["reason"])}。'
              '181是保留账户配置数，不是独立假设数；阶段二1092项特征/标签比较不能直接加成同口径账户次数，'
              '更广的自适应选择历史仍未完全测量。不得把登记候选数当完整搜索次数。', '',
              '| 研究族诊断 | 状态 | 值 | 原因 |', '| --- | --- | --- | --- |']
    for item in inputs.panel.family_diagnostics:
        lines.append(f'| {clean(item.name)} | {LABELS.get(item.status.value, item.status.value)} | '
                     f'{"—" if item.value is None else f"{item.value:.6g}"} | {clean(item.reason or "—")} |')
    lines += ['', 'PBO用于观察重选策略后的过拟合风险，DSR用于解释多次尝试后的Sharpe证据；'
              '均不表示未来获利概率，不参与候选排名或新增验收门。'
              f'DSR诊断列按已见全样本Sharpe选为{family["selected_for_dsr_only"]["candidate_id"]}，'
              '此选择只服务统计诊断，不是阶段四排序或用户选型。重复和零方差列原样保留；'
              '若出现不可用，不通过删掉不利或退化列修复结果。', '',
              '本轮PBO为78.571%：在预声明的10块组合划分中，较多选样段的优胜配置在其余段落落到'
              '较差的一半，提示研究族排名不稳定。这不是某个推荐候选未来亏损概率。'
              '98个中心有97个超额年化95%重抽样区间跨零，全部86个通过目标的候选均在其中；'
              '唯一未跨零的C0108又未通过参数绝对风险要求。数值达标与证据不确定性必须同时呈现，'
              '不能据本阶段宣布已经确认独立超额收益。', '',
              '## 排序敏感性与行为分组', '',
              '| 预声明变体 | 层级/名次/可比状态改变的候选数 |', '| --- | ---: |']
    for variant in inputs.comparison.sensitivities:
        changed = sum((item.status, item.pareto_layer, item.rank_min, item.rank_max)
                      != (rankings[short(item.candidate)].status, rankings[short(item.candidate)].pareto_layer,
                          rankings[short(item.candidate)].rank_min, rankings[short(item.candidate)].rank_max)
                      for item in variant.rows)
        lines.append(f'| {variant.name} | {changed} |')
    lines += ['', '分箱精度减半/加倍及相邻指标优先级交换仅披露敏感性，不回写事前排序。'
              f'平台保留{len(inputs.comparison.behavior_groups)}个同口径行为组；'
              '先逐候选完成检验，再分组展示。相同中心行为未用于跨源码或跨候选替代扰动、费用证据。', '',
              '分箱减半/加倍分别改变2/6个候选的位置，首档仍为C0031/C0200；'
              '若交换参数年化Q10与回撤Q90的先后顺序，79个候选位置变化，首档变为C0307。'
              '这说明首选依赖事前声明的收益与风险取舍，而非存在所有偏好下都最优的策略；'
              '本轮仍严格沿用原排序。', '',
              '## 局限、交接及下一步', '',
              '继续采用用户确认的DAILY_RANGE_V3日价格区间成交，不考虑成交量；'
              'DFLS容差及账户诊断能力保持既定设计。当前没有新增分钟完整账户或成交容量验证。'
              '约定17:30决策，公共运行默认20:31；EX003 pilot时钟等价证据只覆盖该pilot及其保留输入，'
              '历史17:30数据发布/修订链仍未认证，本轮不扩张这一证明。', '',
              '全部数据已见，已继承阶段二及阶段三选择历史。参数与费用独立检验，不交叉叠加；'
              '本轮不含10%/20%半径、整数邻档或类别切换。完整数值验收仅对这些声明条件成立，'
              '不等同独立超额收益优势确认、真实流动性验证或未来回撤保证。', '',
              recommendation(inputs.comparison), '',
              '请用户明确选择进入阶段五的候选，或要求补证/暂不推进；本交付没有记录用户选型、'
              '启动阶段五、冻结、部署、PTE或生产变更。技术FULL校验通过仅认证身份、证据和确定性复算，'
              '研究结论须同时阅读目标验收、可比状态及上述限制。发布与校验的实际状态以回执为准。', '',
              '实验源码、协议、96参数计划、全部原始账户、SE请求/面板/比较、输入核验及反证均显式关联。'
              '见[事前协议](protocols/stage4.json)、[预检查](others/precheck.json)和[独立收尾核验](others/final_checks.json)。'
              '原MANDATE、CANDIDATES和已发布账户保持不可变。数据、候选快照和delivery/evidence资产须独立保留，'
              '仅克隆Git仓库不足以恢复研究。', '']
    return '\n'.join(lines)


def input_manifest():
    paths = [WORK / name for name in BUILD_FILES]
    paths += sorted((WORK / 'results').glob('*.json'))
    paths += sorted((WORK / 'plans').glob('*.json'))
    paths += sorted((EROOT / 'src').glob('*.py'))
    paths += [EROOT / 'protocols/stage4.json', EROOT / 'others/state.json',
              EROOT / 'others/protocol_ref.json', EROOT / 'others/mapping_refs.json',
              EROOT / 'others/precheck.json', EROOT / 'others/resource_addendum.json',
              EROOT / 'others/resource_addendum_ref.json', WORK / 'parallel_tail_state.json',
              EROOT / 'others/recovery_01.json', EROOT / 'others/recovery_01_ref.json',
              EROOT / 'others/recovery_02.json', EROOT / 'others/recovery_02_ref.json']
    return {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest() for path in paths}


def original_references(inputs):
    refs = [EvidenceRef.from_dict(row['evidence']) for row in inputs.sources['accounts']]
    refs += [EvidenceRef.from_dict(item) for item in inputs.sources['parameter_plans']]
    refs += [EvidenceRef.from_dict(read(EROOT / 'others/state.json')['authorization']),
             EvidenceRef.from_dict(read(EROOT / 'others/protocol_ref.json')),
             EvidenceRef.from_dict(read(EROOT / 'others/resource_addendum_ref.json'))]
    refs += [EvidenceRef.from_dict(item) for item in read(EROOT / 'others/mapping_refs.json').values()]
    recovery = read(EROOT / 'others/recovery_01.json')
    refs += [EvidenceRef.from_dict(read(EROOT / 'others/recovery_01_ref.json')),
             EvidenceRef.from_dict(recovery['failure']),
             EvidenceRef.from_dict(recovery['previous_orchestration'])]
    recovery_two = read(EROOT / 'others/recovery_02.json')
    refs.append(EvidenceRef.from_dict(read(EROOT / 'others/recovery_02_ref.json')))
    refs.extend(EvidenceRef.from_dict(item) for item in recovery_two['failure_references'].values())
    by_identity = {}
    for ref in refs:
        key = (ref.experiment.experiment_id, ref.evidence_id, ref.sha256)
        if ref.experiment.strategy_id != 'S015':
            raise ValueError('publication evidence outside S015')
        if key not in by_identity:
            ref.resolve(ROOT)
            by_identity[key] = ref
    return tuple(by_identity.values())


def payload(inputs):
    bindings = tuple(d.TargetMandateBinding(target_id, item_id) for target_id, item_id in
                     sorted(inputs.sources['mandate']['target_bindings'].items()))
    benchmarks = [item.item_id for item in inputs.mandate.items
                  if isinstance(item.requirement, d.BenchmarkRequirement)]
    if len(benchmarks) != 1:
        raise ValueError('one confirmed benchmark mandate is required')
    # Keep explicit negative account identities as well as the no-design method.
    by_evaluation = {item['evaluation_id']: EvidenceRef.from_dict(item['evidence'])
                     for item in inputs.sources['accounts']}
    contrary_by_hash = {}
    protocol_ref = EvidenceRef.from_dict(read(EROOT / 'others/protocol_ref.json'))
    contrary_by_hash[protocol_ref.sha256] = protocol_ref
    for rank in inputs.comparison.rows:
        for check in rank.target_checks:
            evaluation_ids = ()
            if isinstance(check, m.TargetCheck) and check.status.value == 'FAILED':
                evaluation_ids = check.evaluation_ids
            elif isinstance(check, m.ParameterGroupCheck) and check.status.value == 'FAILED':
                evaluation_ids = tuple(point.evaluation_id for point in check.points
                                       if any(item.status.value == 'FAILED'
                                              for item in (*point.joint_checks, *point.all_point_checks)))
            for evaluation_id in evaluation_ids:
                reference = by_evaluation[evaluation_id]
                contrary_by_hash[reference.sha256] = reference
    contrary = tuple(contrary_by_hash.values())
    return d.CandidateAssessmentDelivery(
        inputs.source_candidates, inputs.source_mandate, inputs.request, inputs.panel,
        inputs.comparison_request, inputs.comparison, bindings,
        inputs.sources['mandate']['frequency_window_item_id'], benchmarks[0],
        recommendation(inputs.comparison), contrary,
        ('请用户选择进入阶段五的具体候选，或决定补证、暂不推进；未记录任何用户选型。',),
        tuple(EvidenceRef.from_dict(item) for item in inputs.sources['parameter_plans']),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preview', 'publish'))
    args = parser.parse_args()
    if (EROOT / 'report_ref.json').exists() or (ROOT / 'research/S015/deliveries/ASSESSMENT/1').exists():
        raise RuntimeError('A publication already exists; use a deliberate new revision, never overwrite')
    inputs = load_inputs(require_final_check=args.mode == 'publish')
    artifact = payload(inputs)
    refs = original_references(inputs)
    manifest = input_manifest()
    if args.mode == 'preview':
        text = report(inputs)
        (EROOT / 'report.md').write_text(text, encoding='utf-8', newline='\n')
        save(EROOT / 'others/publication_inputs.json', manifest)
        save(EROOT / 'others/publication_precheck.json', {
            'status': 'READY_FOR_REVIEW', 'scope': 'typed assembly and declared coverage; no publication or FULL call',
            'centers': len(inputs.request.centers), 'parameter_points': len(inputs.request.perturbations),
            'explicit_original_references': len(refs), 'preview_report_sha256': sha256(text.encode()).hexdigest(),
            'comparison_request_sha256': artifact.comparison_request.sha256,
            'recommendation': artifact.recommendation,
        })
        print(json.dumps({'preview': 'READY_FOR_REVIEW', 'report': 'research/S015/experiments/EX005_20261022/report.md',
                          'centers': 98, 'publication': 'NOT_EXECUTED'}, ensure_ascii=False), flush=True)
        return
    if not (EROOT / 'report.md').is_file() or not (EROOT / 'others/publication_inputs.json').is_file():
        raise RuntimeError('Run preview and review the report before publish')
    if manifest != read(EROOT / 'others/publication_inputs.json'):
        raise RuntimeError('Underlying source/results changed since preview; regenerate and review')
    raw_report = (EROOT / 'report.md').read_bytes()
    if sha256(raw_report).hexdigest() != read(EROOT / 'others/publication_precheck.json')['preview_report_sha256']:
        raise RuntimeError('Report changed since preview; regenerate and review before publication')
    repository = RepositoryContext.discover(ROOT)
    batch = ResearchBatchRef('S015')
    context = create_research_context(repository, batch)
    materials = {}

    def material(name, path):
        suffix = path.suffix.removeprefix('.')
        media = {'json': 'application/json', 'py': 'text/x-python'}[suffix]
        materials[name] = publish_evidence(context, MaterialEvidenceWrite(
            EXPERIMENT, name, path.read_bytes(), media, suffix))

    for name in BUILD_FILES:
        material(Path(name).stem, WORK / name)
    material('parallel_tail_state', WORK / 'parallel_tail_state.json')
    for path in sorted((EROOT / 'src').glob('*.py')):
        material('source_' + path.stem, path)
    for name in ('precheck', 'method_review', 'parallel_review', 'authentication_parallel_precheck',
                 'final_checks', 'publication_inputs', 'publication_precheck'):
        material(name, EROOT / 'others' / f'{name}.json')
    # Preserve orchestration coverage and explicit failed/not-applicable plan records.
    for path in sorted((WORK / 'results').glob('*.json')):
        material('results_' + path.stem, path)
    for cid in sorted(DEGENERATE):
        material('not_applicable_' + cid, WORK / 'plans' / f'{cid}.json')
    all_refs = refs + tuple(materials.values())
    report_ref = publish_evidence(context, ExperimentReportWrite(
        EXPERIMENT, sha256(raw_report).hexdigest(), ExperimentOutcome.COMPLETED, all_refs))
    summary_ref = materials['summary']
    facts = (
        d.FactValue('center_count', 98, 'candidate_identities', d.FactStatus.AVAILABLE, (summary_ref,)),
        d.FactValue('parameter_accounts', 3072, 'account_scenarios', d.FactStatus.AVAILABLE, (summary_ref,)),
        d.FactValue('pressure_accounts', 98, 'account_scenarios', d.FactStatus.AVAILABLE, (summary_ref,)),
        d.FactValue('fully_accepted', sum(row.acceptance_status.value == 'PASSED' for row in inputs.comparison.rows),
                    'candidate_identities', d.FactStatus.AVAILABLE, (summary_ref,)),
        d.FactValue('two_degenerate_parameter_methods', None, '32_point_design', d.FactStatus.NOT_APPLICABLE,
                    (materials['not_applicable_C0030'], materials['not_applicable_C0062']),
                    'C0030/C0062只有一个有效连续坐标，固定半径不能形成32个不同点；不自动通过。'),
    )
    text = raw_report.decode('utf-8')
    text = text.replace('](protocols/', '](../../../experiments/EX005_20261022/protocols/')
    text = text.replace('](others/', '](../../../experiments/EX005_20261022/others/')
    text = text.replace('](../../deliveries/', '](../../')
    receipt = assemble_delivery(repository,
        d.DeliveryDefinition(batch, d.DeliveryStage.ASSESSMENT, 1,
                             (inputs.source_candidates, inputs.source_mandate)),
        d.DeliveryContent(artifact, d.DeliveryStatus.COMPLETE, facts, (), report=text,
                          evidence=(*all_refs, report_ref)))
    validation = validate_delivery(repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    experiment = validate_experiment(repository, ExperimentValidationRequest(
        EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(EROOT / 'others/delivery_validation.json', {
        'delivery': receipt.reference.to_dict(), 'validation': validation.to_dict(),
        'experiment': experiment.to_dict(), 'report': report_ref.to_dict(),
        'material_refs': {name: ref.to_dict() for name, ref in materials.items()},
    })
    if validation.status is not d.ValidationStatus.PASS or experiment.status.value != 'PASS':
        raise RuntimeError('Publication requires investigation; inspect retained validation without overwrite')
    print(json.dumps({'delivery': receipt.reference.to_dict(), 'validation': validation.status.value,
                      'experiment': experiment.status.value}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
