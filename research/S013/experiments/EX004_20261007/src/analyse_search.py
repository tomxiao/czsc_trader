"""Freeze researcher calculations and same-configuration price comparisons."""
import json
from collections import Counter
from common import ROOT, RUNS, save, PROTOCOLS
from select_frontier import frontier


def main():
    rows = json.loads((RUNS / 'search_results.json').read_text(encoding='utf-8'))['rows']
    valid = [r for r in rows if r['status'] == 'SUCCEEDED']
    assert len({r['config_hash'] for r in valid}) == len(valid)
    old = json.loads((ROOT / 'research/S013/assets/runs/EX003_20261007/historical/search_results.json').read_text(encoding='utf-8'))['rows']
    old_success = {r['config_hash']: r for r in old if r['status'] == 'SUCCEEDED'}
    old_baseline = json.loads((ROOT / 'research/S013/assets/runs/EX003_20261007/historical/economic_verification.json').read_text(encoding='utf-8'))['full_gate_summary']
    matched = []
    for row in valid:
        if row['config_hash'] not in old_success:
            continue
        previous = old_success[row['config_hash']]
        assert row['parameters'] == previous['parameters']
        matched.append({'config_hash': row['config_hash'], 'raw_candidate_id': previous['candidate_id'],
            'hfq_candidate_id': row['candidate_id'],
            'raw_net_cagr': previous['net_cagr'], 'hfq_net_cagr': row['net_cagr'],
            'raw_buyhold_cagr': previous['buyhold_cagr'], 'hfq_buyhold_cagr': row['buyhold_cagr'],
            'raw_closed_trades': previous['closed_trades'], 'hfq_closed_trades': row['closed_trades'],
            'raw_gates': previous['gates'], 'hfq_gates': row['gates'],
            'raw_result_hash': previous['result_hash'], 'hfq_result_hash': row['result_hash']})
    groups = {}
    for name in sorted({r['search'] for r in rows}):
        group = [r for r in rows if r['search'] == name]
        successful = [r for r in group if r['status'] == 'SUCCEEDED']
        groups[name] = {'evaluations': len(group), 'successes': len(successful),
            'statuses': dict(Counter(r['status'] for r in group)),
            'unique_configurations': len({r['config_hash'] for r in successful}),
            'qualified': sum(r['qualified'] for r in successful),
            'best_return': None if not successful else max(successful, key=lambda r: r['net_cagr'])['candidate_id']}
    centers = set()
    for path in PROTOCOLS.glob('*followup*plan.json'):
        decision = json.loads(path.read_text(encoding='utf-8'))['decision']
        for key in ('frequency_DD_center', 'return_center', 'risk_center'):
            if key in decision:
                centers.add(decision[key]['candidate_id'])
    selected = frontier(rows, centers)
    domains = {}
    for key in valid[0]['parameters']:
        numbers = sorted({r['parameters'][key] for r in valid if r['parameters'][key] is not None})
        domains[key] = {'values': numbers, 'none_count': sum(r['parameters'][key] is None for r in valid)}
    result = {
        'evaluations': len(rows), 'unique_successful_configurations': len(valid),
        'statuses': dict(Counter(r['status'] for r in rows)),
        'gate_pass_counts': {k: sum(r['gates'][k] for r in valid) for k in valid[0]['gates']},
        'qualified_ids': [r['candidate_id'] for r in valid if r['qualified']],
        'retained_frontier_and_controls': [r['candidate_id'] for r in selected],
        'frontier_definition': '逐年回撤通过集合中的净年化/频率二维非支配配置；频率在4处截断，达标后不额外偏好更高频率；全部达标配置保留，另留基线、最高收益反证与搜索启发式最小缺口对照。此集合用于阶段三解释，未作阶段四排序。',
        'groups': groups, 'actual_parameter_values': domains,
        'old_raw_search_statuses': dict(Counter(r['status'] for r in old)),
        'old_account_request_schema': 3,
        'old_account_evidence_use': '旧schema3账户原件保持不可变；本轮schema4价格契约的新评价重新计算，旧统计仅用于同配置历史对照，不作为本轮可复验的新账户证据',
        'baseline_price_change': {name: {'raw': old_baseline[name], 'hfq': valid[0][name]}
                                  for name in ('net_cagr', 'buyhold_cagr', 'return_threshold', 'closed_trades')},
        'matched_old_unique_configurations': len(matched),
        'same_configuration_price_comparisons': matched,
        'selection_history': '旧配置由EX003原始价格目标选择；EX004先固定重算全部成功配置，再以新账本确定局部扩边与反证。整个开发池用于选择，无独立封存样本。',
    }
    save('search_analysis.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in (
        'actual_parameter_values', 'same_configuration_price_comparisons')}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
