"""Independent completed-account audit; no account execution or economic selection."""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / 'research/S007/assets/runs/EX004_20261010'
PLAN_PATH = ROOT / 'research/S007/experiments/EX004_20261010/protocols/plan.json'
SOURCES = {}


def read(path):
    path = Path(path)
    data = path.read_bytes()
    SOURCES[path.relative_to(ROOT).as_posix()] = {'sha256': sha256(data).hexdigest(), 'bytes': len(data)}
    return json.loads(data)


def evidence(ref):
    ex = ref['experiment']
    path = ROOT / f"research/{ex['strategy_id']}/assets/evidence/{ex['experiment_id']}/{ref['evidence_id']}"
    raw = read(path)
    assert SOURCES[path.relative_to(ROOT).as_posix()]['sha256'] == ref['sha256']
    validate_evaluation_evidence(raw)
    assert raw['execution_mode'] == 'FULL'
    return raw


def select(raw):
    runs = [x for x in raw['runs'] if x['scenario_id'] == 'baseline']
    assessments = [x for x in raw['assessment_evidence'] if x['scenario_id'] == 'baseline']
    assert len(runs) == len(assessments) == 1
    return runs[0], assessments[0]


def metric(assessment):
    # Independently use complete account equity and explicitly include initial wealth.
    days = assessment['account']
    wealth = np.array([assessment['initial_cash']] + [x['equity'] for x in days], dtype=float)
    assert len(days) > 0 and np.isfinite(wealth).all() and (wealth > 0).all()
    return {'net_cagr': float((wealth[-1] / wealth[0]) ** (252 / len(days)) - 1),
            'drawdown_magnitude': float(np.max(1 - wealth / np.maximum.accumulate(wealth)))}


def reconcile(run, assessment):
    days = run['ledgers']['account_daily']['data']
    assessment_days = assessment['account']
    fills = run['ledgers']['fills']['data']
    assessed_fills = assessment['fills']
    assert len(days) == len(assessment_days) and len(fills) == len(assessed_fills)
    assert [x['date'][:10] for x in days] == sorted(set(x['date'][:10] for x in days))
    for day, assessed in zip(days, assessment_days, strict=True):
        assert day['date'][:10] == assessed['session']
        for k in ('cash', 'quantity', 'close', 'equity'):
            assert day[k] == assessed[k]
    by_date, cycle_flow, cycle_quantity = defaultdict(list), defaultdict(float), defaultdict(int)
    for actual, assessed in zip(fills, assessed_fills, strict=True):
        assert actual['fill_time'][:10] == assessed['session']
        for k in ('side', 'quantity', 'price', 'fees', 'cycle_id'):
            assert actual[k] == assessed[k]
        assert actual['side'] in ('BUY', 'SELL')
        assert actual['quantity'] > 0 and actual['quantity'] % 100 == 0
        by_date[actual['fill_time'][:10]].append(actual)
    assert set(by_date).issubset({x['date'][:10] for x in days})
    cash, quantity = assessment['opening_cash'], assessment['opening_quantity']
    assert quantity == 0
    rate = assessment['scenario_context']['one_way_cost']
    assert rate == .001
    maximum_cash_error = maximum_equity_error = maximum_fee_error = 0.
    for day in days:
        maximum_cash_error = max(maximum_cash_error, abs(cash - day['cash_before']))
        assert quantity == day['quantity_before']
        for fill in by_date[day['date'][:10]]:
            sign = 1 if fill['side'] == 'BUY' else -1
            turnover = fill['quantity'] * fill['price']
            maximum_fee_error = max(maximum_fee_error, abs(fill['fees'] - turnover * rate))
            flow = -sign * turnover - fill['fees']
            cash += flow
            quantity += sign * fill['quantity']
            cycle_flow[fill['cycle_id']] += flow
            cycle_quantity[fill['cycle_id']] += sign * fill['quantity']
            assert quantity >= 0 and cash >= -1e-6
        maximum_cash_error = max(maximum_cash_error, abs(cash - day['cash']))
        maximum_equity_error = max(maximum_equity_error,
                                   abs(day['equity'] - (day['cash'] + day['quantity'] * day['close'])))
        assert quantity == day['quantity'] and quantity % 100 == 0
    closed = {x['cycle_id']: x for x in assessment['closed_cycles']}
    assert len(closed) == len(assessment['closed_cycles'])
    assert all(cycle_quantity[k] == 0 for k in closed)
    assert set(closed).issubset(cycle_flow)
    open_ids = set(cycle_flow) - set(closed)
    assert all(cycle_quantity[k] > 0 for k in open_ids)
    assert sum(cycle_quantity.values()) == quantity
    profits = sum(cycle_flow[k] for k in closed)
    open_profit = sum(cycle_flow[k] + cycle_quantity[k] * days[-1]['close'] for k in open_ids)
    cash_profit_error = abs(profits + open_profit + assessment['opening_cash'] - days[-1]['equity'])
    assert max(maximum_cash_error, maximum_equity_error, maximum_fee_error, cash_profit_error) < 1e-6
    trades = run['ledgers']['trades']['data']
    assert {x['cycle_id'] for x in trades if x['status'] == 'CLOSED'} == set(closed)
    assert {x['cycle_id'] for x in trades if x['status'] == 'OPEN'} == open_ids
    assert len(trades) == len(closed) + len(open_ids)
    return {'maximum_cash_error': maximum_cash_error, 'maximum_equity_error': maximum_equity_error,
            'maximum_fee_error': maximum_fee_error, 'cash_profit_reconciliation_error': cash_profit_error,
            'closed_cycles': len(closed), 'open_cycles': len(open_ids), 'fee_rate': rate,
            'cash_quantity_fee_equity_reconciliation': 'PASS'}


