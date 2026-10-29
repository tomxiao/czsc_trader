"""Three frozen entry hypotheses, with authenticated price labels and statistics."""
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
import numpy as np
from czsc_trader.application import (RepositoryContext, publish_evidence, validate_experiment)
from czsc_trader.research_tools import (EvidenceRef, ExperimentRef, MaterialEvidenceWrite,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope)

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OLD = WORK.parent/'EX021_20261029'
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', WORK.name)
NAMES = ('B', 'C', 'F', 'T', 'H')
NEW_NAMES = ('F', 'T', 'H')
HORIZONS = (3, 13, 26, 65, 130)


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
        raise ValueError('Changed evidence')
    return path


def load_previous():
    pre = read(OLD/'others/pre_run_evidence.json')['materials']
    for name in ('study', 'mechanisms'):
        ref = pre[name+'-source']
        if digest(authenticate(ref)) != digest(OLD/f'src/{name}.py'):
            raise ValueError('Changed frozen helper source')
    search_path = sys.path.copy()
    try:
        sys.path.insert(0, str(OLD/'src'))
        spec = importlib.util.spec_from_file_location('ex021_frozen', OLD/'src/study.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = search_path
    return module


previous = load_previous()
from mechanisms import sparse, summary, match, block_weights, bootstrap
from entries import compute


def context():
    search_path = sys.path.copy()
    try:
        return previous.context()
    finally:
        sys.path[:] = search_path


def prior_refs():
    refs = previous.prior_refs()
    pre = read(OLD/'others/pre_run_evidence.json')['materials']
    refs.update({'statistics-source': pre['mechanisms-source'], 'statistics-driver-source': pre['study-source'],
                 'ex021-report': read(OLD/'others/publication.json')['report']})
    for ref in refs.values():
        authenticate(ref)
    return refs


def input_data(refs):
    rows, prior_facts, prior_analysis = previous.inputs(refs)
    search_path = sys.path.copy()
    try:
        legacy = previous.legacy_module().legacy
    finally:
        sys.path[:] = search_path
    if digest(legacy.PREP) != digest(authenticate(refs['prepared-reference'])):
        raise ValueError('Prepared reference differs from frozen evidence')
    bars, constraints, identities = legacy.fetch(context())
    if identities != prior_analysis['inputs']:
        raise ValueError('Prepared products changed')
    by_i = {f['i']: f for f in prior_facts}
    closes = [x.isoformat() for x in bars.Date]
    opens = [x.isoformat() for x in bars.BarStart]
    for row in rows:
        if row['signal_at'] != closes[row['i']] or row['entry_at'] != opens[row['i']+1]:
            raise ValueError('Reused labels do not align with fetched bars')
    return rows, prior_facts, bars, identities, by_i


def background_segments(facts):
    result, active, previous_i = [], None, None
    for f in facts:
        i = f['i']
        if previous_i is not None and i != previous_i+1:
            raise ValueError('Cannot bridge missing decision indices')
        if 'B' in f['signals']:
            if active is None:
                active = {'start': i, 'end': i, 'left_censored': previous_i is None,
                          'right_censored': False, 'members': [], 'signals': {name: [] for name in NAMES}}
                result.append(active)
            active['end'] = i
            active['members'].append(i)
            for name in f['signals']:
                active['signals'][name].append(i)
        else:
            active = None
        previous_i = i
    if active is not None:
        active['right_censored'] = True
    return result


def compare(control, targets, days, weights, boot=False):
    result = {'summary': summary(targets), 'matched': match(control, targets)}
    good = [r for r in targets if r['price_net_return'] is not None]
    target_ids = {r['i'] for r in good}
    groups = {}
    for r in control:
        if r['price_net_return'] is not None:
            groups.setdefault(r['stratum'], []).append(r['i'])
    result['matched']['support']['all_target_cell_events'] = sum(
        bool(groups.get(r['stratum'])) and set(groups[r['stratum']]).issubset(target_ids) for r in good)
    result['matched']['support']['self_in_control_events'] = sum(
        r['i'] in groups.get(r['stratum'], []) for r in good)
    draws = None
    if boot:
        result['bootstrap'], draws = bootstrap(control, targets, days, weights)
    return result, draws


def add_groups(item, control, pop, days, weights):
    item['concentration'] = previous.concentration(pop)
    for key, groups in (('years', [str(y) for y in range(2019, 2026)]),
                        ('months', sorted({r['month'] for r in control}))):
        item[key] = {g: compare([r for r in control if r['date'].startswith(g)],
                     [r for r in pop if r['date'].startswith(g)], days, weights)[0] for g in groups}


def horizon_task(args):
    n, rows, signals, days, weights = args
    result, draws = {'all': summary(rows), 'signals': {}}, {}
    background = [r for r in rows if r['i'] in signals['B']]
    for name in NAMES:
        chosen = [r for r in rows if r['i'] in signals[name]]
        reduced = set(sparse(signals[name], n))
        result['signals'][name] = {}
        for mode, pop in (('raw', chosen), ('nonoverlap', [r for r in chosen if r['i'] in reduced])):
            item, sample = compare(rows, pop, days, weights, n == 13)
            item['indices'] = [r['i'] for r in pop]
            if n == 13:
                add_groups(item, rows, pop, days, weights)
                draws[name+'/'+mode] = sample
            if name != 'B':
                item['background'], sample = compare(background, pop, days, weights, n == 13)
                if n == 13:
                    draws[name+'/'+mode+'/background'] = sample
            result['signals'][name][mode] = item
    return str(n), result, draws


def duration_task(args):
    # Authenticated EX021 common-cohort implementation, unchanged.
    return previous.duration_task(args)


def declared_sources():
    pairs = [('design', WORK/'protocols/design.md'), ('authorization', WORK/'protocols/authorization.md'),
             ('checks', WORK/'others/checks.json')]
    pairs.extend((p.stem+'-source', p) for p in sorted((WORK/'src').glob('*.py')) if p.stem != 'render')
    return pairs


def material(research, name, path):
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        {'.json': 'application/json', '.gz': 'application/gzip'}.get(path.suffix, 'text/plain'), path.suffix[1:]))


