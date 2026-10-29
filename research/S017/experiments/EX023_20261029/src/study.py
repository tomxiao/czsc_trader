"""Fixed-entry, fixed-horizon evidence follow-up; no new prices or strategies."""
# ruff: noqa: E402
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import gzip
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
from time import perf_counter

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
from czsc_trader.application import RepositoryContext, publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentRef, MaterialEvidenceWrite,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope)

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OLD = WORK.parent/'EX022_20261029'
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', WORK.name)
HORIZONS = (3, 13, 26, 65, 130)
METRICS = ('13', '26', '65', '130', '26-65', '65-130')
KEY_METRICS = ('65', '26-65')
CONTROLS = ('ordinary', 'B', 'C')
COHORTS = ('nonoverlap130', 'raw', 'first_B')


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False).encode('utf-8'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def authenticate(value):
    ref = EvidenceRef.from_dict(value)
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError('Evidence identity mismatch')
    return path


def load_previous():
    pre = read(OLD/'others/pre_run_evidence.json')['materials']
    for name in ('study', 'entries'):
        if digest(authenticate(pre[name+'-source'])) != digest(OLD/f'src/{name}.py'):
            raise ValueError('Frozen helper source changed')
    search_path = sys.path.copy()
    try:
        sys.path.insert(0, str(OLD/'src'))
        spec = importlib.util.spec_from_file_location('ex022_frozen', OLD/'src/study.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = search_path


previous = load_previous()


def context():
    search_path = sys.path.copy()
    try:
        return previous.context()
    finally:
        sys.path[:] = search_path


def prior_refs():
    pub = read(OLD/'others/publication.json')
    pre = read(OLD/'others/pre_run_evidence.json')
    refs = {'events': pre['previous']['events'], 'facts': pub['materials']['signal-facts'],
        'segments': pub['materials']['segments'], 'analysis': pub['materials']['analysis'], 'report': pub['report'],
        'entry-source': pre['materials']['entries-source'], 'helper-source': pre['materials']['study-source'],
        'statistics-source': pre['previous']['statistics-source'],
        'statistics-driver-source': pre['previous']['statistics-driver-source']}
    for ref in refs.values():
        authenticate(ref)
    return refs


def load_gzip(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def inputs(refs):
    rows = load_gzip(authenticate(refs['events']))
    facts = load_gzip(authenticate(refs['facts']))
    segments = load_gzip(authenticate(refs['segments']))
    prior = read(authenticate(refs['analysis']))
    if len(rows) != 113950 or len(facts) != 22790 or prior['reserved_2026_used']:
        raise ValueError('Population contract changed')
    signals = {name: {f['i'] for f in facts if name in f['signals']} for name in ('B', 'C', 'T')}
    if len(signals['T']) != 67 or any(len(signals[k]) != prior['signal_counts'][k] for k in signals):
        raise ValueError('Original signal identity changed')
    if not signals['T'] <= signals['B'] or any(not ('2019-01-02' <= r['date'] <= '2025-12-31') for r in rows):
        raise ValueError('Signal membership or permitted dates changed')
    lookup = {n: {r['i']: r for r in rows if r['n'] == n} for n in HORIZONS}
    ids = {f['i'] for f in facts}
    if any(set(lookup[n]) != ids for n in HORIZONS):
        raise ValueError('Horizon membership mismatch')
    complete = set.intersection(*({i for i, r in lookup[n].items() if r['price_net_return'] is not None} for n in HORIZONS))
    return rows, facts, segments, prior, signals, lookup, complete


def make_cohorts(signals, segments, lookup, complete, prior):
    preselected = {'nonoverlap130': previous.sparse(signals['T'], 130), 'raw': sorted(signals['T']),
        'first_B': [s['signals']['T'][0] for s in segments if not s['left_censored'] and s['signals']['T']]}
    result = {}
    for name, original in preselected.items():
        members = [i for i in original if i in complete]
        excluded = [{'i': i, 'reasons': {str(n): lookup[n][i]['status'] for n in HORIZONS
                     if lookup[n][i]['price_net_return'] is None}} for i in original if i not in complete]
        result[name] = {'preselected_indices': original, 'common_complete_indices': members, 'excluded': excluded}
        if name in ('nonoverlap130', 'raw'):
            old = prior['duration']['T'][name]
            if any(result[name][k] != old[k] for k in result[name]):
                raise ValueError('Prior fixed cohort did not reproduce')
    if len(result['nonoverlap130']['common_complete_indices']) != 45 or len(result['raw']['common_complete_indices']) != 66:
        raise ValueError('Known T cohorts changed')
    if preselected['first_B'] != prior['first']['T']['indices']:
        raise ValueError('Prior first-in-segment membership changed')
    return result


def metric_rows(lookup, complete):
    result = {}
    for metric in METRICS:
        if '-' not in metric:
            result[metric] = [dict(lookup[int(metric)][i], metric=metric) for i in sorted(complete)]
        else:
            a, b = map(int, metric.split('-'))
            result[metric] = [dict(lookup[a][i], metric=metric,
                price_net_return=lookup[b][i]['price_net_return']-lookup[a][i]['price_net_return']) for i in sorted(complete)]
    return result


def concentration(rows):
    positives = sorted([r for r in rows if r['price_net_return'] > 0], key=lambda r: (-r['price_net_return'], r['i']))
    total = sum(r['price_net_return'] for r in positives)
    year = {str(y): {'count': sum(r['date'].startswith(str(y)) for r in rows),
        'net_sum': sum(r['price_net_return'] for r in rows if r['date'].startswith(str(y))),
        'positive_sum': sum(r['price_net_return'] for r in positives if r['date'].startswith(str(y)))} for y in range(2019, 2026)}
    return {'count': len(rows), 'net_sum': sum(r['price_net_return'] for r in rows),
        'positive_sum': total, 'negative_sum': sum(r['price_net_return'] for r in rows if r['price_net_return'] < 0),
        'positive_events': len(positives), 'largest_positive':
            {k: positives[0][k] for k in ('i', 'date', 'price_net_return')} if positives else None,
        'largest_event_positive_share': positives[0]['price_net_return']/total if total else None,
        'top3_positive_share': sum(r['price_net_return'] for r in positives[:3])/total if total else None,
        'largest_year_positive_share': max(v['positive_sum'] for v in year.values())/total if total else None,
        'years': year, 'scope': 'Arithmetic event returns, not account PnL or independent cycles.'}


def compare_all(controls, targets, days, weights, boot=False):
    items, samples = {}, {}
    for name, rows in controls.items():
        items[name], samples[name] = previous.compare(rows, targets, days, weights, boot)
    return items, samples


def analyze_task(args):
    cohort, members, metrics, control_ids, days, weights = args
    member_set = set(members)
    result, draws = {'metrics': {}, 'stress': {}}, {}
    for metric, rows in metrics.items():
        targets = [r for r in rows if r['i'] in member_set]
        controls = {name: [r for r in rows if r['i'] in ids] for name, ids in control_ids.items()}
        comparisons, samples = compare_all(controls, targets, days, weights[20], metric in KEY_METRICS)
        item = {'comparisons': comparisons}
        if metric in KEY_METRICS:
            item['concentration'] = concentration(targets)
            for control, sample in samples.items():
                draws[f'{metric}/{control}/20'] = sample
            if cohort == 'nonoverlap130':
                for control, population in controls.items():
                    interval, sample = previous.bootstrap(population, targets, days, weights[60])
                    comparisons[control]['bootstrap60'] = interval
                    draws[f'{metric}/{control}/60'] = sample
                stress = {'years': {}, 'leave_year_out': {}, 'drop_positive_events': {}}
                for y in map(str, range(2019, 2026)):
                    # Keep the original control population in every influence diagnostic.
                    stress['years'][y] = compare_all(controls, [r for r in targets if r['date'].startswith(y)], days, weights[20])[0]
                    stress['leave_year_out'][y] = compare_all(controls, [r for r in targets if not r['date'].startswith(y)], days, weights[20])[0]
                positive = sorted([r for r in targets if r['price_net_return'] > 0], key=lambda r: (-r['price_net_return'], r['i']))
                for count in (1, 3):
                    removed = positive[:count]
                    remove_ids = {r['i'] for r in removed}
                    stress['drop_positive_events'][str(count)] = {
                        'removed': [{k: r[k] for k in ('i', 'date', 'price_net_return')} for r in removed],
                        'comparisons': compare_all(controls, [r for r in targets if r['i'] not in remove_ids], days, weights[20])[0]}
                result['stress'][metric] = stress
        result['metrics'][metric] = item
    return cohort, result, draws


def declared_sources():
    pairs = [('design', WORK/'protocols/design.md'), ('authorization', WORK/'protocols/authorization.md'), ('checks', WORK/'others/checks.json')]
    pairs.extend((p.stem+'-source', p) for p in sorted((WORK/'src').glob('*.py')) if p.stem != 'render')
    return pairs


def material(research, name, path):
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        {'.json': 'application/json', '.gz': 'application/gzip'}.get(path.suffix, 'text/plain'), path.suffix[1:]))


def run():
    start = perf_counter()
    if (WORK/'others/pre_run_evidence.json').exists():
        raise ValueError('Frozen run exists; inspect before retry')
    sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    check = read(WORK/'others/checks.json')
    if check['status'] != 'PASS' or check['sources'] != sources:
        raise ValueError('Source-bound focused checks required')
    refs, research = prior_refs(), context()
    pre = {name: material(research, name, path).to_dict() for name, path in declared_sources()}
    save(WORK/'others/pre_run_evidence.json', {'materials': pre, 'previous': refs})
    print('PROTOCOL_AND_SOURCES_PUBLISHED', flush=True)
    rows, facts, segments, prior, signals, lookup, complete = inputs(refs)
    cohorts = make_cohorts(signals, segments, lookup, complete, prior)
    metrics = metric_rows(lookup, complete)
    control_ids = {'ordinary': complete, 'B': signals['B'] & complete, 'C': signals['C'] & complete}
    days = sorted({r['date'] for r in rows})
    assert len(days) == 1760
    weights, starts_hash = {}, {}
    for block in (20, 60):
        weights[block], starts = previous.block_weights(len(days), block=block)
        starts_hash[str(block)] = sha256(starts.astype('<i8').tobytes()).hexdigest()
    results, draws = {}, {}
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        tasks = [(c, cohorts[c]['common_complete_indices'], metrics, control_ids, days, weights) for c in COHORTS]
        for c, result, sample in pool.map(analyze_task, tasks):
            results[c], draws[c] = result, sample
            print('COHORT_COMPLETE', c, flush=True)
    trows = [r for r in rows if r['n'] == 13 and r['i'] in signals['T']]
    from collections import Counter
    frequency = {'signals': len(trows), 'planned_entry_days': len({r['date'] for r in trows}),
        'entry_status': dict(Counter(r['entry_status'] for r in trows)),
        'segments_with_T': sum(bool(s['signals']['T']) for s in segments if not s['left_censored']),
        'years': {str(y): {'signals': sum(r['date'].startswith(str(y)) for r in trows),
                          'planned_entry_days': len({r['date'] for r in trows if r['date'].startswith(str(y))})} for y in range(2019, 2026)},
        'scope': 'Signals grouped by planned entry date, not closed account trades.'}
    (WORK/'others/bootstrap_draws.json.gz').write_bytes(gzip.compress(json.dumps(draws, allow_nan=False).encode(), mtime=0))
    save(WORK/'others/analysis.json', {'schema': 's017-retest-delayed-repair/v1', 'experiment': EXPERIMENT.to_dict(),
        'protocol_sha256': digest(WORK/'protocols/design.md'), 'sources': sources, 'previous': refs,
        'eligible': len(facts), 'common_complete_controls': {k: len(v) for k, v in control_ids.items()},
        'signal_counts': {k: len(v) for k, v in signals.items()}, 'cohorts': cohorts, 'results': results, 'frequency': frequency,
        'bootstrap': {'replicates': 1000, 'blocks': [20, 60], 'seed': 17, 'sessions': len(days),
                      'starts_sha256': starts_hash, 'workers': 2, 'native_threads': 1},
        'artifacts': {'bootstrap_draws': digest(WORK/'others/bootstrap_draws.json.gz')},
        'new_entry_expressions': 0, 'new_accounts': 0, 'reserved_2026_used': False,
        'prior_cohort_reproduction': 'PASS', 'seconds': perf_counter()-start})
    print('ANALYSIS_COMPLETE', perf_counter()-start, flush=True)


def publish():
    research = context()
    pre = read(WORK/'others/pre_run_evidence.json')
    for name, path in declared_sources():
        if digest(path) != digest(authenticate(pre['materials'][name])):
            raise ValueError('Frozen material changed: '+name)
    for ref in pre['previous'].values():
        authenticate(ref)
    analysis = read(WORK/'others/analysis.json')
    check, judgment = read(WORK/'others/result_validation.json'), read(WORK/'others/judgment.json')
    if (check['status'] != 'PASS' or check['analysis_sha256'] != digest(WORK/'others/analysis.json')
            or check['verification_source_sha256'] != digest(WORK/'src/verify.py')
            or judgment['analysis_sha256'] != check['analysis_sha256']):
        raise ValueError('Verification or judgment identity mismatch')
    for name, value in analysis['artifacts'].items():
        if digest(WORK/f'others/{name}.json.gz') != value:
            raise ValueError('Changed result artifact')
    paths = [('analysis', 'others/analysis.json'), ('bootstrap-draws', 'others/bootstrap_draws.json.gz'),
        ('verification', 'others/result_validation.json'), ('judgment', 'others/judgment.json'), ('render-source', 'src/render.py')]
    extra = {name: material(research, name, WORK/path).to_dict() for name, path in paths}
    refs = tuple(EvidenceRef.from_dict(v) for v in [*pre['materials'].values(), *pre['previous'].values(), *extra.values()])
    report = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, digest(WORK/'report.md'), ExperimentOutcome.COMPLETED, refs))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'report': report.to_dict(), 'validation': validation.to_dict(), 'materials': extra})
    if validation.status.value != 'PASS':
        raise ValueError('Report publication failed validation')
    print('REPORT_PUBLICATION_PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'publish'))
    run() if parser.parse_args().action == 'run' else publish()
