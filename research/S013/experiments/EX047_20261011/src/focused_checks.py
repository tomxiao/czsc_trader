"""Synthetic-only proofs for original13 forward/reverse one-step substitutions."""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

from coordinate import COORDINATES, COORDINATE_NAMES, hybrid
from transition import Feature, RouteRule, SignalKind, SignalState, step


HERE = Path(__file__).resolve().parent
ROOT = next(parent for parent in HERE.parents if (parent / 'research/S013/experiments').is_dir())


def main():
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    def refuse(name, callback):
        try:
            callback()
        except (ValueError, TypeError):
            checks.append(name)
        else:
            raise AssertionError('Expected explicit refusal: ' + name)

    geometry = json.loads((ROOT / 'research/S013/experiments/EX046_20261011/protocols/geometry.json').read_text(encoding='utf-8'))
    check('original13 ordered domain/kind exact', [list(row) for row in COORDINATES] == geometry['coordinates'])
    check('transition source byte-exact EX044', (HERE / 'transition.py').read_bytes() ==
          (ROOT / 'research/S013/experiments/EX044_20261011/src/transition.py').read_bytes())
    center = Feature('bear', 10., 9.9, .20, .25, .30, .40, .35, .20,
                     RouteRule(.30, .90, 8), RouteRule(.40, .80, 4, .10))
    point = Feature('bull', 10., 9.9, .15, .35, .30, .40, .45, .25,
                    RouteRule(.35, .85, 7), RouteRule(.45, .75, 3, .15))
    mappings = {
        'bull.range_window': ('bull_range_position',),
        'bear.range_window': ('bear_range_position',),
        'regime_window': ('raw_route',), 'regime_threshold': ('raw_route',),
        'confirmation.lookback': ('confirmation_score',),
        'confirmation.threshold': ('confirmation_threshold',),
    }
    for route in ('bull', 'bear'):
        for name in ('entry', 'exit', 'max_hold') + (('acf_min',) if route == 'bear' else ()):
            mappings[route + '.' + name] = (route + '_rule', name)
    checks_before = len(checks)
    for base, source, label in ((center, point, 'forward'), (point, center, 'reverse')):
        for coordinate in COORDINATE_NAMES:
            path = mappings[coordinate]
            before = asdict(base)
            expected = asdict(base)
            source_dict = asdict(source)
            if len(path) == 1:
                expected[path[0]] = 'bull' if path[0] == 'raw_route' else source_dict[path[0]]
            else:
                expected[path[0]][path[1]] = source_dict[path[0]][path[1]]
            result = hybrid(base, source, coordinate, 'bull', 'bull')
            check(label + ' only ' + coordinate, asdict(result) == expected and asdict(base) == before)
            identity = hybrid(base, base, coordinate, base.raw_route, base.raw_route)
            check(label + ' identity ' + coordinate, identity == base)
    mapping_checks = len(checks) - checks_before

    # Four combinations must be recomputed against each current BASE. Reusing
    # point's whole regime or forward arrays fails this deliberately chosen case.
    close, lag_c, lag_p, theta_c, theta_p = 10., 10., 8., .20, .30
    momentum_c, momentum_p = close / lag_c - 1, close / lag_p - 1
    def route(m, theta):
        return 'bull' if m >= theta else 'bear'
    combinations = {'cc': route(momentum_c, theta_c), 'pc': route(momentum_p, theta_c),
                    'cp': route(momentum_c, theta_p), 'pp': route(momentum_p, theta_p)}
    base = replace(center, raw_route=combinations['cc'])
    source = replace(point, raw_route=combinations['pp'])
    check('W forward uses pointW centerTheta', hybrid(base, source, 'regime_window', combinations['pc']).raw_route == 'bull')
    check('theta forward uses centerW pointTheta', hybrid(base, source, 'regime_threshold',
          rawrouteThresholdOnly=combinations['cp']).raw_route == 'bear')
    check('W reverse uses centerW pointTheta', hybrid(source, base, 'regime_window', combinations['cp']).raw_route == 'bear')
    check('theta reverse uses pointW centerTheta', hybrid(source, base, 'regime_threshold',
          rawrouteThresholdOnly=combinations['pc']).raw_route == 'bull')
    check('original return threshold equality is bull', route(.25, .25) == 'bull')

    state = SignalState()
    equal = replace(center, bear_range_position=.40, bear_acf_value=.10, confirmation_score=.20)
    check('entry/acf/score equality all pass', step(SignalKind.ORIGINAL_TIME, state, equal).reason == 'entry')
    check('score L replacement does not alter ACF or threshold',
          hybrid(center, point, 'confirmation.lookback') == replace(center, confirmation_score=.45))
    held = SignalState(True, 'bear', 0)
    for value in (1, 60):
        source = replace(point, bear_rule=replace(point.bear_rule, max_hold=value))
        result = hybrid(center, source, 'bear.max_hold')
        check('integer H boundary ' + str(value), type(result.bear_rule.max_hold) is int and result.bear_rule.max_hold == value)
    h1 = replace(center, bear_rule=replace(center.bear_rule, max_hold=1))
    check('age plus one H1 exits first held decision', step(SignalKind.ORIGINAL_TIME, held, h1).reason == 'time')
    h60 = replace(center, bear_rule=replace(center.bear_rule, max_hold=60))
    check('H60 age58 holds', step(SignalKind.ORIGINAL_TIME, SignalState(True, 'bear', 58), h60).reason == 'hold')
    check('H60 age59 exits', step(SignalKind.ORIGINAL_TIME, SignalState(True, 'bear', 59), h60).reason == 'time')
    check('observed age is never clipped to substituted H',
          step(SignalKind.ORIGINAL_TIME, SignalState(True, 'bear', 60), h1).reason == 'time')
    range_and_time = replace(h1, bear_range_position=h1.bear_rule.exit, raw_route='bull')
    check('range equality priority over time and regime', step(SignalKind.ORIGINAL_TIME, held, range_and_time).reason == 'range')
    check('time priority over raw regime', step(SignalKind.ORIGINAL_TIME, held, replace(h1, raw_route='bull')).reason == 'time')

    # Joint entry+threshold change can alter target although each single change
    # leaves target unchanged; per-coordinate counts must not be added.
    c = replace(center, bear_range_position=.20, confirmation_score=0., confirmation_threshold=.10,
                bear_rule=RouteRule(.10, .80, 4, .10))
    p = replace(c, confirmation_threshold=-.10, bear_rule=replace(c.bear_rule, entry=.30))
    outcomes = [step(SignalKind.ORIGINAL_TIME, state, feature).outcome('target_reason')
                for feature in (c, hybrid(c, p, 'bear.entry'), hybrid(c, p, 'confirmation.threshold'), p)]
    check('non-additivity joint entry and score threshold', outcomes ==
          [(0, 'flat'), (0, 'confirmation_rejected'), (0, 'flat'), (1, 'entry')])

    # Both observed states are fixed independently in either direction. These
    # calls deliberately discard next_state: there is no hybrid path replay.
    states = (SignalState(), SignalState(True, 'bull', 2), SignalState(True, 'bear', 0), SignalState(True, 'bear', 7))
    step_calls = 0
    for observed in states:
        before = asdict(observed)
        for base, source in ((center, point), (point, center)):
            for coordinate in COORDINATE_NAMES:
                decision = step(SignalKind.ORIGINAL_TIME, observed, hybrid(base, source, coordinate, 'bull', 'bear'))
                assert decision.target in (0, 1)
                assert isinstance(decision.outcome('target_reason'), tuple)
                step_calls += 1
        check('fixed observed state immutable ' + repr(observed.physical), asdict(observed) == before)

    refuse('unknown coordinate', lambda: hybrid(center, point, 'bull.acf_min'))
    refuse('typed features only', lambda: hybrid(asdict(center), point, 'bull.entry'))
    refuse('W route missing', lambda: hybrid(center, point, 'regime_window'))
    refuse('threshold route missing', lambda: hybrid(center, point, 'regime_threshold'))
    refuse('invalid recomputed route', lambda: hybrid(center, point, 'regime_window', 'flat'))
    refuse('different input prices', lambda: hybrid(center, replace(point, signal_close=11.), 'bear.entry'))
    refuse('different raw ACF', lambda: hybrid(center, replace(point, bear_acf_value=.5), 'bear.entry'))
    refuse('inactive bull ACF changed', lambda: hybrid(center, replace(point, bull_rule=replace(point.bull_rule, acf_min=.1)), 'bull.entry'))
    cross_entry = replace(point, bear_rule=RouteRule(.85, .90, 3, .15))
    refuse('single entry infeasible does not clip or swap exit', lambda: hybrid(center, cross_entry, 'bear.entry'))
    cross_exit = replace(point, bear_rule=RouteRule(.10, .20, 3, .15))
    refuse('single exit infeasible does not clip or swap entry', lambda: hybrid(center, cross_exit, 'bear.exit'))
    for invalid in (True, 1., 0, 61):
        refuse('integer H invalid ' + repr(invalid), lambda value=invalid: replace(center.bear_rule, max_hold=value))
    refuse('financial NaN feature', lambda: replace(point, confirmation_score=float('nan')))
    result = {'status': 'PURE_PASS', 'new_account_evaluations': 0, 'native_account_reads': 0,
              'checks': checks, 'check_count': len(checks), 'mapping_identity_checks': mapping_checks,
              'fixed_state_one_step_calls': step_calls, 'four_base_dependent_regimes': combinations,
              'non_additivity_outcomes': outcomes,
              'source_files': {name: sha256((HERE / name).read_bytes()).hexdigest()
                               for name in ('coordinate.py', 'focused_checks.py', 'transition.py')},
              'limits': ['Synthetic helper proofs only; not a financial account or source authentication.',
                         'Driver must certify full-daily range/score/window numerical provenance and all unchanged inputs.',
                         'Point observed states arise from joint13 paths; conditional single steps are not single-coordinate financial counterfactuals.',
                         'No next-state propagation, additive profit attribution, probability inference or qualification change.']}
    output = ROOT / '.tmp/ex047-coordinate-prototype/focused.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'check_count', 'mapping_identity_checks', 'fixed_state_one_step_calls')}, allow_nan=False))


if __name__ == '__main__':
    main()
