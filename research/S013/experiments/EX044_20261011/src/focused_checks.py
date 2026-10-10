"""Pure EX044 state/one-step contrasts; no real accounts or evaluation APIs."""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

import numpy as np
import pandas as pd
from probe import diagnose_probe, fixed_values
from transition import SignalKind, RouteRule, Feature, SignalState, step, trace
from contrasts import classify, compare_same_kind, cross_actual


def run():
    counts = {'step_cases': 0, 'rejected_inputs': 0, 'binary_partitions': 0,
              'multivalue_partitions': 0, 'probe_cases': 0, 'trace_cases': 0}
    original = SignalKind.ORIGINAL_TIME
    new = SignalKind.MEAN_BEAR_TIME_BELOW_CLOSE
    bull = RouteRule(entry=.4, exit=.8, max_hold=4, acf_min=None)
    bear = RouteRule(entry=.4, exit=.8, max_hold=4, acf_min=.1)
    feature = Feature(raw_route='bear', signal_close=99., previous_signal_close=100.,
        bull_range_position=.2, bear_range_position=.2, bull_acf_value=.2,
        bear_acf_value=.2, confirmation_score=0., confirmation_threshold=-.2,
        bull_rule=bull, bear_rule=bear)
    flat = SignalState(holding=False, route=None, age=0)

    def check(kind, state, f, target, reason, expected):
        result = step(kind, state, f)
        assert result.target == target and result.reason == reason
        assert result.next_state == expected, (asdict(state), asdict(f), asdict(result), asdict(expected))
        counts['step_cases'] += 1
        return result

    def refuse(call):
        try:
            call()
        except (AssertionError, ValueError, TypeError):
            counts['rejected_inputs'] += 1
            return
        raise AssertionError('Invalid state/input accepted')

    for kind in (original, new):
        entered = SignalState(holding=True, route='bear', age=0,
                              entry_anchor=99. if kind == new else None)
        check(kind, flat, feature, 1, 'entry', entered)
        check(kind, flat, replace(feature, confirmation_score=-.2), 1, 'entry', entered)
        check(kind, flat, replace(feature, confirmation_score=np.nextafter(-.2, -np.inf)),
              0, 'confirmation_rejected', flat)
        check(kind, flat, replace(feature, bear_range_position=np.nextafter(.4, np.inf)), 0, 'flat', flat)
        check(kind, flat, replace(feature, bear_acf_value=np.nextafter(.1, -np.inf)), 0, 'flat', flat)
        check(kind, flat, replace(feature, bear_range_position=.4, bear_acf_value=.1), 1, 'entry', entered)
        held = SignalState(holding=True, route='bear', age=2,
                           entry_anchor=100. if kind == new else None)
        check(kind, held, feature, 1, 'hold', replace(held, age=3))
        for position, age, raw, reason in ((.8, 3, 'bull', 'range'),
                                          (.2, 3, 'bull', 'time'), (.2, 2, 'bull', 'regime')):
            ending = replace(held, age=age)
            expected = flat if kind == original else replace(flat, last_exit_reason=reason,
                last_exit_route='bear', last_exit_category='BELOW' if reason == 'time' else None)
            check(kind, ending, replace(feature, bear_range_position=position, raw_route=raw),
                  0, reason, expected)

    held = SignalState(holding=True, route='bear', age=3, entry_anchor=100.)
    for price, category in ((np.nextafter(100., 0.), 'BELOW'), (100., 'EQUAL'),
                            (np.nextafter(100., np.inf), 'ABOVE')):
        expected = replace(flat, last_exit_reason='time', last_exit_route='bear', last_exit_category=category)
        check(new, held, replace(feature, signal_close=price), 0, 'time', expected)
        # Non-selected EQUAL/ABOVE classes preserve original score entry even on a falling day.
        if category != 'BELOW':
            entered = SignalState(holding=True, route='bear', age=0, entry_anchor=99.)
            check(new, expected, feature, 1, 'entry', entered)

    pending = replace(flat, last_exit_reason='time', last_exit_route='bear', last_exit_category='BELOW')
    check(new, pending, replace(feature, confirmation_score=-.4), 0, 'entry_direction_rejected', pending)
    check(new, pending, replace(feature, signal_close=100., previous_signal_close=100.),
          0, 'entry_direction_rejected', pending)
    rising = replace(feature, previous_signal_close=98.)
    check(new, pending, replace(rising, confirmation_score=-.4), 0, 'confirmation_rejected', pending)
    check(new, pending, rising, 1, 'entry', SignalState(True, 'bear', 0, entry_anchor=99.))
    check(new, pending, replace(feature, bear_range_position=.6), 0, 'flat', pending)
    check(new, pending, replace(feature, raw_route='bull', bull_range_position=.6), 0, 'flat', pending)
    check(new, pending, replace(feature, raw_route='bull'), 1, 'entry',
          SignalState(True, 'bull', 0, entry_anchor=99.))
    bull_held = SignalState(True, 'bull', 3, entry_anchor=100.)
    check(new, bull_held, replace(feature, raw_route='bull'), 0, 'time',
          replace(flat, last_exit_reason='time', last_exit_route='bull', last_exit_category=None))

    # Illegal normalized states cannot quietly erase an economically active anchor.
    for state, changes in ((held, {'entry_anchor': None}), (held, {'entry_anchor': 0.}),
                            (held, {'entry_anchor': np.nan}), (held, {'route': None}),
                            (held, {'age': -1}), (held, {'last_exit_reason': 'time'}),
                            (flat, {'entry_anchor': 100.}), (flat, {'route': 'bear'}),
                            (flat, {'age': 1}), (pending, {'last_exit_category': 'UNKNOWN'}),
                            (pending, {'last_exit_reason': 'range'}), (pending, {'last_exit_route': 'bull'})):
        refuse(lambda state=state, changes=changes: step(new, replace(state, **changes), feature))
    for changes in ({'raw_route': 'UNKNOWN'}, {'signal_close': 0.},
                    {'previous_signal_close': np.nan}, {'confirmation_score': np.nan},
                    {'bear_acf_value': np.inf}):
        refuse(lambda changes=changes: step(new, flat, replace(feature, **changes)))

    # Independent truth table: labels describe which swap reproduces D, not causal isolation.
    def expected_class(a, b, c, d):
        if a == d:
            return 'equal' if b == a and c == a else 'cancellation'
        if b == d and c == d:
            return 'either_sufficient'
        if b == d:
            return 'input_only'
        if c == d:
            return 'state_only'
        return 'joint_interaction'

    for values in product((0, 1), repeat=4):
        assert classify(*values) == expected_class(*values)
        counts['binary_partitions'] += 1
    outcomes = ((0, 'flat'), (0, 'time'), (0, 'entry_direction_rejected'), (1, 'entry'))
    categories = {key: 0 for key in ('equal', 'cancellation', 'either_sufficient',
                                    'input_only', 'state_only', 'joint_interaction')}
    for values in product(outcomes, repeat=4):
        category = classify(*values)
        assert category == expected_class(*values)
        categories[category] += 1
        counts['multivalue_partitions'] += 1
    assert all(categories.values()) and sum(categories.values()) == 256
    # Third reasons are retained: input_only means only B reaches D; C need not equal A.
    assert classify((0, 'flat'), (1, 'entry'), (0, 'time'), (1, 'entry')) == 'input_only'
    assert classify((0, 'flat'), (0, 'time'), (0, 'entry_direction_rejected'), (1, 'entry')) == 'joint_interaction'

    # Fixed120 probe changes only the causal input field, never score/threshold/parameters/state.
    samples = np.linspace(-.3, .3, 121)
    raw_acf = .1
    fixed120 = raw_acf - float(np.mean(samples[:120]))
    probed = replace(feature, bear_acf_value=fixed120)
    unchanged = set(asdict(feature)) - {'bear_acf_value'}
    assert all(asdict(feature)[key] == asdict(probed)[key] for key in unchanged)
    changed_future = samples.copy()
    changed_future[-1] = 1000.
    assert raw_acf - float(np.mean(changed_future[:120])) == fixed120
    for kind in (original, new):
        kind_held = held if kind == new else replace(held, entry_anchor=None)
        for state in (flat, kind_held):
            native = step(kind, state, replace(feature, bear_acf_value=.1))
            same = step(kind, state, replace(feature, bear_acf_value=np.nextafter(.1, np.inf)))
            assert native == same
            counts['probe_cases'] += 1
        native = step(kind, flat, replace(feature, bear_acf_value=.1))
        flip = step(kind, flat, replace(feature, bear_acf_value=np.nextafter(.1, -np.inf)))
        assert native.target == 1 and flip.target == 0 and native.next_state != flip.next_state
        for state, f in ((kind_held, feature), (flat, replace(feature, raw_route='bull'))):
            assert step(kind, state, f) == step(kind, state, replace(f, bear_acf_value=-100.))
            counts['probe_cases'] += 1
    refused = step(new, pending, feature)
    ineligible = step(new, pending, replace(feature, bear_acf_value=np.nextafter(.1, -np.inf)))
    assert refused.target == ineligible.target == 0 and refused.reason != ineligible.reason
    assert refused.next_state == ineligible.next_state == pending
    counts['probe_cases'] += 1

    # December T may execute in January; the final missing execution date is retained.
    dates = (date(2022, 12, 30), date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5))
    executions = (date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5), None)
    features = (feature, feature, feature, feature)
    traces = []

    def certified(kind, fs, ds=dates, es=executions):
        current, decisions = flat, []
        for f in fs:
            decision = step(kind, current, f)
            decisions.append(decision)
            current = decision.next_state
        return trace(kind, fs, tuple(d.target for d in decisions), tuple(d.reason for d in decisions), ds, es)

    def verify_partitions(rows, partitions, category_key, difference_key, labels):
        for basis, key in (('signal_year', 'signal_date'), ('execution_year', 'execution_date')):
            mapping = partitions[basis]
            expected_years = {row[key][:4] for row in rows if row[key] is not None}
            assert set(mapping) == {'ALL', *expected_years, *({'NONE'} if basis == 'execution_year' else set())}
            for year, summary in mapping.items():
                selected = rows if year == 'ALL' else [r for r in rows if
                    (r[key] is None if year == 'NONE' else r[key] is not None and r[key][:4] == year)]
                assert summary['days'] == len(selected)
                if category_key:
                    assert set(summary['counts']) == set(labels)
                    assert summary['counts'] == {label: sum(r[category_key] == label for r in selected) for label in labels}
                if difference_key:
                    assert summary['actual_difference_days'] == sum(r[difference_key] for r in selected)
            assert sum(s['days'] for y, s in mapping.items() if y != 'ALL') == len(rows)

    def verify_runs(rows, runs, key):
        flattened = []
        for segment in runs:
            assert segment['first_index'] == len(flattened)
            assert segment['last_index'] - segment['first_index'] + 1 == segment['length']
            flattened.extend([segment['value']] * segment['length'])
        assert flattened == [row[key] for row in rows]
        assert runs[-1]['last_index'] == len(rows) - 1
        assert runs[-1]['last_execution_date'] == rows[-1]['execution_date']

    def verify_comparison(center, point):
        compared = compare_same_kind(center, point)
        rows = compared['all_days']
        assert compared['status'] == 'PASS' and len(rows) == len(center.features)
        assert [r['index'] for r in rows] == list(range(len(rows)))
        for row in rows:
            i = row['index']
            assert row['center_state_before'] == asdict(center.before[i])
            assert row['point_state_before'] == asdict(point.before[i])
            assert row['input_features_different'] == (center.features[i] != point.features[i])
            assert row['decision_state_different'] == (center.before[i] != point.before[i])
            physical = center.before[i].physical != point.before[i].physical
            assert row['physical_state_different'] == physical
            assert row['memory_only_state_difference'] == (not physical and center.before[i] != point.before[i])
            wanted_group = ('physical_different_' if physical else 'physical_equal_') + (
                'decision_different' if row['decision_state_different'] else 'decision_equal')
            assert row['state_group'] == wanted_group
            for outcome in ('target', 'target_reason'):
                values = tuple(item['target'] if outcome == 'target' else (item['target'], item['reason'])
                    for item in (row['four_decisions'][label] for label in ('A', 'B', 'C', 'D')))
                assert row[outcome + '_category'] == expected_class(*values)
                assert row[outcome + '_actual_difference'] == (values[0] != values[3])
        for outcome, summary in compared['outcomes'].items():
            key, difference = outcome + '_category', outcome + '_actual_difference'
            verify_partitions(rows, summary['partitions'], key, difference, categories)
            verify_runs(rows, summary['classification_runs'], key)
            verify_runs(rows, summary['actual_difference_runs'], difference)
            first = next((r for r in rows if r[difference]), None)
            expected_first = None if first is None else {name: first[name]
                for name in ('index', 'signal_date', 'execution_date')}
            assert summary['first_actual_divergence'] == expected_first
        state = compared['state_propagation']
        state_labels = ('physical_equal_decision_equal', 'physical_equal_decision_different',
                        'physical_different_decision_equal', 'physical_different_decision_different')
        verify_partitions(rows, state['partitions'], 'state_group', 'memory_only_state_difference', state_labels)
        verify_runs(rows, state['state_group_runs'], 'state_group')
        verify_runs(rows, state['memory_only_runs'], 'memory_only_state_difference')
        assert compared['tail_states'] == {'center': asdict(center.tail_state), 'point': asdict(point.tail_state)}
        counts['trace_cases'] += 1
        return compared

    for kind in (original, new):
        current, decisions = flat, []
        for f in features:
            decision = step(kind, current, f)
            decisions.append(decision)
            current = decision.next_state
        traced = trace(kind, features, tuple(d.target for d in decisions), tuple(d.reason for d in decisions),
                       dates, executions)
        assert len(traced.before) == len(traced.after) == len(traced.decisions) == 4
        assert traced.before[0] == flat and traced.after[-1] == decisions[-1].next_state
        assert traced.execution_dates[-1] is None
        traces.append(traced)
        counts['trace_cases'] += 1
        refuse(lambda: trace(kind, features, (0,) * 4, tuple(d.reason for d in decisions), dates, executions))
        refuse(lambda: trace(kind, features, tuple(d.target for d in decisions), tuple(d.reason for d in decisions),
                             tuple(reversed(dates)), executions))
        refuse(lambda: trace(kind, features, tuple(d.target for d in decisions), tuple(d.reason for d in decisions),
                             dates, (dates[0], *executions[1:])))
        same = compare_same_kind(traced, traced)
        assert isinstance(same, dict)
        verify_comparison(traced, traced)
    refuse(lambda: compare_same_kind(traces[0], traces[1]))
    observed = cross_actual(*traces)
    assert all(not row['physical_state_difference'] for row in observed['all_days'])
    assert any(asdict(a) != asdict(b) for a, b in zip(traces[0].before, traces[1].before, strict=True))
    for name, summary in observed['summaries'].items():
        verify_partitions(observed['all_days'], summary['partitions'], None, name, ())
        verify_runs(observed['all_days'], summary['difference_runs'], name)

    # Dependent state paths are certified separately; B/C steps never become a new replay.
    rng = np.random.default_rng(13)
    long_dates = (date(2022, 12, 28), date(2022, 12, 29), date(2022, 12, 30),
                  date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5),
                  date(2023, 12, 28), date(2023, 12, 29), date(2024, 1, 2), date(2024, 1, 3))
    long_execution = (*long_dates[1:], None)
    observed_classes, observed_state_groups = set(), set()
    for kind in (original, new):
        for _ in range(32):
            fc, fp = [], []
            last_close = 100.
            for _ in long_dates:
                closing = last_close + float(rng.choice((-2., -1., 0., 1., 2.)))
                f = replace(feature, raw_route=str(rng.choice(('bull', 'bear'))), signal_close=closing,
                    previous_signal_close=last_close, bull_range_position=float(rng.uniform(0, 1)),
                    bear_range_position=float(rng.uniform(0, 1)), bear_acf_value=float(rng.uniform(-.2, .3)),
                    confirmation_score=float(rng.uniform(-.4, .4)))
                fc.append(f)
                fp.append(replace(f, raw_route=f.raw_route if rng.random() < .8 else
                    ('bull' if f.raw_route == 'bear' else 'bear'),
                    bear_range_position=float(np.clip(f.bear_range_position + rng.uniform(-.1, .1), 0, 1)),
                    confirmation_score=f.confirmation_score + .05,
                    bull_rule=replace(bull, max_hold=3), bear_rule=replace(bear, max_hold=3, entry=.5)))
                last_close = closing
            center = certified(kind, fc, long_dates, long_execution)
            point = certified(kind, fp, long_dates, long_execution)
            before_center, before_point = center, point
            compared = verify_comparison(center, point)
            assert center == before_center and point == before_point
            observed_classes.update(row[outcome + '_category'] for row in compared['all_days']
                                    for outcome in ('target', 'target_reason'))
            observed_state_groups.update(row['state_group'] for row in compared['all_days'])
    # Aligned but tampered transition/state/date arrays must be rejected.
    bad_after = replace(point, after=(flat, *point.after[1:]))
    refuse(lambda: compare_same_kind(center, bad_after))
    bad_dates = replace(point, signal_dates=tuple(reversed(point.signal_dates)))
    refuse(lambda: compare_same_kind(center, bad_dates))

    # Direct integration of the declared probe functions with an independent ACF/reference formula.
    bar_dates = pd.bdate_range(end='2023-01-05', periods=220)
    price_rng = np.random.default_rng(23)
    closes = 100. * np.exp(np.cumsum(price_rng.normal(0., .004, len(bar_dates))))
    bars = pd.DataFrame({'Close': closes}, index=bar_dates)
    probe_dates = pd.DatetimeIndex(dates)

    def independent_raw(data):
        returns = data.Close.astype(float).pct_change(fill_method=None).to_numpy()
        raw = np.full(len(returns), np.nan)
        for i in range(20, len(returns)):
            window = returns[i - 19:i + 1]
            centered = window - window.mean()
            variance = np.mean(centered ** 2)
            if not np.isclose(variance, 0.):
                raw[i] = float(np.dot(centered[1:], centered[:-1]) / 19 / variance)
        return pd.Series(raw, index=data.index)

    raw = independent_raw(bars)
    certified_raw = raw.reindex(probe_dates).to_numpy()
    fixed = fixed_values(bars, probe_dates, certified_raw)
    expected_fixed = tuple(float(raw.iloc[i] - np.mean(raw.iloc[i - 120:i].to_numpy()))
        for i in bar_dates.get_indexer(probe_dates))
    np.testing.assert_allclose(fixed, expected_fixed, rtol=0., atol=1e-14)
    # Current shock changes current ACF, while its strictly-past120 reference stays fixed.
    changed = bars.copy()
    changed.loc[probe_dates[0], 'Close'] *= 1.2
    changed_raw = independent_raw(changed).reindex(probe_dates).to_numpy()
    changed_fixed = fixed_values(changed, probe_dates, changed_raw)
    assert changed_raw[0] != certified_raw[0]
    np.testing.assert_allclose(changed_raw[0] - changed_fixed[0], certified_raw[0] - fixed[0], rtol=0., atol=1e-14)
    future = bars.copy()
    future.loc[future.index > probe_dates[0], 'Close'] *= 1.3
    future_raw = independent_raw(future).reindex(probe_dates).to_numpy()
    assert fixed_values(future, probe_dates, future_raw)[0] == fixed[0]
    refuse(lambda: fixed_values(bars, probe_dates, certified_raw + .001))
    refuse(lambda: fixed_values(bars.iloc[-130:], probe_dates, certified_raw))

    probe_keys = ('target_different', 'target_reason_different', 'next_state_different')

    def verify_probe(own, values):
        output = diagnose_probe(own, values)
        rows = output['all_days']
        assert len(rows) == len(values) and [r['index'] for r in rows] == list(range(len(rows)))
        for i, row in enumerate(rows):
            actual = own.decisions[i]
            altered = step(own.kind, own.before[i], replace(own.features[i], bear_acf_value=values[i]))
            assert row['target_different'] == (actual.target != altered.target)
            assert row['target_reason_different'] == (actual.outcome('target_reason') != altered.outcome('target_reason'))
            assert row['next_state_different'] == (actual.next_state != altered.next_state)
            assert row['actual']['next_state'] == asdict(actual.next_state)
            assert row['probe']['next_state'] == asdict(altered.next_state)
            if own.before[i].holding:
                assert actual == altered, 'Holding exits must ignore a changed bear-entry ACF'
        assert output['all_next_states_identical'] == (not any(r['next_state_different'] for r in rows))
        for basis, key in (('signal_year', 'signal_date'), ('execution_year', 'execution_date')):
            mapping = output['partitions'][basis]
            years = {r[key][:4] for r in rows if r[key] is not None}
            assert set(mapping) == {'ALL', *years, *({'NONE'} if basis == 'execution_year' else set())}
            for year, summary in mapping.items():
                selected = rows if year == 'ALL' else [r for r in rows if
                    (r[key] is None if year == 'NONE' else r[key] is not None and r[key][:4] == year)]
                assert summary == {'days': len(selected), **{name: sum(r[name] for r in selected) for name in probe_keys}}
            assert sum(summary['days'] for year, summary in mapping.items() if year != 'ALL') == len(rows)
        assert rows[-1]['execution_date'] is None
        counts['probe_cases'] += 1
        return output

    for own in traces:
        verify_probe(own, fixed)
        changed_probe = verify_probe(own, (-.1,) * len(own.features))
        assert changed_probe['partitions']['signal_year']['ALL'] == {
            'days': 4, 'target_different': 1, 'target_reason_different': 1, 'next_state_different': 1}
        same_probe = verify_probe(own, (.2,) * len(own.features))
        assert same_probe['all_next_states_identical']
        assert all(same_probe['partitions']['signal_year']['ALL'][key] == 0 for key in probe_keys)
    short_rule = replace(bear, max_hold=1)
    context_features = tuple(replace(feature, signal_close=closing, previous_signal_close=previous,
        bear_rule=short_rule) for closing, previous in ((99., 100.), (98., 99.), (97., 98.)))
    context_trace = certified(new, context_features, dates[:3], (*executions[:2], None))
    reason_only = verify_probe(context_trace, (.2, .2, -.1))
    assert reason_only['partitions']['signal_year']['ALL'] == {
        'days': 3, 'target_different': 0, 'target_reason_different': 1, 'next_state_different': 0}
    assert reason_only['all_next_states_identical'], 'Equal next states certify state/target continuation, not unchanged reasons'

    return {'status': 'PURE_PASS', 'new_account_evaluations': 0, 'new_account_preparations': 0,
            'counts': counts, 'truth_table_categories': categories,
            'observed_trace_categories': sorted(observed_classes), 'observed_state_groups': sorted(observed_state_groups),
            'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'limits': 'Synthetic one-step predicates and states only. Swap sufficiency labels do not establish single-parameter causality or profits. Fixed120 probe does not replay future signals or cash.'}


def main():
    result = run()
    folder = Path(__file__).resolve().parent.parents[4] / '.tmp/ex044-diagnosis'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'focused.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n',
        encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
