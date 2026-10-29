"""Independent EX023 membership, influence, accounting and uncertainty audit.

Statistical helpers are adapted from the independent EX022 verifier. This file
does not call production estimators to compute expected values. Published facts
and labels are authenticated; no new prices or original fill paths are loaded.
"""
# ruff: noqa: E402
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import gzip
from itertools import groupby
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'
import numpy as np

from study import WORK, authenticate, digest, inputs, read, save


HORIZONS = (3, 13, 26, 65, 130)
NAMES = ('B', 'C', 'F', 'T', 'H')
METRICS = ('13', '26', '65', '130', '26-65', '65-130')
KEY_METRICS = ('65', '26-65')
CONTROLS = ('ordinary', 'B', 'C')
COHORTS = ('nonoverlap130', 'raw', 'first_B')
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


def independent_weights(days, block):
    n = len(days)
    rng = np.random.default_rng(17)
    starts = rng.integers(0, n-block+1, size=(1000, math.ceil(n/block)))
    weights = np.zeros((1000, n), dtype=np.int64)
    for j, row in enumerate(starts):
        selected = [d for start in row for d in range(int(start), int(start)+block)][:n]
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


def expected_concentration(rows):
    positive = sorted((r for r in rows if r['price_net_return'] > 0),
                      key=lambda r: (-r['price_net_return'], r['i']))
    total = math.fsum(r['price_net_return'] for r in positive)
    years = {}
    for year in map(str, range(2019, 2026)):
        selected = [r for r in rows if r['date'].startswith(year)]
        years[year] = {'count': len(selected), 'net_sum': math.fsum(r['price_net_return'] for r in selected),
                      'positive_sum': math.fsum(r['price_net_return'] for r in selected if r['price_net_return'] > 0)}
    return {'count': len(rows), 'net_sum': math.fsum(r['price_net_return'] for r in rows),
        'positive_sum': total, 'negative_sum': math.fsum(r['price_net_return'] for r in rows if r['price_net_return'] < 0),
        'positive_events': len(positive),
        'largest_positive': {key: positive[0][key] for key in ('i', 'date', 'price_net_return')} if positive else None,
        'largest_event_positive_share': positive[0]['price_net_return']/total if total else None,
        'top3_positive_share': math.fsum(r['price_net_return'] for r in positive[:3])/total if total else None,
        'largest_year_positive_share': max(v['positive_sum'] for v in years.values())/total if total else None,
        'years': years, 'scope': 'Arithmetic event returns, not account PnL or independent cycles.'}


def check_source_identity(analysis, pre):
    equal(analysis['previous'], pre['previous'], 'previous_refs')
    for ref in pre['previous'].values():
        authenticate(ref)
    equal(analysis['protocol_sha256'], digest(WORK/'protocols/design.md'), 'protocol_sha256')
    for name, reference in pre['materials'].items():
        source = authenticate(reference)
        if name in ('design', 'authorization'):
            equal(digest(WORK/'protocols'/f'{name}.md'), digest(source), 'frozen_protocol/'+name)
        elif name == 'checks':
            equal(digest(WORK/'others/checks.json'), digest(source), 'frozen_checks')
        elif name.endswith('-source'):
            equal(digest(WORK/'src'/(name.removesuffix('-source')+'.py')), digest(source), 'frozen_source/'+name)
    for name, expected_hash in analysis['sources'].items():
        equal(digest(WORK/'src'/name), expected_hash, 'analysis_source/'+name)
    for name, expected_hash in analysis['artifacts'].items():
        equal(digest(WORK/f'others/{name}.json.gz'), expected_hash, 'artifact/'+name)


