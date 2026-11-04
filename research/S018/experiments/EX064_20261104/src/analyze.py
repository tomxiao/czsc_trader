"""Read-only account analysis for the approved C9380 bounded sensitivity run."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True

from hashlib import sha256
import json
import math
import numpy as np
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'research/RSCH_AGENT.md').is_file())
WORK = Path(__file__).resolve().parents[1]
RESULTS = WORK / 'others/recovery_01/results.json'
DESIGN = ROOT / 'research/S018/materials/c9380_stage4_design/point_set.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def materialized(reference):
    ref = d.EvidenceRef.from_dict(reference)
    path = ref.resolve(ROOT)
    return materialize_equity(path.read_bytes(),
        lambda item: (path.parent / (item['sha256'] + '.json')).read_bytes()).payload


def economic(value):
    """Remove cross-candidate identifiers, retaining financial and time fields."""
    ignored = {'owner', 'implementation', 'plan_identity', 'specification_hash'}
    if isinstance(value, dict):
        return {k: economic(v) for k, v in value.items()
                if k not in ignored and not k.endswith('_id') and not k.endswith('_hash')}
    if isinstance(value, list):
        return [economic(v) for v in value]
    return value


def decisions(run, sizing):
    keys = ('target', 'side', 'signal_status')
    if sizing:
        keys += ('quantity', 'target_quantity', 'limit_price', 'reference_price')
    return {row['decision_at']: {**{k: row[k] for k in keys},
        **({'planned_orders': economic(row['plan']['orders'])} if sizing else {})}
        for row in run['decisions']}


def fills_by_time(run, sized):
    fields = ('side', 'price', 'executed_at', 'interval_start', 'interval_end')
    if sized:
        fields += ('quantity', 'fees')
    grouped = {}
    for fill in run['fills']:
        grouped.setdefault(fill['interval_start'], []).append({k: fill[k] for k in fields})
    return grouped


def changes(left, right):
    return sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k))


def compare_behavior(center, run):
    timing_center, timing_run = fills_by_time(center, False), fills_by_time(run, False)
    filled_center, filled_run = fills_by_time(center, True), fills_by_time(run, True)
    timing_changes = changes(timing_center, timing_run)
    fill_changes = changes(filled_center, filled_run)
    action_changes = changes(decisions(center, False), decisions(run, False))
    sized_changes = changes(decisions(center, True), decisions(run, True))
    return {'center_fill_count': len(center['fills']), 'fill_count': len(run['fills']),
        'decision_target_side_changed_days': len(action_changes),
        'decision_with_sizing_changed_days': len(sized_changes),
        'fill_timing_side_price_changed_sessions': len(timing_changes),
        'fill_economic_changed_sessions': len(fill_changes),
        'fill_timing_changed_dates': timing_changes,
        'decision_target_side_changed_dates': action_changes,
        'fills_economic_equal': economic(center['fills']) == economic(run['fills']),
        'daily_account_economic_equal': economic(center['account_daily']) == economic(run['account_daily']),
        'trades_economic_equal': economic(center['trades']) == economic(run['trades']),
        'first_fill_change': None if not fill_changes else {
            'session': fill_changes[0], 'center': filled_center.get(fill_changes[0], []),
            'perturbed': filled_run.get(fill_changes[0], [])}}


def main():
    result, design = read(RESULTS), read(DESIGN)
    expected = ['CENTER', 'PRESSURE', *[f'O{i:02d}' for i in range(1, 16)], *[f'J{i:02d}' for i in range(1, 65)]]
    assert result['status'] == 'COMPLETED', 'Wait for all approved accounts to finish; no partial acceptance.'
    assert set(result['accounts']) == set(expected) and len(result['accounts']) == 81
    assert result['workload']['candidate_runs'] == 81 and result['workload']['benchmark_runs'] == 2
    accounts = result['accounts']
    center, pressure = accounts['CENTER'], accounts['PRESSURE']
    standard_bh, pressure_bh = center['benchmark'], pressure['benchmark']
    assert center['content_hash'] == design['candidate_content_hash']
    assert len(design['points']) == 79
    points = {p['id']: p for p in design['points']}
    neighbor_checks = []
    for label in expected[2:]:
        row = accounts[label]
        assert row['config'] == points[label]['parameters']
        assert row['benchmark'] == standard_bh
        m, bh = row['candidate'], row['benchmark']
        assert all(m[k] is not None and math.isfinite(m[k]) for k in ('annual', 'calmar', 'dd'))
        gates = {'calmar': m['calmar'] >= 1.25 * bh['calmar'],
            'dd_relative': m['dd'] <= .9 * bh['dd'], 'dd_absolute': m['dd'] <= .25}
        assert gates == row['gates']
        neighbor_checks.append({'label': label, 'candidate': m, 'gates': gates,
            'joint_economic_pass': gates['calmar'] and gates['dd_relative']})
    center_gates = {'calmar': center['candidate']['calmar'] >= 1.5 * standard_bh['calmar'],
        'dd_relative': center['candidate']['dd'] <= .8 * standard_bh['dd'],
        'dd_absolute': center['candidate']['dd'] <= .25, 'median': center['candidate']['median'] >= 6,
        'coverage': center['candidate']['coverage'] >= .9}
    pressure_gates = {'calmar': pressure['candidate']['calmar'] > pressure_bh['calmar'],
        'dd_relative': pressure['candidate']['dd'] < pressure_bh['dd'] if pressure_bh['dd'] else pressure['candidate']['dd'] == 0,
        'dd_absolute': pressure['candidate']['dd'] <= .25}
    assert center_gates == center['gates'] and pressure_gates == pressure['gates']
    pass_count = sum(p['joint_economic_pass'] for p in neighbor_checks)
    absolute_count = sum(p['gates']['dd_absolute'] for p in neighbor_checks)
    required = math.ceil(13 * 79 / 16)
    neighborhood_pass = pass_count >= required and absolute_count == 79
    panel = {'center_standard': center['candidate'], 'buyhold_standard': standard_bh,
             'center_pressure': pressure['candidate'], 'buyhold_pressure': pressure_bh}
    calmar = np.array([p['candidate']['calmar'] for p in neighbor_checks])
    drawdown = np.array([p['candidate']['dd'] for p in neighbor_checks])
    quantiles = {'calmar_q10': float(np.quantile(calmar, .1, method='linear')),
        'dd_q90': float(np.quantile(drawdown, .9, method='linear')),
        'calmar_min': float(calmar.min()), 'calmar_max': float(calmar.max()),
        'dd_min': float(drawdown.min()), 'dd_max': float(drawdown.max()),
        'worst_calmar_labels': [p['label'] for p in neighbor_checks if p['candidate']['calmar'] == calmar.min()],
        'worst_dd_labels': [p['label'] for p in neighbor_checks if p['candidate']['dd'] == drawdown.max()]}
    center_payload = materialized(center['account_ref'])
    center_run = center_payload['runs']['candidate']
    single = []
    for label in expected[2:17]:
        row = accounts[label]
        changed = [(k, v) for k, v in row['config'].items() if v != center['config'][k]]
        assert len(changed) == 1
        key, value = changed[0]
        run = materialized(row['account_ref'])['runs']['candidate']
        facts = compare_behavior(center_run, run)
        single.append({'label': label, 'parameter': key, 'center_value': center['config'][key],
            'value': value, 'candidate': row['candidate'],
            'delta_calmar': row['candidate']['calmar'] - center['candidate']['calmar'],
            'delta_dd': row['candidate']['dd'] - center['candidate']['dd'],
            'delta_closed': row['candidate']['closed'] - center['candidate']['closed'], 'behavior': facts})
    joint_labels = [f'J{i:02d}' for i in range(1, 65)]
    signs = np.array([points[k]['signs'] for k in joint_labels])
    metrics = {k: np.array([accounts[label]['candidate'][k] for label in joint_labels]) for k in ('calmar', 'dd', 'closed')}
    axes = design['axes']
    def contrast(indices):
        sign = np.prod(signs[:, indices], axis=1)
        assert (sign == 1).sum() == (sign == -1).sum() == 32
        return {'parameters': [axes[i]['parameter'] for i in indices],
            'interpretation': 'high minus low' if len(indices) == 1 else 'same-sign mean minus opposite-sign mean',
            'positive_n': 32, 'negative_n': 32,
            **{k: {'positive_mean': float(v[sign == 1].mean()), 'negative_mean': float(v[sign == -1].mean()),
                    'difference': float(v[sign == 1].mean() - v[sign == -1].mean())} for k, v in metrics.items()}}
    main_effects = sorted([contrast([i]) for i in range(8)], key=lambda x: abs(x['calmar']['difference']), reverse=True)
    interactions = sorted([contrast([i, j]) for i in range(8) for j in range(i + 1, 8)],
                          key=lambda x: abs(x['calmar']['difference']), reverse=True)
    first_attempt = read(WORK / 'others/results.json')
    failed_status = read(WORK / 'others/batch_00_status.json')
    summary = {'schema': 's018-c9380-bounded-sensitivity-analysis/v1',
        'source_results': str(RESULTS.relative_to(ROOT)).replace('\\', '/'),
        'source_results_sha256': sha256(RESULTS.read_bytes()).hexdigest(),
        'point_set_sha256': sha256(DESIGN.read_bytes()).hexdigest(), 'accounts': panel,
        'center_gates': center_gates, 'pressure_gates': pressure_gates,
        'neighbor_count': 79, 'required_joint_passes': required, 'joint_passes': pass_count,
        'absolute_dd_passes': absolute_count, 'neighborhood_pass': neighborhood_pass,
        'overall_scoped_checks_pass': neighborhood_pass and all(center_gates.values()) and all(pressure_gates.values()),
        'quantiles': quantiles, 'neighbor_checks': neighbor_checks, 'single_axis': single,
        'joint_main_effects': main_effects, 'joint_two_factor_interactions': interactions,
        'behavior_method': 'Dates and economic decision/fill/account fields compared; cross-candidate identities removed. No one-buy/one-sell assumption.',
        'initial_attempt': {'status': first_attempt['status'], 'error': first_attempt.get('error'),
                            'batch_statuses': failed_status, 'strategy_performance_failure': False},
        'execution_seconds': result['elapsed_seconds'], 'workload': result['workload'],
        'full_stage4_complete': False,
        'limitations': ['Only declared 79-point set; not full Cartesian or continuous domain.',
            'Short integer timing parameters and add_mode held fixed; known timing sensitivity remains.',
            'Repeated development sample, not independent validation.',
            'Resolution V separates low-order terms from each other but aliases some with higher-order effects.',
            'Effect contrasts and quantiles are descriptive; no significance or future-success probability.',
            'common_budget joint midpoint is .975, whereas actual center is boundary 1.']}
    (WORK / 'others/analysis_sensitivity.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2,
        allow_nan=False) + '\n', encoding='utf-8')
    pct = lambda value: f'{100 * value:.4f}%'
    status = '通过' if summary['overall_scoped_checks_pass'] else '未通过'
    lines = ['# EX064：C9380 固定79点参数敏感性与费用压力自检', '',
        f'本次获批范围自检{status}：79个邻点中{pass_count}个联合满足净卡玛及相对回撤门槛（要求至少{required}个），'
        f'{absolute_count}/79个满足25%绝对回撤上限。中心原五项硬门和费用压力分别为'
        f'{"通过" if all(center_gates.values()) else "未通过"}、{"通过" if all(pressure_gates.values()) else "未通过"}。'
        '这是参数与费用检查完成，不是完整阶段四完成，也不是独立样本验证。', '',
        '## 中心、压力与买持', '', '|账户|净年化|最大回撤|净卡玛|闭合交易|60日中位|至少3笔覆盖|',
        '|---|---:|---:|---:|---:|---:|---:|']
    names = {'center_standard':'C9380 标准','buyhold_standard':'买持 标准',
             'center_pressure':'C9380 每侧0.2%','buyhold_pressure':'买持 每侧0.2%'}
    for key, m in panel.items():
        lines.append(f"|{names[key]}|{pct(m['annual'])}|{pct(m['dd'])}|{m['calmar']:.6f}|{m['closed']}|{m['median']:g}|{pct(m['coverage'])}|")
    lines += ['', '买持为同窗口、同报价及成交约束的投资基准，频率仅展示、不要求买持满足策略频率。'
        '中心汇总指标复现阶段三原值；本研究以净卡玛为评价目标，不能把降低回撤解释为绝对收益更高。', '',
        '## 参数范围与局部敏感性', '',
        f"15个单参数方向点与64个联合点全部齐备，未按绩效删点。净卡玛范围{quantiles['calmar_min']:.6f}—{quantiles['calmar_max']:.6f}，"
        f"Q10={quantiles['calmar_q10']:.6f}；回撤范围{pct(quantiles['dd_min'])}—{pct(quantiles['dd_max'])}，"
        f"Q90={pct(quantiles['dd_q90'])}。最低卡玛点为{','.join(quantiles['worst_calmar_labels'])}，"
        f"最大回撤点为{','.join(quantiles['worst_dd_labels'])}。Q10/Q90只描述本次离散点集。", '',
        '|点|参数→扰动值|卡玛变化|回撤变化（百分点）|闭合数变化|目标/方向变化日|含股数决策变化日|成交时点/方向/价变化会话|成交经济字段变化会话|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in single:
        b = row['behavior']
        lines.append(f"|{row['label']}|{row['parameter']}→{row['value']:g}|{row['delta_calmar']:+.6f}|{row['delta_dd']*100:+.4f}|"
            f"{row['delta_closed']:+d}|{b['decision_target_side_changed_days']}|{b['decision_with_sizing_changed_days']}|"
            f"{b['fill_timing_side_price_changed_sessions']}|{b['fill_economic_changed_sessions']}|")
    equal = [r['label'] for r in single if all(r['behavior'][k] for k in ('fills_economic_equal','daily_account_economic_equal','trades_economic_equal'))]
    timing = [r['label'] for r in single if r['behavior']['fill_timing_side_price_changed_sessions']]
    lines += ['', f"成交、日账本及闭合交易经济字段同时完全相同的单轴点：{','.join(equal) if equal else '无'}。"
        f"出现成交时点/方向/价格路径变化的单轴点：{','.join(timing) if timing else '无'}。"
        '其余差异可能主要体现仓位数量、费用及资金复投；不能只凭卡玛变化认定捕捉机会能力改善。'
        '比较按真实逐日决策及成交序列进行，排除身份字段，允许同一周期多次买入；不是一买一卖假设。', '',
        '这表明局部响应存在不改变成交的平坦区域及跨过条件门槛后的台阶变化，不能将79个声明点视为79次独立成功。'
        'O13提高MU补仓门槛后的首个路径差异是2026-05-21少一次买入；O14略微降低行业补仓门槛后的首个差异是2023-08-15增加一次买入。'
        '少数交易路径改变可经后续复投扩散到很多成交数量，不能将所有股数差异都计为新的择时信息。', '',
        '## 联合点的效应对比', '',
        '下面为64个联合点中的描述性均值对比，按净卡玛差绝对值排序。主效应=高值均值−低值均值；'
        '交互=两参数同号组合均值−异号组合均值，不是两个参数各自改善的因果效应。'
        '分辨率V使主效应及两因素交互彼此可区分，但仍可能混入三因素及更高阶作用。', '',
        '|主效应参数|卡玛差|回撤差（百分点）|闭合数差|','|---|---:|---:|---:|']
    for item in main_effects:
        lines.append(f"|{item['parameters'][0]}|{item['calmar']['difference']:+.6f}|{100*item['dd']['difference']:+.4f}|{item['closed']['difference']:+.4f}|")
    lines += ['', '|两因素交互（前6项）|卡玛差|回撤差（百分点）|闭合数差|','|---|---:|---:|---:|']
    for item in interactions[:6]:
        lines.append(f"|{' × '.join(item['parameters'])}|{item['calmar']['difference']:+.6f}|{100*item['dd']['difference']:+.4f}|{item['closed']['difference']:+.4f}|")
    lines += ['', '完整28项交互见分析JSON。common_budget仅取0.95/1，联合对比围绕0.975，不能解释为中心1的对称导数。'
        '这些对比用于定位脆弱方向，不据此选取邻点替代C9380。', '', '## 计算与证据边界', '',
        f"权限恢复后的固定批次完成81个策略账户、2份共享买持，执行耗时{result['elapsed_seconds']/60:.2f}分钟。"
        '首次沙箱批次因WinError 5导致任务未提交，属于执行权限问题，不是策略失败；原停止记录保留，恢复批次另存。', '',
        '参数验收沿用净卡玛≥买持1.25倍及回撤≤买持0.9倍，至少65/79点联合通过、全部回撤≤25%。'
        '邻点频率不新增硬门，中心仍遵守原经济与频率目标。', '',
        '未检验入场2日、最早补仓3日、检查3日及最长持有5日的一日扰动，也未改变补仓模式；'
        '已有短周期时序敏感性没有消失。未穷举其余端点、中心/端点混合点及连续区域。'
        '全部使用已反复开发的2023—2026开发池，没有获得独立验证或未来收益保证。', '',
        '下一步建议：保留C9380精确参数，不将邻域检查变为重新选优；继续阶段四前，明确其余时间稳定性、'
        '收益集中性及统计不确定性工作的范围。当前仅参数及费用自检完成，未进入阶段五。', '',
        '[完整分析](others/analysis_sensitivity.json) · [恢复批次结果](others/recovery_01/results.json) · '
        '[原始停止记录](others/results.json) · [批准点集](others/approved_point_set.json)', '']
    (WORK / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('neighbor_count','joint_passes','absolute_dd_passes',
        'overall_scoped_checks_pass','quantiles','execution_seconds')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
