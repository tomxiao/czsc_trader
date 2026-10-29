"""Independent EX024 numbered-entry census verification.

Statistics and interval helpers are copied from independent EX022 verification,
not production estimators. New expressions use a separately implemented scalar
oracle plus independent feature arithmetic. Original fills are not rebuilt.
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
from numbered_entries import scalar_at, prepare_scalar


HORIZONS = (3, 13, 26, 65, 130)
NAMES = ('S017-M001', 'S017-M002', 'S017-M003', 'S017-M004', 'S017-M005')
NEW_NAMES = NAMES[2:]
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


def expected_features(bars, ids):
    """Calculate facts once from raw arrays, excluding each candle's future."""
    op, high, low, close, volume = (bars[k].to_numpy(dtype=float) for k in ('Open', 'High', 'Low', 'Close', 'Volume'))
    local = bars.BarStart.dt.tz_convert('America/New_York')
    dates = [str(t.date()) for t in local]
    slots = [int(t.hour*60+t.minute) for t in local]
    if len(set(zip(dates, slots))) != len(bars):
        raise AssertionError('Repeated local-date/slot in original bars')
    tr = [None]+[max(high[j]-low[j], abs(high[j]-close[j-1]), abs(low[j]-close[j-1]))
                 for j in range(1, len(bars))]
    history, volume_medians, history_counts = {}, {}, {}
    for j, (day, slot) in enumerate(zip(dates, slots)):
        past = history.setdefault(slot, [])
        if any(prior_day >= day for prior_day, _ in past):
            raise AssertionError('Same-slot reference includes current/future date')
        selected = past[-20:]
        history_counts[j] = len(selected)
        volume_medians[j] = float(np.median([value for _, value in selected])) if len(selected) == 20 else None
        past.append((day, float(volume[j])))
    result = {}
    for i in ids:
        if i < 15 or volume_medians[i-1] is None:
            raise AssertionError('Incomplete history in shared eligible population')
        result[i] = {'close': float(close[i]), 'open': float(op[i]),
            'previous_close': float(close[i-1]), 'previous_open': float(op[i-1]),
            'close_t4': float(close[i-4]), 'previous_high': float(high[i-1]),
            'previous_atr': math.fsum(tr[i-13:i])/13, 'previous_tr1': float(tr[i-1]),
            'previous_tr2': float(tr[i-2]), 'previous_tr3': float(tr[i-3]),
            'down_count3': sum(close[j] < close[j-1] for j in range(i-3, i)),
            'prior_volume': float(volume[i-1]), 'same_slot_volume_median20': volume_medians[i-1],
            'same_slot_history_count': history_counts[i-1], 'atr_before_prior': math.fsum(tr[i-14:i-1])/13,
            'prior_local_day': dates[i-1], 'prior_local_slot_minutes': slots[i-1]}
    return result


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
    rows, reference, bars, identities = inputs(pre['previous'])
    equal(analysis['inputs'], identities, 'prepared_input_identities')
    prior = read(authenticate(pre['previous']['reference-analysis']))
    equal(digest(authenticate(pre['previous']['reference-facts'])), prior['artifacts']['signal_facts'], 'old_fact_identity')
    facts = read_gzip(WORK/'others/signal_facts.json.gz')
    draws = read_gzip(WORK/'others/bootstrap_draws.json.gz')
    ids = [f['i'] for f in reference]
    equal(ids, list(range(ids[0], ids[-1]+1)), 'consecutive_ids')
    equal(len(ids), 22790, 'eligible_count')
    equal(len(rows), 113950, 'label_count')
    equal([f['i'] for f in facts], ids, 'new_fact_membership')
    equal(sorted(draws), sorted([*('horizon/'+str(n) for n in HORIZONS),
                                *('duration/'+name for name in NAMES)]), 'draw_groups')
    expected = expected_features(bars, ids)
    prepared = prepare_scalar(bars)
    original_by = {f['i']: f for f in reference}
    signals = {name: set() for name in NAMES}
    for row in facts:
        i = row['i']
        state = scalar_at(bars, i, prepared=prepared)
        if state is None:
            raise AssertionError(f'Scalar history missing at {i}')
        names = [name for legacy, name in (('B', NAMES[0]), ('T', NAMES[1])) if legacy in original_by[i]['signals']]
        names.extend(name for name in NEW_NAMES if state[name])
        equal(row['signals'], names, f'scalar_flags/{i}')
        equal(row['facts'], expected[i], f'scalar_features/{i}')
        equal(row['signal_at'], bars.iloc[i].Date.isoformat(), f'fact_time/{i}')
        for name in names:
            signals[name].add(i)
        COUNTS['scalar_signal_rows'] += 1
    equal(analysis['signal_counts'], {name: len(value) for name, value in signals.items()}, 'signal_counts')
    equal(len(signals[NAMES[0]]), prior['signal_counts']['B'], 'M001_prior_identity')
    equal(len(signals[NAMES[1]]), prior['signal_counts']['T'], 'M002_prior_identity')
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
                    if name in NEW_NAMES and mode == 'nonoverlap':
                        equal(sample, independent_bootstrap(pop, targets, days, weights), label+'/independent_draws')
                    if name != NAMES[0]:
                        adjusted_targets = [r for r in adjusted if r['i'] in chosen]
                        sample = draws['horizon/'+str(n)][name+'/'+mode+'/background_adjusted']
                        expected_draw_keys.append(name+'/'+mode+'/background_adjusted')
                        check_comparison(item['background_adjusted'], adjusted, adjusted_targets, label+'/background_adjusted', sample)
                        if name in NEW_NAMES and mode == 'nonoverlap':
                            equal(sample, independent_bootstrap(adjusted, adjusted_targets, days, weights), label+'/background_adjusted/independent_draws')
                    elif 'background_adjusted' in item:
                        raise AssertionError('M001 must not claim mechanical self-adjusted information')
                    if name in NEW_NAMES:
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
    equal(analysis['eligible'], len(ids), 'eligible')
    equal(analysis['new_entry_expressions'], 3, 'new_entry_expressions')
    equal(analysis['new_accounts'], 0, 'new_accounts')
    equal(analysis['reserved_2026_used'], False, 'reserved_used')
    equal(analysis['reference_signal_reproduction'], 'PASS', 'reference_reproduction')
    save(WORK/'others/result_validation.json', {'status': 'PASS',
        'analysis_sha256': digest(analysis_path), 'verification_source_sha256': digest(Path(__file__)),
        'counts': dict(COUNTS),
        'scope': 'Authenticated prepared data and prior references; every eligible new signal independently scalar-checked, all feature facts/fees/memberships/matching and intervals checked; six new primary nonoverlap ordinary/state-adjusted bootstrap sets independently rebuilt. Original fills not rebuilt.'})
    print('RESULT_VALIDATION_PASS', dict(COUNTS), flush=True)


def read_gzip(path):
    import json
    return json.loads(gzip.decompress(path.read_bytes()))


if __name__ == '__main__':
    main()
