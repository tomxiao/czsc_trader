"""Fixed, prechecked S017 stage-two accounts through public research APIs."""
from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo
import argparse
import json
import os

from dataflows import (PreparedDataRef, ProviderConfig, TimeInterval, InstrumentId,
                       MarketId, AssetClass, SourceRef, BarFrequency)
from strategy_runtime import (EquityAuxiliaryInput, EquityStrategyDefinition,
    EquityStrategyCandidate, equity_source_hash, ResearchExecutionSpec, UsEquitySpec,
    AccountPolicy, CashAvailabilityPolicy, ExecutionResources)
from czsc_trader.application import (RepositoryContext, create_research_context,
                                    publish_evidence, publish_evidence_many)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef, EquitySources,
    EquityEvaluationRequest, EquityBuyHold, EvaluationBenchmark, EvaluationEvidenceWrite,
    MaterialEvidenceWrite, ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode)

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp' / 's017-research' / WORK.name
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(SCRATCH)
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', WORK.name)
BATCH = ResearchBatchRef('S017')
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
SOURCE = SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028')
INSTRUMENT = InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE')
DATA_READINESS = ROOT / 'research/S017/experiments/EX009_20261029/others/data_readiness.json'


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2, default=str,
                               allow_nan=False).encode('utf-8'))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def context(workers=2):
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('workers must fit the explicitly coordinated 1..4 process budget')
    resources = ExecutionResources(max_workers=workers, native_threads_per_worker=1, random_seed=17)
    return create_research_context(REPOSITORY, BATCH, providers=ProviderConfig(bindings={}),
                                  execution_spec=SPEC, resources=resources)


def configurations():
    values = read(WORK / 'protocols/configurations.json')
    contracts = read(WORK / 'protocols/candidate_contracts.json')
    if type(values) is not dict or not values or set(values) != set(contracts):
        raise ValueError('fixed configurations and candidate contracts must have the same nonempty keys')
    if any(type(params) is not dict for params in values.values()):
        raise TypeError('each fixed configuration must contain a parameter object')
    parent = ROOT / 'research/S017/experiments/EX014_20261029/protocols'
    expected = read(parent / 'candidate_contracts.json')['C0043']
    if expected['warmup_bars'] != 261:
        raise ValueError('original entry-only history contract changed')
    expected['warmup_bars'] = 273
    if (set(values) != {'C0045'} or values['C0045'] != read(parent / 'configurations.json')['C0043']
            or contracts['C0045'] != expected):
        raise ValueError('EX016 must inherit C0043 parameters and all inputs except explicit 273-bar minimum')
    return values


def candidate(key, parameters):
    declared = read(WORK / 'protocols/candidate_contracts.json')[key]
    fields = {'warmup_bars', 'feedback_mode', 'session_context', 'auxiliary_inputs'}
    if type(declared) is not dict or set(declared) != fields:
        raise ValueError('candidate contract requires the exact four declared input fields')
    source = WORK / 'src'
    files = ('strategy.py',)
    definition = EquityStrategyDefinition(INSTRUMENT, SPEC, declared['warmup_bars'],
        'strategy:decide', files, equity_source_hash(source, files), json.dumps(parameters),
        feedback_mode=declared['feedback_mode'], session_context=declared['session_context'],
        auxiliary_inputs=tuple(EquityAuxiliaryInput.from_dict(item) for item in declared['auxiliary_inputs']))
    return EquityStrategyCandidate('S017', key, definition, source)


