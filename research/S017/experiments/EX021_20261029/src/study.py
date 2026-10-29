"""Authenticated reanalysis of EX020 event labels, with no new price fetch or accounts."""
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
from czsc_trader.application import (RepositoryContext, create_research_context,
    publish_evidence, validate_experiment)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope)
from mechanisms import NAMES, HORIZONS, flags, sparse, episodes, summary, match, bootstrap, block_weights

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OLD = WORK.parent/'EX020_20261029'
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', WORK.name)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2, default=str,
                               allow_nan=False).encode('utf-8'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def authenticate(reference):
    ref = EvidenceRef.from_dict(reference)
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError('Evidence content mismatch')
    return path


def legacy_module():
    pre = read(OLD/'others/pre_run_evidence.json')['materials']
    for name in ('study', 'signals'):
        path = authenticate(pre[name+'-source'])
        if digest(OLD/f'src/{name}.py') != digest(path):
            raise ValueError('Frozen source changed')
    sys.path.insert(0, str(OLD/'src'))
    spec = importlib.util.spec_from_file_location('ex020_frozen', OLD/'src/study.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def context():
    old = legacy_module()
    scratch = ROOT/'.tmp/s017-decomposition'
    scratch.mkdir(exist_ok=True, parents=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(scratch)
    return create_research_context(REPOSITORY, ResearchBatchRef('S017'),
        providers=old.legacy.ProviderConfig(bindings={}), execution_spec=old.legacy.SPEC,
        resources=old.legacy.ExecutionResources(max_workers=2, native_threads_per_worker=1, random_seed=17))


def prior_refs():
    publication = read(OLD/'others/publication.json')
    if publication['validation']['status'] != 'PASS':
        raise ValueError('Prior report was not published successfully')
    refs = {k: publication['materials'][k] for k in ('events', 'signal-facts', 'analysis')}
    refs['report'] = publication['report']
    refs.update({k: v for k, v in read(OLD/'others/pre_run_evidence.json')['materials'].items()
                 if k in ('study-source', 'signals-source', 'design', 'prepared-reference', 'legacy-label-source')})
    for ref in refs.values():
        authenticate(ref)
    return refs


def inputs(refs):
    rows = json.loads(gzip.decompress(authenticate(refs['events']).read_bytes()))
    facts = json.loads(gzip.decompress(authenticate(refs['signal-facts']).read_bytes()))
    old = read(authenticate(refs['analysis']))
    if len(facts) != 22790 or len(rows) != 5*22790 or old['reserved_2026_used']:
        raise ValueError('Prior population changed')
    for f in facts:
        if flags(f['facts'])['C'] != ('C' in f['signals']):
            raise ValueError('Original C does not reproduce')
    if {r['n'] for r in rows} != set(HORIZONS):
        raise ValueError('Unexpected horizons')
    if any(not ('2019-01-02' <= r['date'] <= '2025-12-31') for r in rows):
        raise ValueError('Outside permitted development window')
    return rows, facts, old


def concentration(rows):
    positive = [r for r in rows if r['price_net_return'] is not None and r['price_net_return'] > 0]
    total = sum(r['price_net_return'] for r in positive)
    yearly = {str(y): sum(r['price_net_return'] for r in positive if r['date'].startswith(str(y)))
              for y in range(2019, 2026)}
    return {'positive_sum': total, 'positive_sum_by_year': yearly,
        'largest_year_share': max(yearly.values())/total if total else None,
        'largest_event_share': max((r['price_net_return'] for r in positive), default=0)/total if total else None,
        'scope': 'Arithmetic sums of event returns, possibly overlapping; not account PnL.'}


def compare(control, targets, days, weights, include_boot=False):
    result = {'summary': summary(targets), 'matched': match(control, targets)}
    draws = None
    if include_boot:
        result['bootstrap'], draws = bootstrap(control, targets, days, weights)
    return result, draws


def horizon_task(args):
    n, rows, signals, days, weights = args
    result, draws = {'all': summary(rows), 'signals': {}, 'confirmation': {}}, {}
    for name in NAMES:
        chosen = [r for r in rows if r['i'] in signals[name]]
        reduced = set(sparse(signals[name], n))
        result['signals'][name] = {}
        for mode, pop in (('raw', chosen), ('nonoverlap', [r for r in chosen if r['i'] in reduced])):
            item, sample = compare(rows, pop, days, weights, n == 13)
            item['indices'] = [r['i'] for r in pop]
            if n == 13:
                item['concentration'] = concentration(pop)
                item['years'] = {str(y): compare([r for r in rows if r['date'].startswith(str(y))],
                    [r for r in pop if r['date'].startswith(str(y))], days, weights)[0] for y in range(2019, 2026)}
                item['months'] = {m: compare([r for r in rows if r['month'] == m],
                    [r for r in pop if r['month'] == m], days, weights)[0] for m in sorted({r['month'] for r in rows})}
            result['signals'][name][mode] = item
            if sample is not None:
                draws[name+'/'+mode] = sample
    control = [r for r in rows if r['i'] in signals['D_NR']]
    for mode in ('raw', 'nonoverlap'):
        ids = set(result['signals']['C'][mode]['indices'])
        result['confirmation'][mode], sample = compare(control, [r for r in rows if r['i'] in ids], days, weights, n == 13)
        if sample is not None:
            draws['confirmation/'+mode] = sample
    return str(n), result, draws


def duration_task(args):
    name, by_n, ids, days, weights = args
    complete = set.intersection(*({r['i'] for r in by_n[n] if r['price_net_return'] is not None} for n in HORIZONS))
    lookup = {n: {r['i']: r for r in by_n[n]} for n in HORIZONS}
    result, draws = {}, {}
    for mode, original in (('raw', sorted(ids)), ('nonoverlap130', sparse(ids, 130))):
        members = [i for i in original if i in complete]
        excluded = [{'i': i, 'reasons': {str(n): lookup[n][i]['status'] for n in HORIZONS
                     if lookup[n][i]['price_net_return'] is None}} for i in original if i not in complete]
        item = {'preselected_indices': original, 'common_complete_indices': members,
                'excluded': excluded, 'horizons': {}, 'increments': {}}
        targets = set(members)
        for n in HORIZONS:
            control = [r for r in by_n[n] if r['i'] in complete]
            selected = [r for r in by_n[n] if r['i'] in targets]
            item['horizons'][str(n)], sample = compare(control, selected, days, weights, True)
            draws[mode+'/'+str(n)] = sample
        for a, b in ((13, 26), (26, 65), (65, 130)):
            control = [dict(lookup[a][i], price_net_return=lookup[b][i]['price_net_return']-lookup[a][i]['price_net_return'])
                       for i in sorted(complete)]
            selected = [r for r in control if r['i'] in targets]
            key = f'{a}-{b}'
            item['increments'][key], sample = compare(control, selected, days, weights, True)
            draws[mode+'/'+key] = sample
        result[mode] = item
    return name, result, draws


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
        raise ValueError('A frozen run already exists; investigate before changing or retrying')
    research = context()
    check = read(WORK/'others/checks.json')
    sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    if check['status'] != 'PASS' or check['sources'] != sources:
        raise ValueError('Focused checks are not bound to exact sources')
    refs = prior_refs()
    pre = {name: material(research, name, path).to_dict() for name, path in declared_sources()}
    save(WORK/'others/pre_run_evidence.json', {'materials': pre, 'previous': refs})
    print('PROTOCOL_AND_SOURCES_PUBLISHED', flush=True)
    rows, facts, old = inputs(refs)
    signals = {name: {f['i'] for f in facts if flags(f['facts'])[name]} for name in NAMES}
    episode_rows = episodes(facts)
    by_n = {n: [r for r in rows if r['n'] == n] for n in HORIZONS}
    days = sorted({r['date'] for r in rows})
    assert len(days) == 1760
    weights, starts = block_weights(len(days))
    horizons, durations, draws = {}, {}, {}
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        for n, item, sample in pool.map(horizon_task, [(n, by_n[n], signals, days, weights) for n in HORIZONS]):
            horizons[n] = item
            draws['horizon/'+n] = sample
            print('HORIZON_COMPLETE', n, flush=True)
        for name, item, sample in pool.map(duration_task, [(name, by_n, signals[name], days, weights) for name in NAMES]):
            durations[name] = item
            draws['duration/'+name] = sample
            print('DURATION_COMPLETE', name, flush=True)
    valid_episodes = [e for e in episode_rows if not e['left_censored']]
    episode_results = {}
    for name, ids in (('first_D', {e['start'] for e in valid_episodes}),
                      ('first_C', {e['confirmations'][0] for e in valid_episodes if e['confirmations']})):
        pop = [r for r in by_n[13] if r['i'] in ids]
        episode_results[name], sample = compare(by_n[13], pop, days, weights, True)
        episode_results[name]['indices'] = sorted(ids)
        episode_results[name]['concentration'] = concentration(pop)
        draws['episode/'+name] = sample
    artifacts = {'bootstrap_draws': draws, 'episodes': episode_rows}
    for name, value in artifacts.items():
        (WORK/f'others/{name}.json.gz').write_bytes(gzip.compress(json.dumps(value, allow_nan=False).encode(), mtime=0))
    save(WORK/'others/analysis.json', {'schema': 's017-oversold-decomposition/v1', 'experiment': EXPERIMENT.to_dict(),
        'protocol_sha256': digest(WORK/'protocols/design.md'), 'sources': sources, 'previous': refs,
        'eligible': len(facts), 'signal_counts': {k: len(v) for k, v in signals.items()},
        'horizons': horizons, 'duration': durations, 'episode_results': episode_results,
        'episode_counts': {'total': len(episode_rows), 'left_censored': sum(e['left_censored'] for e in episode_rows),
            'right_censored': sum(e['right_censored'] for e in episode_rows),
            'usable': len(valid_episodes), 'with_C': sum(bool(e['confirmations']) for e in valid_episodes),
            'without_C': sum(not e['confirmations'] for e in valid_episodes)},
        'bootstrap': {'replicates': 1000, 'block_sessions': 20, 'seed': 17, 'sessions': len(days),
            'starts_sha256': sha256(starts.astype('<i8').tobytes()).hexdigest(), 'workers': 2, 'native_threads': 1},
        'prior_C_primary_nonoverlap': old['horizons']['13']['signals']['C']['nonoverlap'],
        'artifacts': {name: digest(WORK/f'others/{name}.json.gz') for name in artifacts},
        'new_entry_expressions': 3, 'new_accounts': 0, 'reserved_2026_used': False,
        'seconds': perf_counter()-start})
    print('ANALYSIS_COMPLETE', perf_counter()-start, flush=True)


def publish():
    research = context()
    pre = read(WORK/'others/pre_run_evidence.json')
    for name, path in declared_sources():
        if digest(path) != digest(authenticate(pre['materials'][name])):
            raise ValueError('Frozen material changed: '+name)
    for ref in pre['previous'].values():
        authenticate(ref)
    check = read(WORK/'others/result_validation.json')
    judgment = read(WORK/'others/judgment.json')
    if check['status'] != 'PASS' or check['analysis_sha256'] != digest(WORK/'others/analysis.json'):
        raise ValueError('Analysis has not passed independent verification')
    if judgment['analysis_sha256'] != check['analysis_sha256'] or check['verification_source_sha256'] != digest(WORK/'src/verify.py'):
        raise ValueError('Verification or judgment identity mismatch')
    for name, value in read(WORK/'others/analysis.json')['artifacts'].items():
        if digest(WORK/f'others/{name}.json.gz') != value:
            raise ValueError('Changed result artifact')
    paths = [('analysis', 'others/analysis.json'), ('bootstrap-draws', 'others/bootstrap_draws.json.gz'),
             ('episodes', 'others/episodes.json.gz'), ('verification', 'others/result_validation.json'),
             ('judgment', 'others/judgment.json'), ('render-source', 'src/render.py')]
    extra = {name: material(research, name, WORK/path).to_dict() for name, path in paths}
    refs = tuple(EvidenceRef.from_dict(v) for v in [*pre['materials'].values(), *pre['previous'].values(), *extra.values()])
    report = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, digest(WORK/'report.md'), ExperimentOutcome.COMPLETED, refs))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'report': report.to_dict(), 'validation': validation.to_dict(), 'materials': extra})
    if validation.status.value != 'PASS':
        raise ValueError('Report publication validation failed')
    print('REPORT_PUBLICATION_PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'publish'))
    run() if parser.parse_args().action == 'run' else publish()
