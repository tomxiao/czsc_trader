"""Reconcile all four literal gates and retain the relevant feasible frontier."""
from collections import Counter
import json
from common import WORK, save


def main():
    rows = json.loads((WORK / 'search_results_r4.json').read_text(encoding='utf-8'))['rows']
    valid = [r for r in rows if r['status'] == 'SUCCEEDED']
    assert len(valid) == len({r['config_hash'] for r in valid})
    assert all(r['qualified'] == all(r['gates'].values()) for r in valid)
    feasible = [r for r in valid if r['gates']['annual_drawdown']
                and r['gates']['negative_buyhold_year_profit']]
    frontier = []
    for row in feasible:
        x, y = row['net_cagr'], min(row['frequency60'], 4.)
        if not any(o['net_cagr'] >= x and min(o['frequency60'], 4.) >= y
                   and (o['net_cagr'] > x or min(o['frequency60'], 4.) > y) for o in feasible):
            frontier.append(row['candidate_id'])
    qualified = [r['candidate_id'] for r in valid if r['qualified']]
    adaptive = [r for r in valid if 'bull' in r['parameters']]
    new = [r for r in valid if r['search'].startswith('four_gate')]
    highlights = {
        'old_high_return': 'C0385', 'old_sparse_positive': 'C0315', 'old_deep_positive': 'C0058',
        'same_adaptive_without_state_exit': 'C0439',
        'closest_four_gate_deficit': min(valid, key=lambda r: r['deficit'])['candidate_id'],
        'highest_adaptive_return': max(adaptive, key=lambda r: r['net_cagr'])['candidate_id'],
        'closest_adaptive_deficit': min(adaptive, key=lambda r: r['deficit'])['candidate_id'],
    }
    frequent = [r for r in feasible if r['gates']['frequency']]
    if frequent:
        highlights['highest_return_with_other_three_gates'] = max(frequent, key=lambda r: r['net_cagr'])['candidate_id']
    retained = sorted(set(frontier + qualified + list(highlights.values())))
    by_id = {r['candidate_id']: r for r in valid}
    groups = {}
    for name in sorted({r['search'] for r in rows}):
        attempts = [r for r in rows if r['search'] == name]
        success = [r for r in attempts if r['status'] == 'SUCCEEDED']
        groups[name] = {'attempts': len(attempts), 'successful_configurations': len(success),
                        'qualified': sum(r['qualified'] for r in success),
                        'states': dict(Counter(r['status'] for r in attempts))}
    value = {'attempts_total': len(rows), 'successful_configurations': len(valid),
             'new_successful_configurations': len(new), 'new_attempts': sum(r['search'].startswith('four_gate') for r in rows),
             'states': dict(Counter(r['status'] for r in rows)), 'groups': groups,
             'gate_pass_counts': {k: sum(r['gates'][k] for r in valid) for k in valid[0]['gates']},
             'qualified_ids': qualified, 'feasible_return_frequency_frontier': frontier,
             'frontier_definition': '先满足逐年回撤与负基准年份盈利，在收益/截断到4的平均频率上保留非支配点；并保留全部四项目标达标配置及必要反证。阶段三展示，不是阶段四排序。',
             'retained_ids': retained, 'highlights': highlights,
             'retained_rows': [by_id[c] for c in retained],
             'selection_history': '旧378配置、2022/2023已知结果、当轮结果用于后续设计；无独立样本外数据，不推断未来年度盈利保证。'}
    save('four_gate_search_analysis.json', value)
    print(json.dumps({k: v for k, v in value.items() if k not in ('retained_rows', 'groups')}, ensure_ascii=False))
    for c in highlights.values():
        r = by_id[c]
        print(json.dumps({k: r[k] for k in ('candidate_id', 'net_cagr', 'closed_trades', 'gates', 'deficit')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
