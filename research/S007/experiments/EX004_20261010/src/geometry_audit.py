"""Independent arithmetic and runtime-contract audit; never evaluates accounts."""
# ruff: noqa: E402
from copy import deepcopy
from hashlib import sha256
import json
from math import sqrt
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / 'research/S007/experiments/EX004_20261010'
sys.path.insert(0, str(BASE / 'src'))
from aligned_common import candidate, context, original, DEPENDENCIES

INTEGERS = {'bull.range_window', 'bear.range_window', 'bull.max_hold', 'bear.max_hold',
            'regime_window', 'confirmation.lookback'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def get(parameters, name):
    for part in name.split('.'):
        parameters = parameters[part]
    return parameters


def put(parameters, name, value):
    parts = name.split('.')
    for part in parts[:-1]:
        parameters = parameters[part]
    parameters[parts[-1]] = value


def coordinates(strategy, parameters):
    if strategy == 'S013':
        return {k: get(parameters, k) for k in PLAN['strategies'][strategy]['bounds']}
    score = parameters['rule']['score']
    w = score['base_weights']
    risk = w['price_intraday_range'] + w['risk_shibor_on_change_5d']
    opportunity = w['risk_global_spx_return'] + w['risk_chinext_turnover_z20']
    return {'risk_context_total': risk, 'opportunity_share_nonrisk': opportunity / (1 - risk),
            'opp_spx_fraction': w['risk_global_spx_return'] / opportunity,
            'risk_shibor_fraction': w['risk_shibor_on_change_5d'] / risk,
            'confirm_share_fraction': score['confirmation_weights']['micro_share_change_5d_lag1'],
            **{k: score[k] for k in ('entry_threshold', 'exit_threshold', 'confirmation_threshold')}}


def valid(strategy, values, bounds):
    if any(not lo <= values[k] <= hi for k, (lo, hi) in bounds.items()):
        return False
    if strategy == 'S013':
        return all(values[r + '.entry'] < values[r + '.exit'] for r in ('bull', 'bear'))
    risk = values['risk_context_total']
    opportunity = (1 - risk) * values['opportunity_share_nonrisk']
    weights = ((1 - risk) * (1 - values['opportunity_share_nonrisk']),
               risk * (1 - values['risk_shibor_fraction']),
               risk * values['risk_shibor_fraction'],
               opportunity * values['opp_spx_fraction'],
               opportunity * (1 - values['opp_spx_fraction']))
    return values['exit_threshold'] < values['entry_threshold'] and max(weights) <= .35


def norm(a, b, bounds):
    return sqrt(sum(((b[k] - a[k]) / (hi - lo)) ** 2 for k, (lo, hi) in bounds.items()))


def replay_geometry(strategy, center, bounds):
    names = list(bounds)
    widths = np.array([hi - lo for lo, hi in bounds.values()])
    origin = np.array([center[k] for k in names])
    integer = np.array([strategy == 'S013' and k in INTEGERS for k in names])
    rng = np.random.default_rng(13)
    records = []
    for radius in PLAN['radii']:
        accepted, attempts, rejected, seen = [], 0, {}, set()
        while len(accepted) < 32:
            attempts += 1
            assert attempts < 100000
            unit = rng.standard_normal(len(names))
            unit /= np.linalg.norm(unit)
            desired = radius * unit
            proposed = origin + desired * widths
            proposed[integer] = np.round(proposed[integer])
            actual_integer = (proposed[integer] - origin[integer]) / widths[integer]
            integer_energy = float(np.dot(actual_integer, actual_integer))
            if integer_energy >= radius * radius:
                rejected['integer_radius'] = rejected.get('integer_radius', 0) + 1
                continue
            # Recreate original operations, retaining a separately checked norm.
            desired[integer] = actual_integer
            scale = sqrt((radius * radius - integer_energy)
                         / float(np.sum(desired[~integer] ** 2)))
            proposed[~integer] = origin[~integer] + widths[~integer] * desired[~integer] * scale
            values = {k: int(v) if flag else float(v)
                      for k, v, flag in zip(names, proposed, integer, strict=True)}
            if not valid(strategy, values, bounds):
                rejected['domain_or_constraints'] = rejected.get('domain_or_constraints', 0) + 1
                continue
            key = tuple(values.values())
            if key in seen:
                rejected['duplicate'] = rejected.get('duplicate', 0) + 1
                continue
            seen.add(key)
            accepted.append(values)
        records.append({'radius': radius, 'attempts': attempts, 'accepted': accepted,
                        'geometric_rejections': rejected})
    return records


PLAN = read(BASE / 'protocols/plan.json')


def main():
    result = {'status': 'PASS', 'plan_sha256': sha256((BASE / 'protocols/plan.json').read_bytes()).hexdigest(),
              'script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(), 'strategies': {},
              'accounts_evaluated': 0, 'blocking_findings': []}
    unique_total = 0
    for strategy, spec in PLAN['strategies'].items():
        bounds, center = spec['bounds'], spec['center_coordinates']
        params = spec['center_parameters']
        old, _, _ = original(strategy)
        original_params = json.loads(json.dumps(dict(old.strategy.payload['parameters']), default=dict))
        assert params == original_params
        measured_center = coordinates(strategy, params)
        assert max(abs(measured_center[k] - center[k]) for k in center) < 1e-14
        assert len(bounds) == (8 if strategy == 'S007' else 13)
        regenerated = replay_geometry(strategy, center, bounds)
        cases = spec['cases']
        summaries, identities = [], {}
        for radius_record, geometry in zip(regenerated, spec['geometry'], strict=True):
            radius = radius_record['radius']
            joint = [x for x in cases if x['kind'] == 'JOINT' and x['radius'] == radius]
            assert len(joint) == 32
            assert radius_record['attempts'] == geometry['attempts']
            assert radius_record['geometric_rejections'] == geometry['geometric_rejections']
            reconstruction_errors = []
            integer_change_counts = {k: 0 for k in bounds if strategy == 'S013' and k in INTEGERS}
            for independent, case in zip(radius_record['accepted'], joint, strict=True):
                coordinate_error = max(abs(independent[k] - case['coordinates'][k]) for k in bounds)
                assert coordinate_error < 1e-14
                physical = coordinates(strategy, case['parameters'])
                assert max(abs(physical[k] - case['coordinates'][k]) for k in bounds) < 1e-14
                actual = norm(measured_center, physical, bounds)
                assert abs(actual - radius) < 1e-12
                reconstruction_errors.append(abs(actual - radius))
                for k in integer_change_counts:
                    assert type(physical[k]) is int
                    integer_change_counts[k] += physical[k] != measured_center[k]
            summaries.append({'radius': radius, 'joint_count': len(joint),
                              'maximum_actual_radius_error': max(reconstruction_errors),
                              'integer_changed_point_counts': integer_change_counts,
                              'geometric_rejections': geometry['geometric_rejections'],
                              'attempts': geometry['attempts']})
        for case in cases:
            physical = coordinates(strategy, case['parameters'])
            assert max(abs(physical[k] - case['coordinates'][k]) for k in bounds) < 1e-14
            unchanged = deepcopy(case['parameters'])
            if strategy == 'S013':
                for k in bounds:
                    put(unchanged, k, get(params, k))
            else:
                unchanged['rule']['score'] = deepcopy(params['rule']['score'])
                assert case['parameters']['rule']['score']['orientations'] == params['rule']['score']['orientations']
                assert abs(sum(case['parameters']['rule']['score']['base_weights'].values()) - 1) < 1e-14
                assert abs(sum(case['parameters']['rule']['score']['confirmation_weights'].values()) - 1) < 1e-14
            assert unchanged == params
            actual = norm(center, case['coordinates'], bounds)
            assert abs(actual - case['actual_radius']) < 1e-14
            status = case.get('design_status', 'READY')
            expected = ('NO_PARAMETER_CHANGE' if actual == 0 else
                        'READY' if valid(strategy, case['coordinates'], bounds) else 'OUTSIDE_DOMAIN_OR_CONSTRAINT')
            assert status == expected
            if status != 'READY':
                assert 'candidate_id' not in case
                continue
            identifier = case['candidate_id']
            child = candidate(strategy, identifier, case['parameters'])
            runtime = context(strategy, 1).runtime
            identity = runtime.identify(child, dependencies=DEPENDENCIES)
            assert identity.content_sha256 == case['content_sha256']
            assert identity.source_sha256 == case['source_sha256'] == spec['parent']['source_sha256']
            if identifier not in identities:
                runtime.describe(child)
                identities[identifier] = identity.content_sha256
            else:
                assert identities[identifier] == identity.content_sha256
        assert len(identities) == spec['unique_feasible_configurations']
        result['strategies'][strategy] = {'dimensions': len(bounds), 'center_unchanged': True,
            'fixed_parameters_unchanged': True, 'joint_geometry': summaries,
            'unique_runtime_describe_passed': len(identities),
            'nonready_axes': sum(c.get('design_status', 'READY') != 'READY' for c in cases),
            'point_coordinates_match_actual_payload': True}
        unique_total += len(identities)
    assert unique_total == 300
    result['unique_runtime_describe_passed'] = unique_total
    result['limitations'] = ['Mixed constrained distribution; does not claim uniform sphere.',
                             'Matched standardized total radius answers equal total parameter error; individual semantics, feasible domain shapes and native market/account contexts differ.',
                             'Integer axes have actual radii after rounding; never pool them with exact-radius JOINT results.',
                             'Parameter bounds encode historical coordinate choices and center-conditioned threshold projections, not an invariant economic-risk metric.',
                             'All samples remain reused development data; no out-of-sample inference.']
    (ROOT / 'research/S007/assets/runs/EX004_20261010/geometry-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