def run():
    start = perf_counter()
    if (WORK/'others/pre_run_evidence.json').exists():
        raise ValueError('Frozen run exists; investigate before retry')
    check = read(WORK/'others/checks.json')
    sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    if check['status'] != 'PASS' or check['sources'] != sources:
        raise ValueError('Source-bound checks required')
    refs, research = prior_refs(), context()
    pre = {name: material(research, name, path).to_dict() for name, path in declared_sources()}
    save(WORK/'others/pre_run_evidence.json', {'materials': pre, 'previous': refs})
    print('PROTOCOL_AND_SOURCES_PUBLISHED', flush=True)
    rows, prior_facts, bars, identities, prior_by = input_data(refs)
    flags, ready, features = compute(bars)
    eligible = [f['i'] for f in prior_facts]
    if not ready.iloc[eligible].all():
        raise ValueError('New expression history missing in original eligible population')
    facts = []
    for i in eligible:
        names = [name for name in NAMES if bool(flags.iloc[i][name])]
        if ('C' in names) != ('C' in prior_by[i]['signals']):
            raise ValueError('Original C did not reproduce')
        raw = features.iloc[i].to_dict()
        facts.append({'i': i, 'signal_at': bars.iloc[i].Date.isoformat(), 'signals': names,
                      'facts': {k: None if v is None or (isinstance(v, (float, np.floating)) and not np.isfinite(v))
                                else bool(v) if isinstance(v, (bool, np.bool_)) else float(v) for k, v in raw.items()}})
    signals = {name: {f['i'] for f in facts if name in f['signals']} for name in NAMES}
    assert not signals['F'] & signals['T']
    assert all(signals[name] <= signals['B'] for name in NAMES)
    segments = background_segments(facts)
    days = sorted({r['date'] for r in rows})
    assert len(days) == 1760
    weights, starts = block_weights(len(days))
    by_n = {n: [r for r in rows if r['n'] == n] for n in HORIZONS}
    horizons, durations, draws = {}, {}, {}
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        for n, item, sample in pool.map(horizon_task, [(n, by_n[n], signals, days, weights) for n in HORIZONS]):
            horizons[n], draws['horizon/'+n] = item, sample
            print('HORIZON_COMPLETE', n, flush=True)
        for name, item, sample in pool.map(duration_task, [(name, by_n, signals[name], days, weights) for name in NAMES]):
            durations[name], draws['duration/'+name] = item, sample
            print('DURATION_COMPLETE', name, flush=True)
    usable = [s for s in segments if not s['left_censored']]
    first = {}
    for name in NAMES:
        ids = {s['signals'][name][0] for s in usable if s['signals'][name]}
        pop = [r for r in by_n[13] if r['i'] in ids]
        item, sample = compare(by_n[13], pop, days, weights, True)
        item['indices'] = sorted(ids)
        add_groups(item, by_n[13], pop, days, weights)
        draws['first/'+name] = sample
        if name != 'B':
            item['background'], sample = compare([r for r in by_n[13] if r['i'] in signals['B']], pop, days, weights, True)
            draws['first/'+name+'/background'] = sample
        first[name] = item
    artifacts = {'signal_facts': facts, 'segments': segments, 'bootstrap_draws': draws}
    for name, value in artifacts.items():
        (WORK/f'others/{name}.json.gz').write_bytes(gzip.compress(json.dumps(value, allow_nan=False).encode(), mtime=0))
    save(WORK/'others/analysis.json', {'schema': 's017-downside-failure-census/v1', 'experiment': EXPERIMENT.to_dict(),
        'protocol_sha256': digest(WORK/'protocols/design.md'), 'sources': sources, 'previous': refs,
        'eligible': len(eligible), 'inputs': identities, 'signal_counts': {k: len(v) for k, v in signals.items()},
        'overlap': {a: {b: len(signals[a] & signals[b]) for b in NAMES} for a in NAMES},
        'horizons': horizons, 'duration': durations, 'first': first,
        'segment_counts': {'total': len(segments), 'usable': len(usable),
            'left_censored': sum(s['left_censored'] for s in segments),
            'right_censored': sum(s['right_censored'] for s in segments),
            'with_signal': {name: sum(bool(s['signals'][name]) for s in usable) for name in NAMES},
            'without_signal': {name: sum(not s['signals'][name] for s in usable) for name in NAMES}},
        'bootstrap': {'replicates': 1000, 'block_sessions': 20, 'seed': 17, 'sessions': len(days),
            'starts_sha256': sha256(starts.astype('<i8').tobytes()).hexdigest(), 'workers': 2, 'native_threads': 1},
        'artifacts': {name: digest(WORK/f'others/{name}.json.gz') for name in artifacts},
        'new_primary_expressions': 3, 'new_background_expressions': 1, 'new_entry_expressions': 4,
        'new_accounts': 0, 'reserved_2026_used': False, 'seconds': perf_counter()-start})
    print('ANALYSIS_COMPLETE', perf_counter()-start, flush=True)