def reconstruct_signals(facts):
    signals = {name: set() for name in NAMES}
    d = {}
    for row in facts:
        i, f = row['i'], row['facts']
        d[i] = f['previous_close'] <= f['previous_mean']-2*f['previous_atr']
        equal(float(d[i]), f['D'], f'original_D/{i}')
        # The first 12 background windows extend into already-authenticated warmup facts.
        b = bool(f['background'])
        if i >= facts[0]['i']+12:
            equal(b, any(d[j] for j in range(i-12, i+1)), f'background_window/{i}')
        t = b and f['reference_low_index'] <= i-3
        if t:
            t = (f['post_low_high'] is not None and f['post_low_high'] >= f['reference_low']+f['previous_atr']
                 and f['reference_low'] <= f['low'] <= f['reference_low']+.5*f['previous_atr']
                 and f['close'] > f['previous_high'])
        expected = {'B': b, 'C': d[i] and f['close'] > f['previous_high'],
            'F': b and f['low'] < f['reference_low'] and f['close'] > f['reference_low'],
            'T': t, 'H': b and f['recent_low3'] > f['prior_low3'] and f['close'] > f['prior_high3']}
        equal(row['signals'], [name for name in NAMES if expected[name]], f'original_signal_flags/{i}')
        for name in NAMES:
            if expected[name]:
                signals[name].add(i)
    for name in NAMES:
        equal(signals[name]-signals['B'], set(), name+'/background_subset')
    equal(signals['F'] & signals['T'], set(), 'F_T_disjoint')
    return signals


def reconstruct_segments(signals, ids):
    segments = []
    for _, values in groupby(enumerate(sorted(signals['B'])), key=lambda pair: pair[1]-pair[0]):
        members = [i for _, i in values]
        segments.append({'start': members[0], 'end': members[-1], 'members': members,
            'left_censored': members[0] == ids[0], 'right_censored': members[-1] == ids[-1],
            'signals': {name: [i for i in members if i in signals[name]] for name in NAMES}})
    return segments


