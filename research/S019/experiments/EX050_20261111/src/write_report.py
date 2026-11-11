"""Render completed stage-four results without embedding anticipated conclusions."""
from hashlib import sha256
import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]
COUNTS = {'C0966': 242, 'C1010': 728, 'C0909': 728}
NAMES = {'weak_fraction': '弱参与仓位', 'quiet_fraction': '安静期仓位',
    'participation_threshold': '成交参与阈值', 'participation_width': '参与过渡宽度',
    'trail_atr': 'ATR退出倍数', 'exit_width': '退出过渡宽度'}


def read(path):
    return json.loads((WORK/path).read_bytes())


def pct(value):
    return f'{value:.4%}'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |',
        *['| '+' | '.join(map(str, row))+' |' for row in rows]])


def main():
    scope = read('protocols/scope.json')
    assessment = read('others/assessment_summary.json')
    summary = read('others/account_summary.json')
    accounts = read('others/account_results.json')
    attempts = read('others/account_attempts.json')
    ranking = read('others/research_nar_ranking.json')
    temporal = read('others/assessment_temporal.json')
    bootstrap = read('others/statistics_bootstrap.json')
    audit = read('others/semantic_audit.json')
    statistics = read('others/statistics_summary.json')
    assert accounts['status'] == 'COMPLETE' and len(accounts['accounts']) == 1704
    assert list(COUNTS) == scope['selected'] and len(scope['deferred']) == 109
    assert assessment['qualified_nar_ranking'] == ranking['ranking']
    assert all(x['business_rules'] == 'PASS' for x in audit['results'])
    assert all(x['serialized_targets_exact'] == 'PASS' for x in audit['results'])
    assert statistics['verification'] == 'PASSED'
    native_ci = statistics['completion']['native_ci_check']
    assert native_ci['status'] == 'PASSED_EXACT_ENDPOINT_EQUALITY'
    assert native_ci['panel_sha256'] == sha256((WORK/'others/panel.json').read_bytes()).hexdigest()
    assert {r['candidate']['candidate_id'] for r in assessment['candidates']} == {'S019-'+cid for cid in COUNTS}
    assert all(len(r['target_checks']) == 12 for r in assessment['candidates'])
    accepted = [x['candidate']['candidate_id'].removeprefix('S019-') for x in ranking['ranking']]
    conclusion = f'本批3个候选完成阶段四完整自检，{len(accepted)}个通过全部原目标。'
    conclusion += '达标后的纯NAR顺序为：'+'、'.join(accepted)+'。' if accepted else '本批达标推荐集合为空。'
    centers, neighbors, stresses, levels, axes_only, acceptance = [], [], [], [], [], []
    for row in assessment['candidates']:
        cid = row['candidate']['candidate_id'].removeprefix('S019-')
        n = COUNTS[cid]
        c, p, s = row['center'], row['parameter'], row['stress']
        assert p['required_points'] == p['valid_points'] == n
        assert p['pass_rate'] == summary['groups'][cid]['joint_pass_rate']
        assert not row['coverage_gaps']
        coverage = row['frequency_coverage']
        centers.append([cid, pct(c['nar']), pct(c['mdd']), f"{c['calmar']:.6f}",
            row['diagnostics']['FREQUENCY_MEDIAN'], pct(coverage['covered_windows']/coverage['total_windows'])])
        neighbors.append([cid, n, pct(p['pass_rate']), p['joint_passes'], p['required_passes'],
            pct(p['minimum_nar']), pct(p['maximum_mdd']), f"{p['minimum_calmar']:.6f}", p['status']])
        stresses.append([cid, pct(s['nar']), pct(s['mdd']), f"{s['calmar']:.6f}"])
        failures = [x['target']['target_id'] for x in row['target_checks'] if x['status'] == 'FAILED']
        acceptance.append([cid, row['acceptance_status'], '、'.join(failures) or '无'])
        for axis, slices in summary['groups'][cid]['parameter_level_diagnostics'].items():
            assert len(slices) == 3
            assert abs(sum(x['n']*x['joint_pass_rate'] for x in slices)-p['joint_passes']) < 1e-9
            levels.append([cid, NAMES[axis], *[f"{x['value']:.8g} / {x['n']} / {pct(x['joint_pass_rate'])}" for x in slices]])
        central = accounts['accounts'][cid+'_CENTER']['parameters']
        for key, point in accounts['accounts'].items():
            if point['parent'] != cid or not point['label'].startswith('P'):
                continue
            changed = [k for k, v in point['parameters'].items() if v != central[k]]
            if changed == ['trail_atr'] or set(changed) == {'trail_atr'}:
                m = point['candidate']
                axes_only.append([cid, key, f"{point['parameters']['trail_atr']/central['trail_atr']-1:+.0%}",
                    pct(m['nar']), pct(m['drawdown']), f"{m['calmar']:.6f}",
                    all(point['selfcheck_gates'][k] for k in ('nar', 'calmar', 'relative_dd'))])
    assert len(axes_only) == 6
    times, annual = [], []
    for row in temporal['candidates']:
        cid = row['candidate']['candidate_id'].removeprefix('S019-')
        distribution = row['rolling_distributions']
        runs = row['consecutive_lagging_rolling_windows']
        times.append([cid, f"{distribution['nar_excess']['above_zero']}/46", f"{distribution['calmar_excess']['above_zero']}/46",
            runs['nar_excess']['maximum_count'], runs['calmar_excess']['maximum_count'],
            pct(row['profit_contribution']['largest_winner_share_of_positive_closed_pnl'])])
        for year in row['years']:
            annual.append([cid, year['window_id'], pct(year['strategy']['period_return']),
                pct(year['strategy']['nar']), pct(year['strategy']['mdd']), f"{year['strategy']['calmar']:.4f}"])
    intervals = []
    for row in bootstrap['comparisons']:
        nar, calmar = row['cagr'], row['calmar']
        intervals.append([row['champion_id']+' − '+row['comparator_id'],
            f"[{100*nar['lower_95']:.2f}, {100*nar['upper_95']:.2f}]pp",
            f"[{calmar['lower_95']:.4f}, {calmar['upper_95']:.4f}]"])
    resources = [[a['attempt'], a['status'], a['resources']['workers'], a['resources']['native_threads'],
        a['equity_statistics']['candidate_runs'], a['equity_statistics']['benchmark_runs'],
        f"{a['elapsed_seconds']/60:.2f}"] for a in attempts]
    lines = ['# S019阶段四：C0966、C1010、C0909', 'Status: COMPLETE；RSCH；本批3项，另109项待选。',
        '## 研究结论', conclusion, table(['候选', '全部原目标', '失败目标'], acceptance),
        '中心NAR≥55%、Calmar≥5及原MDD、频率、自检标准保持。全部12项目标通过后，研究排序只使用未舍入标准NAR，精确同值并列。',
        '## 范围、样本与证据',
        '承接[CANDIDATES/7](../../deliveries/CANDIDATES/7/report.md)及MANDATE/2；[批准范围](protocols/authorization.md)与[事前方案](protocols/plan.md)固定3个候选。原112项交接集合保留，其余109项列于[范围清单](protocols/scope.json)。',
        '2021预热，2022-01-03至2026-10-30连续已见历史，1212交易日、15702个M30决策。MU/SOXX、HFQ整数单位、10万美元、限价买入/市价卖出与原数据合同保持。该历史已反复参与开发，独立前瞻表现仍待后续观察。',
        '## 中心及费用压力', table(['候选','NAR','MDD','Calmar','60日闭合中位数','至少3笔窗口覆盖率'], centers),
        '中心MDD≤25%且≤同费用买持MDD的80%；60日闭合中位数≥6，至少3笔窗口覆盖率≥90%。',
        table(['候选','双倍费用NAR','双倍费用MDD','双倍费用Calmar'], stresses),
        '标准费用每侧0.1%，压力每侧0.2%。压力要求NAR≥50%、Calmar≥4.5、MDD≤25%且严格小于同压力买持，买持MDD为零时策略须同为零。3个中心与3个压力账户精确复用；请求逐字段核验仅实验归属变化，原证据身份保持。',
        '## 完整参数敏感性',
        '硬退出的5个有效连续参数，以及两种渐进退出各6个有效连续参数，分别采用中心与上下5%完整三水平笛卡尔积，剔除整体中心，共242、728、728个非中心点。无效参数按适用性依据固定；整数最小合法步长超过5%时固定，类别与布尔保持结构。',
        '邻点联合要求NAR≥50%、Calmar≥4.5、MDD≤同费买持90%，联合通过率≥80%；全部点MDD≤25%。每个点有效且等权，完整分母固定，使用未舍入数据验收。',
        table(['候选','完整N','通过率','实际通过点','所需通过点','最低NAR','最高MDD','最低Calmar','邻域验收'], neighbors),
        '各轴切片在同一完整点集中，按该轴下档/中心/上档分组，其余有效轴联合变化；每格为参数值 / N / 通过率。切片帮助定位敏感区间，正式结论仍取完整邻域。',
        table(['候选','参数','下5%','中心','上5%'], levels),
        '以下从完整点集提取其他参数固定中心的纯ATR上下5%扰动，便于对照此前退出敏感性问题。',
        table(['候选','账户','ATR变化','NAR','MDD','Calmar','邻点联合通过'], axes_only),
        '逐点结果、失败目标、分位数与切片见[账户结果](others/account_results.json)、[参数摘要](others/account_summary.json)和[完整验收](others/assessment_summary.json)。',
        '## 时间稳定性与收益集中性',
        '使用原中心连续账户，252交易日窗口、21日步长，共46个重叠窗口。窗口起点继承前日权益和原持仓；连续落后按窗口序列统计。',
        table(['候选','NAR胜买持','Calmar胜买持','NAR最长落后窗口','Calmar最长落后窗口','最大单笔盈利贡献'], times),
        table(['候选','年度','期间收益','NAR','MDD','Calmar'], annual),
        '2026截至10月30日。最大单笔贡献采用最大一笔盈利闭合交易净利润/全部盈利闭合交易净利润总和。相对买持和固定S018-v1的完整同窗对照分别见[时间证据](others/assessment_temporal.json)、[S018-v1对照](others/temporal_s018_reference.json)。',
        '## 统计不确定性与选择历史',
        '公共SE成对平稳Bootstrap使用10000次、平均块长21交易日、固定seed20261110，报告已选配置相对绩效的条件95%区间。重叠窗口和反复选择历史的依赖需结合研究族诊断解释。',
        table(['差值方向','NAR差95%区间','Calmar差95%区间'], intervals),
        '[统计说明](others/statistics_report.md)保留完整历史计数、重复实现、原六门加NAR的年度回看、公开投影及统计局限；完整自适应搜索与人工选型偏差仍单列为未量化。统计诊断用于解释证据与风险，沿用既定数值验收条件。',
        f"年度回看共{statistics['selection_summary']['planned_windows']}对窗口，其中{statistics['selection_summary']['no_eligible_windows']}对无合格者，另{statistics['selection_summary']['selected_windows']}对选出旧候选，后续观察通过{statistics['selection_summary']['passed_observations']}项、失败{statistics['selection_summary']['failed_observations']}项。当前三个中心在2025年度经济条件通过，但60日闭合中位均4。年度回看描述原门槛跨年份的敏感性，正式资格仍按约定全窗核验。",
        '## 执行、核验与交付',
        'Windows单会话进程池实际最大61，本轮账户回放采用61进程、每进程1原生线程。公共TDR执行会话与检查点绑定完整请求、源码、父子关系和逐点参数计划；同场景买持共享。实际执行记录如下。',
        table(['执行段','状态','进程','每进程线程','策略回放','买持回放','分钟'], resources),
        f"累计账户任务记录{accounts['elapsed_seconds']/60:.2f}分钟；完整1698邻点，复用6个中心/压力场景。独立业务核验覆盖{len(audit['results'])}账户、{sum(x['decisions'] for x in audit['results']):,}个决策，全部PASS，见[审计](others/semantic_audit.json)。",
        '公共schema12原生验收与比较原样保留；不同机制各自完整5/6轴几何独立验证，参数分位数按各自设计解释。正式研究推荐仅采用[原目标后纯NAR排序](others/research_nar_ranking.json)，原生多指标名次作为辅助证据，详见[可比性核验](others/assessment_comparability.json)。',
        '正式交付ASSESSMENT/3承接完整CANDIDATES/7与MANDATE/2，采用INTEGRITY发布校验，见[发布回执](others/assessment_publication.json)。本轮新增优化轮0，剩余7轮保持。',
        '## 下一步',
        ('建议用户审阅本报告及已见历史风险，选择具体达标候选进入阶段五；精确冻结计划另行批准。' if accepted else
         '建议依据完整邻域的敏感轴及机制差异确定下一步优化方向，或从保留候选中选择下一批自检对象。原目标保持，后续研究范围由用户决定。')]
    (WORK/'report.md').write_bytes(('\n\n'.join(lines)+'\n').encode())
    print('REPORT_READY', accepted, flush=True)


if __name__ == '__main__':
    main()
