"""Conditional-breakout event study, reusing certified equal execution labels."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import multiprocessing as mp
import sys
from time import perf_counter
from common import (ROOT, WORK, NAMES, PREP, context, read, save, digest, authenticate, fetch, material)
import numpy as np
from signals import compute
from temporal import analyze_temporal


def load_helper():
    old = WORK.parent/'EX028_20261030'
    pre = {key.replace('\\', '/'): value for key, value in read(old/'others/pre_run_evidence.json')['materials'].items()}
    relative = 'research/S017/experiments/EX028_20261030/src/census.py'
    ref = pre[relative]
    if digest(authenticate(ref)) != digest(old/'src/census.py'):
        raise ValueError('Retained statistics helper changed')
    spec = importlib.util.spec_from_file_location('ex028_census_statistics', old/'src/census.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    search_path = sys.path.copy()
    try:
        # The retained helper imports its original vector module. Our new
        # experiment intentionally has no legacy strategy.py runtime module.
        sys.path.insert(0, str(old/'src'))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = search_path
    return module


def freeze():
    if (WORK/'others/pre_run_evidence.json').exists():
        raise ValueError('Existing frozen run requires investigation rather than overwrite')
    if read(WORK/'others/entry_checks.json')['status'] != 'PASS':
        raise ValueError('Source-bound focused mechanism checks required')
    files = [WORK/'src'/n for n in ('common.py', 'strategy_v3.py', 'signals.py', 'check_entries.py', 'temporal.py', 'study.py')]
    files += [*sorted((WORK/'protocols').glob('*.*')), WORK/'others/entry_checks.json', PREP]
    research = context()
    refs = {str(p.relative_to(ROOT)).replace('\\', '/'): material(research, 'pre-'+str(j), p).to_dict()
            for j, p in enumerate(files)}
    oldpub = read(WORK.parent/'EX029_20261030/others/publication.json')
    save(WORK/'others/pre_run_evidence.json', {'materials': refs,
        'retained_report': oldpub['report'],
        'retained_events': oldpub['materials']['others/events.json.gz'],
        'retained_census': oldpub['materials']['others/census.json']})
    print('PRE_RUN_SOURCES_FROZEN', flush=True)


def horizon_task(arguments):
    n, values, days = arguments
    helper, comparisons = load_helper(), {}
    for name in NAMES:
        selected = [r for r in values if name in r['signals']]
        control = [r for r in values if name not in r['signals'] and name in r['parents']]
        comparisons[name] = {}
        for mode, population in (('raw', selected), ('nonoverlap', helper.sparse(selected, n))):
            item = {'summary': helper.summary(population), 'ordinary': helper.matched(control, population)}
            if n == 6 and mode == 'nonoverlap':
                item['net_bootstrap'] = bootstrap_net(population, days)
            comparisons[name][mode] = item
    return str(n), comparisons


def bootstrap_net(targets, days):
    complete = [r for r in targets if r['price_net_return'] is not None]
    values = np.array([r['price_net_return'] for r in complete], dtype=float)
    ids = np.array([r['day_index'] for r in complete], dtype=int)
    rng, draws, undefined = np.random.default_rng(17), [], 0
    for _ in range(1000):
        starts = rng.integers(0, len(days)-19, size=int(np.ceil(len(days)/20)))
        sampled = (starts[:, None]+np.arange(20)).ravel()[:len(days)]
        weights = np.bincount(sampled, minlength=len(days))[ids]
        if not weights.sum():
            undefined += 1
        else:
            draws.append(float(np.average(values, weights=weights)))
    return {'replicates': 1000, 'block_sessions': 20, 'defined': len(draws), 'undefined': undefined,
        'interval95': np.quantile(draws, [.025, .975]).tolist() if draws else None,
        'scope': 'Own event net mean only. Matched increments report support and point estimates, not a confidence interval.'}


def run():
    started = perf_counter()
    pre = read(WORK/'others/pre_run_evidence.json')
    for relative, ref in pre['materials'].items():
        if digest(ROOT/relative) != digest(authenticate(ref)):
            raise ValueError('Frozen source changed: '+relative)
    helper = load_helper()
    old = read(authenticate(pre['retained_census']))
    retained = helper.read_gzip(authenticate(pre['retained_events']))
    bars, _, identities = fetch()
    if old['inputs'] != identities or len(retained) != 22790*3:
        raise ValueError('Execution-label population or input identity changed')
    flags, parents, regimes = compute(bars)
    rows = []
    flags_by_i = {}
    for r in retained:
        i = r['i']
        if i not in flags_by_i:
            flags_by_i[i] = [n for n in NAMES if bool(flags.loc[i, n])]
        if ('S017-M017' in r['signals']) != ('S017-M017' in flags_by_i[i]):
            raise ValueError('Original conditional breakthrough signal differs')
        if str(regimes.iloc[i]) == 'UNREADY':
            raise ValueError('Cannot drop original eligible population')
        rows.append(dict(r, signals=flags_by_i[i], regime=str(regimes.iloc[i]),
            parents=[n for n in NAMES if bool(parents.loc[i, n])]))
    days = sorted({r['date'] for r in rows})
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        horizons = dict(pool.map(horizon_task, [(n, [r for r in rows if r['n'] == n], days) for n in (3, 6, 13)]))
    temporal = analyze_temporal(rows, days, NAMES, selection_names=('S017-M019', 'S017-M020'))
    helper.write_gzip(WORK/'others/events.json.gz', rows)
    result = {'schema': 's017-conditional-breakthrough-census/v1', 'inputs': identities,
        'protocol_sha256': digest(WORK/'protocols/design.md'), 'retained_events': pre['retained_events'],
        'eligible': len(flags_by_i), 'sessions': len(days),
        'signal_counts': {n: sum(n in v for v in flags_by_i.values()) for n in NAMES},
        'horizons': horizons, 'temporal': temporal, 'events_sha256': digest(WORK/'others/events.json.gz'),
        'reserved_2026_used': False, 'new_execution_labels': 0, 'reused_execution_labels': len(rows),
        'sampling_workers': 2, 'native_threads': 1,
        'sampling_note': 'Independent horizon summaries use two spawn workers; identical execution labels reused without recalculation.',
        'seconds': perf_counter()-started}
    save(WORK/'others/census.json', result)
    scores, selected = {}, []
    for name in ('S017-M019', 'S017-M020'):
        core = horizons['6'][name]['nonoverlap']
        net, delta = core['summary']['net_mean'], core['ordinary']['net_increment']
        scores[name] = {'net_mean': net, 'same_context_increment': delta}
        if net is not None and delta is not None and net > 0 and delta > 0:
            selected.append(name)
    save(WORK/'others/selection.json', {'selected_mechanisms': selected, 'census_sha256': digest(WORK/'others/census.json'),
        'protocol_sha256': result['protocol_sha256'], 'source_sha256': digest(WORK/'src/study.py'),
        'scores': scores,
        'planned_new_strategy_accounts': len(selected),
        'scope': 'Predeclared event-to-prototype resource decision, not a new acceptance requirement.'})
    print('CENSUS_COMPLETE', result['signal_counts'], 'SELECTED', selected, 'seconds', result['seconds'], flush=True)
    print('TEMPORAL_CHOICES', Counter(f['choice'] for f in temporal['sequential']['folds']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('freeze', 'run'))
    args = parser.parse_args()
    freeze() if args.action == 'freeze' else run()