def request(cand):
    readiness = read(DATA_READINESS)
    if readiness['status'] != 'READY' or readiness['scope'] != ['2018-11-01', '2025-12-31']:
        raise ValueError('joint prepared inputs are not ready for the fixed development window')
    ref = readiness['reference']
    prepared = PreparedDataRef(UUID(ref['space_id']), UUID(ref['preparation_id']), ref['manifest_sha256'])
    zone = ZoneInfo('America/New_York')
    window = TimeInterval(datetime(2019, 1, 2, 9, 30, tzinfo=zone), datetime(2025, 12, 31, 16, tzinfo=zone))
    return EquityEvaluationRequest(EXPERIMENT, cand, window, date(2018, 11, 1),
        EquitySources(SOURCE, SOURCE, SOURCE, SOURCE), 100000., .001, prepared=prepared,
        benchmark=EvaluationBenchmark(EquityBuyHold(SPEC)), window_id='DEV_2019_2025',
        scenario_id='STANDARD', measurement_tier='FORMAL', drawdown_basis='BAR_CLOSE',
        concentration_basis='MAX_SINGLE', frequency_window_days=60)


def material(research, name, path):
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        'application/json' if path.suffix == '.json' else 'text/plain', path.suffix[1:]))


def initialize():
    candidates = {key: candidate(key, params) for key, params in configurations().items()}
    values = {key: cand.definition.to_dict() for key, cand in candidates.items()}
    path = WORK / 'protocols/definitions.json'
    encoded = json.loads(json.dumps(values, default=str))
    if path.exists() and read(path) != encoded:
        raise ValueError('saved definitions differ from the exact current strategy and protocols')
    if not path.exists():
        save(path, values)
    return candidates