def publish():
    research = context()
    pre = read(WORK/'others/pre_run_evidence.json')
    for name, path in declared_sources():
        if digest(path) != digest(authenticate(pre['materials'][name])):
            raise ValueError('Changed frozen source '+name)
    for ref in pre['previous'].values():
        authenticate(ref)
    analysis = read(WORK/'others/analysis.json')
    check = read(WORK/'others/result_validation.json')
    judgment = read(WORK/'others/judgment.json')
    if (check['status'] != 'PASS' or check['analysis_sha256'] != digest(WORK/'others/analysis.json')
            or check['verification_source_sha256'] != digest(WORK/'src/verify.py')
            or judgment['analysis_sha256'] != check['analysis_sha256']):
        raise ValueError('Result identity or verification failed')
    for name, value in analysis['artifacts'].items():
        if digest(WORK/f'others/{name}.json.gz') != value:
            raise ValueError('Changed result artifact')
    paths = [('analysis', 'others/analysis.json'), ('signal-facts', 'others/signal_facts.json.gz'),
        ('segments', 'others/segments.json.gz'), ('bootstrap-draws', 'others/bootstrap_draws.json.gz'),
        ('verification', 'others/result_validation.json'), ('judgment', 'others/judgment.json'), ('render-source', 'src/render.py')]
    extra = {name: material(research, name, WORK/path).to_dict() for name, path in paths}
    refs = tuple(EvidenceRef.from_dict(v) for v in [*pre['materials'].values(), *pre['previous'].values(), *extra.values()])
    report = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, digest(WORK/'report.md'), ExperimentOutcome.COMPLETED, refs))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'report': report.to_dict(), 'validation': validation.to_dict(), 'materials': extra})
    if validation.status.value != 'PASS':
        raise ValueError('Publication validation failed')
    print('REPORT_PUBLICATION_PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'publish'))
    run() if parser.parse_args().action == 'run' else publish()
