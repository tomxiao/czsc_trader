"""Common normalized Euclidean radius, with disclosed mixed-domain geometry."""
from copy import deepcopy
from math import sqrt
import numpy as np

from aligned_common import OLD, read

S007_BOUNDS = {
    'risk_context_total': (.10, .35), 'opportunity_share_nonrisk': (.50, .80),
    'opp_spx_fraction': (.25, .75), 'confirm_share_fraction': (.25, .75),
    'risk_shibor_fraction': (.25, .75),
    'entry_threshold': (-.01473815381505864, .11611323419703372),
    'exit_threshold': (-.10897658738936969, .060999012644694345),
    'confirmation_threshold': (-.4703754547068948, .05577996427635461),
}
S013_BOUNDS = {
    'bull.range_window': (30, 360), 'bear.range_window': (30, 360),
    'bull.entry': (.05, .85), 'bear.entry': (.05, .985),
    'bull.exit': (.5, 1.), 'bear.exit': (.5, 1.),
    'bull.max_hold': (1, 30), 'bear.max_hold': (1, 30),
    'bear.acf_min': (-.6, .5), 'regime_window': (5, 60),
    'regime_threshold': (-.04, .04), 'confirmation.threshold': (-.3, .1),
    'confirmation.lookback': (40, 120),
}
INTEGERS = {'bull.range_window', 'bear.range_window', 'bull.max_hold',
            'bear.max_hold', 'regime_window', 'confirmation.lookback'}
RADII = (.05, .10, .20)
JOINT_COUNT = 32


def get(parameters, path):
    value = parameters
    for name in path.split('.'):
        value = value[name]
    return value


def put(parameters, path, value):
    parts = path.split('.')
    target = parameters
    for name in parts[:-1]:
        target = target[name]
    target[parts[-1]] = value


def center(strategy, parameters):
    if strategy == 'S007':
        return read(OLD/'protocols/adapted_plan.json')['center']['coordinates']
    return {name: get(parameters, name) for name in S013_BOUNDS}


def materialize(strategy, parameters, coordinates):
    result = deepcopy(parameters)
    if strategy == 'S013':
        for name, value in coordinates.items():
            put(result, name, value)
        return result
    score = result['rule']['score']
    v = coordinates
    risk = v['risk_context_total']
    opportunity = (1-risk)*v['opportunity_share_nonrisk']
    score['base_weights'] = {
        'price_close_vwap_deviation': (1-risk)*(1-v['opportunity_share_nonrisk']),
        'price_intraday_range': risk*(1-v['risk_shibor_fraction']),
        'risk_chinext_turnover_z20': opportunity*(1-v['opp_spx_fraction']),
        'risk_global_spx_return': opportunity*v['opp_spx_fraction'],
        'risk_shibor_on_change_5d': risk*v['risk_shibor_fraction'],
    }
    f = v['confirm_share_fraction']
    score['confirmation_weights'] = {'micro_share_change_5d_lag1': f,
        'tsfresh__log_volume_change__mean__lb20': 1-f}
    for name in ('entry_threshold', 'exit_threshold', 'confirmation_threshold'):
        score[name] = v[name]
    return result


def legal(strategy, original, values, bounds):
    if not all(bounds[name][0] <= value <= bounds[name][1] for name, value in values.items()):
        return False
    if strategy == 'S007':
        score = materialize(strategy, original, values)['rule']['score']
        return (values['exit_threshold'] < values['entry_threshold']
                and max(score['base_weights'].values()) <= .35)
    return all(values[route+'.entry'] < values[route+'.exit'] for route in ('bull', 'bear'))


def distance(before, after, bounds):
    return sqrt(sum(((after[k]-before[k])/(high-low))**2 for k, (low, high) in bounds.items()))


def joint(strategy, parameters):
    bounds = S007_BOUNDS if strategy == 'S007' else S013_BOUNDS
    before = center(strategy, parameters)
    names = list(bounds)
    widths = np.array([bounds[k][1]-bounds[k][0] for k in names])
    base = np.array([before[k] for k in names])
    integer = np.array([strategy == 'S013' and k in INTEGERS for k in names])
    rng = np.random.default_rng(13)
    cases, geometry = [], []
    for radius in RADII:
        accepted, seen, attempts, rejected = 0, set(), 0, {}
        while accepted < JOINT_COUNT:
            attempts += 1
            assert attempts < 100000, 'Declared geometric budget exhausted'
            direction = rng.normal(size=len(names))
            direction /= np.linalg.norm(direction)
            delta = radius*direction
            raw = base+widths*delta
            raw[integer] = np.rint(raw[integer])
            delta[integer] = (raw[integer]-base[integer])/widths[integer]
            integer_squared = float(np.sum(delta[integer]**2))
            if integer_squared >= radius**2:
                rejected['integer_radius'] = rejected.get('integer_radius', 0)+1
                continue
            delta[~integer] *= sqrt((radius**2-integer_squared)/float(np.sum(delta[~integer]**2)))
            raw[~integer] = base[~integer]+widths[~integer]*delta[~integer]
            values = {k: int(value) if mask else float(value)
                      for k, value, mask in zip(names, raw, integer, strict=True)}
            if not legal(strategy, parameters, values, bounds):
                rejected['domain_or_constraints'] = rejected.get('domain_or_constraints', 0)+1
                continue
            key = tuple(values.values())
            if key in seen:
                rejected['duplicate'] = rejected.get('duplicate', 0)+1
                continue
            actual = distance(before, values, bounds)
            assert abs(actual-radius) < 1e-12
            seen.add(key)
            cases.append({'kind': 'JOINT', 'radius': radius, 'index_within_radius': accepted,
                          'coordinates': values, 'actual_radius': actual,
                          'parameters': materialize(strategy, parameters, values)})
            accepted += 1
        geometry.append({'radius': radius, 'attempts': attempts, 'accepted': accepted,
                         'geometric_rejections': rejected})
    return cases, geometry


def axes(strategy, parameters):
    bounds = S007_BOUNDS if strategy == 'S007' else S013_BOUNDS
    before = center(strategy, parameters)
    cases = []
    for radius in RADII:
        for name, (low, high) in bounds.items():
            for sign in (-1, 1):
                values = dict(before)
                raw = before[name]+sign*radius*(high-low)
                values[name] = int(np.rint(raw)) if strategy == 'S013' and name in INTEGERS else raw
                actual = distance(before, values, bounds)
                status = ('NO_PARAMETER_CHANGE' if actual == 0 else
                          'READY' if legal(strategy, parameters, values, bounds) else 'OUTSIDE_DOMAIN_OR_CONSTRAINT')
                cases.append({'kind': 'AXIS', 'radius': radius, 'axis': name, 'sign': sign,
                              'coordinates': values, 'actual_radius': actual,
                              'design_status': status,
                              'parameters': materialize(strategy, parameters, values)})
    return cases
