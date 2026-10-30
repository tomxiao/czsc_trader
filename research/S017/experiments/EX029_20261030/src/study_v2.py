"""Conditional-breakout event study, reusing certified equal execution labels."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import multiprocessing as mp
import sys
from time import perf_counter
from common import (ROOT, WORK, NAMES, PREP, context, read, save, digest, authenticate, fetch, material)
from strategy import compute
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
    spec.loader.exec_module(module)
    return module


def freeze():
    if (WORK/'others/pre_run_evidence.json').exists():
        raise ValueError('Existing frozen run requires investigation rather than overwrite')
    if read(WORK/'others/entry_checks.json')['status'] != 'PASS':
        raise ValueError('Source-bound focused mechanism checks required')
    files = [WORK/'src'/n for n in ('common.py', 'strategy.py', 'check_entries.py', 'temporal.py', 'study.py')]
    files += [*sorted((WORK/'protocols').glob('*.*')), WORK/'others/entry_checks.json', PREP]
    research = context()
    refs = {str(p.relative_to(ROOT)).replace('\\', '/'): material(research, 'pre-'+str(j), p).to_dict()
            for j, p in enumerate(files)}
    oldpub = read(WORK.parent/'EX028_20261030/others/publication.json')
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
        control = [r for r in values if name not in r['signals']
            and (name != 'S017-M017' or 'S017-M018' in r['signals'])]
        comparisons[name] = {}
        for mode, population in (('raw', selected), ('nonoverlap', helper.sparse(selected, n))):
            item = {'summary': helper.summary(population), 'ordinary': helper.matched(control, population)}
            if n == 6 and mode == 'nonoverlap':
                item['bootstrap'] = helper.bootstrap(control, population, days)
            comparisons[name][mode] = item
    complement = [r for r in values if 'S017-M012' in r['signals'] and 'S017-M017' not in r['signals']]
    comparisons['M012_EXCLUDING_M017_DIAGNOSTIC'] = {
        'raw': helper.summary(complement), 'nonoverlap': helper.summary(helper.sparse(complement, n)),
        'interpretation': 'Complementary descriptive members, not an independent mechanism or causal estimate.'}
    return str(n), comparisons


def run():
    started = perf_counter()
    revision = read(WORK/'others/statistics_loader_revision.json')
    if digest(authenticate(revision['source'])) != digest(WORK/'src/study_v2.py'):
        raise ValueError('Revised statistics loader must be frozen')
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
        if ('S017-M012' in r['signals']) != ('S017-M012' in flags_by_i[i]):
            raise ValueError('Original breakthrough signal differs')
        if str(regimes.iloc[i]) == 'UNREADY':
            raise ValueError('Cannot drop original eligible population')
        rows.append(dict(r, signals=flags_by_i[i], regime=str(regimes.iloc[i]),
            parents=[n for n in NAMES if bool(parents.loc[i, n])]))
    days = sorted({r['date'] for r in rows})
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        horizons = dict(pool.map(horizon_task, [(n, [r for r in rows if r['n'] == n], days) for n in (3, 6, 13)]))
    temporal = analyze_temporal(rows, days, NAMES, selection_names=('S017-M017',))
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
    core = horizons['6']['S017-M017']['nonoverlap']
    net, delta = core['summary']['net_mean'], core['ordinary']['net_increment']
    selected = ['S017-M017'] if net is not None and delta is not None and net > 0 and delta > 0 else []
    save(WORK/'others/selection.json', {'selected_mechanisms': selected, 'census_sha256': digest(WORK/'others/census.json'),
        'protocol_sha256': result['protocol_sha256'], 'source_sha256': digest(WORK/'src/study_v2.py'),
        'main_net_mean': net, 'main_low_background_increment': delta,
        'planned_new_strategy_accounts': 4 if selected else 0,
        'scope': 'Predeclared event-to-prototype resource decision, not a new acceptance requirement.'})
    print('CENSUS_COMPLETE', result['signal_counts'], 'SELECTED', selected, 'seconds', result['seconds'], flush=True)
    print('TEMPORAL_CHOICES', Counter(f['choice'] for f in temporal['sequential']['folds']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('freeze', 'run'))
    args = parser.parse_args()
    freeze() if args.action == 'freeze' else run()
