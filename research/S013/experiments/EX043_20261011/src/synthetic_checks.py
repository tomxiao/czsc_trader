"""Pure EX043 independent-oracle checks; no account evaluation or preparation."""
# ruff: noqa: E402
import ast
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from strategy_evaluator import (
    AssessmentCandidate, ParameterCoordinate, ParameterCoordinateKind,
    ParameterDesignRequest, ParameterPerturbationProtocol, ParameterSpace,
    build_parameter_perturbation_design,
)

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]


def synthetic(plan, source):
    """Public precheck entry; only synthetic data and pure helper functions."""
    assert Path(source).resolve() == (SRC / 'strategy_runtime').resolve()
    if plan:
        assert {c['label'] for c in plan['configurations']} == {'N0', 'N1', 'N2', 'N3'}
    sys.path.insert(0, str(SRC))
    oracle = importlib.import_module('direction_oracle')
    package = SRC / 'strategy_runtime/strategies'
    spec = importlib.util.spec_from_file_location(
        'ex043_synthetic', package / '__init__.py', submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    MechanismRange = importlib.import_module(spec.name + '.mechanism_range').MechanismRange

    oldtree = ast.parse((ROOT / 'research/S013/experiments/EX041_20261011/src/direction_oracle_v2.py').read_text('utf-8'))
    newtree = ast.parse((SRC / 'direction_oracle.py').read_text('utf-8'))
    functions = [next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_audit_dates')
                 for tree in (oldtree, newtree)]
    assert ast.dump(functions[0], include_attributes=False) == ast.dump(functions[1], include_attributes=False)
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and
        any('strategy_runtime' in value for value in (
            [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or '']))
        for n in ast.walk(newtree)), 'Independent oracle must not import SRT'
    original = json.loads((ROOT / 'research/S013/experiments/EX015_20261011/protocols/plan.json').read_text('utf-8-sig'))['controls'][0]
    p0 = deepcopy(original['payload']['parameters'])
    geometry = json.loads((ROOT / 'research/S013/experiments/EX015_20261011/protocols/geometry.json').read_text('utf-8-sig'))


    def get_path(parameters, name):
        for part in name.split('.'):
            parameters = parameters[part]
        return parameters


    def materialize(values):
        p = deepcopy(p0)
        for (name, _, _, kind), value in zip(geometry['coordinates'], values, strict=True):
            parts, target = name.split('.'), p
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = int(value) if kind == 'INTEGER' else float(value)
        return p


    def in_declared_domain(p):
        for name, low, high, kind in geometry['coordinates']:
            value = get_path(p, name)
            if not np.isfinite(value) or not low <= value <= high:
                return False
            if kind == 'INTEGER' and type(value) is not int:
                return False
        return p['bull']['entry'] < p['bull']['exit'] and p['bear']['entry'] < p['bear']['exit']


    space = ParameterSpace(tuple(ParameterCoordinate(name, float(get_path(p0, name)), low, high,
        ParameterCoordinateKind(kind)) for name, low, high, kind in geometry['coordinates']), '1' * 64, '2' * 64)
    protocol = ParameterPerturbationProtocol(**geometry['protocol'])
    designs = [build_parameter_perturbation_design(ParameterDesignRequest(
        AssessmentCandidate(f'S013-C{number}', str(number % 10) * 64), protocol, space),
        feasibility=lambda values: values[1] < values[2] and values[5] < values[6]).design
        for number in (2132, 4300, 4301, 4302, 4303)]
    assert len(space.coordinates) == 13 and all(len(d.points) == 32 for d in designs)
    assert all(d.points == designs[0].points and d.space.coordinates == space.coordinates for d in designs)

    rng = np.random.default_rng(13)
    days = pd.bdate_range('2019-01-01', periods=430)
    close = 100 * np.exp(np.cumsum(.006 * np.sin(np.arange(430) * .12) + rng.normal(0, .003, 430)))
    opening = close * np.exp(rng.normal(0, .003, 430))
    opening[210:214] = close[210:214]
    bars = pd.DataFrame({'Date': days, 'Open': opening, 'Close': close,
        'High': np.maximum(close, opening) * 1.005, 'Low': np.minimum(close, opening) * .995,
        'Amount': np.exp(rng.normal(16, .2, 430)), 'Volume': np.exp(rng.normal(12, .2, 430))}).iloc[:420].copy()
    signals, valid = days[200:420], days[201:421]
    calrequest = NS(start=days[0].date(), end=valid[-1].date())
    all_dates = pd.date_range(calrequest.start, calrequest.end)
    opened = all_dates.weekday < 5
    previous, last = [], days[0] - pd.offsets.BDay()
    for day, is_open in zip(all_dates, opened, strict=True):
        previous.append(last)
        if is_open:
            last = day
    calendar = pd.DataFrame({'Date': all_dates, 'IsOpen': opened.astype(int), 'PreviousTradingDate': previous})
    plan = NS(requests={'daily': 'daily', 'calendar': calrequest}, calendar_name='calendar',
        calendar_sha256='a' * 64, calendar_dates=tuple(all_dates[opened].date),
        tradable_window=NS(start=valid[0].date(), end=valid[-1].date()),
        signal_dates={v.date(): s.date() for v, s in zip(valid, signals, strict=True)})
    binding = NS(plan=plan, prepared='synthetic-prepared')
    execution = NS(execution_daily=pd.DataFrame({'dt': days[200:421]}), evaluation_sessions=tuple(valid))


    def native(p, data=None):
        data = bars if data is None else data
        frame = MechanismRange(ParameterSet(p)).calculate_history({'daily': data}, signals).assign(
            signal_date=signals, valid_session=valid)
        bound = NS(strategy=NS(payload={'parameters': p}), input_bindings={'full': binding}, execution_data=execution)

        def fetch(req, *, prepared):
            assert prepared == 'synthetic-prepared'
            if req == 'daily':
                return NS(ready=True, dataframe=data)
            assert req is calrequest
            return NS(ready=True, dataframe=calendar, identity=NS(content_sha256='a' * 64))

        return NS(data=NS(fetch=fetch)), bound, frame


    def reject(call):
        try:
            call()
        except (AssertionError, ValueError, TypeError):
            return 1
        raise AssertionError('Illegal parameter/state/date accepted')


    audits = drifts = memory = gates = boundary = nullable_checks = native_parameter_rejections = 0
    reasons, observed_categories = set(), set()


    def audit_and_memory(p, data=None):
        nonlocal audits, memory, gates
        data = bars if data is None else data
        ctx, bound, frame = native(p, data)
        result = oracle.audit_direction(ctx, bound, frame, p)
        assert result['confirmation_threshold'] == p['confirmation']['threshold']
        assert result['date_audit']['exact_signal_execute_pairs'] == len(signals)
        required = 'BELOW' if '_BELOW_' in p['mechanism'] else 'ABOVE'
        assert np.array_equal(frame.entry_direction_gate_applies,
            frame.confirmation_opportunity & frame.regime.eq('bear') & frame.last_exit_reason.eq('time')
            & frame.last_exit_route.eq('bear') & frame.last_exit_category.eq(required))
        expected = oracle._reconstruct(data.set_index(pd.DatetimeIndex(data.Date)), signals, p)
        anchor = None
        for i in range(len(frame) - 1):
            current, nextrow = frame.iloc[i], frame.iloc[i + 1]
            if current.signal_reason == 'entry':
                anchor = current.entry_signal_close
                assert all(nextrow[n] is None for n in ('last_exit_reason', 'last_exit_route', 'last_exit_category'))
            elif current.signal_reason in ('loss', 'trailing', 'range', 'time', 'regime'):
                assert nextrow.last_exit_reason == current.signal_reason
                assert nextrow.last_exit_route == expected.active_route.iloc[i]
                if current.signal_reason == 'time' and expected.active_route.iloc[i] == 'bear':
                    assert anchor is not None
                    wanted = ('BELOW' if current.entry_signal_close < anchor else
                              'ABOVE' if current.entry_signal_close > anchor else 'EQUAL')
                    assert nextrow.last_exit_category == wanted
                    observed_categories.add(wanted)
                else:
                    assert nextrow.last_exit_category is None
            elif current.signal_reason in ('flat', 'entry_direction_rejected', 'confirmation_rejected'):
                assert all(nextrow[n] == current[n] for n in ('last_exit_reason', 'last_exit_route', 'last_exit_category'))
            memory += 1
        gates += int(frame.entry_direction_gate_applies.sum())
        audits += 1
        reasons.update(frame.signal_reason)
        return ctx, bound, frame, result


    for mechanism in sorted(oracle.MECHANISMS):
        for point in designs[0].points:
            p = materialize(point.coordinates)
            p['mechanism'] = mechanism
            assert in_declared_domain(p)
            audit_and_memory(p)
        p = deepcopy(p0)
        p['mechanism'] = mechanism
        for threshold in (-.4, 0., .4):
            p['confirmation']['threshold'] = threshold
            ctx, bound, frame, result = audit_and_memory(p)
        for name in result['audited_fields']:
            bad = frame.copy()
            value = bad[name].iloc[7]
            if name in ('signal_date', 'valid_session'):
                bad.loc[bad.index[7], name] = pd.Timestamp(value) + pd.Timedelta(days=1)
            elif isinstance(value, (bool, np.bool_)):
                bad.loc[bad.index[7], name] = not value
            elif isinstance(value, str) or value is None:
                bad.loc[bad.index[7], name] = 'tampered'
            else:
                bad.loc[bad.index[7], name] = float(value) + .001
            drifts += reject(lambda: oracle.audit_direction(ctx, bound, bad, p))
        for stop, trail, level, hold in ((.001, .001, .91, 1), (None, .001, .99, 2),
                                        (None, None, .68, 8), (None, None, .99, 1)):
            q = deepcopy(p0)
            q['mechanism'] = mechanism
            for route in ('bull', 'bear'):
                q[route].update(stop_loss=stop, trailing_stop=trail, max_hold=hold,
                    entry=min(q[route]['entry'], level - .01), exit=level)
            audit_and_memory(q)
        # Explicit equality at an exit, and adjacent IEEE floats, have no epsilon.
        for closing, category in ((np.nextafter(100., 0.), 'BELOW'), (100., 'EQUAL'),
                                  (np.nextafter(100., np.inf), 'ABOVE')):
            assert oracle._exit_category(closing, 100.) == category
            boundary += 1
        q = deepcopy(p0)
        q['mechanism'] = mechanism
        q['confirmation']['threshold'] = -.5
        q['regime_threshold'] = .2
        q['bear'].update(acf_min=-.6, entry=.99, exit=1., max_hold=1)
        data = bars.copy()
        data.loc[data.index[200:206], 'Close'] = [100., 100., 100., 99., 100., 101.]
        data['Open'] = data.Close * 1.0001
        data['High'], data['Low'] = data.Close * 1.05, data.Close * .95
        audit_and_memory(q, data)

    for name, low, high, kind in geometry['coordinates']:
        for invalid in (low - 1, high + 1, np.nan):
            q = deepcopy(p0)
            parts, target = name.split('.'), q
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = int(invalid) if kind == 'INTEGER' and np.isfinite(invalid) else invalid
            assert not in_declared_domain(q)
            q['mechanism'] = sorted(oracle.MECHANISMS)[0]
            if name == 'bear.acf_min' and np.isfinite(invalid):
                # Source accepts any finite ACF; the declared study domain is narrower.
                MechanismRange(ParameterSet(q))
            else:
                native_parameter_rejections += reject(lambda: MechanismRange(ParameterSet(q)))
            boundary += 1
        if kind == 'INTEGER':
            q = deepcopy(p0)
            parts, target = name.split('.'), q
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = float(get_path(q, name))
            assert not in_declared_domain(q)
            boundary += 1

    for name, categories in {'last_exit_reason': ('time', 'regime', 'range', 'loss', 'trailing'),
                             'last_exit_route': ('bull', 'bear'),
                             'last_exit_category': ('BELOW', 'EQUAL', 'ABOVE')}.items():
        for absence in (None, float('nan'), np.float64('nan')):
            assert oracle._assert_exit_metadata([absence], [None], name) == 1
            nullable_checks += 1
        for bad in ('', 'None', 'nan', pd.NA, pd.NaT, 0., np.inf):
            drifts += reject(lambda: oracle._assert_exit_metadata([bad], [None], name))
        for wanted in categories:
            for bad in (None, float('nan'), 'UNKNOWN'):
                drifts += reject(lambda: oracle._assert_exit_metadata([bad], [wanted], name))
            assert oracle._assert_exit_metadata([wanted], [wanted], name) == 0
            nullable_checks += 1
    assert gates > 0 and observed_categories == {'BELOW', 'EQUAL', 'ABOVE'}
    assert {'entry', 'entry_direction_rejected', 'confirmation_rejected', 'flat', 'hold',
            'loss', 'trailing', 'range', 'time', 'regime'} <= reasons
    helper_states = helper_pairs = 0
    from itertools import combinations, product
    import run_parameters as parameter_helper
    import pair_parameters as pairing_helper
    for flags in product((False, True), repeat=4):
        selected = parameter_helper.select_new_centers(
            {'configurations': [{'label': f'N{i}'} for i in range(4)]},
            {'rows': {f'N{i}': {'qualified': flag} for i, flag in enumerate(flags)}})
        assert [c['label'] for c in selected] == [f'N{i}' for i, flag in enumerate(flags) if flag]
        helper_states += 1
    for count in range(1, 5):
        for selected in combinations(tuple(f'N{i}' for i in range(4)), count):
            labels = ('B0-TIME', *selected)
            panel = {'status': 'PASS', 'points': {label: [
                {'point_index': point.index, 'coordinates': list(point.coordinates),
                 'actual_radius': point.actual_radius, 'net_cagr': .12, 'drawdown': .08,
                 'closed_trades': 120, 'qualified': True,
                 'annual': {'2022': {'return': .02}, '2023': {'return': .03}}}
                for point in designs[0].points] for label in labels},
                'summaries': {label: {'role': 'synthetic', 'center_qualified': True,
                    'q10_cagr': .12, 'q90_drawdown': .08, 'return_degradation': 0.,
                    'drawdown_degradation': 0.} for label in labels}}
            paired = pairing_helper.pair_analysis(panel)
            assert all(row['complete_pairs'] == 32 for row in paired['comparisons'].values())
            expected_pairs = len(selected) + sum(first in selected and second in selected
                for first, second in (('N0', 'N1'), ('N2', 'N3'), ('N0', 'N2'), ('N1', 'N3')))
            assert len(paired['comparisons']) == expected_pairs
            helper_pairs += 1
    assert pairing_helper.pair_analysis({'status': 'NOT_APPLICABLE', 'reason': 'NONE'})['comparisons'] == {}
    output = {'status': 'PURE_PASS', 'new_account_evaluations': 0, 'new_account_preparations': 0,
        'mechanisms': sorted(oracle.MECHANISMS), 'parameter_points': 128, 'selection_states': helper_states, 'pair_panels': helper_pairs, 'points_per_center': 32,
        'native_synthetic_oracle_audits': audits, 'state_drift_rejections': drifts,
        'signal_memory_checks': memory, 'gate_opportunities': gates,
        'parameter_and_strict_price_boundaries': boundary,
        'native_parameter_rejections': native_parameter_rejections, 'nullable_metadata_checks': nullable_checks,
        'observed_exit_categories': sorted(observed_categories), 'signal_reasons': sorted(reasons),
        'calendar_oracle_AST_identical_to_EX041_v2': True, 'oracle_imports_SRT': False,
        'limits': 'Pure synthetic paths only. Declared13-domain boundary checks do not add new economic gates. No market result reads or profit forecast.'}
    return output


def main():
    output = synthetic({}, SRC / 'strategy_runtime')
    folder = ROOT / '.tmp/ex043_parameters'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'focused.json').write_text(json.dumps(output, indent=2, allow_nan=False) + '\n',
        encoding='utf-8', newline='\n')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
