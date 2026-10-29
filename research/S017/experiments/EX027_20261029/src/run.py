"""One integrated, fixed-entry three-exit research round using public accounts."""
# ruff: noqa: E402
import argparse
from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
from dataflows import PreparedDataRef, ProviderConfig, TimeInterval, InstrumentId, MarketId, AssetClass, SourceRef, BarFrequency
from strategy_runtime import (EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash,
    ResearchExecutionSpec, UsEquitySpec, AccountPolicy, CashAvailabilityPolicy, ExecutionResources)
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, publish_evidence_many
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EquitySources,
    EquityEvaluationRequest, EquityBuyHold, EvaluationBenchmark, EvaluationEvidenceWrite,
    MaterialEvidenceWrite, ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode)

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT/'.tmp/s017-research'/WORK.name
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(SCRATCH)
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', WORK.name)
BATCH = ResearchBatchRef('S017')
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
SOURCE = SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028')
INSTRUMENT = InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE')
DATA_READINESS = ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json'
EXPECTED = {
    'C0048': {'exit_mechanism': 'S017-M009', 'max_holding_bars': 65},
    'C0049': {'exit_mechanism': 'S017-M010', 'max_holding_bars': 65},
    'C0050': {'exit_mechanism': 'S017-M011', 'max_holding_bars': 65, 'trailing_atr_multiple': 3.0},
}

def read(path):
    return json.loads(path.read_bytes())

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False).encode('utf-8'))

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def context(workers=2):
    if type(workers) is not int or not 1 <= workers <= 3:
        raise ValueError('Only one to three coordinated workers are allowed')
    return create_research_context(REPOSITORY, BATCH, providers=ProviderConfig(bindings={}),
        execution_spec=SPEC, resources=ExecutionResources(max_workers=workers, native_threads_per_worker=1, random_seed=17))

def configurations():
    values = read(WORK/'protocols/configurations.json')
    if values != EXPECTED:
        raise ValueError('Fixed three-exit competition changed')
    return values

def candidate(key, parameters):
    if key not in EXPECTED or parameters != EXPECTED[key]:
        raise ValueError('Unapproved parameter or candidate')
    source, files = WORK/'src', ('strategy.py',)
    definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, 'strategy:decide', files,
        equity_source_hash(source, files), json.dumps(parameters), feedback_mode='CONFIRMED_EXECUTION',
        session_context=False, auxiliary_inputs=())
    return EquityStrategyCandidate('S017', key, definition, source)

def request(cand):
    ref = read(DATA_READINESS)['reference']
    if ref['manifest_sha256'] != 'bdba8f6a3e9475ed62a3295bdcccd6bb2286f5e081ec44b79811c1bcb72dce93':
        raise ValueError('Original data identity changed')
    prepared = PreparedDataRef(UUID(ref['space_id']), UUID(ref['preparation_id']), ref['manifest_sha256'])
    zone = ZoneInfo('America/New_York')
    return EquityEvaluationRequest(EXPERIMENT, cand,
        TimeInterval(datetime(2019, 1, 2, 9, 30, tzinfo=zone), datetime(2025, 12, 31, 16, tzinfo=zone)),
        date(2018, 11, 1), EquitySources(SOURCE, SOURCE, SOURCE, SOURCE), 100000., .001, prepared=prepared,
        benchmark=EvaluationBenchmark(EquityBuyHold(SPEC)), window_id='DEV_2019_2025', scenario_id='STANDARD',
        measurement_tier='FORMAL', drawdown_basis='BAR_CLOSE', concentration_basis='MAX_SINGLE', frequency_window_days=60)

def material(research, name, path):
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        {'.json': 'application/json', '.gz': 'application/gzip'}.get(path.suffix, 'text/plain'), path.suffix[1:]))

def initialize():
    candidates = {key: candidate(key, params) for key, params in configurations().items()}
    values = {key: item.definition.to_dict() for key, item in candidates.items()}
    path = WORK/'protocols/definitions.json'
    if path.exists() and read(path) != json.loads(json.dumps(values, default=str)):
        raise ValueError('Frozen definitions changed')
    if not path.exists():
        save(path, values)
    return candidates

