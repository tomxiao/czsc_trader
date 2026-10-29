"""Independent EX026 final disjoint-control verification.

Statistical helpers are adapted from the independent EX024/EX022 verifiers.
Expected values never call production estimators. Authenticated EX025 facts
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
TARGET = 'S017-M005'
PARENTS = ('S017-M007', 'S017-M008')
NAMES = ('S017-M001', TARGET, *PARENTS)
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


def main():
    analysis_path = WORK/'others/analysis.json'
    analysis, pre = read(analysis_path), read(WORK/'others/pre_run_evidence.json')
    equal(analysis['schema'], 's017-final-disjoint-ablation/v1', 'schema')
    equal(analysis['previous'], pre['previous'], 'previous_refs')
    for ref in pre['previous'].values():
        authenticate(ref)
    equal(analysis['protocol_sha256'], digest(WORK/'protocols/design.md'), 'protocol_sha256')
    expected_materials = {'design', 'authorization', 'checks'} | {
        p.stem+'-source' for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    equal(set(pre['materials']), expected_materials, 'frozen_material_inventory')
    for name, reference in pre['materials'].items():
        source = authenticate(reference)
        if name in ('design', 'authorization'):
            equal(digest(WORK/'protocols'/f'{name}.md'), digest(source), 'frozen_protocol/'+name)
        elif name == 'checks':
            equal(digest(WORK/'others/checks.json'), digest(source), 'frozen_checks')
        elif name.endswith('-source'):
            equal(digest(WORK/'src'/(name.removesuffix('-source')+'.py')), digest(source), 'frozen_source/'+name)
    current_sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    equal(analysis['sources'], current_sources, 'analysis_sources')
    checks = read(WORK/'others/checks.json')
    equal(checks['status'], 'PASS', 'source_checks_status')
    equal(checks['sources'], current_sources, 'source_checks_identity')
    equal(analysis['artifacts'], {'bootstrap_draws': digest(WORK/'others/bootstrap_draws.json.gz')}, 'artifact_identity')
    rows, reference, prior = inputs(pre['previous'])
    equal(analysis['inputs'], prior['inputs'], 'inherited_input_identities')
    validation = read(authenticate(pre['previous']['reference-verification']))
    equal(validation['status'], 'PASS', 'prior_validation_status')
    equal(validation['analysis_sha256'], digest(authenticate(pre['previous']['reference-analysis'])), 'prior_validation_identity')
    equal(digest(authenticate(pre['previous']['reference-facts'])), prior['artifacts']['signal_facts'], 'old_fact_identity')
    equal(prior['reserved_2026_used'], False, 'prior_reserved_sample')
    draws = read_gzip(WORK/'others/bootstrap_draws.json.gz')
    ids = [f['i'] for f in reference]
    equal(ids, list(range(ids[0], ids[-1]+1)), 'consecutive_ids')
    equal(len(ids), 22790, 'eligible_count')
    equal(len(rows), 113950, 'label_count')
    signals = {name: set() for name in NAMES}
    for row in reference:
        i, f = row['i'], row['facts']
        base = f['previous_close'] < f['previous_open'] and f['close'] > f['previous_high']
        narrow = f['previous_tr1'] <= f['atr_before_prior']
        volume = f['prior_volume'] >= 1.5*f['same_slot_volume_median20']
        states = {'S017-M005': base and narrow and volume, 'S017-M006': base,
                  'S017-M007': base and narrow, 'S017-M008': base and volume}
        for name, value in states.items():
            equal(name in row['signals'], value, f'fixed_predicate/{i}/{name}')
        for name in NAMES:
            if name in row['signals']:
                signals[name].add(i)
        COUNTS['scalar_signal_rows'] += 1
    equal(signals[TARGET], signals[PARENTS[0]] & signals[PARENTS[1]], 'factor_intersection')
    equal(analysis['signal_counts'], {name: len(value) for name, value in signals.items()}, 'signal_counts')
    equal(analysis['signal_counts'], {name: prior['signal_counts'][name] for name in NAMES}, 'prior_counts')
    by_fact = {f['i']: f for f in reference}
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
    equal(sorted(analysis['results']), sorted(PARENTS), 'result_groups')
    equal(sorted(draws), sorted(PARENTS), 'draw_groups')
    pop = by_n[65]
    adjusted = [dict(r, stratum=r['stratum']+'|M001='+('1' if r['i'] in signals['S017-M001'] else '0')) for r in pop]
    for parent in PARENTS:
        block = analysis['results'][parent]
        control_ids = signals[parent]-signals[TARGET]
        equal(control_ids & signals[TARGET], set(), parent+'/disjoint_controls')
        equal(block['target'], TARGET, parent+'/target')
        equal(block['parent'], parent, parent+'/parent')
        equal(block['parent_signals'], len(signals[parent]), parent+'/parent_count')
        equal(block['exclusive_controls'], len(control_ids), parent+'/exclusive_count')
        equal(sorted(block['modes']), ['nonoverlap', 'raw'], parent+'/modes')
        expected_keys = []
        for mode in ('raw', 'nonoverlap'):
            selected = sorted(signals[TARGET]) if mode == 'raw' else independent_sparse(signals[TARGET], 65)
            equal(selected, prior['horizons']['65']['signals'][TARGET][mode]['indices'], mode+'/original_target_indices')
            equal(sorted(block['modes'][mode]), ['background_adjusted', 'ordinary'], parent+'/'+mode+'/match_modes')
            for label, universe in (('ordinary', pop), ('background_adjusted', adjusted)):
                chosen = set(selected)
                controls = [r for r in universe if r['i'] in control_ids]
                targets = [r for r in universe if r['i'] in chosen]
                item = block['modes'][mode][label]
                key = mode+'/'+label
                description = parent+'/'+key
                sample = draws[parent][key]
                expected_keys.append(key)
                cells = {r['stratum'] for r in controls}
                expected_design = {
                    'target_indices': [r['i'] for r in targets],
                    'control_indices': [r['i'] for r in controls],
                    'signal_supported_indices': [r['i'] for r in targets if r['stratum'] in cells],
                    'signal_unmatched_indices': [r['i'] for r in targets if r['stratum'] not in cells]}
                equal(item['design'], expected_design, description+'/pre_label_design')
                equal(item['control_summary'], expected_summary(controls), description+'/control_summary')
                check_comparison(item, controls, targets, description, sample)
                equal(item['summary'], prior['horizons']['65']['signals'][TARGET][mode]['summary'], description+'/unchanged_target_summary')
                equal(item['matched']['support']['self_in_control_events'], 0, description+'/self_excluded')
                equal(item['matched']['support']['all_target_cell_events'], 0, description+'/all_targets_excluded')
                supported_ids = set(expected_match(controls, targets)['supported_indices'])
                equal(item['supported_concentration'], expected_concentration([r for r in targets if r['i'] in supported_ids]), description+'/concentration')
                equal(sorted(item['years']), [str(y) for y in range(2019, 2026)], description+'/years')
                for year in map(str, range(2019, 2026)):
                    check_comparison(item['years'][year], [r for r in controls if r['date'].startswith(year)],
                                     [r for r in targets if r['date'].startswith(year)], description+'/'+year)
                equal(sample, independent_bootstrap(controls, targets, days, weights), description+'/independent_draws')
        equal(sorted(draws[parent]), sorted(expected_keys), parent+'/draw_keys')
    equal(analysis['primary'], {'parent': 'S017-M007', 'mode': 'nonoverlap', 'matching': 'background_adjusted', 'horizon': 65}, 'primary_contract')
    equal(analysis['eligible'], len(ids), 'eligible')
    equal(analysis['new_entry_expressions'], 0, 'new_entry_expressions')
    equal(analysis['new_accounts'], 0, 'new_accounts')
    equal(analysis['reserved_2026_used'], False, 'reserved_used')
    equal(analysis['ablation_followup_rounds_allowed'], 0, 'decomposition_closed')
    equal(analysis['reference_signal_reproduction'], 'PASS', 'reference_reproduction')
    equal(COUNTS['independently_recomputed_bootstrap_sets'], 8, 'all_eight_bootstraps')
    save(WORK/'others/result_validation.json', {'status': 'PASS',
        'analysis_sha256': digest(analysis_path), 'verification_source_sha256': digest(Path(__file__)),
        'counts': dict(COUNTS),
        'scope': 'Authenticated unchanged EX025 feature facts and EX020 labels; fixed factor predicates, all inherited fees and memberships, pre-label and complete-label support, exclusive controls, yearly comparisons, concentration, all intervals and eight 1000-draw bootstraps independently verified. Undefined comparisons retained. Original OHLC features and fills not rebuilt.'})
    print('RESULT_VALIDATION_PASS', dict(COUNTS), flush=True)


def read_gzip(path):
    import json
    return json.loads(gzip.decompress(path.read_bytes()))


if __name__ == '__main__':
    main()
