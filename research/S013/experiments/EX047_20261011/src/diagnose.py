"""Authenticated original33, single-coordinate decisions on observed states only."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'
from collections import Counter
import importlib.util
import json
import numpy as np
import pandas as pd
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from common import ROOT, SRC, PROTOCOLS, OUTPUT, TRANSPORT, SOURCE_CALLS, context, read, write, cache_read, file_hash
from native_reference import verified_json, load_original_oracle, bound_bars, json_standard
from transition import SignalKind, Feature, trace, validate_parameters, step
from coordinate import COORDINATE_NAMES as COORDINATES, hybrid

REASONS = ('flat', 'entry', 'hold', 'range', 'time', 'regime', 'confirmation_rejected')
ROUTES = (None, 'bull', 'bear')
METRICS = ('target', 'target_reason', 'next_state')


def encode(decision):
    state = decision.next_state
    assert state.entry_anchor is None and state.last_exit_reason is None
    return [decision.target, REASONS.index(decision.reason), ROUTES.index(state.route), state.age]


def outcome(encoded, metric):
    if metric == 'target':
        return encoded[0]
    if metric == 'target_reason':
        return tuple(encoded[:2])
    if metric == 'next_state':
        return encoded[0], encoded[2], encoded[3]
    raise ValueError('Unknown metric')


def source_check():
    plan = verified_json(read(PROTOCOLS / 'plan_reference.json'))
    assert plan == read(PROTOCOLS / 'plan.json')
    for name, digest in plan['source_files'].items():
        assert file_hash(SRC / name) == digest, name
    for name, digest in plan['external_source_files'].items():
        assert name.startswith('research/S013/') and file_hash(ROOT / name) == digest, name
    return plan


def calendar_oracle():
    path = ROOT / 'research/S013/experiments/EX043_20261011/src/direction_oracle.py'
    spec = importlib.util.spec_from_file_location('s013_ex047_calendar_oracle', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scalar(parameters, path):
    value = parameters
    for part in path.split('.'):
        value = value[part]
    return value


def routes(bars, dates, window, threshold):
    momentum = (bars.Close.astype(float) / bars.Close.astype(float).shift(window) - 1).reindex(dates)
    assert np.isfinite(momentum).all()
    return tuple(np.where(momentum >= threshold, 'bull', 'bear')), tuple(float(x) for x in momentum)


def complete_pair(center, point, center_parameters, point_parameters, bars):
    assert center.kind == point.kind == SignalKind.ORIGINAL_TIME
    assert center.signal_dates == point.signal_dates and center.execution_dates == point.execution_dates
    dates = pd.DatetimeIndex(pd.to_datetime(center.signal_dates))
    c, p = center_parameters, point_parameters
    w_route, pw_momentum = routes(bars, dates, p['regime_window'], c['regime_threshold'])
    t_route, cw_momentum = routes(bars, dates, c['regime_window'], p['regime_threshold'])
    assert tuple(feature.raw_route for feature in center.features) == tuple(
        'bull' if value >= c['regime_threshold'] else 'bear' for value in cw_momentum)
    assert tuple(feature.raw_route for feature in point.features) == tuple(
        'bull' if value >= p['regime_threshold'] else 'bear' for value in pw_momentum)
    rows, counts = [], Counter()
    first_actual = {name: None for name in METRICS}
    for i, (fc, fp, sc, sp, ac, ap) in enumerate(zip(center.features, point.features,
            center.before, point.before, center.decisions, point.decisions, strict=True)):
        a, b, cc, d = (encode(step(center.kind, state, feature))
                      for state, feature in ((sc, fc), (sc, fp), (sp, fc), (sp, fp)))
        assert a == encode(ac) and d == encode(ap)
        forward, reverse = [], []
        for name in COORDINATES:
            fh = hybrid(fc, fp, name, w_route[i], t_route[i])
            # Reverse has point as the base; changing W uses center W/point threshold,
            # changing threshold uses point W/center threshold. Do not reuse forward W arrays.
            rh = hybrid(fp, fc, name, t_route[i], w_route[i])
            if scalar(c, name) == scalar(p, name):
                assert fh == fc and rh == fp, (name, i)
            forward.append([encode(step(center.kind, sc, fh)), encode(step(center.kind, sp, fh))])
            reverse.append([encode(step(center.kind, sc, rh)), encode(step(center.kind, sp, rh))])
        row = {'index': i, 'signal_date': center.signal_dates[i], 'execution_date': center.execution_dates[i],
               'center_before': [int(sc.holding), ROUTES.index(sc.route), sc.age],
               'point_before': [int(sp.holding), ROUTES.index(sp.route), sp.age],
               'full_four': [a, b, cc, d], 'forward': forward, 'reverse': reverse,
               'momentum_center_window': cw_momentum[i], 'momentum_point_window': pw_momentum[i],
               'window_only_raw_route': w_route[i], 'threshold_only_raw_route': t_route[i]}
        # All dates/coordinates are retained. Counters are descriptive, overlapping, nonadditive.
        for metric in METRICS:
            actual_different = outcome(a, metric) != outcome(d, metric)
            counts[f'actual/{metric}/different'] += actual_different
            if actual_different and first_actual[metric] is None:
                first_actual[metric] = {'index': i, 'signal_date': center.signal_dates[i],
                    'equal_observed_states': sc == sp,
                    'forward_matches_point_center_state': [name for j, name in enumerate(COORDINATES)
                        if outcome(forward[j][0], metric) == outcome(d, metric)],
                    'forward_matches_point_point_state': [name for j, name in enumerate(COORDINATES)
                        if outcome(forward[j][1], metric) == outcome(d, metric)]}
            for state_index, state_name, base, full in ((0, 'center_state', a, b), (1, 'point_state', cc, d)):
                base_value, full_value = outcome(base, metric), outcome(full, metric)
                different = base_value != full_value
                counts[f'{state_name}/{metric}/all_coordinates_change'] += different
                reproduce = []
                for j, name in enumerate(COORDINATES):
                    fv, rv = outcome(forward[j][state_index], metric), outcome(reverse[j][state_index], metric)
                    prefix = f'{state_name}/{metric}/{name}/'
                    counts[prefix + 'forward_changes_base'] += fv != base_value
                    counts[prefix + 'forward_reproduces_changed_full'] += different and fv == full_value
                    counts[prefix + 'reverse_changes_full'] += rv != full_value
                    counts[prefix + 'reverse_restores_base'] += different and rv == base_value
                    counts[prefix + 'individual_change_cancelled_in_full'] += not different and fv != base_value
                    reproduce.append(fv == full_value)
                counts[f'{state_name}/{metric}/changed_full_no_single_reproduces'] += different and not any(reproduce)
        rows.append(row)
    assert len(rows) == 1636
    # Recompute every count for every signal/execution year from the exact rows using this same
    # metric predicate; no chronology omitted, including pre-2020 signal and None execution.
    summaries = {'ALL': dict(counts)}
    year_groups = {('signal', year): [r for r in rows if r['signal_date'][:4] == year]
                   for year in sorted({r['signal_date'][:4] for r in rows})}
    year_groups.update({('execution', year): [r for r in rows if r['execution_date'] is not None
                      and r['execution_date'][:4] == year]
                      for year in sorted({r['execution_date'][:4] for r in rows if r['execution_date'] is not None})})
    year_groups[('execution', 'NONE')] = [r for r in rows if r['execution_date'] is None]
    for (basis, year), selected in year_groups.items():
        yearly = Counter({key: 0 for key in counts})
        for row in selected:
            a, b, cc, d = row['full_four']
            for metric in METRICS:
                yearly[f'actual/{metric}/different'] += outcome(a, metric) != outcome(d, metric)
                for si, sn, base, full in ((0, 'center_state', a, b), (1, 'point_state', cc, d)):
                    bv, dv = outcome(base, metric), outcome(full, metric)
                    different, reproduce = bv != dv, []
                    yearly[f'{sn}/{metric}/all_coordinates_change'] += different
                    for j, name in enumerate(COORDINATES):
                        fv, rv = outcome(row['forward'][j][si], metric), outcome(row['reverse'][j][si], metric)
                        prefix = f'{sn}/{metric}/{name}/'
                        yearly[prefix + 'forward_changes_base'] += fv != bv
                        yearly[prefix + 'forward_reproduces_changed_full'] += different and fv == dv
                        yearly[prefix + 'reverse_changes_full'] += rv != dv
                        yearly[prefix + 'reverse_restores_base'] += different and rv == bv
                        yearly[prefix + 'individual_change_cancelled_in_full'] += not different and fv != bv
                        reproduce.append(fv == dv)
                    yearly[f'{sn}/{metric}/changed_full_no_single_reproduces'] += different and not any(reproduce)
        summaries[f'{basis}/{year}'] = {'days': len(selected), 'counts': dict(yearly)}
    for basis in ('signal', 'execution'):
        selected = [value for key, value in summaries.items() if key.startswith(basis + '/')]
        assert sum(item['days'] for item in selected) == 1636
        assert all(sum(item['counts'][key] for item in selected) == value for key, value in counts.items())
    return {'status': 'PASS', 'days': len(rows), 'all_days': rows, 'summaries': summaries,
            'first_actual_divergence': first_actual,
            'center_parameters': c, 'point_parameters': p,
            'coordinate_values': {name: [scalar(c, name), scalar(p, name)] for name in COORDINATES}}


def main():
    plan = source_check()
    assert not OUTPUT.exists(), 'Retain any previous success/failure; no overwrite'
    identity_audit, original_oracle, old_trace, verify_account = load_original_oracle()
    calendar, ctx = calendar_oracle(), context(1)
    prepared = cache_read(TRANSPORT / 'prepared.pkl.gz')
    transport = next(row for row in prepared if row['label'] == 'B0-TIME')
    parameter_plan = transport['plan']
    matrix = read(ROOT / 'research/S013/assets/runs/EX043_20261011/parameter_matrix_v3.json')
    points = sorted((r for r in matrix['rows'] if r['center'] == 'B0-TIME'), key=lambda row: row['point_index'])
    assert [row['point_index'] for row in points] == list(range(32))
    native, parameters, audits, accounts = {}, {}, {}, {}
    benchmark = None
    try:
        for item in [None, *points]:
            key = 'center' if item is None else f"P{item['point_index']:02d}"
            bound, result = (transport['center'], transport['result']) if item is None else cache_read(TRANSPORT / (item['label'] + '.pkl.gz'))
            ref = plan['input_accounts'][key]
            formal = verified_json(ref)
            validate_evaluation_evidence(formal)
            assert formal == serialize_evaluation_evidence(bound, result)
            identity, funds = identity_audit(ctx, bound, result, formal), verify_account(bound, result)
            assert funds['known_low_error_potential_orders'] == 0 and len(result.runs) == 1
            if benchmark is None:
                benchmark, center_identity = result.runs[0].buyhold.execution, identity
                assert bound.strategy.candidate_id == 'C2132'
                assert parameter_plan.design.center.content_sha256 == identity['content_sha256']
            else:
                assert identity['source_sha256'] == center_identity['source_sha256']
                assert identity['dependency_sha256'] == center_identity['dependency_sha256']
                assert bound.strategy.candidate_id == item['candidate_id'] and identity['content_sha256'] == item['content_sha256']
                assert result.request_hash == item['request_hash'] and result.result_hash == item['result_hash']
                assert bound.lineage.parameter_binding.point == parameter_plan.design.bind_point(item['point_index'])
                assert verified_json(bound.lineage.parameter_binding.plan.to_dict()) == parameter_plan.to_dict()
                derivation = bound.lineage.derivation
                assert derivation.kind.value == 'PARAMETERS' and derivation.parent_content_sha256 == center_identity['content_sha256']
                assert derivation.child.candidate_id == item['candidate_id'] and derivation.child_content_sha256 == item['content_sha256']
            for name in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
                pd.testing.assert_frame_equal(getattr(benchmark, name), getattr(result.runs[0].buyhold.execution, name), check_exact=True)
            frame, p = result.runs[0].execution.decisions, bound.strategy.payload['parameters']
            rules, bars = validate_parameters(SignalKind.ORIGINAL_TIME, p), bound_bars(ctx, bound)
            dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize().as_unit('ns')
            executions = pd.DatetimeIndex(pd.to_datetime(frame.valid_session)).normalize().as_unit('ns')
            assert len(dates) == 1636
            dates_audit = calendar._audit_dates(ctx, bound, next(iter(bound.input_bindings.values())), frame, dates, bars)
            values, _, _ = original_oracle(ctx, bound, frame, p, old_trace)
            raw = tuple(float(x) for x in values.raw_acf)
            closes, previous = bars.Close.reindex(dates), bars.Close.shift(1).reindex(dates)
            features = tuple(Feature(str(row.regime), float(closes.iloc[i]), float(previous.iloc[i]),
                float(row.bull_range_position), float(row.bear_range_position), raw[i], raw[i],
                float(row.confirmation_score), float(p['confirmation']['threshold']), *rules)
                for i, row in enumerate(frame.itertuples()))
            native[key] = trace(SignalKind.ORIGINAL_TIME, features, tuple(float(x) for x in frame.target_position),
                                tuple(frame.signal_reason), tuple(dates), tuple(executions))
            parameters[key], accounts[key] = p, ref
            audits[key] = {'public_identity': identity, 'native_funds': funds, 'calendar': dates_audit,
                'serialized_account': 'EXACT_EQUAL', 'benchmark_ledgers': 'EXACT_EQUAL',
                'independent_original_features_and_signal_state': 'EXACT_EQUAL', 'signal_rows': len(dates)}
            print({'authenticated_original_accounts': len(native), 'key': key}, flush=True)
        assert len(native) == 33 and not SOURCE_CALLS
        pairs = {}
        for i in range(32):
            key = f'P{i:02d}'
            pairs[key] = complete_pair(native['center'], native[key], parameters['center'], parameters[key], bars)
            print({'complete_single_coordinate_pairs': len(pairs), 'days': 1636}, flush=True)
        result = {'status': 'PASS', 'plan_reference': read(PROTOCOLS / 'plan_reference.json'),
            'input_accounts': accounts, 'audits': audits, 'pairs': pairs, 'coordinates': list(COORDINATES),
            'encoding': {'decision': ['target', 'reason_code', 'next_route_code', 'next_age'],
                         'reasons': list(REASONS), 'routes': list(ROUTES),
                         'before_state': ['holding', 'route_code', 'age'], 'four': ['A=Fc(Sc)', 'B=Fp(Sc)', 'C=Fc(Sp)', 'D=Fp(Sp)'],
                         'forward_and_reverse': 'Each coordinate list has [on observed center state, on observed point state]. Forward changes only selected center coordinate to point; reverse changes only selected point coordinate to center. Original state has no other memory fields.'},
            'summary': {'unique_native_accounts': 33, 'native_signal_rows': 33 * 1636,
                        'complete_pairs': 32, 'complete_coordinate_pair_days': 32 * 13 * 1636,
                        'single_coordinate_step_evaluations': 32 * 13 * 1636 * 4,
                        'new_account_evaluations': 0, 'new_account_preparations': 0, 'cash_replays': 0, 'provider_calls': SOURCE_CALLS},
            'limits': plan['limits']}
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(json_standard(result), ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8', newline='\n')
        print({'diagnosis': 'PASS', **result['summary']}, flush=True)
    except Exception as error:
        assert not OUTPUT.exists()
        write(OUTPUT, {'status': 'FAILED', 'plan_reference': read(PROTOCOLS / 'plan_reference.json'),
            'input_accounts': accounts, 'audits': audits, 'new_account_evaluations': 0,
            'error': {'type': type(error).__name__, 'message': str(error)},
            'policy': 'Retain immutable failure; no partial PASS or account replay'})
        raise


if __name__ == '__main__':
    main()