def center_exact(old, fresh):
    old_run, _ = select(old)
    fresh_run, _ = select(fresh)
    assert set(old_run['ledgers']) == set(fresh_run['ledgers'])
    checks = {}
    for name, ledger in old_run['ledgers'].items():
        left = pd.DataFrame(ledger['data'])
        right = pd.DataFrame(fresh_run['ledgers'][name]['data'])
        assert set(left.columns) == set(right.columns) and len(left) == len(right)
        cols = [c for c in left if not c.endswith('_id')]
        pd.testing.assert_frame_equal(left[cols], right[cols], check_exact=True, check_dtype=True)
        checks[name] = {'rows': len(left), 'non_identity_fields_exact': True}
    return checks


def checked(raw, panel_row=None):
    run, assessment = select(raw)
    stats = metric(assessment)
    observed = run['observation']
    assert abs(stats['net_cagr'] - observed['net_cagr']) < 1e-12
    assert abs(stats['drawdown_magnitude'] - abs(observed['max_drawdown'])) < 1e-12
    if panel_row is not None:
        assert raw['request_hash'] == panel_row['request_hash']
        assert raw['result_hash'] == panel_row['result_hash']
        assert assessment['candidate']['content_sha256'] == panel_row['content_sha256']
        assert abs(stats['net_cagr'] - panel_row['metrics']['net_cagr']) < 1e-12
        assert abs(stats['drawdown_magnitude'] - abs(panel_row['metrics']['max_drawdown'])) < 1e-12
    return run, assessment, stats, reconcile(run, assessment)


def degradation(center, observations):
    q10 = float(np.quantile([x['net_cagr'] for x in observations], .1, method='linear'))
    q90 = float(np.quantile([x['drawdown_magnitude'] for x in observations], .9, method='linear'))
    return {'count': len(observations), 'q10_net_cagr': q10, 'q90_drawdown_magnitude': q90,
            'return_degradation': max(0., center['net_cagr'] - q10),
            'drawdown_worsening': max(0., q90 - center['drawdown_magnitude'])}


