"""Pure EX045 independent-oracle checks; no account evaluation or preparation."""
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
        assert {c['label'] for c in plan['configurations']} == {'N0'}
    sys.path.insert(0, str(SRC))
    oracle = importlib.import_module('direction_oracle')
    package = SRC / 'strategy_runtime/strategies'
    spec = importlib.util.spec_from_file_location(
        'ex045_synthetic', package / '__init__.py', submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    MechanismRange = importlib.import_module(spec.name + '.mechanism_range').MechanismRange

    oldtree = ast.parse((ROOT / 'research/S013/experiments/EX043_20261011/src/direction_oracle.py').read_text('utf-8'))
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
        for number in (2132, 5300)]
    assert len(space.coordinates) == 13 and all(len(d.points) == 32 for d in designs)
    assert all(d.points == designs[0].points and d.space.coordinates == space.coordinates for d in designs)

    rng = np.random.default_rng(13)
    days = pd.bdate_range('2019-01-01', periods=510)
    close = 100 * np.exp(np.cumsum(.006 * np.sin(np.arange(510) * .12) + rng.normal(0, .003, 510)))
    opening = close * np.exp(rng.normal(0, .003, 510))
    opening[210:214] = close[210:214]
    bars = pd.DataFrame({'Date': days, 'Open': opening, 'Close': close,
        'High': np.maximum(close, opening) * 1.005, 'Low': np.minimum(close, opening) * .995,
        'Amount': np.exp(rng.normal(16, .2, 510)), 'Volume': np.exp(rng.normal(12, .2, 510))}).iloc[:500].copy()
    signals, valid = days[400:500], days[401:501]
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
    execution = NS(execution_daily=pd.DataFrame({'dt': days[400:501]}), evaluation_sessions=tuple(valid))


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


    for mechanism in ('MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE',):
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
        data.loc[data.index[400:406], 'Close'] = [100., 100., 100., 99., 100., 101.]
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
    # Authenticate unchanged parent bytes and all economic state logic against frozen43.
    old_src = ROOT / 'research/S013/experiments/EX043_20261011/src'
    old_package = old_src / 'strategy_runtime/strategies'
    parent_files = ('__init__.py', 'range_reversion.py', 'adaptive_range.py',
                    'confirmed_range.py', 'reentry_confirmed_range.py')
    assert all((package / name).read_bytes() == (old_package / name).read_bytes() for name in parent_files)
    trees = [ast.parse((base / 'mechanism_range.py').read_text('utf-8')) for base in (old_package, package)]
    loops = [next(node for node in ast.walk(tree) if isinstance(node, ast.For) and
                  isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name)
                  and node.iter.func.id == 'enumerate') for tree in trees]
    assert ast.dump(loops[0], include_attributes=False) == ast.dump(loops[1], include_attributes=False)
    old_spec = importlib.util.spec_from_file_location('ex045_old43_control', old_package / '__init__.py',
        submodule_search_locations=[str(old_package)])
    old_module = importlib.util.module_from_spec(old_spec)
    sys.modules[old_spec.name] = old_module
    old_spec.loader.exec_module(old_module)
    OldMechanism = importlib.import_module(old_spec.name + '.mechanism_range').MechanismRange
    oracle_spec = importlib.util.spec_from_file_location('ex045_old43_oracle', old_src / 'direction_oracle.py')
    old_oracle = importlib.util.module_from_spec(oracle_spec)
    oracle_spec.loader.exec_module(old_oracle)
    assert oracle.MECHANISMS == old_oracle.MECHANISMS | {'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE'}
    fixed_branch_cases = center_equivalence = old_compatibility = integer_boundaries = warmup_failures = 0
    all_data = bars.set_index(pd.DatetimeIndex(bars.Date))
    fixed_frames = {}
    for lookback in (40, 60, 80, 120):
        p = deepcopy(p0)
        p['mechanism'] = 'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE'
        p['confirmation']['lookback'] = lookback
        _, _, frame, _ = audit_and_memory(p)
        fixed_frames[lookback] = frame
        prior = deepcopy(p)
        prior['mechanism'] = 'MEAN_BEAR_TIME_BELOW_CLOSE'
        old_frame = OldMechanism(ParameterSet(prior)).calculate_history({'daily': bars}, signals)
        compatible = MechanismRange(ParameterSet(prior)).calculate_history({'daily': bars}, signals)
        pd.testing.assert_frame_equal(old_frame, compatible, check_exact=True)
        old_compatibility += 1
        score_fields = ['confirmation_score', 'confirmation_acf', 'confirmation_turnover', 'confirmation_volume']
        pd.testing.assert_frame_equal(frame[score_fields], old_frame[score_fields], check_exact=True)
        if lookback == 120:
            pd.testing.assert_frame_equal(frame.drop(columns=['signal_date', 'valid_session']), old_frame, check_exact=True)
            pd.testing.assert_frame_equal(oracle._reconstruct(all_data, signals, p),
                old_oracle._reconstruct(all_data, signals, prior), check_exact=True)
            center_equivalence += 1
        else:
            assert not np.array_equal(frame.bear_acf_baseline.to_numpy(), old_frame.bear_acf_baseline.to_numpy())
        fixed_branch_cases += 1
    for lookback in (40, 60, 80):
        for name in ('bear_acf_baseline', 'bear_acf_centered', 'bear_acf_raw'):
            np.testing.assert_array_equal(fixed_frames[lookback][name], fixed_frames[120][name])
        assert not np.array_equal(fixed_frames[lookback].confirmation_score, fixed_frames[120].confirmation_score)
    for path, low, high in (('bull.range_window', 21, 360), ('bear.range_window', 21, 360),
                           ('bull.max_hold', 1, 60), ('bear.max_hold', 1, 60),
                           ('regime_window', 5, 60), ('confirmation.lookback', 40, 120)):
        for value in (low, high):
            p = deepcopy(p0)
            p['mechanism'] = 'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE'
            parts, target = path.split('.'), p
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
            audit_and_memory(p)
            integer_boundaries += 1
    for lookback in (40, 120):
        p = deepcopy(p0)
        p['mechanism'] = 'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE'
        p['confirmation']['lookback'] = lookback
        p['regime_window'] = 5
        p['bull']['range_window'] = p['bear']['range_window'] = 21
        implementation = MechanismRange(ParameterSet(p))
        daily = next(item for item in implementation.definition.inputs.requirements if item.name == 'daily')
        assert daily.lookback_sessions == 141
        minimal = bars.iloc[:141].copy()
        minimal_dates = pd.DatetimeIndex(minimal.Date.iloc[-1:])
        actual = implementation.calculate_history({'daily': minimal}, minimal_dates)
        expected = oracle._reconstruct(minimal.set_index(pd.DatetimeIndex(minimal.Date)), minimal_dates, p)
        for name in expected:
            if name not in ('holding_before', 'route_before', 'age_before', 'active_route', 'eligible'):
                if name in ('last_exit_reason', 'last_exit_route', 'last_exit_category'):
                    oracle._assert_exit_metadata(actual[name], expected[name], name)
                else:
                    np.testing.assert_array_equal(actual[name], expected[name])
        short = bars.iloc[:140].copy()
        short_dates = pd.DatetimeIndex(short.Date.iloc[-1:])
        warmup_failures += reject(lambda: implementation.calculate_history({'daily': short}, short_dates))
        warmup_failures += reject(lambda: oracle._reconstruct(short.set_index(pd.DatetimeIndex(short.Date)), short_dates, p))
        fixed_branch_cases += 1
    p = deepcopy(p0)
    p['mechanism'] = 'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE'
    p['confirmation']['lookback'] = 40
    cut = 450
    future = bars.copy()
    future.loc[future.index > cut, ['Open', 'Close', 'High', 'Low']] *= 1.2
    future.loc[future.index > cut, ['Amount', 'Volume']] *= 2.
    _, _, base_frame = native(p)
    _, _, future_frame = native(p, future)
    prefix = signals <= pd.Timestamp(bars.Date.iloc[cut])
    pd.testing.assert_frame_equal(base_frame.loc[prefix], future_frame.loc[prefix], check_exact=True)
    base_expected = oracle._reconstruct(all_data, signals, p)
    future_expected = oracle._reconstruct(future.set_index(pd.DatetimeIndex(future.Date)), signals, p)
    pd.testing.assert_frame_equal(base_expected.loc[prefix], future_expected.loc[prefix], check_exact=True)
    current = bars.copy()
    current.loc[cut, ['Open', 'Close', 'High', 'Low']] *= 1.2
    _, _, current_frame = native(p, current)
    cut_date = pd.Timestamp(bars.Date.iloc[cut])
    assert current_frame.bear_acf_raw.loc[cut_date] != base_frame.bear_acf_raw.loc[cut_date]
    assert current_frame.bear_acf_baseline.loc[cut_date] == base_frame.bear_acf_baseline.loc[cut_date]
    assert int(prefix.sum()) == 51
    output = {'status': 'PURE_PASS', 'new_account_evaluations': 0, 'new_account_preparations': 0,
        'mechanism': 'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE', 'supported_mechanisms': sorted(oracle.MECHANISMS),
        'parameter_points': 32, 'coordinates': 13, 'points_per_center': 32,
        'native_synthetic_oracle_audits': audits, 'state_drift_rejections': drifts,
        'signal_memory_checks': memory, 'gate_opportunities': gates,
        'parameter_and_strict_price_boundaries': boundary,
        'native_parameter_rejections': native_parameter_rejections, 'nullable_metadata_checks': nullable_checks,
        'observed_exit_categories': sorted(observed_categories), 'signal_reasons': sorted(reasons),
        'calendar_oracle_AST_identical_to_EX043': True, 'oracle_imports_SRT': False,
        'center_L120_old_runtime_and_oracle_exact': center_equivalence,
        'old_mechanism_compatibility_cases': old_compatibility,
        'fixed120_vs_scoreL_cases': fixed_branch_cases, 'integer_boundary_cases': integer_boundaries,
        'minimal_141_price_warmup_rejections': warmup_failures,
        'future_invariance_native_oracle_signal_rows': int(prefix.sum()),
        'strict_past_current_shock_baseline_unchanged': True, 'economic_state_loop_AST_exact43': True,
        'limits': 'Pure synthetic paths only. Declared13-domain boundary checks do not add new economic gates. No market result reads or profit forecast.'}
    return output


def main():
    output = synthetic({}, SRC / 'strategy_runtime')
    folder = ROOT / '.tmp/ex045-synthetic'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'focused.json').write_text(json.dumps(output, indent=2, allow_nan=False) + '\n',
        encoding='utf-8', newline='\n')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
