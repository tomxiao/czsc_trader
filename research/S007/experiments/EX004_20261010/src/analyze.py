"""Matched-radius diagnostics from immutable complete account evidence."""
from hashlib import sha256
import numpy as np
import pandas as pd

from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from aligned_common import ROOT, PROTOCOLS, runs, read, write, material


def load(reference):
    ref = EvidenceRef.from_dict(reference)
    value = read(ref.resolve(ROOT))
    validate_evaluation_evidence(value)
    return value


def metrics(raw):
    ev = next(x for x in raw['assessment_evidence'] if x['scenario_id'] == 'baseline')
    wealth = np.r_[ev['initial_cash'], [x['equity'] for x in ev['account']]]
    result = {'net_cagr': float((wealth[-1]/wealth[0])**(252/len(ev['account']))-1),
              'drawdown': float(np.max(1-wealth/np.maximum.accumulate(wealth)))}
    obs = next(x['observation'] for x in raw['runs'] if x['scenario_id'] == 'baseline')
    assert abs(result['net_cagr']-obs['net_cagr']) < 1e-12
    assert abs(result['drawdown']-abs(obs['max_drawdown'])) < 1e-12
    account = pd.DataFrame(next(x for x in raw['runs'] if x['scenario_id'] == 'baseline')['ledgers']['account_daily']['data'])
    return result, account


def main():
    plan = read(PROTOCOLS/'plan.json')
    summary = {'status': 'PASS', 'plan': read(PROTOCOLS/'plan_reference.json'),
               'interpretation': 'Same normalized total radius under declared native domains; conditional finite development-pool diagnostics, not intrinsic/global robustness or overall winner.',
               'strategies': {}, 'behavior_pairs': {}, 'references': []}
    all_rows = []
    for strategy, spec in plan['strategies'].items():
        panel = read(runs(strategy)/'panel_rebound.json')
        assert panel['status'] == 'COMPLETE' and panel['count'] == spec['unique_feasible_configurations']
        center_ref = read(runs(strategy)/'center_rebound.json')['evidence']
        center_metrics, center_account = metrics(load(center_ref))
        summary['references'].append(center_ref)
        evaluated = {}
        for row in panel['rows']:
            assert row['status'] == 'SUCCEEDED'
            value = load(row['evidence'])
            m, account = metrics(value)
            pd.testing.assert_series_equal(account.date, center_account.date, check_exact=True)
            fraction = float(np.mean(account.target_position.to_numpy() != center_account.target_position.to_numpy()))
            assert fraction == row['behavior_change_fraction']
            assert row['content_sha256'] == next(x['content_sha256'] for x in spec['cases'] if x.get('candidate_id') == row['candidate_id'])
            evaluated[row['candidate_id']] = {**m, 'behavior_change_fraction': fraction}
            summary['references'].append(row['evidence'])
        points, curves = [], []
        for case in spec['cases']:
            point = {k: case[k] for k in ('index', 'kind', 'radius', 'actual_radius')}
            point['strategy'] = strategy
            if 'candidate_id' in case:
                point.update(candidate_id=case['candidate_id'], **evaluated[case['candidate_id']])
                point['cagr_change'] = point['net_cagr']-center_metrics['net_cagr']
                point['drawdown_change'] = point['drawdown']-center_metrics['drawdown']
            else:
                point['design_status'] = case['design_status']
            for key in ('axis', 'sign'):
                if key in case:
                    point[key] = case[key]
            points.append(point)
        for radius in plan['radii']:
            group = [x for x in points if x['kind'] == 'JOINT' and x['radius'] == radius]
            assert len(group) == 32 and all(abs(x['actual_radius']-radius) < 1e-12 for x in group)
            q10 = float(np.quantile([x['net_cagr'] for x in group], .1, method='linear'))
            q90 = float(np.quantile([x['drawdown'] for x in group], .9, method='linear'))
            curves.append({'radius': radius, 'count': 32, 'q10_cagr': q10, 'q90_drawdown': q90,
                           'cagr_degradation': max(0., center_metrics['net_cagr']-q10),
                           'drawdown_worsening': max(0., q90-center_metrics['drawdown']),
                           'mean_cagr_change': float(np.mean([x['cagr_change'] for x in group])),
                           'behavior_fraction_q10': float(np.quantile([x['behavior_change_fraction'] for x in group], .1)),
                           'behavior_fraction_q90': float(np.quantile([x['behavior_change_fraction'] for x in group], .9))})
        summary['strategies'][strategy] = {'center': center_metrics, 'curves': curves, 'points': points,
            'unique_accounts': len(evaluated), 'domain_geometry': spec['geometry']}
        all_rows.extend(points)
    for radius in plan['radii']:
        groups = [sorted([x for x in summary['strategies'][s]['points'] if x['kind'] == 'JOINT' and x['radius'] == radius],
                         key=lambda x: (x['behavior_change_fraction'], x['candidate_id'])) for s in ('S007', 'S013')]
        pairs = []
        for rank, (a, b) in enumerate(zip(*groups, strict=True)):
            gap = abs(a['behavior_change_fraction']-b['behavior_change_fraction'])
            if gap <= .01:
                pairs.append({'rank': rank, 'S007': a, 'S013': b, 'fraction_gap': gap})
        summary['behavior_pairs'][str(radius)] = {'pairs': pairs, 'matched': len(pairs),
            'available_each': 32, 'coverage': len(pairs)/32, 'tolerance': .01,
            'S007_mean_cagr_change': float(np.mean([x['S007']['cagr_change'] for x in pairs])) if pairs else None,
            'S013_mean_cagr_change': float(np.mean([x['S013']['cagr_change'] for x in pairs])) if pairs else None}
    summary['validated_complete_accounts'] = len(summary['references'])
    assert summary['validated_complete_accounts'] == 302
    write(runs('S007')/'aligned_results.json', summary)
    pd.DataFrame(all_rows).to_csv(runs('S007')/'aligned_points.csv', index=False)
    ref = material('aligned-distance-results', runs('S007')/'aligned_results.json')
    write(PROTOCOLS/'results_reference.json', ref.to_dict())
    print({s: summary['strategies'][s]['curves'] for s in ('S007', 'S013')}, flush=True)
    print({'validated_complete_accounts': 302,
           'behavior_pair_coverage': {k: v['matched'] for k, v in summary['behavior_pairs'].items()},
           'sha256': sha256((runs('S007')/'aligned_results.json').read_bytes()).hexdigest()}, flush=True)


if __name__ == '__main__':
    main()