def checked_precheck():
    checked = read(WORK/'others/precheck.json')
    mechanism = read(WORK/'others/precheck_mechanism.json')
    if checked['status'] != 'PASS' or mechanism['status'] != 'PASS':
        raise ValueError('Prechecks must pass')
    for document in (checked, mechanism):
        if document['strategy_source_sha256'] != digest(WORK/'src/strategy.py'):
            raise ValueError('Precheck strategy identity changed')
    if checked['precheck_source_sha256'] != digest(WORK/'src/precheck.py'):
        raise ValueError('Precheck source changed')
    if mechanism['check_source_sha256'] != digest(WORK/'src/check_mechanism.py'):
        raise ValueError('Mechanism check source changed')
    if read(WORK/'others/entry_reproduction.json')['status'] != 'PASS':
        raise ValueError('Original M005 signal reproduction failed')
    if checked['entry_reproduction_sha256'] != digest(WORK/'others/entry_reproduction.json'):
        raise ValueError('Entry reproduction evidence changed after precheck')
    return checked

def run(mode='CREATE', workers=2):
    mode = CheckpointMode(mode)
    checked_precheck()
    candidates, research = initialize(), context(workers)
    files = [(p.stem+'-source', p) for p in sorted((WORK/'src').glob('*.py'))
             if p.stem in ('run', 'strategy', 'precheck', 'check_mechanism', 'analyze')]
    files += [(p.stem.replace('_', '-'), p) for p in sorted((WORK/'protocols').iterdir()) if p.is_file()]
    files += [('precheck', WORK/'others/precheck.json'),
        ('precheck-mechanism', WORK/'others/precheck_mechanism.json'),
        ('entry-reproduction', WORK/'others/entry_reproduction.json'), ('prepared-reference', DATA_READINESS)]
    path = WORK/'others/pre_run_evidence.json'
    if path.exists():
        if mode is not CheckpointMode.RESUME:
            raise ValueError('Existing frozen run requires explicit RESUME')
        from czsc_trader.research_tools import EvidenceRef
        before = read(path)
        for name, file in files:
            ref = EvidenceRef.from_dict(before[name])
            if digest(ref.resolve(ROOT)) != digest(file):
                raise ValueError('Frozen input changed: '+name)
    else:
        if mode is not CheckpointMode.CREATE:
            raise ValueError('No frozen run to resume')
        before = {name: material(research, name, file).to_dict() for name, file in files}
        save(path, before)
    requests = []
    for key, item in candidates.items():
        requests.append(research.evaluation.prepare(request(item)))
        print('PREPARED', key, flush=True)
    def progress(event):
        print(json.dumps(asdict(event), default=str), flush=True)
    with ResearchExecutionSession(research, experiment=EXPERIMENT,
            checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id, mode), on_progress=progress) as execution:
        outcomes = research.evaluation.evaluate_many(tuple(requests), execution=execution)
        statuses = [{'candidate': req.candidate.candidate_id, 'status': outcome.status.value,
            'error': None if outcome.error is None else asdict(outcome.error)}
            for req, outcome in zip(requests, outcomes, strict=True)]
        save(WORK/'others/execution_status.json', statuses)
        save(WORK/'others/execution_stats.json', asdict(execution.stats))
        if any(item.status.value != 'SUCCEEDED' for item in outcomes):
            raise RuntimeError(statuses)
        writes = tuple(EvaluationEvidenceWrite(EXPERIMENT, 'account-'+req.candidate.candidate_id, req, outcome.result)
            for req, outcome in zip(requests, outcomes, strict=True))
        published = publish_evidence_many(research, writes, execution=execution)
        save(WORK/'others/publication_status.json', [asdict(item) for item in published])
        save(WORK/'others/execution_stats.json', asdict(execution.stats))
        if any(item.status.value != 'PUBLISHED' for item in published):
            raise RuntimeError('Account publication failed')
        rows = {}
        for req, outcome, publication in zip(requests, outcomes, published, strict=True):
            value = outcome.result.payload
            rows[req.candidate.candidate_id] = {'evidence': publication.reference.to_dict(),
                'evaluation_identity': value['evaluation_identity'], 'evaluation_id': value['evaluation_id'],
                'request_hash': outcome.result.request_hash, 'execution_status': outcome.status.value,
                'publication_status': publication.status.value, 'candidate': value['runs']['candidate']['metrics'],
                'buy_hold': value['runs']['buy_hold']['metrics']}
        save(WORK/'others/accounts.json', rows)
        print('ACCOUNTS_PUBLISHED', sorted(rows), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'run'))
    parser.add_argument('--mode', choices=('CREATE', 'RESUME'), default='CREATE')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    initialize() if args.action == 'init' else run(args.mode, args.workers)
