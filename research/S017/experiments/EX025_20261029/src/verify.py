"""Independent EX025 fixed-condition ablation verification.

Statistical helpers are adapted from the independent EX024/EX022 verifiers.
Expected values never call production estimators. Authenticated EX024 facts
and EX020 labels are reused; no bars, features or original fills are rebuilt.
"""
# ruff: noqa: E402
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import gzip
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'
import numpy as np

from study import WORK, authenticate, digest, inputs, read, save


HORIZONS = (3, 13, 26, 65, 130)
NAMES = ('S017-M001', 'S017-M002', 'S017-M005', 'S017-M006', 'S017-M007', 'S017-M008')
FACTOR_NAMES = NAMES[2:]
PAIRS = (('S017-M005', 'S017-M007'), ('S017-M005', 'S017-M008'),
         ('S017-M005', 'S017-M006'), ('S017-M007', 'S017-M006'), ('S017-M008', 'S017-M006'))
COUNTS = Counter()


def equal(actual, expected, label):
    """Compare full structures, permitting only roundoff in finite numbers."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise AssertionError(f'{label}: dictionary keys differ')
        for key, value in expected.items():
            equal(actual[key], value, f'{label}/{key}')
    elif isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            raise AssertionError(f'{label}: sequence length differs')
        for i, (left, right) in enumerate(zip(actual, expected)):
            equal(left, right, f'{label}/{i}')
    elif isinstance(expected, (float, np.floating)):
        if not isinstance(actual, (int, float)) or not math.isfinite(actual):
            raise AssertionError(f'{label}: expected finite value, received {actual!r}')
        if not math.isclose(actual, float(expected), rel_tol=1e-10, abs_tol=2e-12):
            raise AssertionError(f'{label}: {actual!r} != {expected!r}')
    elif actual != expected:
        raise AssertionError(f'{label}: {actual!r} != {expected!r}')
    COUNTS['checked_values'] += 1


def expected_stats(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return {'count': 0}
    count = len(values)
    positive = [v for v in values if v > 0]
    negative = [v for v in values if v < 0]
    payoff = None
    if positive and negative:
        payoff = (math.fsum(positive)/len(positive))/(-math.fsum(negative)/len(negative))
    return {'count': count, 'mean': math.fsum(values)/count,
            'median': float(np.quantile(values, .5)),
            'win_rate': len(positive)/count, 'payoff_ratio': payoff,
            'q10': float(np.quantile(values, .1)), 'q90': float(np.quantile(values, .9))}


def expected_summary(rows):
    return {'events': len(rows), 'days': len(set(r['date'] for r in rows)),
            'status': dict(Counter(r['status'] for r in rows)),
            'price': expected_stats(r['price_net_return'] for r in rows)}


def baseline_match(control, targets):
    groups = {}
    for r in control:
        if r['price_net_return'] is not None:
            groups.setdefault(r['stratum'], []).append(r['price_net_return'])
    complete = [r for r in targets if r['price_net_return'] is not None]
    supported = [r for r in complete if r['stratum'] in groups]
    means = {k: math.fsum(v)/len(v) for k, v in groups.items()}
    return {'all_target': expected_summary(targets),
            'supported_target': expected_summary(supported),
            'unmatched_indices': [r['i'] for r in complete if r['stratum'] not in groups],
            'supported_indices': [r['i'] for r in supported],
            'control': expected_stats(means[r['stratum']] for r in supported),
            'difference': expected_stats(r['price_net_return']-means[r['stratum']] for r in supported),
            'support': {'cells': len(set(r['stratum'] for r in supported)),
                        'minimum_control_count': min((len(groups[r['stratum']]) for r in supported), default=None),
                        'singleton_targets': sum(len(groups[r['stratum']]) == 1 for r in supported)}}


def expected_match(control, targets, extended=True):
    result = baseline_match(control, targets)
    if extended:
        complete = [r for r in targets if r['price_net_return'] is not None]
        target_ids = {r['i'] for r in complete}
        controls = {}
        for row in control:
            if row['price_net_return'] is not None:
                controls.setdefault(row['stratum'], set()).add(row['i'])
        result['support']['all_target_cell_events'] = sum(
            bool(controls.get(r['stratum'])) and not (controls[r['stratum']]-target_ids) for r in complete)
        result['support']['self_in_control_events'] = sum(
            r['i'] in controls.get(r['stratum'], set()) for r in complete)
    return result


def expected_interval(values):
    valid = [v for v in values if v is not None]
    return {'valid_replicates': len(valid), 'undefined_replicates': len(values)-len(valid),
            'interval_95': [float(v) for v in np.quantile(valid, [.025, .975])] if valid else None}


def check_comparison(item, control, targets, label, draws=None, extended=True):
    equal(item['summary'], expected_summary(targets), label+'/summary')
    expected = expected_match(control, targets, extended)
    equal(item['matched'], expected, label+'/matched')
    COUNTS['comparisons'] += 1
    if draws is not None:
        equal(sorted(draws), ['all_target_mean', 'difference', 'supported_target_mean'], label+'/draw_keys')
        for name, values in draws.items():
            equal(len(values), 1000, label+'/'+name+'/replicates')
            if any(v is not None and not math.isfinite(v) for v in values):
                raise AssertionError(label+': non-finite bootstrap draw')
        supported_empty = sum(v is None for v in draws['supported_target_mean'])
        difference_empty = sum(v is None for v in draws['difference'])
        equal(item['bootstrap'], {
            'intervals': {name: expected_interval(v) for name, v in draws.items()},
            'empty_target_replicates': supported_empty,
            'unsupported_control_replicates': difference_empty-supported_empty,
            'original_unmatched': len(expected['unmatched_indices'])}, label+'/bootstrap')
        if difference_empty < supported_empty:
            raise AssertionError(label+': delta present when target mean is absent')
        if any(a is None and b is not None for a, b in zip(draws['supported_target_mean'], draws['difference'])):
            raise AssertionError(label+': missing target unexpectedly has comparison')
        COUNTS['bootstrap_interval_sets'] += 1
    elif 'bootstrap' in item:
        raise AssertionError(label+': unexpected bootstrap without retained draws')


def independent_sparse(indices, horizon):
    chosen = []
    for i in sorted(indices):
        if not chosen or i-chosen[-1] > horizon+1:
            chosen.append(i)
    return chosen


def expected_concentration(rows):
    positive = [r for r in rows if r['price_net_return'] is not None and r['price_net_return'] > 0]
    total = math.fsum(r['price_net_return'] for r in positive)
    years = {str(y): math.fsum(r['price_net_return'] for r in positive if r['date'].startswith(str(y)))
             for y in range(2019, 2026)}
    return {'positive_sum': total, 'positive_sum_by_year': years,
            'largest_year_share': max(years.values())/total if total else None,
            'largest_event_share': max((r['price_net_return'] for r in positive), default=0)/total if total else None,
            'scope': 'Arithmetic sums of event returns, possibly overlapping; not account PnL.'}


def independent_weights(days):
    n = len(days)
    rng = np.random.default_rng(17)
    starts = rng.integers(0, n-19, size=(1000, math.ceil(n/20)))
    weights = np.zeros((1000, n), dtype=np.int64)
    for j, row in enumerate(starts):
        selected = [d for start in row for d in range(int(start), int(start)+20)][:n]
        for day, count in Counter(selected).items():
            weights[j, day] = count
    equal(weights.sum(axis=1).tolist(), [n]*1000, 'weights/session_totals')
    return weights, sha256(starts.astype('<i8').tobytes()).hexdigest()


def independent_bootstrap(control, targets, days, weights):
    """Recompute via sorted cell reductions, independent of bincount estimator."""
    control = sorted((r for r in control if r['price_net_return'] is not None), key=lambda r: r['stratum'])
    targets = [r for r in targets if r['price_net_return'] is not None]
    groups = sorted(set(r['stratum'] for r in control))
    cells = {value: j for j, value in enumerate(groups)}
    supported = [r for r in targets if r['stratum'] in cells]
    day_ids = {d: j for j, d in enumerate(days)}
    x = np.array([r['price_net_return'] for r in control], dtype=float)
    xd = np.array([day_ids[r['date']] for r in control], dtype=int)
    starts = np.array([j for j, r in enumerate(control) if j == 0 or r['stratum'] != control[j-1]['stratum']], dtype=int)
    a = np.array([r['price_net_return'] for r in targets], dtype=float)
    ad = np.array([day_ids[r['date']] for r in targets], dtype=int)
    y = np.array([r['price_net_return'] for r in supported], dtype=float)
    yd = np.array([day_ids[r['date']] for r in supported], dtype=int)
    yc = np.array([cells[r['stratum']] for r in supported], dtype=int)
    result = {'all_target_mean': [], 'supported_target_mean': [], 'difference': []}
    for w in weights:
        aw, yw = w[ad], w[yd]
        result['all_target_mean'].append(float(np.average(a, weights=aw)) if aw.sum() else None)
        if not yw.sum():
            result['supported_target_mean'].append(None)
            result['difference'].append(None)
            continue
        result['supported_target_mean'].append(float(np.average(y, weights=yw)))
        cw = w[xd]
        den = np.add.reduceat(cw, starts)
        num = np.add.reduceat(cw*x, starts)
        if any(den[c] == 0 for c in yc[yw > 0]):
            result['difference'].append(None)
            continue
        positive = yw > 0
        delta = y[positive]-num[yc[positive]]/den[yc[positive]]
        result['difference'].append(float(np.average(delta, weights=yw[positive])))
    COUNTS['independently_recomputed_bootstrap_sets'] += 1
    return result


def check_groups(item, control, targets, label):
    equal(item['concentration'], expected_concentration(targets), label+'/concentration')
    equal(sorted(item['years']), [str(y) for y in range(2019, 2026)], label+'/years')
    equal(sorted(item['months']), sorted(set(r['month'] for r in control)), label+'/months')
    for key in ('years', 'months'):
        for group, comparison in item[key].items():
            check_comparison(comparison, [r for r in control if r['date'].startswith(group)],
                             [r for r in targets if r['date'].startswith(group)], label+'/'+key+'/'+group)


def main():
    analysis_path = WORK/'others/analysis.json'
    analysis, pre = read(analysis_path), read(WORK/'others/pre_run_evidence.json')
    equal(analysis['previous'], pre['previous'], 'previous_refs')
    for ref in pre['previous'].values():
        authenticate(ref)
    equal(analysis['protocol_sha256'], digest(WORK/'protocols/design.md'), 'protocol_sha256')
    equal(analysis['mechanism_index_sha256'], digest(WORK/'protocols/mechanism_index.json'), 'numbering_snapshot')
    for name, reference in pre['materials'].items():
        source = authenticate(reference)
        if name in ('design', 'authorization'):
            equal(digest(WORK/'protocols'/f'{name}.md'), digest(source), 'frozen_protocol/'+name)
        elif name == 'mechanism-index':
            equal(digest(WORK/'protocols/mechanism_index.json'), digest(source), 'frozen_numbering_snapshot')
        elif name == 'checks':
            equal(digest(WORK/'others/checks.json'), digest(source), 'frozen_checks')
        elif name.endswith('-source'):
            equal(digest(WORK/'src'/(name.removesuffix('-source')+'.py')), digest(source), 'frozen_source/'+name)
    for name, expected_hash in analysis['sources'].items():
        equal(digest(WORK/'src'/name), expected_hash, 'analysis_source/'+name)
    for name, expected_hash in analysis['artifacts'].items():
        equal(digest(WORK/f'others/{name}.json.gz'), expected_hash, 'artifact/'+name)
    rows, reference, prior = inputs(pre['previous'])
    equal(analysis['inputs'], prior['inputs'], 'inherited_input_identities')
    validation = read(authenticate(pre['previous']['reference-verification']))
    equal(validation['status'], 'PASS', 'prior_validation_status')
    equal(validation['analysis_sha256'], digest(authenticate(pre['previous']['reference-analysis'])), 'prior_validation_identity')
    equal(digest(authenticate(pre['previous']['reference-facts'])), prior['artifacts']['signal_facts'], 'old_fact_identity')
    facts = read_gzip(WORK/'others/signal_facts.json.gz')
    draws = read_gzip(WORK/'others/bootstrap_draws.json.gz')
    ids = [f['i'] for f in reference]
    equal(ids, list(range(ids[0], ids[-1]+1)), 'consecutive_ids')
    equal(len(ids), 22790, 'eligible_count')
    equal(len(rows), 113950, 'label_count')
    equal([f['i'] for f in facts], ids, 'new_fact_membership')
    equal(sorted(draws), sorted([*('horizon/'+str(n) for n in HORIZONS),
                                *('duration/'+name for name in NAMES),
                                *('contrast/'+a+'__'+b for a, b in PAIRS)]), 'draw_groups')
    original_by = {f['i']: f for f in reference}
    signals = {name: set() for name in NAMES}
    for row in facts:
        i, f = row['i'], row['facts']
        base = f['previous_close'] < f['previous_open'] and f['close'] > f['previous_high']
        narrow = f['previous_tr1'] <= f['atr_before_prior']
        volume = f['prior_volume'] >= 1.5*f['same_slot_volume_median20']
        states = {'S017-M005': base and narrow and volume, 'S017-M006': base,
                  'S017-M007': base and narrow, 'S017-M008': base and volume}
        expected_names = [name for name in NAMES[:2] if name in original_by[i]['signals']]
        expected_names.extend(name for name in FACTOR_NAMES if states[name])
        equal(row['signals'], expected_names, f'independent_predicates/{i}')
        equal(states['S017-M005'], 'S017-M005' in original_by[i]['signals'], f'old_M005_identity/{i}')
        equal({k: v for k, v in row.items() if k != 'signals'},
              {k: v for k, v in original_by[i].items() if k != 'signals'}, f'immutable_reference_facts/{i}')
        for name in expected_names:
            signals[name].add(i)
        COUNTS['scalar_signal_rows'] += 1
    equal(signals['S017-M005'], signals['S017-M007'] & signals['S017-M008'], 'factor_intersection')
    for target, control in PAIRS:
        equal(signals[target]-signals[control], set(), target+'/nested_in/'+control)
    equal(analysis['signal_counts'], {name: len(value) for name, value in signals.items()}, 'signal_counts')
    equal(len(signals[NAMES[0]]), prior['signal_counts'][NAMES[0]], 'M001_prior_identity')
    equal(len(signals[NAMES[1]]), prior['signal_counts'][NAMES[1]], 'M002_prior_identity')
    equal(len(signals['S017-M005']), prior['signal_counts']['S017-M005'], 'M005_prior_count')
    equal(len(signals[NAMES[1]]), 67, 'M002_original_67')
    equal(analysis['overlap'], {a: {b: len(signals[a] & signals[b]) for b in NAMES} for a in NAMES}, 'overlap')
    by_fact = {f['i']: f for f in facts}
    by_n = {n: [r for r in rows if r['n'] == n] for n in HORIZONS}
    east = ZoneInfo('America/New_York')
    for n, pop in by_n.items():
        equal([r['i'] for r in pop], ids, f'{n}/population_ids')
        for row in pop:
            i = row['i']
            at = datetime.fromisoformat(row['entry_at']).astimezone(east)
            equal(row['date'], str(at.date()), f'{n}/{i}/date')
            equal(row['month'], at.strftime('%Y-%m'), f'{n}/{i}/month')
            equal(row['stratum'], at.strftime('%Y-%m|%H:%M'), f'{n}/{i}/stratum')
            equal(row['signal_at'], by_fact[i]['signal_at'], f'{n}/{i}/signal_time')
            if not '2019-01-02' <= row['date'] <= '2025-12-31':
                raise AssertionError('Outside authorized development window')
            limit = (Decimal(str(by_fact[i]['facts']['close']))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01')
            equal(row['limit_price'], float(limit), f'{n}/{i}/limit')
            complete = row['price_net_return'] is not None
            equal(row['status'] == 'COMPLETE', complete, f'{n}/{i}/complete')
            if row['entry_price'] is not None and (row['entry_price'] <= 0 or row['entry_price'] > float(limit)+1e-12):
                raise AssertionError('Invalid limit-buy price')
            if complete:
                if row['exit_price'] is None or row['exit_price'] <= 0 or row['entry_price'] is None:
                    raise AssertionError('Complete event lacks execution prices')
                net = (row['exit_price']*.999-row['entry_price']*1.001)/(row['entry_price']*1.001)
                equal(row['price_net_return'], net, f'{n}/{i}/fees')
            COUNTS['event_rows'] += 1
    days = sorted({r['date'] for r in rows})
    equal(len(days), 1760, 'sessions')
    weights, starts_hash = independent_weights(days)
    equal(analysis['bootstrap'], {'replicates': 1000, 'block_sessions': 20, 'seed': 17,
        'sessions': len(days), 'starts_sha256': starts_hash, 'workers': 2, 'native_threads': 1}, 'bootstrap_contract')
    for n, pop in by_n.items():
        block = analysis['horizons'][str(n)]
        equal(block['all'], expected_summary(pop), f'{n}/all')
        equal(sorted(block['signals']), sorted(NAMES), f'{n}/signal_names')
        expected_draw_keys = []
        adjusted = [dict(r, stratum=r['stratum']+'|M001='+('1' if r['i'] in signals[NAMES[0]] else '0')) for r in pop]
        for name in NAMES:
            equal(sorted(block['signals'][name]), ['nonoverlap', 'raw'], f'{n}/{name}/modes')
            for mode in ('raw', 'nonoverlap'):
                chosen_ids = sorted(signals[name]) if mode == 'raw' else independent_sparse(signals[name], n)
                chosen = set(chosen_ids)
                targets = [r for r in pop if r['i'] in chosen]
                item = block['signals'][name][mode]
                label = f'horizon/{n}/{name}/{mode}'
                equal(item['indices'], chosen_ids, label+'/indices')
                sample = draws['horizon/'+str(n)][name+'/'+mode] if n == 65 else None
                check_comparison(item, pop, targets, label, sample)
                if n == 65:
                    expected_draw_keys.append(name+'/'+mode)
                    check_groups(item, pop, targets, label)
                    if name != NAMES[0]:
                        adjusted_targets = [r for r in adjusted if r['i'] in chosen]
                        sample = draws['horizon/'+str(n)][name+'/'+mode+'/background_adjusted']
                        expected_draw_keys.append(name+'/'+mode+'/background_adjusted')
                        check_comparison(item['background_adjusted'], adjusted, adjusted_targets, label+'/background_adjusted', sample)
                    elif 'background_adjusted' in item:
                        raise AssertionError('M001 must not claim mechanical self-adjusted information')
                    if name in FACTOR_NAMES:
                        equal(sorted(item['background_slices']), ['inside', 'outside'], label+'/slice_keys')
                        for slice_name, inside in (('inside', True), ('outside', False)):
                            control = [r for r in pop if (r['i'] in signals[NAMES[0]]) == inside]
                            selected = [r for r in targets if (r['i'] in signals[NAMES[0]]) == inside]
                            sample = draws['horizon/'+str(n)][name+'/'+mode+'/'+slice_name]
                            expected_draw_keys.append(name+'/'+mode+'/'+slice_name)
                            check_comparison(item['background_slices'][slice_name], control, selected, label+'/'+slice_name, sample)
                    elif 'background_slices' in item:
                        raise AssertionError('Unexpected reference signal slices')
                elif 'background_adjusted' in item or 'background_slices' in item:
                    raise AssertionError('Unplanned secondary-horizon background analysis')
        equal(sorted(draws['horizon/'+str(n)]), sorted(expected_draw_keys), f'{n}/draw_keys')
    lookup = {n: {r['i']: r for r in pop} for n, pop in by_n.items()}
    complete_ids = {i for i in ids if all(lookup[n][i]['status'] == 'COMPLETE' for n in HORIZONS)}
    for name in NAMES:
        expected_draw_keys = []
        equal(sorted(analysis['duration'][name]), ['nonoverlap130', 'raw'], name+'/duration_modes')
        for mode in ('raw', 'nonoverlap130'):
            original = sorted(signals[name]) if mode == 'raw' else independent_sparse(signals[name], 130)
            members = [i for i in original if i in complete_ids]
            excluded = [{'i': i, 'reasons': {str(n): lookup[n][i]['status'] for n in HORIZONS
                         if lookup[n][i]['status'] != 'COMPLETE'}} for i in original if i not in complete_ids]
            item = analysis['duration'][name][mode]
            label = f'duration/{name}/{mode}'
            equal(item['preselected_indices'], original, label+'/preselected')
            equal(item['common_complete_indices'], members, label+'/complete')
            equal(item['excluded'], excluded, label+'/excluded')
            chosen = set(members)
            for n in HORIZONS:
                control = [r for r in by_n[n] if r['i'] in complete_ids]
                targets = [r for r in by_n[n] if r['i'] in chosen]
                check_comparison(item['horizons'][str(n)], control, targets, label+'/'+str(n),
                                 draws['duration/'+name][mode+'/'+str(n)], extended=False)
                expected_draw_keys.append(mode+'/'+str(n))
            for a, b in ((13, 26), (26, 65), (65, 130)):
                key = f'{a}-{b}'
                control = []
                for i in sorted(complete_ids):
                    equal(lookup[a][i]['entry_price'], lookup[b][i]['entry_price'], label+'/'+key+'/same_entry_cost')
                    equal(lookup[a][i]['entry_at'], lookup[b][i]['entry_at'], label+'/'+key+'/same_entry_time')
                    delta = (lookup[b][i]['exit_price']-lookup[a][i]['exit_price'])*.999/(lookup[a][i]['entry_price']*1.001)
                    control.append(dict(lookup[a][i], price_net_return=delta))
                targets = [r for r in control if r['i'] in chosen]
                check_comparison(item['increments'][key], control, targets, label+'/'+key,
                                 draws['duration/'+name][mode+'/'+key], extended=False)
                expected_draw_keys.append(mode+'/'+key)
        equal(sorted(draws['duration/'+name]), sorted(expected_draw_keys), name+'/duration_draw_keys')
    expected_pair_keys = [target+'__'+control for target, control in PAIRS]
    equal(sorted(analysis['contrasts']), sorted(expected_pair_keys), 'contrast_keys')
    primary_rows = by_n[65]
    adjusted = [dict(r, stratum=r['stratum']+'|M001='+('1' if r['i'] in signals[NAMES[0]] else '0'))
                for r in primary_rows]
    for target, control in PAIRS:
        key = target+'__'+control
        result = analysis['contrasts'][key]
        equal(result['target'], target, key+'/target_identity')
        equal(result['control'], control, key+'/control_identity')
        equal(sorted(result['modes']), ['nonoverlap', 'raw'], key+'/modes')
        expected_keys = []
        for mode in ('raw', 'nonoverlap'):
            selected = sorted(signals[target]) if mode == 'raw' else independent_sparse(signals[target], 65)
            selected_ids = set(selected)
            equal(sorted(result['modes'][mode]), ['background_adjusted', 'ordinary'], key+'/'+mode+'/labels')
            for label, universe in (('ordinary', primary_rows), ('background_adjusted', adjusted)):
                # Control always retains all raw parent events, including nested targets.
                controls = [r for r in universe if r['i'] in signals[control]]
                targets = [r for r in universe if r['i'] in selected_ids]
                item = result['modes'][mode][label]
                comparison_name = key+'/'+mode+'/'+label
                sample_key = mode+'/'+label
                expected_keys.append(sample_key)
                sample = draws['contrast/'+key][sample_key]
                equal(item['indices'], selected, comparison_name+'/indices')
                check_comparison(item, controls, targets, comparison_name, sample)
                equal(item['matched']['support']['self_in_control_events'], item['summary']['price']['count'], comparison_name+'/self_inclusion')
                equal(item['matched']['unmatched_indices'], [], comparison_name+'/no_unmatched_nested_targets')
                equal(sorted(item['years']), [str(y) for y in range(2019, 2026)], comparison_name+'/years')
                for year in map(str, range(2019, 2026)):
                    check_comparison(item['years'][year], [r for r in controls if r['date'].startswith(year)],
                                     [r for r in targets if r['date'].startswith(year)], comparison_name+'/'+year)
                if mode == 'nonoverlap' and label == 'background_adjusted':
                    equal(sample, independent_bootstrap(controls, targets, days, weights), comparison_name+'/independent_draws')
        equal(sorted(draws['contrast/'+key]), sorted(expected_keys), key+'/draw_keys')
    for name in ('S017-M001', 'S017-M002', 'S017-M005'):
        equal(analysis['duration'][name], prior['duration'][name], name+'/old_duration_exact')
        for n in HORIZONS:
            equal(analysis['horizons'][str(n)]['signals'][name], prior['horizons'][str(n)]['signals'][name], name+f'/old_horizon/{n}')
    equal(analysis['eligible'], len(ids), 'eligible')
    equal(analysis['new_entry_expressions'], 3, 'new_entry_expressions')
    equal(analysis['new_accounts'], 0, 'new_accounts')
    equal(analysis['reserved_2026_used'], False, 'reserved_used')
    equal(analysis['reference_signal_reproduction'], 'PASS', 'reference_reproduction')
    save(WORK/'others/result_validation.json', {'status': 'PASS',
        'analysis_sha256': digest(analysis_path), 'verification_source_sha256': digest(Path(__file__)),
        'counts': dict(COUNTS),
        'scope': 'Authenticated unchanged EX024 feature facts and EX020 labels; all new predicates independently checked, old references reproduced, all fees/memberships/ordinary-state-slice-parent matches and intervals checked; five nonoverlap state-adjusted parent contrasts independently bootstrapped. Original OHLC features and fills not rebuilt.'})
    print('RESULT_VALIDATION_PASS', dict(COUNTS), flush=True)


def read_gzip(path):
    import json
    return json.loads(gzip.decompress(path.read_bytes()))


if __name__ == '__main__':
    main()
