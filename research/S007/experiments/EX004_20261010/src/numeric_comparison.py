"""Compare released analysis outputs against independent account arithmetic."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[5]
RUN = ROOT / 'research/S007/assets/runs/EX004_20261010'
checks = []


def check(path, a, b):
    assert a == b, (path, a, b)
    checks.append({'path': path, 'exact': True,
                   'absolute_difference': abs(a-b) if isinstance(a, (int, float)) else None})


def read(path):
    return json.loads(path.read_bytes())


def parameter(parameters, axis):
    for key in axis.split('.'):
        parameters = parameters[key]
    return parameters


def main():
    aligned = read(RUN / 'aligned_results.json')
    independent = read(RUN / 'results-audit.json')
    plan_path = ROOT / 'research/S007/experiments/EX004_20261010/protocols/plan.json'
    plan = read(plan_path)
    check('status', aligned['status'], independent['status'])
    check('plan_sha256', aligned['plan']['sha256'], independent['plan_sha256'])
    check('unique_perturbation_accounts', sum(s['unique_accounts'] for s in aligned['strategies'].values()),
          independent['independent_accounts_validated'])
    check('complete_accounts_including_two_centers', aligned['validated_complete_accounts'],
          independent['independent_accounts_validated'] + 2)
    separate_axes = {}
    sensitivities = {}
    for strategy, spec in plan['strategies'].items():
        a, b = aligned['strategies'][strategy], independent['strategies'][strategy]
        check(f'{strategy}.center.cagr', a['center']['net_cagr'], b['center_metrics']['net_cagr'])
        check(f'{strategy}.center.dd', a['center']['drawdown'], b['center_metrics']['drawdown_magnitude'])
        curves = {c['radius']: c for c in a['curves']}
        for c in b['joint_results']:
            k = curves[c['radius']]
            for left, right in [('count', 'count'), ('q10_cagr', 'q10_net_cagr'),
                                ('q90_drawdown', 'q90_drawdown_magnitude'),
                                ('cagr_degradation', 'return_degradation'),
                                ('drawdown_worsening', 'drawdown_worsening')]:
                check(f'{strategy}.R={c["radius"]}.{left}', k[left], c[right])
            joint_ids = [x['candidate_id'] for x in spec['cases'] if x['kind'] == 'JOINT' and x['radius'] == c['radius']]
            audit_points = {p['candidate_id']: p for p in b['points']}
            check(f'{strategy}.R={c["radius"]}.mean_cagr_change', k['mean_cagr_change'],
                  float(np.mean([audit_points[i]['net_cagr'] - b['center_metrics']['net_cagr'] for i in joint_ids])))
            for q in (.1, .9):
                check(f'{strategy}.R={c["radius"]}.behavior_fraction_q{int(q*100)}',
                      k[f'behavior_fraction_q{int(q*100)}'],
                      float(np.quantile([audit_points[i]['behavior_change_fraction'] for i in joint_ids], q, method='linear')))
        points = {p['candidate_id']: p for p in b['points']}
        expected = Counter(c['kind'] for c in spec['cases'])
        check(f'{strategy}.point_kind_counts', dict(Counter(p['kind'] for p in a['points'])), dict(expected))
        for p in a['points']:
            if 'candidate_id' not in p:
                continue
            q = points[p['candidate_id']]
            for left, right in [('net_cagr', 'net_cagr'), ('drawdown', 'drawdown_magnitude'),
                                ('behavior_change_fraction', 'behavior_change_fraction')]:
                check(f'{strategy}.{p["index"]}.{left}', p[left], q[right])
        axes = {(p['radius'], p['axis'], p['sign']): p for p in a['points'] if p['kind'] == 'AXIS'}
        check(f'{strategy}.axis_count', len(axes), len(b['axis_results_separate_from_joint']))
        for p in b['axis_results_separate_from_joint']:
            q = axes[(p['radius'], p['axis'], p['sign'])]
            check(f'{strategy}.axis.{p["radius"]}.{p["axis"]}.{p["sign"]}.radius', q['actual_radius'], p['actual_radius'])
            check(f'{strategy}.axis.{p["radius"]}.{p["axis"]}.{p["sign"]}.candidate', q.get('candidate_id'), p.get('candidate_id'))
            if 'candidate_id' in p:
                for left, right in [('net_cagr', 'net_cagr'), ('drawdown', 'drawdown_magnitude'),
                                    ('cagr_change', 'cagr_change'), ('drawdown_change', 'drawdown_change')]:
                    check(f'{strategy}.axis.{p["radius"]}.{p["axis"]}.{p["sign"]}.{left}', q[left], p[right])
            else:
                check(f'{strategy}.axis.{p["radius"]}.{p["axis"]}.{p["sign"]}.status', q['design_status'], p['design_status'])
        separate_axes[strategy] = {'all_declared_axes': len(axes),
            'feasible_axis_records': sum('candidate_id' in p for p in axes.values()),
            'nonexecuted_axis_records': sum('candidate_id' not in p for p in axes.values()),
            'joint_each_radius': [c['count'] for c in b['joint_results']],
            'axes_excluded_from_joint_quantiles': True}
        if strategy == 'S013':
            feasible = [p for p in b['axis_results_separate_from_joint'] if 'candidate_id' in p]
            def detail(point):
                case = next(c for c in spec['cases'] if c.get('candidate_id') == point['candidate_id'])
                return {**point, 'before': parameter(spec['center_parameters'], point['axis']),
                        'after': parameter(case['parameters'], point['axis']),
                        'return_degradation_pp': -100 * point['cagr_change'],
                        'drawdown_worsening_pp': 100 * point['drawdown_change']}
            sensitivities['S013'] = {'worst_feasible_return_axis': detail(min(feasible, key=lambda p: p['cagr_change'])),
                'worst_feasible_drawdown_axis': detail(max(feasible, key=lambda p: p['drawdown_change'])),
                'each_radius': []}
            for radius in plan['radii']:
                group = [p for p in feasible if p['radius'] == radius]
                sensitivities['S013']['each_radius'].append({'radius': radius,
                    'worst_return_axis': detail(min(group, key=lambda p: p['cagr_change'])),
                    'worst_drawdown_axis': detail(max(group, key=lambda p: p['drawdown_change']))})
    coverage = []
    for pairing in independent['behavior_rank_pairing']:
        radius = pairing['radius']
        x = aligned['behavior_pairs'][str(radius)]
        check(f'pairing.{radius}.matched', x['matched'], pairing['matched_pairs'])
        check(f'pairing.{radius}.coverage', x['coverage'], pairing['matching_rate'])
        check(f'pairing.{radius}.available', x['available_each'], pairing['total_rank_pairs'])
        check(f'pairing.{radius}.tolerance', x['tolerance'], .01)
        groups = [sorted([p for p in aligned['strategies'][s]['points'] if p['kind'] == 'JOINT' and p['radius'] == radius],
                         key=lambda p: (p['behavior_change_fraction'], p['candidate_id'])) for s in ('S007', 'S013')]
        audit_all = {p['rank']: p for p in pairing['pairs'] + pairing['unmatched']}
        check(f'pairing.{radius}.all_rank_count', len(audit_all), 32)
        for rank, (left, right) in enumerate(zip(*groups, strict=True)):
            for s, p in [('S007', left), ('S013', right)]:
                check(f'pairing.{radius}.{rank}.{s}.candidate', p['candidate_id'], audit_all[rank][s]['candidate_id'])
                check(f'pairing.{radius}.{rank}.{s}.fraction', p['behavior_change_fraction'], audit_all[rank][s]['behavior_change_fraction'])
        for p, q in zip(x['pairs'], pairing['pairs'], strict=True):
            check(f'pairing.{radius}.{p["rank"]}.rank', p['rank'], q['rank'])
            check(f'pairing.{radius}.{p["rank"]}.gap', p['fraction_gap'], q['gap'])
            for s in ('S007', 'S013'):
                for left, right in [('candidate_id', 'candidate_id'), ('net_cagr', 'net_cagr'),
                                    ('drawdown', 'drawdown_magnitude'), ('behavior_change_fraction', 'behavior_change_fraction')]:
                    check(f'pairing.{radius}.{p["rank"]}.{s}.{left}', p[s][left], q[s][right])
        for s in ('S007', 'S013'):
            expected_mean = float(np.mean([p[s]['net_cagr'] - independent['strategies'][s]['center_metrics']['net_cagr']
                                           for p in pairing['pairs']])) if pairing['pairs'] else None
            check(f'pairing.{radius}.{s}.mean_cagr_change', x[f'{s}_mean_cagr_change'], expected_mean)
        coverage.append({'radius': radius, 'matched': x['matched'], 'coverage': x['coverage'],
                         'unmatched_retained_in_independent_audit': len(pairing['unmatched']),
                         'all32_rank_order_exact': True})
    sources = {}
    for path in (RUN / 'aligned_results.json', RUN / 'results-audit.json', plan_path,
                 ROOT / 'research/S007/experiments/EX004_20261010/src/results_audit.py', Path(__file__)):
        blob = path.read_bytes()
        sources[path.relative_to(ROOT).as_posix()] = {'sha256': sha256(blob).hexdigest(), 'bytes': len(blob)}
    result = {'status': 'PASS', 'comparison_count': len(checks), 'difference_count': 0,
              'maximum_numeric_absolute_difference': max(c['absolute_difference'] or 0 for c in checks),
              'accounts': {'perturbations': 300, 'current_centers': 2, 'current_complete_accounts': 302,
                           'additional_original_center_controls_checked': 2, 'new_accounts_executed': 0},
              'axis_separation': separate_axes, 'behavior_pairing': coverage,
              'requested_axis_sensitivity_diagnostics': sensitivities, 'checks': checks, 'sources': sources,
              'limitations': ['No overall winner, economic gate, point replacement, or out-of-sample inference.',
                              'Reported worst axis directions describe only prospectively sampled feasible axes.']}
    (RUN / 'numeric-comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'comparison_count', 'difference_count', 'maximum_numeric_absolute_difference',
                                          'behavior_pairing', 'requested_axis_sensitivity_diagnostics')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
