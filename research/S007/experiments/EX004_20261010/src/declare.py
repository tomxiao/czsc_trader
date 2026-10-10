"""Publish all point coordinates, bounds and handling before account outcomes."""
from hashlib import sha256
import json
import numpy as np

from aligned_common import (
    ROOT, BASE, PROTOCOLS, EXPERIMENTS, DEPENDENCIES, runs, original,
    read, write, material, context, candidate, fingerprint,
)
from design import S007_BOUNDS, S013_BOUNDS, RADII, JOINT_COUNT, joint, axes, center, distance


def main():
    assert not (PROTOCOLS/'plan_reference.json').exists(), 'No rewriting published design'
    audit = read(runs('S007')/'domain-audit.json')
    assert audit['status'] == 'PASS'
    protocol = {
        'version': 'aligned-normalized-distance-v1', 'declared_before_account_evaluation': True,
        'authorization': {'user_message': '同意，请执行', 'scope': 'Approved preceding aligned-distance design',
            'branch': 'codex/s007-v1-robustness', 'date': '2026-10-10',
            'excluded': ['new market samples/cutoffs', 'holdout', 'new economic gates',
                         'overall score/winner', 'platform/frozen edits', 'PTE/production', 'merge/tag/push']},
        'radii': list(RADII), 'joint_points_per_radius_per_strategy': JOINT_COUNT,
        'seed': 13, 'resources': {'workers': 4, 'native_threads': 1},
        'distance': 'sqrt(sum(((parameter-center)/(declared upper-lower))**2)); equal total distance, not equal per-parameter uncertainty',
        'joint_sampling': 'Gaussian normalized direction; nearest half-even integer lattice; preserve integer moves then rescale continuous remainder to exact radius; reject only prospective geometric infeasibility/duplicates. Mixed constrained distribution, not uniform sphere.',
        'geometry': 'Native domains/constraints preserved; accepted directions conditional on each feasible domain. Upper-bound window can move downward or remain fixed. Same radius does not make parameter semantics/domain shapes equivalent.',
        'axes': 'Every coordinate +/- each radius; nearest integer may change actual distance. Infeasible/no-change points recorded and not evaluated; do not pool these with matched-radius main results.',
        'quantiles': 'LINEAR Q10 CAGR and Q90 drawdown including initial equity. Retain all economic outcomes; no point replacement after evaluation.',
        'behavior_comparison': 'JOINT points only. Fraction of native executed-session target positions different from center; sort each strategy by change fraction and pair by rank within each radius, retain pairs only if absolute gap<=.01. Pairing does not inspect economic returns; report overlap/coverage and unmatched cases.',
        'no_automatic_retries': True, 'stopping': 'Complete prospective feasible points; technical failures retain error, no economic aggregates across missing points.',
        'native_contexts': {'S007': '588080.SH / 100000 / 2021-01-05..2026-09-02 / raw account / research observation adapter',
                           'S013': '510500.SH / 1000000 / 2020-01-02..2026-09-30 / HFQ_RESEARCH / exact C2132 implementation'},
        'fixed_rules': 'Original instruments, price roles, capital, fees10bp, structure switches, orientations, normalization, execution controls and inactive None filters. Test only declared8/13 active numerical coordinates.',
        'bound_basis': 'S007 five original group coordinates plus center-conditioned discovery-quantile numeric projections; S013 original parent primitive search envelopes and route-specific extensions. Integer interpolation newly declared, not historical exhaustive search.',
        'domain_audit': material('aligned-domain-audit', runs('S007')/'domain-audit.json').to_dict(),
        'source_files': [fingerprint(x) for x in sorted((BASE/'src').glob('*.py'))],
        'strategies': {},
    }
    for strategy in ('S007', 'S013'):
        old, previous, ref = original(strategy)
        params = json.loads(json.dumps(dict(old.strategy.payload['parameters']), default=dict))
        identifier = 'C9000' if strategy == 'S007' else 'C2132'
        identity = context(strategy, 1).runtime.identify(candidate(strategy, identifier, params), dependencies=DEPENDENCIES)
        assert identity.content_sha256 == context(strategy, 1).runtime.identify(old.strategy, dependencies=old.dependencies).content_sha256
        points, geometry = joint(strategy, params)
        axis_points = axes(strategy, params)
        all_cases = points+axis_points
        next_id = 9400 if strategy == 'S007' else 6000
        content_ids = {}
        for index, case in enumerate(all_cases):
            case['index'] = index
            if case.get('design_status', 'READY') != 'READY':
                continue
            key = sha256(json.dumps(case['parameters'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if key not in content_ids:
                content_ids[key] = f'C{next_id:04}'
                next_id += 1
            case['candidate_id'] = content_ids[key]
            child = candidate(strategy, case['candidate_id'], case['parameters'])
            child_identity = context(strategy, 1).runtime.identify(child, dependencies=DEPENDENCIES)
            assert child_identity.source_sha256 == identity.source_sha256
            context(strategy, 1).runtime.describe(child)
            case['content_sha256'] = child_identity.content_sha256
            case['source_sha256'] = child_identity.source_sha256
        c = center(strategy, params)
        bounds = S007_BOUNDS if strategy == 'S007' else S013_BOUNDS
        assert all(lo <= c[k] <= hi for k, (lo, hi) in bounds.items())
        for case in points:
            assert np.isclose(distance(c, case['coordinates'], bounds), case['radius'], atol=1e-12, rtol=0)
        protocol['strategies'][strategy] = {
            'experiment': EXPERIMENTS[strategy].to_dict(),
            'parent': {'strategy_id': strategy, 'candidate_id': identifier,
                       'content_sha256': identity.content_sha256, 'source_sha256': identity.source_sha256},
            'center_parameters': params, 'center_coordinates': c, 'bounds': bounds,
            'parent_account': ref.to_dict(), 'geometry': geometry, 'cases': all_cases,
            'declared_joint_points': len(points), 'declared_axis_points': len(axis_points),
            'unique_feasible_configurations': len(content_ids),
            'out_of_domain_or_no_change_axes': sum(x.get('design_status', 'READY') != 'READY' for x in axis_points),
        }
    write(PROTOCOLS/'plan.json', protocol)
    reference = material('aligned-distance-prospective-plan', PROTOCOLS/'plan.json')
    write(PROTOCOLS/'plan_reference.json', reference.to_dict())
    write(ROOT/'research/S013/experiments/EX010_20261010/protocols/shared_plan_reference.json', reference.to_dict())
    print({k: {x: v[x] for x in ('declared_joint_points', 'declared_axis_points', 'unique_feasible_configurations',
                               'out_of_domain_or_no_change_axes', 'geometry')}
           for k, v in protocol['strategies'].items()}, flush=True)


if __name__ == '__main__':
    main()