def main():
    analysis_path = WORK/'others/analysis.json'
    analysis, pre = read(analysis_path), read(WORK/'others/pre_run_evidence.json')
    check_source_identity(analysis, pre)
    rows, facts, segments, prior, source_signals, supplied_lookup, supplied_complete = inputs(pre['previous'])
    equal(digest(authenticate(pre['previous']['facts'])), prior['artifacts']['signal_facts'], 'prior_fact_artifact')
    equal(digest(authenticate(pre['previous']['segments'])), prior['artifacts']['segments'], 'prior_segment_artifact')
    ids = [f['i'] for f in facts]
    equal(ids, list(range(ids[0], ids[-1]+1)), 'consecutive_ids')
    equal(len(ids), 22790, 'population_count')
    equal(len(rows), 113950, 'all_event_rows')
    signals = reconstruct_signals(facts)
    for name in ('B', 'C', 'T'):
        equal(source_signals[name], signals[name], name+'/input_membership')
        equal(len(signals[name]), prior['signal_counts'][name], name+'/prior_count')
    equal(len(signals['T']), 67, 'T_raw_67')
    equal(analysis['signal_counts'], {name: len(signals[name]) for name in ('B', 'C', 'T')}, 'signal_counts')
    equal(segments, reconstruct_segments(signals, ids), 'original_background_segments')
    lookup = {n: {r['i']: r for r in rows if r['n'] == n} for n in HORIZONS}
    by_fact = {f['i']: f for f in facts}
    east = ZoneInfo('America/New_York')
    for n in HORIZONS:
        pop = [r for r in rows if r['n'] == n]
        equal([r['i'] for r in pop], ids, f'{n}/population_ids')
        for row in pop:
            i = row['i']
            at = datetime.fromisoformat(row['entry_at']).astimezone(east)
            equal(row['date'], str(at.date()), f'{n}/{i}/date')
            equal(row['month'], at.strftime('%Y-%m'), f'{n}/{i}/month')
            equal(row['stratum'], at.strftime('%Y-%m|%H:%M'), f'{n}/{i}/stratum')
            equal(row['signal_at'], by_fact[i]['signal_at'], f'{n}/{i}/signal_time')
            if not '2019-01-02' <= row['date'] <= '2025-12-31':
                raise AssertionError('Outside permitted development window')
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
                equal(row['price_net_return'], net, f'{n}/{i}/net_return')
            COUNTS['event_rows'] += 1
    equal(supplied_lookup, lookup, 'input_lookup')
    complete_ids = {i for i in ids if all(lookup[n][i]['status'] == 'COMPLETE' for n in HORIZONS)}
    equal(supplied_complete, complete_ids, 'input_common_complete')
    originals = {'nonoverlap130': independent_sparse(signals['T'], 130), 'raw': sorted(signals['T']),
        'first_B': [s['signals']['T'][0] for s in segments if not s['left_censored'] and s['signals']['T']]}
    expected_cohorts = {}
    for name in COHORTS:
        original = originals[name]
        members = [i for i in original if i in complete_ids]
        excluded = [{'i': i, 'reasons': {str(n): lookup[n][i]['status'] for n in HORIZONS
                     if lookup[n][i]['status'] != 'COMPLETE'}} for i in original if i not in complete_ids]
        expected_cohorts[name] = {'preselected_indices': original, 'common_complete_indices': members, 'excluded': excluded}
        if name != 'first_B':
            equal(expected_cohorts[name], {k: prior['duration']['T'][name][k] for k in expected_cohorts[name]}, 'prior_cohort/'+name)
        else:
            equal(original, prior['first']['T']['indices'], 'prior_first_members')
    equal(analysis['cohorts'], expected_cohorts, 'cohorts')
    equal(len(expected_cohorts['nonoverlap130']['common_complete_indices']), 45, 'main_45')
    equal(len(expected_cohorts['raw']['common_complete_indices']), 66, 'raw_66')
    controls_ids = {'ordinary': complete_ids, 'B': signals['B'] & complete_ids, 'C': signals['C'] & complete_ids}
    equal(analysis['common_complete_controls'], {k: len(v) for k, v in controls_ids.items()}, 'control_counts')
    metrics = {}
    for metric in METRICS:
        metrics[metric] = []
        for i in sorted(complete_ids):
            if '-' not in metric:
                row = dict(lookup[int(metric)][i], metric=metric)
            else:
                a, b = map(int, metric.split('-'))
                equal(lookup[a][i]['entry_price'], lookup[b][i]['entry_price'], metric+f'/{i}/same_initial_cost')
                equal(lookup[a][i]['entry_at'], lookup[b][i]['entry_at'], metric+f'/{i}/same_entry_time')
                value = (lookup[b][i]['exit_price']-lookup[a][i]['exit_price'])*.999/(lookup[a][i]['entry_price']*1.001)
                row = dict(lookup[a][i], metric=metric, price_net_return=value)
            metrics[metric].append(row)
    days = sorted({r['date'] for r in rows})
    equal(len(days), 1760, 'sessions')
    weights, starts_hashes = {}, {}
    for block in (20, 60):
        weights[block], starts_hashes[str(block)] = independent_weights(days, block)
    equal(analysis['bootstrap'], {'replicates': 1000, 'blocks': [20, 60], 'seed': 17,
        'sessions': len(days), 'starts_sha256': starts_hashes, 'workers': 2, 'native_threads': 1}, 'bootstrap_contract')
    draws = read_gzip(WORK/'others/bootstrap_draws.json.gz')
    equal(sorted(draws), sorted(COHORTS), 'draw_cohorts')
    equal(sorted(analysis['results']), sorted(COHORTS), 'result_cohorts')
    for cohort in COHORTS:
        chosen_ids = set(expected_cohorts[cohort]['common_complete_indices'])
        result = analysis['results'][cohort]
        equal(sorted(result['metrics']), sorted(METRICS), cohort+'/metric_keys')
        equal(sorted(result['stress']), sorted(KEY_METRICS) if cohort == 'nonoverlap130' else [], cohort+'/stress_keys')
        expected_draw_keys = []
        for metric in METRICS:
            targets = [r for r in metrics[metric] if r['i'] in chosen_ids]
            controls = {name: [r for r in metrics[metric] if r['i'] in controls_ids[name]] for name in CONTROLS}
            item = result['metrics'][metric]
            equal(sorted(item['comparisons']), sorted(CONTROLS), cohort+'/'+metric+'/controls')
            for control in CONTROLS:
                comparison = item['comparisons'][control]
                label = f'{cohort}/{metric}/{control}'
                sample_key = f'{metric}/{control}/20'
                sample = draws[cohort][sample_key] if metric in KEY_METRICS else None
                check_comparison(comparison, controls[control], targets, label, sample)
                if metric in KEY_METRICS:
                    expected_draw_keys.append(sample_key)
                    if cohort == 'nonoverlap130':
                        equal(sample, independent_bootstrap(controls[control], targets, days, weights[20]), label+'/independent20')
                        sample60_key = f'{metric}/{control}/60'
                        sample60 = draws[cohort][sample60_key]
                        expected_draw_keys.append(sample60_key)
                        check_comparison({'summary': comparison['summary'], 'matched': comparison['matched'],
                                          'bootstrap': comparison['bootstrap60']}, controls[control], targets, label+'/60', sample60)
                        equal(sample60, independent_bootstrap(controls[control], targets, days, weights[60]), label+'/independent60')
                    elif 'bootstrap60' in comparison:
                        raise AssertionError('Unplanned 60-session sensitivity outside main cohort')
                elif 'bootstrap60' in comparison:
                    raise AssertionError('Unplanned 60-session sensitivity outside key metrics')
            if metric in KEY_METRICS:
                equal(item['concentration'], expected_concentration(targets), cohort+'/'+metric+'/concentration')
                if cohort == 'nonoverlap130':
                    stress = result['stress'][metric]
                    equal(sorted(stress['years']), [str(y) for y in range(2019, 2026)], metric+'/year_keys')
                    equal(sorted(stress['leave_year_out']), [str(y) for y in range(2019, 2026)], metric+'/leaveyear_keys')
                    for year in map(str, range(2019, 2026)):
                        for key, selected in (('years', [r for r in targets if r['date'].startswith(year)]),
                                              ('leave_year_out', [r for r in targets if not r['date'].startswith(year)])):
                            equal(sorted(stress[key][year]), sorted(CONTROLS), f'{metric}/{key}/{year}/controls')
                            for control in CONTROLS:
                                check_comparison(stress[key][year][control], controls[control], selected,
                                                 f'{metric}/{key}/{year}/{control}')
                    equal(sorted(stress['drop_positive_events']), ['1', '3'], metric+'/drop_keys')
                    positive = sorted((r for r in targets if r['price_net_return'] > 0),
                                      key=lambda r: (-r['price_net_return'], r['i']))
                    for count in (1, 3):
                        removed = positive[:count]
                        expected_removed = [{k: r[k] for k in ('i', 'date', 'price_net_return')} for r in removed]
                        diagnostic = stress['drop_positive_events'][str(count)]
                        equal(diagnostic['removed'], expected_removed, f'{metric}/drop{count}/removed')
                        removed_ids = {r['i'] for r in removed}
                        selected = [r for r in targets if r['i'] not in removed_ids]
                        equal(sorted(diagnostic['comparisons']), sorted(CONTROLS), f'{metric}/drop{count}/controls')
                        for control in CONTROLS:
                            check_comparison(diagnostic['comparisons'][control], controls[control], selected,
                                             f'{metric}/drop{count}/{control}')
        equal(sorted(draws[cohort]), sorted(expected_draw_keys), cohort+'/draw_keys')
    trows = [lookup[13][i] for i in sorted(signals['T'])]
    frequency = {'signals': len(trows), 'planned_entry_days': len({r['date'] for r in trows}),
        'entry_status': dict(Counter(r['entry_status'] for r in trows)),
        'segments_with_T': sum(bool(s['signals']['T']) for s in segments if not s['left_censored']),
        'years': {str(y): {'signals': sum(r['date'].startswith(str(y)) for r in trows),
                          'planned_entry_days': len({r['date'] for r in trows if r['date'].startswith(str(y))})} for y in range(2019, 2026)},
        'scope': 'Signals grouped by planned entry date, not closed account trades.'}
    equal(analysis['frequency'], frequency, 'frequency')
    equal(analysis['eligible'], len(ids), 'eligible')
    equal(analysis['new_entry_expressions'], 0, 'new_expressions')
    equal(analysis['new_accounts'], 0, 'new_accounts')
    equal(analysis['reserved_2026_used'], False, 'reserved_used')
    equal(analysis['prior_cohort_reproduction'], 'PASS', 'prior_reproduction')
    save(WORK/'others/result_validation.json', {'status': 'PASS',
         'analysis_sha256': digest(analysis_path), 'verification_source_sha256': digest(Path(__file__)),
         'counts': dict(COUNTS),
         'scope': 'Authenticated prior signal facts and labels; independent signal predicates, cohorts, metrics, all controls and influence diagnostics; all stored intervals and 12 main bootstrap sets independently rebuilt. First 12 B histories and original OHLC facts are inherited authenticated evidence, not new bar reconstruction.'})
    print('RESULT_VALIDATION_PASS', dict(COUNTS), flush=True)


def read_gzip(path):
    import json
    return json.loads(gzip.decompress(path.read_bytes()))


if __name__ == '__main__':
    main()
