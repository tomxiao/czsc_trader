"""Independent membership, arithmetic, matching and uncertainty checks of EX021.

Expected results below deliberately do not call mechanisms.py. Historical input
authentication is delegated to study.inputs; no bars, providers or sealed data
are loaded. This verifier checks a reanalysis, not the original fill model.
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
NAMES = ('D', 'R', 'C', 'D_NR')
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


def expected_match(control, targets):
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


def expected_interval(values):
    valid = [v for v in values if v is not None]
    return {'valid_replicates': len(valid), 'undefined_replicates': len(values)-len(valid),
            'interval_95': [float(v) for v in np.quantile(valid, [.025, .975])] if valid else None}


def check_comparison(item, control, targets, label, draws=None):
    equal(item['summary'], expected_summary(targets), label+'/summary')
    expected = expected_match(control, targets)
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
    analysis = read(analysis_path)
    pre = read(WORK/'others/pre_run_evidence.json')
    equal(analysis['previous'], pre['previous'], 'previous_refs')
    for reference in pre['previous'].values():
        authenticate(reference)
    equal(analysis['protocol_sha256'], digest(WORK/'protocols/design.md'), 'protocol_sha256')
    for name, reference in pre['materials'].items():
        source = authenticate(reference)
        if name in ('design', 'authorization'):
            equal(digest(WORK/'protocols'/f'{name}.md'), digest(source), 'frozen_protocol/'+name)
        elif name == 'checks':
            equal(digest(WORK/'others/checks.json'), digest(source), 'frozen_checks')
        if name.endswith('-source'):
            filename = name.removesuffix('-source')+'.py'
            equal(digest(WORK/'src'/filename), digest(source), 'frozen_source/'+filename)
    for name, expected_hash in analysis['sources'].items():
        equal(digest(WORK/'src'/name), expected_hash, 'analysis_source/'+name)
    for name, expected_hash in analysis['artifacts'].items():
        equal(digest(WORK/f'others/{name}.json.gz'), expected_hash, 'artifact/'+name)
    rows, facts, old = inputs(pre['previous'])
    draws = read_gzip(WORK/'others/bootstrap_draws.json.gz')
    equal(sorted(draws), sorted([*('horizon/'+str(n) for n in HORIZONS),
                                *('duration/'+name for name in NAMES),
                                'episode/first_D', 'episode/first_C']), 'draw_groups')
    actual_episodes = read_gzip(WORK/'others/episodes.json.gz')
    ids = [f['i'] for f in facts]
    equal(ids, list(range(ids[0], ids[-1]+1)), 'consecutive_facts')
    equal(len(ids), 22790, 'facts_count')
    by_fact = {f['i']: f for f in facts}
    signals = {name: set() for name in NAMES}
    for f in facts:
        value = f['facts']
        # Preserve the frozen formula's floating-point evaluation order.
        d = value['previous_close'] <= value['previous_mean']-2*value['previous_atr']
        r = value['close'] > value['previous_high']
        for name, state in (('D', d), ('R', r), ('C', d and r), ('D_NR', d and not r)):
            if state:
                signals[name].add(f['i'])
        equal(d and r, 'C' in f['signals'], f'C_reproduction/{f["i"]}')
    equal(analysis['signal_counts'], {k: len(v) for k, v in signals.items()}, 'signal_counts')
    equal(signals['C'] | signals['D_NR'], signals['D'], 'D_partition')
    equal(signals['C'] & signals['D_NR'], set(), 'D_disjoint')
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
                raise AssertionError('Out of authorized development window')
            limit = (Decimal(str(by_fact[i]['facts']['close']))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01')
            equal(row['limit_price'], float(limit), f'{n}/{i}/limit')
            complete = row['price_net_return'] is not None
            equal(row['status'] == 'COMPLETE', complete, f'{n}/{i}/complete')
            if row['entry_price'] is not None and (row['entry_price'] <= 0 or row['entry_price'] > float(limit)+1e-12):
                raise AssertionError('Invalid limit-buy price')
            if complete:
                if row['exit_price'] is None or row['exit_price'] <= 0 or row['entry_price'] is None:
                    raise AssertionError('Complete event lacks positive execution prices')
                expected_return = (row['exit_price']*(1-.001)-row['entry_price']*(1+.001))/(row['entry_price']*(1+.001))
                equal(row['price_net_return'], expected_return, f'{n}/{i}/fees')
            COUNTS['event_rows'] += 1
    days = sorted(set(r['date'] for r in rows))
    equal(len(days), 1760, 'sessions')
    weights, starts_hash = independent_weights(days)
    equal(analysis['bootstrap'], {'replicates': 1000, 'block_sessions': 20, 'seed': 17,
          'sessions': len(days), 'starts_sha256': starts_hash, 'workers': 2, 'native_threads': 1}, 'bootstrap_contract')
    for n, pop in by_n.items():
        block = analysis['horizons'][str(n)]
        equal(block['all'], expected_summary(pop), f'{n}/all')
        for name in NAMES:
            for mode in ('raw', 'nonoverlap'):
                chosen_ids = sorted(signals[name]) if mode == 'raw' else independent_sparse(signals[name], n)
                chosen = set(chosen_ids)
                targets = [r for r in pop if r['i'] in chosen]
                item = block['signals'][name][mode]
                label = f'horizon/{n}/{name}/{mode}'
                equal(item['indices'], chosen_ids, label+'/indices')
                sample = draws['horizon/'+str(n)][name+'/'+mode] if n == 13 else None
                check_comparison(item, pop, targets, label, sample)
                if n == 13:
                    equal(item['concentration'], expected_concentration(targets), label+'/concentration')
                    for year, comparison in item['years'].items():
                        check_comparison(comparison, [r for r in pop if r['date'].startswith(year)],
                            [r for r in targets if r['date'].startswith(year)], label+'/year/'+year)
                    for month, comparison in item['months'].items():
                        check_comparison(comparison, [r for r in pop if r['month'] == month],
                            [r for r in targets if r['month'] == month], label+'/month/'+month)
                    equal(sorted(item['years']), [str(y) for y in range(2019, 2026)], label+'/years')
                    equal(sorted(item['months']), sorted(set(r['month'] for r in pop)), label+'/months')
                    if name == 'C':
                        equal(sample, independent_bootstrap(pop, targets, days, weights), label+'/independent_draws')
        control = [r for r in pop if r['i'] in signals['D_NR']]
        for mode in ('raw', 'nonoverlap'):
            chosen = signals['C'] if mode == 'raw' else set(independent_sparse(signals['C'], n))
            targets = [r for r in pop if r['i'] in chosen]
            sample = draws['horizon/'+str(n)]['confirmation/'+mode] if n == 13 else None
            label = f'confirmation/{n}/{mode}'
            check_comparison(block['confirmation'][mode], control, targets, label, sample)
            if n == 13:
                equal(sample, independent_bootstrap(control, targets, days, weights), label+'/independent_draws')
    expected_episodes = []
    for _, values in groupby(enumerate(sorted(signals['D'])), key=lambda pair: pair[1]-pair[0]):
        members = [i for _, i in values]
        expected_episodes.append({'start': members[0], 'end': members[-1], 'members': members,
            'confirmations': [i for i in members if i in signals['C']],
            'left_censored': members[0] == ids[0], 'right_censored': members[-1] == ids[-1]})
    equal(actual_episodes, expected_episodes, 'episodes')
    usable = [e for e in expected_episodes if not e['left_censored']]
    equal(analysis['episode_counts'], {'total': len(expected_episodes),
          'left_censored': sum(e['left_censored'] for e in expected_episodes),
          'right_censored': sum(e['right_censored'] for e in expected_episodes),
          'usable': len(usable), 'with_C': sum(bool(e['confirmations']) for e in usable),
          'without_C': sum(not e['confirmations'] for e in usable)}, 'episode_counts')
    for name in ('first_D', 'first_C'):
        selected = sorted(e['start'] if name == 'first_D' else e['confirmations'][0]
                          for e in usable if name == 'first_D' or e['confirmations'])
        targets = [r for r in by_n[13] if r['i'] in set(selected)]
        item = analysis['episode_results'][name]
        equal(item['indices'], selected, 'episode/'+name+'/indices')
        equal(item['concentration'], expected_concentration(targets), 'episode/'+name+'/concentration')
        check_comparison(item, by_n[13], targets, 'episode/'+name, draws['episode/'+name])
    lookup = {n: {r['i']: r for r in pop} for n, pop in by_n.items()}
    complete = {i for i in ids if all(lookup[n][i]['status'] == 'COMPLETE' for n in HORIZONS)}
    for name in NAMES:
        for mode in ('raw', 'nonoverlap130'):
            original = sorted(signals[name]) if mode == 'raw' else independent_sparse(signals[name], 130)
            members = [i for i in original if i in complete]
            excluded = [{'i': i, 'reasons': {str(n): lookup[n][i]['status'] for n in HORIZONS
                         if lookup[n][i]['status'] != 'COMPLETE'}} for i in original if i not in complete]
            item = analysis['duration'][name][mode]
            label = f'duration/{name}/{mode}'
            equal(item['preselected_indices'], original, label+'/preselected')
            equal(item['common_complete_indices'], members, label+'/complete')
            equal(item['excluded'], excluded, label+'/excluded')
            chosen = set(members)
            for n in HORIZONS:
                control = [r for r in by_n[n] if r['i'] in complete]
                targets = [r for r in by_n[n] if r['i'] in chosen]
                check_comparison(item['horizons'][str(n)], control, targets, label+'/'+str(n),
                                 draws['duration/'+name][mode+'/'+str(n)])
            for a, b in ((13, 26), (26, 65), (65, 130)):
                key = f'{a}-{b}'
                # Same initial capital; the two exit proceeds have identical entry cost.
                control = []
                for i in sorted(complete):
                    equal(lookup[a][i]['entry_price'], lookup[b][i]['entry_price'], label+'/'+key+'/same_entry')
                    equal(lookup[a][i]['entry_at'], lookup[b][i]['entry_at'], label+'/'+key+'/same_entry_at')
                    delta = (lookup[b][i]['exit_price']-lookup[a][i]['exit_price'])*.999/(lookup[a][i]['entry_price']*1.001)
                    control.append(dict(lookup[a][i], price_net_return=delta))
                targets = [r for r in control if r['i'] in chosen]
                check_comparison(item['increments'][key], control, targets, label+'/'+key,
                                 draws['duration/'+name][mode+'/'+key])
    equal(analysis['prior_C_primary_nonoverlap'], old['horizons']['13']['signals']['C']['nonoverlap'], 'prior_C_reference')
    equal(analysis['eligible'], len(ids), 'eligible')
    equal(analysis['new_entry_expressions'], 3, 'new_expressions')
    equal(analysis['new_accounts'], 0, 'new_accounts')
    equal(analysis['reserved_2026_used'], False, 'reserved_used')
    save(WORK/'others/result_validation.json', {'status': 'PASS',
         'analysis_sha256': digest(analysis_path), 'verification_source_sha256': digest(Path(__file__)),
         'counts': dict(COUNTS),
         'scope': 'Authenticated EX020 reanalysis; independent formulas, memberships, all summaries and interval reductions; C primary and confirmation bootstrap draws independently rebuilt. Original OHLC fill paths not rebuilt.'})
    print('RESULT_VALIDATION_PASS', dict(COUNTS), flush=True)


def read_gzip(path):
    import json
    return json.loads(gzip.decompress(path.read_bytes()))


if __name__ == '__main__':
    main()
