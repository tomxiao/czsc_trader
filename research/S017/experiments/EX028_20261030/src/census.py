"""One causal short-horizon census with authenticated legacy execution labels."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import gzip
import importlib.util
import multiprocessing as mp
import sys
from time import perf_counter

from common import (ROOT, WORK, NAMES, PREP, context, read, save, digest, authenticate, fetch, material)
import numpy as np
from strategy import compute
from temporal import analyze_temporal


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def label_source():
    old = WORK.parent/'EX019_20261029'
    ref = read(old/'others/pre_run_evidence.json')['study-source']
    path = authenticate(ref)
    if digest(old/'src/study.py') != digest(path):
        raise ValueError('Retained execution-label implementation changed')
    return module('ex019_execution_labels', path)


def sparse(rows, n):
    result, last = [], -1
    for row in sorted(rows, key=lambda r: r['i']):
        if row['i'] > last:
            result.append(row)
            last = row['i'] + n + 1
    return result


def summary(rows):
    values = np.array([r['price_net_return'] for r in rows if r['price_net_return'] is not None], dtype=float)
    wins, losses = values[values > 0], values[values < 0]
    return {'events': len(rows), 'complete': len(values), 'days': len({r['date'] for r in rows}),
        'statuses': dict(Counter(r['status'] for r in rows)),
        'net_mean': float(values.mean()) if len(values) else None,
        'net_median': float(np.median(values)) if len(values) else None,
        'win_rate': float((values > 0).mean()) if len(values) else None,
        'q05': float(np.quantile(values, .05)) if len(values) else None,
        'mean_win_loss_ratio': float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None,
        'mean_close_path_min': float(np.mean([r['close_path_min'] for r in rows if r['price_net_return'] is not None])) if len(values) else None,
        'mean_close_path_max': float(np.mean([r['close_path_max'] for r in rows if r['price_net_return'] is not None])) if len(values) else None}


def matched(control, targets):
    groups = {}
    for r in control:
        if r['price_net_return'] is not None:
            groups.setdefault(r['stratum'], []).append(r['price_net_return'])
    good = [r for r in targets if r['price_net_return'] is not None]
    supported = [r for r in good if r['stratum'] in groups]
    means = {k: float(np.mean(v)) for k, v in groups.items()}
    return {'complete_targets': len(good), 'supported_targets': len(supported),
        'unsupported_targets': len(good)-len(supported),
        'support_fraction': len(supported)/len(good) if good else None,
        'supported_target_mean': float(np.mean([r['price_net_return'] for r in supported])) if supported else None,
        'control_mean': float(np.mean([means[r['stratum']] for r in supported])) if supported else None,
        'net_increment': float(np.mean([r['price_net_return']-means[r['stratum']] for r in supported])) if supported else None,
        'median_controls': float(np.median([len(groups[r['stratum']]) for r in supported])) if supported else None,
        'singleton_supported_targets': sum(len(groups[r['stratum']]) == 1 for r in supported)}


def bootstrap(control, targets, days):
    """Moving-day-block descriptive uncertainty; re-estimate each control cell."""
    rng, block, replicates = np.random.default_rng(17), 20, 1000
    cells = sorted({r['stratum'] for r in control + targets})
    ci = {s: j for j, s in enumerate(cells)}
    control = [r for r in control if r['price_net_return'] is not None]
    targets = [r for r in targets if r['price_net_return'] is not None]
    cg = np.array([ci[r['stratum']] for r in control], dtype=int)
    cd = np.array([r['day_index'] for r in control], dtype=int)
    cv = np.array([r['price_net_return'] for r in control])
    tg = np.array([ci[r['stratum']] for r in targets], dtype=int)
    td = np.array([r['day_index'] for r in targets], dtype=int)
    tv = np.array([r['price_net_return'] for r in targets])
    deltas, own, undefined = [], [], 0
    for _ in range(replicates):
        starts = rng.integers(0, len(days)-block+1, size=int(np.ceil(len(days)/block)))
        selected = (starts[:, None]+np.arange(block)).ravel()[:len(days)]
        weights = np.bincount(selected, minlength=len(days))
        cw, tw = weights[cd], weights[td]
        sums = np.bincount(cg, weights=cw*cv, minlength=len(cells))
        counts = np.bincount(cg, weights=cw, minlength=len(cells))
        present = tw > 0
        if not present.any() or (counts[tg[present]] == 0).any():
            undefined += 1
            continue
        mean = sums[tg[present]]/counts[tg[present]]
        deltas.append(float(np.average(tv[present]-mean, weights=tw[present])))
        own.append(float(np.average(tv[present], weights=tw[present])))
    return {'replicates': replicates, 'block_sessions': block, 'seed': 17, 'defined': len(deltas),
        'undefined': undefined, 'conditional_increment_interval95': np.quantile(deltas, [.025, .975]).tolist() if deltas else None,
        'conditional_net_mean_interval95': np.quantile(own, [.025, .975]).tolist() if own else None,
        'scope': 'Conditional on defined matched support; overlapping event development sample, not independent validation.'}


def label_task(args):
    bars, constraints, eligible, metadata, horizon = args
    legacy, rows = label_source(), []
    for i in eligible:
        row = legacy.label(bars, constraints, i, horizon)
        row.update(metadata[i])
        row['exit_at'] = bars.Date.iloc[i+horizon+1].isoformat() if i+horizon+1 < len(bars) else None
        rows.append(row)
    return horizon, rows


def frozen_files():
    return [*sorted((WORK/'src').glob('*.py')), *sorted((WORK/'protocols').glob('*.*')),
            WORK/'others/entry_checks.json', WORK/'others/temporal_checks.json', PREP]


def freeze():
    if (WORK/'others/pre_run_evidence.json').exists():
        raise ValueError('Already frozen; inspect existing run before any retry')
    if any(read(WORK/'others'/name)['status'] != 'PASS' for name in ('entry_checks.json', 'temporal_checks.json')):
        raise ValueError('Focused mechanism and time checks required')
    refs = {str(p.relative_to(ROOT)): material(context(), 'pre-'+str(j), p).to_dict()
            for j, p in enumerate(frozen_files())}
    save(WORK/'others/pre_run_evidence.json', {'materials': refs})
    print('PROTOCOL_AND_SOURCES_FROZEN', len(refs), flush=True)


def run():
    started = perf_counter()
    for name, reference in read(WORK/'others/pre_run_evidence.json')['materials'].items():
        if digest(ROOT/name) != digest(authenticate(reference)):
            raise ValueError('Frozen source changed: '+name)
    bars, constraints, identities = fetch()
    flags, parents, regimes = compute(bars)
    eligible = [i for i in range(260, len(bars)-1)
                if str(bars.BarStart.iloc[i+1].tz_convert('America/New_York').date()) >= '2019-01-02']
    if len(eligible) != 22790 or (regimes.iloc[eligible] == 'UNREADY').any():
        raise ValueError('Original eligible population or history readiness differs')
    old_pub = read(WORK.parent/'EX024_20261029/others/publication.json')
    old_facts = {r['i']: r for r in read_gzip(authenticate(old_pub['materials']['signal-facts']))}
    if set(old_facts) != set(eligible):
        raise ValueError('Original M005 reference population differs')
    days = sorted({str(bars.BarStart.iloc[i+1].tz_convert('America/New_York').date()) for i in eligible})
    di = {d: j for j, d in enumerate(days)}
    metadata = {}
    for i in eligible:
        at = bars.BarStart.iloc[i+1].tz_convert('America/New_York')
        signals = [n for n in NAMES if flags.loc[i, n]]
        if 'S017-M005' in old_facts[i]['signals']:
            signals.append('S017-M005')
        metadata[i] = {'date': str(at.date()), 'month': at.strftime('%Y-%m'),
            'stratum': at.strftime('%Y-%m|%H:%M'), 'day_index': di[str(at.date())],
            'signal_at': bars.Date.iloc[i].isoformat(), 'entry_at': at.isoformat(),
            'regime': str(regimes.iloc[i]), 'signals': signals,
            'parents': [n for n in NAMES if parents.loc[i, n]]}
    if len(days) != 1760:
        raise ValueError('Development sessions changed')
    print('INPUTS_BOUND', len(bars), len(eligible), 'signals', Counter(n for r in metadata.values() for n in r['signals']), flush=True)
    rows, horizons = [], {}
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        results = pool.map(label_task, [(bars, constraints, eligible, metadata, n) for n in (3, 6, 13)])
        for n, values in results:
            rows.extend(values)
            comparisons = {}
            for name in (*NAMES, 'S017-M005'):
                selected = [r for r in values if name in r['signals']]
                control = [r for r in values if name not in r['signals']]
                comparisons[name] = {}
                for mode, population in (('raw', selected), ('nonoverlap', sparse(selected, n))):
                    item = {'summary': summary(population), 'ordinary': matched(control, population)}
                    if name in NAMES:
                        item['parent'] = matched([r for r in control if name in r['parents']], population)
                    if n == 6 and mode == 'nonoverlap':
                        item['bootstrap'] = bootstrap(control, population, days)
                    comparisons[name][mode] = item
            horizons[str(n)] = comparisons
            print('LABELS_AND_COMPARISONS_COMPLETE', n, flush=True)
    temporal = analyze_temporal(rows, days, (*NAMES, 'S017-M005'), selection_names=NAMES)
    print('TEMPORAL_COMPLETE', flush=True)
    write_gzip(WORK/'others/events.json.gz', rows)
    save(WORK/'others/census.json', {'schema': 's017-short-entry-census/v1', 'inputs': identities,
        'protocol_sha256': digest(WORK/'protocols/design.md'), 'eligible': len(eligible), 'sessions': len(days),
        'signal_counts': {n: sum(n in r['signals'] for r in metadata.values()) for n in (*NAMES, 'S017-M005')},
        'overlap': {a: {b: sum(a in r['signals'] and b in r['signals'] for r in metadata.values())
            for b in (*NAMES, 'S017-M005')} for a in NAMES}, 'horizons': horizons,
        'temporal': temporal, 'events_sha256': digest(WORK/'others/events.json.gz'),
        'reserved_2026_used': False, 'workers': 2, 'native_threads': 1, 'seconds': perf_counter()-started})
    print('CENSUS_COMPLETE', round(perf_counter()-started, 3), flush=True)


def read_gzip(path):
    import json
    return json.loads(gzip.decompress(path.read_bytes()))


def write_gzip(path, value):
    import json
    path.write_bytes(gzip.compress(json.dumps(value, allow_nan=False).encode(), mtime=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('freeze', 'run'))
    args = parser.parse_args()
    freeze() if args.action == 'freeze' else run()
