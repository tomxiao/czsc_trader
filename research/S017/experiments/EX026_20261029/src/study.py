"""Final disjoint-control diagnosis; unchanged M005 and no additional entry expressions."""
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
OLD = WORK.parent/'EX025_20261029'
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', WORK.name)
TARGET = 'S017-M005'
PARENTS = ('S017-M007', 'S017-M008')
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
    for name in ('study', 'ablation_entries'):
        if digest(authenticate(pre[name+'-source'])) != digest(OLD/f'src/{name}.py'):
            raise ValueError('Frozen helper source changed')
    search_path = sys.path.copy()
    try:
        sys.path.insert(0, str(OLD/'src'))
        spec = importlib.util.spec_from_file_location('ex025_disjoint_helper', OLD/'src/study.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = search_path


previous = load_previous()
stats = previous.stats


def context():
    search_path = sys.path.copy()
    try:
        return previous.context()
    finally:
        sys.path[:] = search_path


def prior_refs():
    pub, pre = read(OLD/'others/publication.json'), read(OLD/'others/pre_run_evidence.json')
    refs = {'events': pre['previous']['events'], 'reference-facts': pub['materials']['signal-facts'],
        'reference-analysis': pub['materials']['analysis'], 'reference-report': pub['report'],
        'reference-verification': pub['materials']['verification'],
        'reference-entry-source': pre['materials']['ablation_entries-source'],
        'helper-source': pre['materials']['study-source'],
        'statistics-driver-source': pre['previous']['statistics-driver-source'],
        'statistics-source': pre['previous']['statistics-source']}
    for ref in refs.values():
        authenticate(ref)
    return refs


def load_gzip(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def inputs(refs):
    rows = load_gzip(authenticate(refs['events']))
    reference = load_gzip(authenticate(refs['reference-facts']))
    prior = read(authenticate(refs['reference-analysis']))
    validation = read(authenticate(refs['reference-verification']))
    if validation['status'] != 'PASS' or validation['analysis_sha256'] != digest(authenticate(refs['reference-analysis'])):
        raise ValueError('Reference verification identity failed')
    if digest(authenticate(refs['reference-facts'])) != prior['artifacts']['signal_facts']:
        raise ValueError('Reference facts identity failed')
    ids = [f['i'] for f in reference]
    if len(rows) != 113950 or len(ids) != 22790 or len(set(ids)) != len(ids) or prior['reserved_2026_used']:
        raise ValueError('Original eligible population changed')
    facts_by = {f['i']: f for f in reference}
    for n in HORIZONS:
        pop = [r for r in rows if r['n'] == n]
        if [r['i'] for r in pop] != ids:
            raise ValueError('Horizon population changed')
        for r in pop:
            if not '2019-01-02' <= r['date'] <= '2025-12-31' or r['signal_at'] != facts_by[r['i']]['signal_at']:
                raise ValueError('Date window or reused label alignment changed')
    return rows, reference, prior


def support_design(controls, targets):
    cells = {r['stratum'] for r in controls}
    return {'target_indices': [r['i'] for r in targets], 'control_indices': [r['i'] for r in controls],
        'signal_supported_indices': [r['i'] for r in targets if r['stratum'] in cells],
        'signal_unmatched_indices': [r['i'] for r in targets if r['stratum'] not in cells]}


def comparison_task(args):
    parent, rows, signals, days, weights = args
    controls_ids = signals[parent]-signals[TARGET]
    if controls_ids & signals[TARGET]:
        raise ValueError('Control must exclude all target mechanism events')
    result, draws = {'target': TARGET, 'parent': parent, 'modes': {},
        'parent_signals': len(signals[parent]), 'exclusive_controls': len(controls_ids)}, {}
    adjusted = [dict(r, stratum=r['stratum']+'|M001='+str(int(r['i'] in signals['S017-M001']))) for r in rows]
    for mode in ('raw','nonoverlap'):
        ids = signals[TARGET] if mode=='raw' else set(stats.sparse(signals[TARGET],65))
        result['modes'][mode] = {}
        for label, universe in (('ordinary',rows),('background_adjusted',adjusted)):
            controls = [r for r in universe if r['i'] in controls_ids]
            targets = [r for r in universe if r['i'] in ids]
            item, sample = stats.compare(controls,targets,days,weights,True)
            item['design'] = support_design(controls,targets)
            item['control_summary'] = stats.summary(controls)
            item['supported_concentration'] = stats.previous.concentration([r for r in targets if r['i'] in set(item['matched']['supported_indices'])])
            item['years'] = {str(y): stats.compare([r for r in controls if r['date'].startswith(str(y))],
                [r for r in targets if r['date'].startswith(str(y))],days,weights)[0] for y in range(2019,2026)}
            result['modes'][mode][label], draws[mode+'/'+label] = item,sample
    return parent,result,draws


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
        raise ValueError('Frozen run exists; inspect before retry')
    sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    check = read(WORK/'others/checks.json')
    if check['status'] != 'PASS' or check['sources'] != sources:
        raise ValueError('Source-bound focused checks required')
    refs, research = prior_refs(), context()
    pre = {name: material(research, name, path).to_dict() for name, path in declared_sources()}
    save(WORK/'others/pre_run_evidence.json', {'materials': pre, 'previous': refs})
    print('PROTOCOL_AND_SOURCES_PUBLISHED', flush=True)
    rows, reference, prior = inputs(refs)
    names = ('S017-M001',TARGET,*PARENTS)
    signals = {name:{f['i'] for f in reference if name in f['signals']} for name in names}
    if {k:len(v) for k,v in signals.items()} != {k:prior['signal_counts'][k] for k in names}:
        raise ValueError('Prior signal identity changed')
    if not signals[TARGET] <= signals[PARENTS[0]] or not signals[TARGET] <= signals[PARENTS[1]]:
        raise ValueError('Required nesting failed')
    days = sorted({r['date'] for r in rows})
    if len(days)!=1760:
        raise ValueError('Calendar changed')
    weights,starts = stats.block_weights(len(days))
    primary = [r for r in rows if r['n']==65]
    results,draws = {},{}
    with ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
        for parent,item,sample in pool.map(comparison_task,[(p,primary,signals,days,weights) for p in PARENTS]):
            results[parent],draws[parent] = item,sample
            print('DISJOINT_COMPARISON_COMPLETE',parent,flush=True)
    (WORK/'others/bootstrap_draws.json.gz').write_bytes(gzip.compress(json.dumps(draws,allow_nan=False).encode(),mtime=0))
    save(WORK/'others/analysis.json',{'schema':'s017-final-disjoint-ablation/v1','experiment':EXPERIMENT.to_dict(),
        'protocol_sha256':digest(WORK/'protocols/design.md'),'sources':sources,'previous':refs,
        'eligible':len(reference),'inputs':prior['inputs'],'signal_counts':{k:len(v) for k,v in signals.items()},
        'results':results,'primary':{'parent':'S017-M007','mode':'nonoverlap','matching':'background_adjusted','horizon':65},
        'bootstrap':{'replicates':1000,'block_sessions':20,'seed':17,'sessions':len(days),
            'starts_sha256':sha256(starts.astype('<i8').tobytes()).hexdigest(),'workers':2,'native_threads':1},
        'artifacts':{'bootstrap_draws':digest(WORK/'others/bootstrap_draws.json.gz')},
        'new_entry_expressions':0,'new_accounts':0,'reserved_2026_used':False,
        'ablation_followup_rounds_allowed':0,'reference_signal_reproduction':'PASS','seconds':perf_counter()-start})
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
    paths = [('analysis', 'others/analysis.json'),
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