def decision_evidence():
    """Bind the seen public accounts and unchanged diagnostic/description sources."""
    path = WORK / 'protocols/decision_evidence.json'
    value = read(path)
    if (value['schema'] != 's017-relative-exception-decision-evidence/v1'
            or value['selection_status'] != 'ADAPTIVE_AFTER_SEEN_RESULTS'):
        raise ValueError('decision evidence must disclose the adaptive selection')
    origins = {'C0013': ExperimentRef('S017', 'EX003_20261028'),
               'C0043': ExperimentRef('S017', 'EX014_20261029')}
    if set(value['accounts']) != set(origins):
        raise ValueError('decision evidence requires both original control accounts')
    refs = {}
    for key, origin in origins.items():
        ref = EvidenceRef.from_dict(value['accounts'][key])
        original = EvidenceRef.from_dict(read(origin.resolve(ROOT) / 'others/accounts.json')[key]['evidence'])
        if ref != original or ref.experiment != origin:
            raise ValueError('decision evidence changed the original account reference')
        ref.resolve(ROOT)
        refs[key] = ref
    required = {
        'decision-diagnosis': 'research/S017/experiments/EX014_20261029/others/diagnostics/C0043_vs_C0013.json',
        'decision-entry-description': 'research/S017/experiments/EX014_20261029/others/entry_difference_description.json',
        'decision-entry-source': 'research/S017/experiments/EX014_20261029/src/describe_entry_difference.py'}
    if set(value['files']) != set(required):
        raise ValueError('decision source snapshots must cover the exact fixed files')
    materials = [('decision-evidence', path)]
    for name, relative in required.items():
        item = value['files'][name]
        source = ROOT / relative
        if item['path'] != relative or sha256(source.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('seen diagnostic or descriptive source changed: ' + name)
        materials.append((name, source))
    diagnosis = read(materials[1][1])
    usage = read(materials[2][1])
    if (diagnosis['status'] != 'COMPUTED'
            or diagnosis['sources'] != [asdict(refs['C0013']), asdict(refs['C0043'])]
            or usage['status'] != 'PASS'
            or {key: EvidenceRef.from_dict(item) for key, item in usage['source_accounts'].items()} != refs
            or usage['script_sha256'] != value['files']['decision-entry-source']['sha256']):
        raise ValueError('decision provenance does not bind computed diagnosis and actual gate usage')
    return tuple(materials), refs


def run(mode='CREATE', workers=2):
    mode = CheckpointMode(mode)
    checked = read(WORK / 'others/precheck.json')
    source_hash = sha256((WORK / 'src/strategy.py').read_bytes()).hexdigest()
    if checked['status'] != 'PASS' or checked['strategy_source_sha256'] != source_hash:
        raise ValueError('precheck must pass for the exact strategy source before account replay')
    if checked['mechanism_source_sha256'] != sha256((WORK / 'src/check_mechanism.py').read_bytes()).hexdigest():
        raise ValueError('focused mechanism check differs from the prechecked source')
    definitions = initialize()
    decision_materials, _ = decision_evidence()
    research = context(workers)
    materials = (
        ('design', WORK / 'protocols/design.md'), ('authorization', WORK / 'protocols/authorization.md'),
        ('configurations', WORK / 'protocols/configurations.json'),
        ('candidate-contracts', WORK / 'protocols/candidate_contracts.json'),
        ('definitions', WORK / 'protocols/definitions.json'), ('runner', Path(__file__)),
        ('precheck', WORK / 'others/precheck.json'), ('source', WORK / 'src/strategy.py'),
        ('precheck-source', WORK / 'src/precheck.py'), ('mechanism-source', WORK / 'src/check_mechanism.py'),
        ('data-readiness', DATA_READINESS),
    ) + decision_materials
    before = {name: material(research, name, path).to_dict() for name, path in materials}
    save(WORK / 'others/pre_run_evidence.json', before)
    requests = []
    for key, cand in definitions.items():
        requests.append(research.evaluation.prepare(request(cand)))
        print('PREPARED', key, flush=True)

    def progress(event):
        print(json.dumps(asdict(event), default=str), flush=True)

    with ResearchExecutionSession(research, experiment=EXPERIMENT,
            checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id, mode),
            on_progress=progress) as execution:
        outcomes = research.evaluation.evaluate_many(tuple(requests), execution=execution)
        statuses = [{'candidate': req.candidate.candidate_id, 'status': outcome.status.value,
                     'error': None if outcome.error is None else asdict(outcome.error)}
                    for req, outcome in zip(requests, outcomes, strict=True)]
        save(WORK / 'others/execution_status.json', statuses)
        save(WORK / 'others/execution_stats.json', asdict(execution.stats))
        if any(outcome.status.value != 'SUCCEEDED' for outcome in outcomes):
            raise RuntimeError(statuses)
        writes = tuple(EvaluationEvidenceWrite(EXPERIMENT, 'account-' + req.candidate.candidate_id,
            req, outcome.result) for req, outcome in zip(requests, outcomes, strict=True))
        publications = publish_evidence_many(research, writes, execution=execution)
        save(WORK / 'others/publication_status.json', [asdict(item) for item in publications])
        stats = asdict(execution.stats)
        save(WORK / 'others/execution_stats.json', stats)
        if any(item.status.value != 'PUBLISHED' for item in publications):
            raise RuntimeError('account publication failed; inspect publication_status.json')
        rows = {}
        for req, outcome, publication in zip(requests, outcomes, publications, strict=True):
            value = outcome.result.payload
            rows[req.candidate.candidate_id] = {
                'evidence': publication.reference.to_dict(), 'evaluation_identity': value['evaluation_identity'],
                'evaluation_id': value['evaluation_id'], 'request_hash': outcome.result.request_hash,
                'execution_status': outcome.status.value, 'publication_status': publication.status.value,
                'execution_stats': stats, 'candidate': value['runs']['candidate']['metrics'],
                'buy_hold': value['runs']['buy_hold']['metrics'],
            }
        save(WORK / 'others/accounts.json', rows)
        print('ACCOUNTS_PUBLISHED', sorted(rows), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='save exact fixed candidate definitions, without data evaluation')
    execute = commands.add_parser('run', help='evaluate and publish the prechecked fixed candidates')
    execute.add_argument('mode', choices=['CREATE', 'RESUME'])
    execute.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    if args.command == 'init':
        initialize()
    else:
        run(args.mode, args.workers)
