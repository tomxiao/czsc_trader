"""Bind local immutable evidence before the single fixed EX039 fit execution."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import socket
import subprocess
import sys
from uuid import UUID

from dataflows import DataRequest, Dataset, EvidenceParameters, PreparePolicy, PreparedDataRef
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import EvidenceRef, ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / 'others'


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def offline(*args, **kwargs):
    raise RuntimeError('EX039 local evidence binding forbids network access')


def verify_map(path):
    refs = read(path)
    if not isinstance(refs, dict) or not refs:
        raise ValueError('Nonempty evidence map required')
    for name, value in refs.items():
        source = ROOT / name
        if Path(name).is_absolute() or not source.resolve().is_relative_to(EX.resolve()):
            raise ValueError('Run evidence source outside experiment')
        ref = EvidenceRef.from_dict(value)
        evidence = ref.resolve(ROOT)
        if (ref.experiment != ExperimentRef('S014', 'EX039_20261019')
                or digest(source) != ref.sha256 or digest(evidence) != ref.sha256
                or source.read_bytes() != evidence.read_bytes()):
            raise ValueError('Run evidence reference/bytes mismatch')
    return refs


def request():
    source = OUT / 'model_inputs.csv'
    return DataRequest(Dataset.STRATEGY_FEATURE_EVIDENCE, 'S014:EX039:FIXED_MODEL_INPUTS_V1',
                       '2020-01-01', '2026-10-15', None, 'daily',
                       EvidenceParameters(ROOT, source.relative_to(ROOT).as_posix(), digest(source)))


def fetch(ctx, ref, expected=None):
    value = ctx.data.fetch(request(), prepared=ref)
    if not value.ready or value.identity.symbol != request().symbol or value.identity.dataset != Dataset.STRATEGY_FEATURE_EVIDENCE:
        raise ValueError('Merged feature public fetch failed')
    if expected and (value.identity.content_sha256 != expected['content_sha256'] or len(value.dataframe) != expected['rows']):
        raise ValueError('Merged feature fetch identity changed')
    return value


def prepare(ctx):
    if (EX / 'protocols/published_run_inputs.json').exists():
        raise FileExistsError('Run lock already exists')
    if read(OUT / 'model_input_preflight.json')['status'] != 'PASS_INPUT_ONLY_NOT_FIT_AUTHORIZATION':
        raise ValueError('Merge preflight required')
    verify_map(EX / 'protocols/published_design.json')
    verify_map(EX / 'protocols/published_etf_repair.json')
    p = ctx.data.prepare((request(),), policy=PreparePolicy.REUSE)
    if not p.ready:
        raise ValueError('Merged feature preparation failed')
    value = fetch(ctx, p.reference)
    r = p.reference
    write(OUT / 'model_inputs_prepared.json', {
        'status': 'READY_LOCAL_DERIVED_INPUTS_NOT_HISTORICAL_VINTAGE_CERTIFICATION',
        'reference': {'space_id': str(r.space_id), 'preparation_id': str(r.preparation_id), 'manifest_sha256': r.manifest_sha256},
        'source_sha256': digest(OUT / 'model_inputs.csv'), 'content_sha256': value.identity.content_sha256,
        'rows': len(value.dataframe), 'fits': 0, 'new_source_calls': 0})
    paths = [p for p in sorted(EX.rglob('*')) if p.is_file() and p.suffix in ('.py', '.json', '.csv')
             and 'raw' not in p.relative_to(EX).parts and '__pycache__' not in p.parts
             and 'fixed_analysis' not in p.parts and p.name != 'published_run_inputs.json']
    refs = {}
    for path in paths:
        suffix = path.suffix[1:]
        media = {'py': 'text/x-python', 'json': 'application/json', 'csv': 'text/csv'}[suffix]
        ref = publish_evidence(ctx, MaterialEvidenceWrite(ExperimentRef('S014', 'EX039_20261019'),
                              'run_' + digest(path)[:20], path.read_bytes(), media, suffix))
        refs[path.relative_to(ROOT).as_posix()] = ref.to_dict()
    write(EX / 'protocols/published_run_inputs.json', refs)
    print(json.dumps({'status': 'RUN_INPUTS_BOUND', 'artifacts': len(refs), 'rows': len(value.dataframe), 'fits': 0}), flush=True)


def run(ctx):
    refs = verify_map(EX / 'protocols/published_run_inputs.json')
    if Path(__file__).resolve().relative_to(ROOT).as_posix() not in refs:
        raise ValueError('Runner must bind its own published source')
    verify_map(EX / 'protocols/published_design.json')
    verify_map(EX / 'protocols/published_etf_repair.json')
    record = read(OUT / 'model_inputs_prepared.json')
    r = record['reference']
    fetch(ctx, PreparedDataRef(UUID(r['space_id']), UUID(r['preparation_id']), r['manifest_sha256']), record)
    if record['source_sha256'] != digest(OUT / 'model_inputs.csv'):
        raise ValueError('Model input source changed')
    slots = OUT / 'fixed_analysis/fit_slots'
    if slots.exists() and list(slots.glob('*.json')):
        raise FileExistsError('Any previous fit slot prohibits another execution')
    subprocess.run([sys.executable, '-u', '-B', str(EX / 'src/analyze_fixed.py'), '--run-fits'], cwd=ROOT, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'run'))
    args = parser.parse_args()
    socket.socket.connect = offline
    socket.create_connection = offline
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'))
    (prepare if args.mode == 'prepare' else run)(ctx)
