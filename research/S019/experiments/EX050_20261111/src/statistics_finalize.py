"""Verify frozen statistical evidence and write a concise research summary.

No account reading/replay. Native assessment CI equality is finalized when the
separate complete-neighborhood assessment panel becomes available.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import statistics_analysis as stats
import statistics_verification as preparation
import temporal_s018_reference as temporal

import numpy as np
import strategy_evaluator as se
from czsc_trader import research_tools as d

WORK, ROOT = stats.WORK, stats.ROOT


def finite_interval(value):
    assert np.isfinite([value[k] for k in ('point_difference', 'lower_95', 'upper_95', 'probability_favorable')]).all()
    assert value['lower_95'] <= value['upper_95']
    assert 0 <= value['probability_favorable'] <= 1


def main():
    archive = stats.read(WORK / 'statistics_archive_receipt.json')
    prior_verification, = [x for x in archive['files'] if x['formal'] == 'others/statistics_verification.json']
    assert prior_verification['sha256'] == stats.digest(WORK / 'statistics_preparation_verification.json')
    preparation.main()
    protocol = stats.read(WORK / 'statistics_protocol.json')
    assert stats.digest(WORK / 'statistics_protocol.json') == stats.digest(WORK.parent / 'protocols/statistics_protocol.json')
    inventory = stats.read(WORK / 'statistics_inventory.json')
    bootstrap = stats.read(WORK / 'statistics_bootstrap.json')
    selection = stats.read(WORK / 'statistics_selection.json')
    selected_preparation = stats.read(WORK / 'statistics_selection_preparation.json')
    projection = d.SelectionWindowFactsResult.from_dict(stats.read(WORK / 'statistics_incremental_projection.json'))
    assert not projection.failures
    assert len(projection.sources) == selected_preparation['incremental_implementations'] == 648
    assert selected_preparation['reused_implementations'] + len(projection.sources) == inventory['unique_implementations']
    assert stats.digest(WORK.parent / 'src/statistics_selection.py') == selected_preparation['source_sha256']
    assert selection['preparation_sha256'] == stats.digest(WORK / 'statistics_selection_preparation.json')
    assert selection['incremental_projection_sha256'] == stats.digest(WORK / 'statistics_incremental_projection.json')
    assert selected_preparation['protocol_sha256'] == stats.digest(WORK / 'statistics_protocol.json')
    assert selected_preparation['inventory_sha256'] == stats.digest(WORK / 'statistics_inventory.json')
    assert projection.request == d.SelectionWindowFactsRequest.from_dict(stats.read(WORK / 'statistics_selection_request.json'))
    for path, fingerprint in selected_preparation['reuse_sources'].items():
        assert stats.digest(ROOT / path) == fingerprint
    groups = selection['groups']
    assert sum(len(x['members']) for x in groups) == inventory['unique_implementations']
    assert len({x for group in groups for x in group['members']}) == inventory['unique_implementations']
    for group in groups:
        result = group['result']
        assert result['status'] == 'COMPLETE' and result['planned_windows'] == 4
        assert len(group['request']['sources']) == len(group['members'])
        assert group['request']['rule'] == selected_preparation['rule']
    values = stats.read(WORK / 'statistics_center_returns.json')['members']
    expected = {}
    for cid, value in values.items():
        metric = se.performance_metrics(np.asarray(value['returns']))
        expected[cid] = {'cagr': metric.cagr, 'max_drawdown': metric.max_drawdown, 'calmar': metric.calmar}
        if 'MU_BUY_HOLD' not in expected:
            bh = se.performance_metrics(np.asarray(value['benchmark_returns']))
            expected['MU_BUY_HOLD'] = {'cagr': bh.cagr, 'max_drawdown': bh.max_drawdown, 'calmar': bh.calmar}
    assert len(bootstrap['comparisons']) == 6
    assert {(x['champion_id'], x['comparator_id']) for x in bootstrap['comparisons']} == {
        tuple(x) for x in protocol['bootstrap']['pairs']}
    assert bootstrap['protocol_sha256'] == stats.digest(WORK / 'statistics_protocol.json')
    for row in bootstrap['comparisons']:
        assert row['repetitions'] == 10000 and row['mean_block_length'] == 21
        for key in ('cagr', 'max_drawdown', 'calmar'):
            finite_interval(row[key])
            difference = expected[row['champion_id']][key] - expected[row['comparator_id']][key]
            assert abs(row[key]['point_difference'] - difference) < 1e-10
    native_ci = {'status': 'PENDING_NATIVE_PANEL', 'owner': 'assess.py compute also asserts exact endpoint equality'}
    if (WORK / 'panel.json').exists():
        panel = stats.read(WORK / 'panel.json')
        assert len(panel['rows']) == 3
        for row in panel['rows']:
            cid = row['candidate']['candidate_id'].removeprefix('S019-')
            b, = [x['cagr'] for x in bootstrap['comparisons'] if x['champion_id'] == cid and x['comparator_id'] == 'MU_BUY_HOLD']
            assert row['uncertainty']['status'] == 'AVAILABLE'
            assert row['uncertainty']['lower_95'] == b['lower_95']
            assert row['uncertainty']['upper_95'] == b['upper_95']
        native_ci = {'status': 'PASSED_EXACT_ENDPOINT_EQUALITY', 'candidates': 3,
                     'panel_sha256': stats.digest(WORK / 'panel.json')}
    s018 = stats.read(WORK / 'temporal_s018_reference.json')
    assert s018['status'] == 'COMPLETE' and set(s018['selected_ids']) == set(protocol['centers'])
    assert s018['source_sha256'] == stats.digest(WORK.parent / 'src/temporal_s018_reference.py')
    assert s018['protocol_sha256'] == stats.digest(WORK / 'statistics_protocol.json')
    for path, fingerprint in s018['source_bindings'].items():
        assert stats.digest(ROOT / path) == fingerprint
    center_temporal = stats.read(WORK / 'statistics_temporal.json')
    for row in s018['candidates']:
        assert len(row['years']) == 5 and len(row['rolling']) == 46
        assert row['source'] == values[row['candidate_id']]['reference']
    temporal_summaries = []
    for row in center_temporal['candidates']:
        temporal_summaries.append({'candidate_id': row['candidate_id'], 'concentration': row['concentration'],
            'closed_cycles': row['closed_cycles'], 'positive_closed_cycles': row['positive_closed_cycles'],
            'years': row['years'], 'scenarios': row['scenarios'],
            'bh_rolling_below': {k: sum(x[k] < 0 for x in row['rolling']) for k in ('nar_excess', 'calmar_excess')},
            'bh_rolling_lag_runs': {k: temporal.runs(row['rolling'], k) for k in ('nar_excess', 'calmar_excess')},
            's018_rolling_below': next(x['below_reference_rolling_count'] for x in s018['candidates'] if x['candidate_id'] == row['candidate_id'])})
    raw_rows = [x for row in inventory['rows'] for x in [row, *row['aliases']]]
    contexts = Counter(x['context_proxy'] for x in inventory['rows'])
    component_names = sorted({k for x in inventory['rows'] for k in x['context_components']})
    different_fields = {key: dict(Counter(x['context_components'][key] for x in inventory['rows']))
                        for key in component_names if len({x['context_components'][key] for x in inventory['rows']}) > 1}
    compact_groups = []
    center_year_checks = []
    for group in groups:
        result = group['result']
        for decision in result['decisions']:
            for checked in decision['checks']:
                cid = checked['candidate']['candidate_id'].removeprefix('S019-')
                if cid in protocol['centers']:
                    center_year_checks.append({'candidate_id': cid, 'selection_year': decision['selection_window_id'],
                        'status': checked['status'], 'failed_targets': [{
                            'target_id': check['target']['target_id'], 'observed': check.get('observed'),
                            'facts': check.get('facts')} for check in checked['checks'] if check['status'] == 'FAILED']})
        compact_groups.append({'context': group['context'], 'member_count': len(group['members']),
            'summary': {k: v for k, v in result.items() if k not in ('decisions', 'observations', 'candidates')},
            'decisions': [{k: v for k, v in x.items() if k != 'checks'} for x in result['decisions']],
            'observations': [{k: v for k, v in x.items() if k != 'checks'} | {
                'failed_targets': [c['target']['target_id'] for c in x['checks'] if c['status'] == 'FAILED'],
                'metric_observations': {c['target']['target_id']: c.get('observed') for c in x['checks']}}
                for x in result['observations']]})
    common_counts = ('planned_windows', 'selected_windows', 'no_eligible_windows', 'passed_observations', 'failed_observations')
    selection_summary = {k: sum(group['result'][k] for group in groups) for k in common_counts}
    proxy = {'PBO_SHARPE_PROXY': {'status': 'NOT_COMPUTED_CURRENT_UNIVERSE'}, **{
        f'DSR_SHARPE_PROXY_{cid}': {'RAW': {'status': 'NOT_COMPUTED_CURRENT_UNIVERSE'},
                                  'EFFECTIVE': {'status': 'NOT_COMPUTED_CURRENT_UNIVERSE'}} for cid in protocol['centers']}}
    completion = {'status': 'COMPLETE', 'published_accounts': inventory['published_account_count'],
                  'unique_implementations': inventory['unique_implementations'],
                  'reused_implementations': selected_preparation['reused_implementations'],
                  'incremental_implementations': len(projection.sources), 'new_strategy_accounts': 0,
                  'source_sha256': stats.digest(WORK.parent / 'src/statistics_analysis.py'),
                  'selection_source_sha256': stats.digest(WORK.parent / 'src/statistics_selection.py'),
                  'protocol_sha256': stats.digest(WORK / 'statistics_protocol.json'),
                  'annual_projection_stats': projection.stats.to_dict(),
                  'preparation_verification_archive': {
                      'path': 'others/statistics_preparation_verification.json',
                      'sha256': prior_verification['sha256']},
                  'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'native_ci_check': native_ci}
    summary = {'verification': 'PASSED', 'completion': completion,
               'selection_summary': selection_summary, 'selection_groups': compact_groups,
               'selected_centers_annual_gate_diagnostics': center_year_checks,
               'bootstrap_comparisons': bootstrap['comparisons'], 'temporal': temporal_summaries,
               'history': inventory['history'], 'accounts_by_origin': dict(Counter(x['experiment'] for x in raw_rows)),
               'exact_definition_alias_count': len(raw_rows) - len(inventory['rows']),
               'header_context_proxies': dict(contexts), 'header_context_differing_fields': different_fields,
               'header_context_review': stats.read(WORK / 'statistics_context_review.json'),
               'public_selection_context_groups': len(groups),
               'sharpe_proxy': proxy, 'historical_sharpe_scope': {
                   'reference': 'research/S019/experiments/EX041_20261110/others/statistics_search_bias.json',
                   'sha256': stats.digest(stats.PRIOR / 'others/statistics_search_bias.json'),
                   'published_accounts': 374, 'unique_implementations': 371,
                   'use': 'Historical record only; no current-candidate eligibility/ranking or current-universe probability.'},
               'actual_nar_gated_adaptive_selection_bias': 'NOT_ESTIMATED',
               'limitations': selected_preparation['limitations'], 'new_hard_gates': [],
               'source_sha256': stats.digest(Path(__file__))}
    stats.save('statistics_summary.json', summary)
    stats.save('statistics_completion.json', completion)
    lines = ['# 三个中心的统计、时间与选择历史诊断', '',
             '完整统计已完成，新增账户回放 0。中心与全部自检验收继续采用原 12 项目标，达标后按未舍入 NAR 排序。', '',
             '## 研究历史与计算范围', '',
             f"保留 {len(raw_rows)} 份标准账户、{len(inventory['rows'])} 个精确实现及 {len(raw_rows)-len(inventory['rows'])} 个精确定义重复别名。复用旧 371 个实现的年度事实，仅对新增 648 个实现调用公共 TDR 投影。",
             f"年度增量投影实际读取 {projection.stats.source_bytes/1e9:.3f} GB，公共调用耗时 {projection.stats.total_seconds:.1f} 秒（读取 {projection.stats.read_seconds:.1f}、解码 {projection.stats.decode_seconds:.1f}、窗口投影 {projection.stats.projection_seconds:.1f} 秒；分项为该调用的测量范围）。",
             'EX041 的失败自检已反馈给后续机制研究，连同 EX043–049 全部有效标准配置进入已见研究历史。EX042 为技术失败，经济账户为零；费用压力与 EX050 当前邻域单列。', '',
             f"证据头有 {len(contexts)} 类输入身份代理（25/994 个精确实现），差异仅为后续结构增加 SOXX 开盘30分钟辅助 bars/sessions，其他共同数据逐项相同；公共 SE/TDR 按正式事实分为 {len(groups)} 个可比组。辅助输入身份与正式账户可比上下文分别保留。", '',
             '## 配对区间', '',
             '公共 stationary bootstrap：10000 次、平均块长 21 个交易日、seed 20261110。区间条件于已见账户收益与已选配置，样本重抽样保持局部时间相关。MDD改善为正表示回撤幅度更小。', '',
             '|比较|NAR差（百分点）及95%区间|MDD改善（百分点）及95%区间|Calmar差及95%区间|',
             '|---|---|---|---|']
    for row in bootstrap['comparisons']:
        fields = []
        for key, scale in [('cagr', 100), ('max_drawdown', 100), ('calmar', 1)]:
            x = row[key]
            fields.append(f"{x['point_difference']*scale:.4f} [{x['lower_95']*scale:.4f}, {x['upper_95']*scale:.4f}]")
        lines.append(f"|{row['champion_id']} − {row['comparator_id']}|" + '|'.join(fields) + '|')
    lines += ['', '三中心对买持的 NAR 差区间均跨零，回撤改善及 Calmar 差区间为正。C0966 对另外两中心的 NAR 差区间为正；三者两两的 MDD 与 Calmar 差区间均跨零。这些结果连同完整邻域和选择历史共同解释，不新增统计显著性门槛。', '',
              '## 时间与集中性', '', '|中心|闭合周期|最大单笔占全部正闭合盈利|46窗 NAR/Calmar 低于BH数|46窗 NAR/Calmar 低于S018数|',
              '|---|---:|---:|---:|---:|']
    for row in temporal_summaries:
        bh, old = row['bh_rolling_below'], row['s018_rolling_below']
        lines.append(f"|{row['candidate_id']}|{row['closed_cycles']}|{row['concentration']:.2%}|{bh['nar_excess']}/{bh['calmar_excess']}|{old['nar_excess']}/{old['calmar_excess']}|")
    lines += ['', '年度及滚动窗口继承连续资金和持仓，2026 截至 10 月 30 日；重叠窗口的落后次数按连续起点描述。固定 S018-v1 采用 EX003 同窗公开证据，锁定 C9397 发布身份，以 C0001 作为研究材料身份，保留其日级执行规则。', '',
              '## 与实际目标一致的年度选择诊断', '',
              '在固定的完整已见候选集合内，每个选择年度先检验原六项中心条件，再按未舍入 NAR 选择，随后观察下一年度；同值并列保留。年度硬门只服务此诊断，正式资格继续按原完整窗口评价。', '',
              '|可比组|实现数|4对窗口中有合格选择|无合格选择|次年原六门通过/失败|', '|---|---:|---:|---:|---:|']
    for i, group in enumerate(compact_groups, 1):
        x = group['summary']
        lines.append(f"|{i}|{group['member_count']}|{x['selected_windows']}|{x['no_eligible_windows']}|{x['passed_observations']}/{x['failed_observations']}|")
    lines += ['', '本次年度选择细节：', '']
    for group in compact_groups:
        for observation in group['observations']:
            v = observation['metric_observations']
            lines.append(f"- {observation['pair_id']} 选择 {observation['candidate']['candidate_id']}，"
                         f"次年 NAR {v['center-nar']:.4%}、Calmar {v['center-calmar']:.4f}、MDD {v['center-risk']:.4%}；"
                         f"未达项：{', '.join(observation['failed_targets'])}。")
    for row in center_year_checks:
        if row['selection_year'] == '2025':
            assert [(x['target_id'], x['observed']) for x in row['failed_targets']] == [('center-frequency', 4.0)]
    lines += ['', '当前三个中心在 2025 年度经济条件均通过，年度内60日闭合交易中位数均为4，因该诊断沿用6的条件而未被选中；2022–2024的单年收益与Calmar也低于原中心数值门槛。该回看把完整窗口的原门槛原样放到单年，揭示门槛跨年份的适用性；正式全窗资格与当前三者的后续自检判定分别保留。']
    lines += ['', '全部候选与规则源于反复使用的开发历史；年度回看呈现选型对时段的敏感性。完整自适应搜索加六门筛选的选择偏差仍记为 NOT_ESTIMATED。本轮优先使用对应实际 NAR 目标的诊断，未重算全族 Sharpe PBO/DSR；EX041 的旧代理值只适用当时 374 账户 / 371 实现范围。', '',
              '逐候选年度、全部46窗口、连续落后段、正盈利分母、原始配对区间与逐项年度选择检查均保留在结构化材料。正式完整自检结果由 assessment 面板统一验收。', '',
              f"公共 assessment 的区间逐值复核状态：{native_ci['status']}。", '',
              '证据：[完整汇总](statistics_summary.json)、[配对区间](statistics_bootstrap.json)、[年度选择](statistics_selection.json)、[时间与集中性](statistics_temporal.json)、[固定S018参照](temporal_s018_reference.json)。']
    (WORK / 'statistics_report.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    artifacts = {p.name: stats.digest(p) for p in WORK.glob('statistics*.json')
                 if p.name != 'statistics_verification.json'}
    artifacts['statistics_report.md'] = stats.digest(WORK / 'statistics_report.md')
    artifacts['temporal_s018_reference.json'] = stats.digest(WORK / 'temporal_s018_reference.json')
    stats.save('statistics_verification.json', {'status': 'PASSED', 'new_strategy_accounts': 0,
        'checks': ['Preparation identities, dependencies and metadata', 'All 1019 unique annual selection sources in comparable groups',
                   '648 incremental public projections without failures', 'Original six gates and pure NAR rule preserved',
                   'Six paired bootstrap intervals and exact point estimates', 'Three standard/pressure and fixed S018 reference bindings'],
        'verification_source_sha256': stats.digest(Path(__file__)), 'native_ci_check': native_ci,
        'protocol_sha256': stats.digest(WORK / 'statistics_protocol.json'), 'artifacts': artifacts})
    print('STATISTICS_VERIFIED', inventory['published_account_count'], inventory['unique_implementations'], native_ci['status'])


if __name__ == '__main__':
    main()
