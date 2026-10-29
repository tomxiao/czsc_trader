"""Numbered entry competition with fixed price labels and background-state controls."""
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
from czsc_trader.application import RepositoryContext, publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentRef, MaterialEvidenceWrite,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope)
from numbered_entries import NAMES as NEW_NAMES, compute

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OLD = WORK.parent/'EX022_20261029'
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', WORK.name)
NAMES = ('S017-M001', 'S017-M002', *NEW_NAMES)
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
        spec = importlib.util.spec_from_file_location('ex022_numbered_helper', OLD/'src/study.py')
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
    refs = previous.prior_refs()
    pub, pre = read(OLD/'others/publication.json'), read(OLD/'others/pre_run_evidence.json')
    refs.update({'reference-facts': pub['materials']['signal-facts'],
        'reference-analysis': pub['materials']['analysis'], 'reference-report': pub['report'],
        'reference-entry-source': pre['materials']['entries-source'], 'helper-source': pre['materials']['study-source']})
    for ref in refs.values():
        authenticate(ref)
    return refs


def load_gzip(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def inputs(refs):
    rows, prior_facts, bars, identities, _ = previous.input_data(refs)
    reference = load_gzip(authenticate(refs['reference-facts']))
    if len(rows) != 113950 or len(prior_facts) != 22790 or [f['i'] for f in reference] != [f['i'] for f in prior_facts]:
        raise ValueError('Original eligible population changed')
    if any(not '2019-01-02' <= r['date'] <= '2025-12-31' for r in rows):
        raise ValueError('Outside authorized development window')
    return rows, reference, bars, identities


def signal_facts(reference, bars):
    flags, ready, features = compute(bars)
    old_flags, old_ready, _ = previous.compute(bars)
    eligible = [f['i'] for f in reference]
    if not ready.iloc[eligible].all() or not old_ready.iloc[eligible].all():
        raise ValueError('Cannot shrink the original eligible population')
    facts = []
    for original in reference:
        i = original['i']
        names = []
        for legacy, name in (('B', NAMES[0]), ('T', NAMES[1])):
            if bool(old_flags.iloc[i][legacy]) != (legacy in original['signals']):
                raise ValueError('Reference signal failed exact reproduction')
            if legacy in original['signals']:
                names.append(name)
        names.extend(name for name in NEW_NAMES if bool(flags.iloc[i][name]))
        raw = features.iloc[i].to_dict()
        values = {k: None if v is None or (isinstance(v, (float, np.floating)) and not np.isfinite(v))
                  else v.item() if isinstance(v, np.generic) else v for k, v in raw.items()}
        facts.append({'i': i, 'signal_at': bars.iloc[i].Date.isoformat(), 'signals': names, 'facts': values})
    return facts


def adjusted_rows(rows, background):
    return [dict(r, stratum=r['stratum']+'|M001='+str(int(r['i'] in background))) for r in rows]


def horizon_task(args):
    n, rows, signals, days, weights = args
    result, draws = {'all': previous.summary(rows), 'signals': {}}, {}
    adjusted = adjusted_rows(rows, signals[NAMES[0]])
    for name in NAMES:
        chosen = [r for r in rows if r['i'] in signals[name]]
        reduced = set(previous.sparse(signals[name], n))
        result['signals'][name] = {}
        for mode, pop in (('raw', chosen), ('nonoverlap', [r for r in chosen if r['i'] in reduced])):
            item, sample = previous.compare(rows, pop, days, weights, n == 65)
            item['indices'] = [r['i'] for r in pop]
            if n == 65:
                previous.add_groups(item, rows, pop, days, weights)
                draws[name+'/'+mode] = sample
                if name != NAMES[0]:
                    target_ids = {r['i'] for r in pop}
                    item['background_adjusted'], sample = previous.compare(adjusted,
                        [r for r in adjusted if r['i'] in target_ids], days, weights, True)
                    draws[name+'/'+mode+'/background_adjusted'] = sample
                if name in NEW_NAMES:
                    item['background_slices'] = {}
                    for label, inside in (('inside', True), ('outside', False)):
                        control = [r for r in rows if (r['i'] in signals[NAMES[0]]) == inside]
                        targets = [r for r in pop if (r['i'] in signals[NAMES[0]]) == inside]
                        item['background_slices'][label], sample = previous.compare(control, targets, days, weights, True)
                        draws[name+'/'+mode+'/'+label] = sample
            result['signals'][name][mode] = item
    return str(n), result, draws


def duration_task(args):
    return previous.duration_task(args)


def declared_sources():
    pairs = [('design', WORK/'protocols/design.md'), ('authorization', WORK/'protocols/authorization.md'),
             ('mechanism-index', WORK/'protocols/mechanism_index.json'), ('checks', WORK/'others/checks.json')]
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
    if digest(WORK/'protocols/mechanism_index.json') != digest(ROOT/'research/S017/materials/mechanism_index.json'):
        raise ValueError('Mechanism index snapshot differs')
    refs, research = prior_refs(), context()
    pre = {name: material(research, name, path).to_dict() for name, path in declared_sources()}
    save(WORK/'others/pre_run_evidence.json', {'materials': pre, 'previous': refs})
    print('PROTOCOL_AND_SOURCES_PUBLISHED', flush=True)
    rows, reference, bars, identities = inputs(refs)
    facts = signal_facts(reference, bars)
    signals = {name: {f['i'] for f in facts if name in f['signals']} for name in NAMES}
    days = sorted({r['date'] for r in rows})
    if len(days) != 1760 or len(signals[NAMES[1]]) != 67:
        raise ValueError('Reference population changed')
    weights, starts = previous.block_weights(len(days))
    by_n = {n: [r for r in rows if r['n'] == n] for n in HORIZONS}
    horizons, durations, draws = {}, {}, {}
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        for n, item, sample in pool.map(horizon_task, [(n, by_n[n], signals, days, weights) for n in HORIZONS]):
            horizons[n], draws['horizon/'+n] = item, sample
            print('HORIZON_COMPLETE', n, flush=True)
        for name, item, sample in pool.map(duration_task, [(name, by_n, signals[name], days, weights) for name in NAMES]):
            durations[name], draws['duration/'+name] = item, sample
            print('DURATION_COMPLETE', name, flush=True)
    artifacts = {'signal_facts': facts, 'bootstrap_draws': draws}
    for name, value in artifacts.items():
        (WORK/f'others/{name}.json.gz').write_bytes(gzip.compress(json.dumps(value, allow_nan=False).encode(), mtime=0))
    save(WORK/'others/analysis.json', {'schema': 's017-numbered-entry-census/v1', 'experiment': EXPERIMENT.to_dict(),
        'protocol_sha256': digest(WORK/'protocols/design.md'), 'sources': sources, 'previous': refs,
        'mechanism_index_sha256': digest(WORK/'protocols/mechanism_index.json'),
        'eligible': len(facts), 'inputs': identities, 'signal_counts': {k: len(v) for k, v in signals.items()},
        'overlap': {a: {b: len(signals[a] & signals[b]) for b in NAMES} for a in NAMES},
        'horizons': horizons, 'duration': durations,
        'bootstrap': {'replicates': 1000, 'block_sessions': 20, 'seed': 17, 'sessions': len(days),
            'starts_sha256': sha256(starts.astype('<i8').tobytes()).hexdigest(), 'workers': 2, 'native_threads': 1},
        'artifacts': {name: digest(WORK/f'others/{name}.json.gz') for name in artifacts},
        'new_entry_expressions': 3, 'new_accounts': 0, 'reserved_2026_used': False,
        'reference_signal_reproduction': 'PASS', 'seconds': perf_counter()-start})
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
    paths = [('analysis', 'others/analysis.json'), ('signal-facts', 'others/signal_facts.json.gz'),
        ('bootstrap-draws', 'others/bootstrap_draws.json.gz'), ('verification', 'others/result_validation.json'),
        ('judgment', 'others/judgment.json'), ('render-source', 'src/render.py')]
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