def main():
    plan = read(PLAN_PATH)
    plan_ref = read(PLAN_PATH.parent / 'plan_reference.json')
    assert SOURCES[PLAN_PATH.relative_to(ROOT).as_posix()]['sha256'] == plan_ref['sha256']
    results = {'status': 'PASS', 'plan_sha256': plan_ref['sha256'], 'strategies': {},
               'independent_accounts_validated': 0, 'account_evaluations_executed': 0}
    behaviors = {}
    for strategy, spec in plan['strategies'].items():
        experiment = spec['experiment']['experiment_id']
        root = ROOT / f'research/{strategy}/assets/runs/{experiment}'
        panel = read(root / 'panel_rebound.json')
        assert panel['status'] == 'COMPLETE'
        assert panel['count'] == panel['total'] == spec['unique_feasible_configurations']
        assert panel['plan']['sha256'] == plan_ref['sha256']
        rows = panel['rows']
        assert all(x['status'] == 'SUCCEEDED' for x in rows)
        by_id = {x['candidate_id']: x for x in rows}
        assert len(by_id) == len(rows)
        feasible = {x['candidate_id'] for x in spec['cases'] if 'candidate_id' in x}
        assert set(by_id) == feasible
        proof = read(root / 'center_rebound.json')
        assert proof['status'] == 'PASS' and proof['original'] == spec['parent_account']
        center_raw, old_center = evidence(proof['evidence']), evidence(proof['original'])
        exact = center_exact(old_center, center_raw)
        native_request = old_center['request_identity']
        native_fields = ('symbol', 'asset_type', 'initial_cash', 'data_cutoff', 'windows',
                         'price_basis', 'pricing', 'benchmark', 'frequency_window_days')
        assert all(center_raw['request_identity'][k] == native_request[k] for k in native_fields)
        baseline_cost = [x for x in native_request['costs'] if x['scenario_id'] == 'baseline']
        assert baseline_cost == [{'measurement_tier': 'FORMAL', 'one_way_cost': .001,
                                  'scenario_id': 'baseline'}]
        assert center_raw['request_identity']['costs'] == baseline_cost
        center_run, center_assessment, center_stats, center_cash = checked(center_raw)
        assert center_assessment['candidate']['content_sha256'] == spec['parent']['content_sha256']
        center_daily = center_run['ledgers']['account_daily']['data']
        center_dates = [x['date'] for x in center_daily]
        center_targets = [x['target_position'] for x in center_daily]
        point_results = {}
        for identifier, row in by_id.items():
            raw = evidence(row['evidence'])
            assert all(raw['request_identity'][k] == native_request[k] for k in native_fields)
            assert raw['request_identity']['costs'] == baseline_cost
            assert raw['request_identity']['content_sha256'] == row['content_sha256']
            assert raw['request_identity']['experiment_id'] == experiment
            run, assessment, stats, cash_check = checked(raw, row)
            matching_cases = [c for c in spec['cases'] if c.get('candidate_id') == identifier]
            assert all(c['content_sha256'] == row['content_sha256']
                       and c['source_sha256'] == row['source_sha256'] == spec['parent']['source_sha256']
                       for c in matching_cases)
            daily = run['ledgers']['account_daily']['data']
            assert [x['date'] for x in daily] == center_dates
            assert len(daily) == len(center_daily)
            changed = sum(a['target_position'] != b for a, b in zip(daily, center_targets, strict=True))
            fraction = changed / len(daily)
            assert changed == row['behavior_changed_sessions']
            assert len(daily) == row['behavior_total_sessions']
            assert fraction == row['behavior_change_fraction']
            point_results[identifier] = {'candidate_id': identifier, **stats,
                'behavior_changed_sessions': changed, 'behavior_total_sessions': len(daily),
                'behavior_change_fraction': fraction, 'reconciliation': cash_check,
                'evidence': row['evidence']}
        joint_summary, axis_summary = [], []
        behaviors[strategy] = {}
        for radius in plan['radii']:
            joint_cases = [c for c in spec['cases'] if c['kind'] == 'JOINT' and c['radius'] == radius]
            assert len(joint_cases) == 32
            observations = [point_results[c['candidate_id']] for c in joint_cases]
            joint_summary.append({'radius': radius, **degradation(center_stats, observations)})
            # Stable sorting preserves prospective point order for exact ties.
            behaviors[strategy][radius] = sorted(observations, key=lambda x: x['behavior_change_fraction'])
            for case in [c for c in spec['cases'] if c['kind'] == 'AXIS' and c['radius'] == radius]:
                record = {k: case[k] for k in ('radius', 'axis', 'sign', 'actual_radius', 'design_status')}
                if 'candidate_id' in case:
                    observation = point_results[case['candidate_id']]
                    record.update(candidate_id=case['candidate_id'], net_cagr=observation['net_cagr'],
                                  drawdown_magnitude=observation['drawdown_magnitude'],
                                  cagr_change=observation['net_cagr'] - center_stats['net_cagr'],
                                  drawdown_change=observation['drawdown_magnitude'] - center_stats['drawdown_magnitude'],
                                  behavior_change_fraction=observation['behavior_change_fraction'])
                axis_summary.append(record)
        results['strategies'][strategy] = {'unique_successful_configurations': len(rows),
            'cost_selection': {'parent_all_scenarios': native_request['costs'],
                               'supplement_declared_baseline_only': baseline_cost,
                               'all_points_and_center_costs_exact': True},
            'center_metrics': center_stats, 'center_original_account_exact': exact,
            'center_reconciliation': center_cash, 'joint_results': joint_summary,
            'axis_results_separate_from_joint': axis_summary, 'points': list(point_results.values())}
        results['independent_accounts_validated'] += len(rows)
    assert results['independent_accounts_validated'] == 300
    pairing = []
    for radius in plan['radii']:
        left, right = behaviors['S007'][radius], behaviors['S013'][radius]
        pairs, unmatched = [], []
        for rank, (a, b) in enumerate(zip(left, right, strict=True)):
            gap = abs(a['behavior_change_fraction'] - b['behavior_change_fraction'])
            record = {'rank': rank, 'gap': gap,
                'S007': {k: a[k] for k in ('candidate_id', 'behavior_change_fraction', 'net_cagr', 'drawdown_magnitude')},
                'S013': {k: b[k] for k in ('candidate_id', 'behavior_change_fraction', 'net_cagr', 'drawdown_magnitude')}}
            (pairs if gap <= .01 else unmatched).append(record)
        pairing.append({'radius': radius, 'matched_pairs': len(pairs), 'total_rank_pairs': 32,
                        'matching_rate': len(pairs) / 32, 'pairs': pairs, 'unmatched': unmatched,
                        'matching_uses_behavior_fraction_only': True})
    results['behavior_rank_pairing'] = pairing
    results['source_files'] = SOURCES
    results['script_sha256'] = sha256(Path(__file__).read_bytes()).hexdigest()
    results['limitations'] = ['No overall winner, economic gate, or point replacement.',
                              'Native market/account contexts differ; radius means equal declared standardized total parameter change.',
                              'Behavior rank matching is conditional diagnostic evidence, not causal identification or market-risk equivalence.',
                              'All economic observations are reused development data.']
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'results-audit.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 独立账户结果审计', '', '状态：PASS。300个唯一配置成功，正式账户证据与逐笔经济账本已核验。', '',
             '| 策略 | 总扰动距离 | 联合点 | 收益Q10 | 回撤Q90 | 年化退化 | 回撤恶化 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for strategy, result in results['strategies'].items():
        for row in result['joint_results']:
            lines.append(f"| {strategy} | {row['radius']:.2f} | {row['count']} | {row['q10_net_cagr'] * 100:.6f}% | {row['q90_drawdown_magnitude'] * 100:.6f}% | {row['return_degradation'] * 100:.6f}个百分点 | {row['drawdown_worsening'] * 100:.6f}个百分点 |")
    lines.extend(['', '行为对照只按改变比例排序配同名次，绝对差不超过1个百分点时保留：', ''])
    for row in pairing:
        lines.append(f"- 距离{row['radius']:.2f}：匹配{row['matched_pairs']}/32，覆盖率{row['matching_rate'] * 100:.2f}%。")
    lines.extend(['', '轴向检查独立列示，未混入32点联合分位统计；不判断总体赢家。'])
    (OUT / 'results-audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'status': results['status'], 'accounts_validated': results['independent_accounts_validated'],
                      'joint': {s: x['joint_results'] for s, x in results['strategies'].items()},
                      'matching': [{k: x[k] for k in ('radius', 'matched_pairs', 'matching_rate')} for x in pairing]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
