"""Independent census checks; this does not certify or replay an account."""
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import json
from math import isclose
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from zoneinfo import ZoneInfo

from common import WORK, NAMES, read, save, digest, authenticate, fetch
import numpy as np
from signals import compute
from temporal import analyze_temporal

ZONE = ZoneInfo('America/New_York')


def equal(a, b):
    if a is None or b is None:
        assert a is b, (a, b)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        assert isclose(a, b, rel_tol=1e-11, abs_tol=1e-13), (a, b)
    else:
        assert a == b, (a, b)


def load_gzip(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def reduce_events(rows, n=6, last=None):
    chosen = []
    for row in sorted(rows, key=lambda r: r['i']):
        if last is None or row['i'] > last+n+1:
            chosen.append(row)
            last = row['i']
    return chosen, last


def maturity(row, cutoff):
    if row['status'] != 'COMPLETE' or row['exit_at'] is None:
        return False
    at = datetime.fromisoformat(row['exit_at'])
    assert at.tzinfo is not None
    return at.astimezone(ZONE).date().isoformat() <= cutoff


def net_stats(rows):
    values = [r['price_net_return'] for r in rows if r['price_net_return'] is not None]
    return len(values), mean(values) if values else None


def controls(population, name):
    return [r for r in population if name not in r['signals']
            and name in r['parents']]


def paired(control, target):
    buckets = defaultdict(list)
    for row in control:
        if row['price_net_return'] is not None:
            buckets[row['stratum']].append(row['price_net_return'])
    complete = [r for r in target if r['price_net_return'] is not None]
    supported = [r for r in complete if r['stratum'] in buckets]
    deltas = [r['price_net_return']-mean(buckets[r['stratum']]) for r in supported]
    return {'complete': len(complete), 'supported': len(supported),
            'unsupported': len(complete)-len(supported),
            'own': mean([r['price_net_return'] for r in supported]) if supported else None,
            'control': mean([mean(buckets[r['stratum']]) for r in supported]) if supported else None,
            'delta': mean(deltas) if deltas else None,
            'median_controls': median([len(buckets[r['stratum']]) for r in supported]) if supported else None,
            'singletons': sum(len(buckets[r['stratum']]) == 1 for r in supported)}


def verify_match(actual, expected):
    for key, other in (('complete_targets', 'complete'), ('supported_targets', 'supported'),
                       ('unsupported_targets', 'unsupported'), ('supported_target_mean', 'own'),
                       ('control_mean', 'control'), ('net_increment', 'delta'),
                       ('median_controls', 'median_controls'), ('singleton_supported_targets', 'singletons')):
        equal(actual[key], expected[other])
    equal(actual['support_fraction'], expected['supported']/expected['complete'] if expected['complete'] else None)


def independently_bootstrap(targets, days, actual):
    values = [row for row in targets if row['price_net_return'] is not None]
    by_day_count = np.zeros(len(days), dtype=int)
    by_day_sum = np.zeros(len(days), dtype=float)
    for row in values:
        by_day_count[row['day_index']] += 1
        by_day_sum[row['day_index']] += row['price_net_return']
    rng, draws, missing = np.random.default_rng(17), [], 0
    for _ in range(1000):
        starts = rng.integers(0, len(days)-19, size=(len(days)+19)//20)
        samples = np.concatenate([np.arange(start,start+20) for start in starts])[:len(days)]
        denominator = sum(by_day_count[samples])
        if denominator:
            draws.append(float(sum(by_day_sum[samples])/denominator))
        else:
            missing += 1
    equal(actual['defined'],len(draws))
    equal(actual['undefined'],missing)
    if draws:
        for expected,value in zip(np.quantile(draws,[.025,.975]),actual['interval95'],strict=True):
            equal(float(expected),value)
    else:
        assert actual['interval95'] is None


def temporal_check(item, population, name, cutoff):
    targets = [r for r in population if name in r['signals']]
    targets, _ = reduce_events(targets)
    complete = [r for r in targets if maturity(r, cutoff)]
    control = [r for r in controls(population, name) if maturity(r, cutoff)]
    expected = paired(control, complete)
    equal(item['trigger_count'], len(targets))
    equal(item['trigger_days'], len({r['date'] for r in targets}))
    equal(item['mature_complete_count'], len(complete))
    equal(item['complete_after_cutoff_count'], sum(r['status'] == 'COMPLETE' and not maturity(r, cutoff) for r in targets))
    equal(item['net_return']['mean'], net_stats(complete)[1])
    equal(item['net_return']['count'], len(complete))
    equal(item['matched']['supported_target_count'], expected['supported'])
    equal(item['matched']['unsupported_target_count'], expected['unsupported'])
    equal(item['matched']['increment']['mean'], expected['delta'])
    equal(item['matched']['target_weighted_control_mean'], expected['control'])
    return net_stats(complete)[1], expected['delta']


def verify_sequential(rows, days, sequential):
    folds = sequential['folds']
    starts = list(range(252, len(days), 63))
    assert len(folds) == len(starts)
    last, pooled = None, []
    for fold, start in zip(folds, starts, strict=True):
        stop = min(start+63, len(days))
        assert fold['train_start'] == days[start-252]
        assert fold['train_end'] == days[start-1]
        assert fold['test_start'] == fold['training_exit_must_precede'] == days[start]
        assert fold['test_end'] == days[stop-1]
        population = [r for r in rows if start-252 <= r['day_index'] < start]
        scores = {}
        for name in NAMES:
            own, delta = temporal_check(fold['training'][name]['nonoverlap'], population, name, days[start-1])
            # Every COMPLETE value admitted by the independent reconstruction
            # has exited before the first test session, not merely signalled.
            assert all(datetime.fromisoformat(r['exit_at']).astimezone(ZONE).date().isoformat() < days[start]
                       for r in population if maturity(r, days[start-1]))
            if name in ('S017-M019','S017-M020') and own is not None and delta is not None and own > 0 and delta > 0:
                scores[name] = delta
        assert set(scores) == set(fold['eligible_training_scores'])
        for name in scores:
            equal(scores[name], fold['eligible_training_scores'][name])
        choice = min(scores, key=lambda name: (-scores[name], name)) if scores else None
        assert choice == fold['choice']
        assert fold['previous_test_selected_i'] == last
        chosen = []
        if choice:
            chosen, last = reduce_events([r for r in rows if start <= r['day_index'] < stop
                                          and choice in r['signals']], last=last)
        assert fold['last_test_selected_i'] == last
        assert [r['i'] for r in chosen] == [r['i'] for r in fold['test_events']]
        for row, event in zip(chosen, fold['test_events'], strict=True):
            assert event['mechanism'] == choice
            assert event['mature_at_fold_end'] == maturity(row, days[stop-1])
            equal(event['net_return'], row['price_net_return'] if maturity(row, days[stop-1]) else None)
        if choice:
            test = [r for r in rows if start <= r['day_index'] < stop]
            complete = [r for r in chosen if maturity(r, days[stop-1])]
            test_controls = [r for r in controls(test, choice) if maturity(r, days[stop-1])]
            expected = paired(test_controls, complete)
            item = fold['test_summary']
            equal(item['net_return']['mean'], net_stats(complete)[1])
            equal(item['matched']['supported_target_count'], expected['supported'])
            equal(item['matched']['increment']['mean'], expected['delta'])
        else:
            assert fold['test_summary'] is None
        pooled.extend(fold['test_events'])
    assert pooled == sequential['pooled']['events']
    equal(sequential['pooled']['selected_events'], len(pooled))
    values = [r['net_return'] for r in pooled if r['net_return'] is not None]
    equal(sequential['pooled']['mature_events'], len(values))
    equal(sequential['pooled']['net_return']['mean'], mean(values) if values else None)
    # Perturb all future outcomes at the first fold boundary, call the actual
    # temporal analysis, and check that that fold's training/choice is invariant.
    perturbations = []
    for index in (0,):
        first = folds[index]['test_start']
        mutated = []
        for row in rows:
            value = dict(row)
            future = row['date'] >= first or (row['exit_at'] is not None and
                datetime.fromisoformat(row['exit_at']).astimezone(ZONE).date().isoformat() >= first)
            if future and value['status'] == 'COMPLETE':
                value['price_net_return'] = 1000000. + row['i']
            mutated.append(value)
        observed = analyze_temporal(mutated, days, NAMES, selection_names=('S017-M019','S017-M020'))['sequential']['folds'][index]
        assert observed['training'] == folds[index]['training']
        assert observed['choice'] == folds[index]['choice']
        perturbations.append(first)
    return {'folds': len(folds), 'future_outcome_perturbations': perturbations,
            'cross_fold_nonoverlap': 'PASS', 'mature_training_only': 'PASS'}


def main():
    started = perf_counter()
    census = read(WORK/'others/census.json')
    events_path = WORK/'others/events.json.gz'
    assert digest(events_path) == census['events_sha256']
    rows = load_gzip(events_path)
    assert len(rows) == 22790*3
    keyed = {(r['i'], r['n']): r for r in rows}
    assert len(keyed) == len(rows)
    by_n = {n: sorted([r for r in rows if r['n'] == n], key=lambda r: r['i']) for n in (3,6,13)}
    assert all(len(pop) == 22790 for pop in by_n.values())
    assert all([r['i'] for r in pop] == [r['i'] for r in by_n[6]] for pop in by_n.values())
    assert all('2019-01-02' <= r['date'] <= '2025-12-31' for r in rows)
    days = sorted({r['date'] for r in rows})
    assert len(days) == 1760
    for row in rows:
        assert row['date'] == days[row['day_index']]
        assert row['month'] == row['date'][:7]
        if row['status'] == 'COMPLETE':
            equal(row['price_net_return'], row['exit_price']*.999/(row['entry_price']*1.001)-1)
        else:
            assert row['price_net_return'] is None
    publication = read(WORK.parent/'EX029_20261030/others/publication.json')
    assert publication['validation']['status'] == 'PASS'
    retained = load_gzip(authenticate(publication['materials']['others/events.json.gz']))
    retained = {(r['i'],r['n']):r for r in retained if r['n'] in (3,6,13)}
    assert len(retained) == 22790*3
    fields = ('status','entry_status','exit_status','entry_price','exit_price','limit_price',
              'price_net_return','close_path_min','close_path_max','information_return','exit_at')
    compared = 0
    for key, old in retained.items():
        current = keyed[key]
        for field in fields:
            equal(current.get(field), old.get(field))
        # Compare timestamps as instants, without depending on offset spelling.
        for field in ('signal_at','entry_at'):
            equal(datetime.fromisoformat(current[field]),datetime.fromisoformat(old[field]))
        assert ('S017-M017' in current['signals']) == ('S017-M017' in old['signals'])
        compared += 1
    assert sum('S017-M017' in r['signals'] for r in by_n[6]) == 910
    bars, _, identities = fetch()
    assert identities == census['inputs']
    flags, parents, regimes = compute(bars)
    closes, highs, lows = (bars[field].to_numpy(dtype=float) for field in ('Close','High','Low'))
    scalar_count = 0
    for row in by_n[6]:
        i = row['i']
        prior_mean = sum(float(value) for value in closes[i-65:i])/65
        older_mean = sum(float(value) for value in closes[i-78:i-13])/65
        background = float(closes[i-1]) < prior_mean
        breakout = float(closes[i]) > max(float(value) for value in highs[i-6:i])
        rising = prior_mean > older_mean
        steady_low = min(float(value) for value in lows[i-6:i]) >= min(float(value) for value in lows[i-12:i-6])
        base = background and breakout
        expected = dict(zip(NAMES,(base,base and rising,base and steady_low),strict=True))
        parent_flags = dict(zip(NAMES,(background,background and rising,background and steady_low),strict=True))
        for name in NAMES:
            assert expected[name] == bool(flags.loc[i,name]) == (name in row['signals'])
            assert parent_flags[name] == bool(parents.loc[i,name]) == (name in row['parents'])
            scalar_count += 1
        assert row['regime'] == regimes.iloc[i]
        equal(row['signal_at'], bars.Date.iloc[i].isoformat())
    for stop in (508, 2000, len(bars)-100):
        short_flags, short_parents, short_regimes = compute(bars.iloc[:stop])
        assert short_flags.equals(flags.iloc[:stop])
        assert short_parents.equals(parents.iloc[:stop])
        assert short_regimes.equals(regimes.iloc[:stop])
    for n, population in by_n.items():
        for name in NAMES:
            chosen = [r for r in population if name in r['signals']]
            assert len(chosen) == census['signal_counts'][name]
            control = controls(population, name)
            for mode, target in (('raw',chosen),('nonoverlap',reduce_events(chosen,n)[0])):
                actual = census['horizons'][str(n)][name][mode]
                equal(actual['summary']['events'],len(target))
                equal(actual['summary']['complete'],net_stats(target)[0])
                equal(actual['summary']['net_mean'],net_stats(target)[1])
                assert actual['summary']['statuses'] == dict(Counter(r['status'] for r in target))
                verify_match(actual['ordinary'],paired(control,target))
                if 'parent' in actual:
                    verify_match(actual['parent'],paired([r for r in control if name in r['parents']],target))
                if n == 6 and mode == 'nonoverlap':
                    boot=actual['net_bootstrap']
                    assert boot['defined']+boot['undefined'] == boot['replicates'] == 1000
                    independently_bootstrap(target,days,boot)
    sequential = verify_sequential(by_n[6], days, census['temporal']['sequential'])
    result = {'status':'PASS','scope':'CENSUS_AND_EVENT_TEMPORAL_ONLY_NO_ACCOUNT_CERTIFICATION',
        'analysis_sha256':digest(WORK/'others/census.json'),'events_sha256':digest(events_path),
        'verification_source_sha256':digest(Path(__file__)), 'strategy_source_sha256':digest(WORK/'src/strategy_v3.py'),
        'legacy_3_6_13_label_comparisons':compared,'scalar_vector_event_comparisons':scalar_count,
        'rows':len(rows),'sessions':len(days),'sequential':sequential,
        'checks':['complete_fee_formula','legacy_label_exact_reproduction','authorized_window',
                  'prepared_data_identity','signal_parent_regime_identity','prefix_causality',
                  'independent_all_horizon_counts_means_matches','bootstrap_defined_denominator',
                  'independent_training_scores_and_selection','training_label_maturity',
                  'cross_fold_deoverlap','future_outcome_perturbation'],
        'seconds':perf_counter()-started}
    save(WORK/'others/result_validation.json',result)
    print(json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
