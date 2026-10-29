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
    intraday = ROOT / 'research/S017/experiments/EX011_20261029/protocols'
    crossday = ROOT / 'research/S017/experiments/EX015_20261029/protocols'
    if (set(values) != {'C0046'}
            or values['C0046'] != {'volume_gate': True, 'allow_overnight': True}
            or read(intraday / 'configurations.json')['C0037'] != {'volume_gate': True}
            or read(crossday / 'configurations.json')['C0044'] != {'allow_overnight': True}
            or contracts['C0046'] != read(intraday / 'candidate_contracts.json')['C0037']
            or contracts['C0046'] != read(crossday / 'candidate_contracts.json')['C0044']):
        raise ValueError('only the fixed high-opening-volume/overnight combination and unchanged input contract are allowed')
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
    """Bind all four observed corners; return the three direct account controls."""
    path = WORK / 'protocols/decision_evidence.json'
    value = read(path)
    if (value['schema'] != 's017-volume-overnight-interaction-decision-evidence/v1'
            or value['selection_status'] != 'ADAPTIVE_AFTER_SEEN_RESULTS'):
        raise ValueError('the fixed interaction selection must disclose already seen results')
    origins = {'C0013': ExperimentRef('S017', 'EX003_20261028'),
               'C0036': ExperimentRef('S017', 'EX011_20261029'),
               'C0037': ExperimentRef('S017', 'EX011_20261029'),
               'C0044': ExperimentRef('S017', 'EX015_20261029')}
    if set(value['accounts']) != set(origins):
        raise ValueError('decision evidence requires the four exact original account references')
    refs = {}
    for key, origin in origins.items():
        ref = EvidenceRef.from_dict(value['accounts'][key])
        original = EvidenceRef.from_dict(read(origin.resolve(ROOT) / 'others/accounts.json')[key]['evidence'])
        if ref != original or ref.experiment != origin:
            raise ValueError('decision evidence changed an original account reference')
        if sha256(ref.resolve(ROOT).read_bytes()).hexdigest() != ref.sha256:
            raise ValueError('decision account bytes changed after authentication')
        refs[key] = ref
    required = {
        'decision-volume-diagnosis': 'research/S017/experiments/EX011_20261029/others/diagnostics/C0037_vs_C0036.json',
        'decision-holding-diagnosis': 'research/S017/experiments/EX015_20261029/others/diagnostics/C0044_vs_C0036.json',
        'decision-volume-description': 'research/S017/experiments/EX015_20261029/others/entry_volume_description.json',
        'decision-volume-source': 'research/S017/experiments/EX015_20261029/src/describe_entry_volume.py'}
    if set(value['files']) != set(required) or set(value['diagnoses']) != {'C0037_vs_C0036', 'C0044_vs_C0036'}:
        raise ValueError('decision sources must include the fixed original diagnoses and adverse volume partition')
    materials = [('decision-evidence', path)]
    for name, relative in required.items():
        item = value['files'][name]
        file = ROOT / relative
        if item['path'] != relative or sha256(file.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('decision source bytes changed: ' + name)
        materials.append((name, file))
    for pair, material_name in (('C0037_vs_C0036', 'decision-volume-diagnosis'),
                                ('C0044_vs_C0036', 'decision-holding-diagnosis')):
        subject, control = pair.split('_vs_')
        origin = origins[subject]
        analysis = read(origin.resolve(ROOT) / 'others/analysis.json')
        reference = EvidenceRef.from_dict(value['diagnoses'][pair])
        raw = reference.resolve(ROOT).read_bytes()
        diagnosis = read(ROOT / required[material_name])
        if (analysis['status'] != 'PASS' or reference.experiment != origin
                or reference != EvidenceRef.from_dict(analysis['diagnostics'][pair]['evidence'])
                or sha256(raw).hexdigest() != reference.sha256
                or json.loads(raw) != diagnosis or diagnosis['status'] != 'COMPUTED'
                or diagnosis['issues']
                or diagnosis['sources'] != [asdict(refs[control]), asdict(refs[subject])]):
            raise ValueError('decision diagnosis is not the completed original account comparison')
    volume = read(ROOT / required['decision-volume-description'])
    if (volume['schema'] != 'S017_C0044_ACTUAL_ENTRY_VOLUME_DESCRIPTION_V1'
            or volume['status'] != 'PASS' or volume['description']['status'] != 'PASS'
            or volume['description']['totals']['closed_cycles'] != 368
            or volume['source_accounts'] != {key: refs[key].to_dict() for key in ('C0044', 'C0036', 'C0037')}
            or volume['script_sha256'] != value['files']['decision-volume-source']['sha256']):
        raise ValueError('decision volume partition does not bind the original adverse evidence')
    return tuple(materials), {key: refs[key] for key in ('C0013', 'C0037', 'C0044')}


def checked_precheck():
    checked = read(WORK / 'others/precheck.json')
    mechanism_path = WORK / 'others/precheck_mechanism.json'
    mechanism = read(mechanism_path)
    source_hash = sha256((WORK / 'src/strategy.py').read_bytes()).hexdigest()
    if (checked['status'] != 'PASS' or checked['strategy_source_sha256'] != source_hash
            or checked['precheck_source_sha256'] != sha256((WORK / 'src/precheck.py').read_bytes()).hexdigest()
            or checked['mechanism_evidence_sha256'] != sha256(mechanism_path.read_bytes()).hexdigest()
            or mechanism['status'] != 'PASS' or mechanism['strategy_source_sha256'] != source_hash
            or mechanism['check_source_sha256'] != sha256((WORK / 'src/check_mechanism.py').read_bytes()).hexdigest()):
        raise ValueError('both public and mechanism prechecks must authenticate the exact source')
    return checked


def run(mode='CREATE', workers=2):
    mode = CheckpointMode(mode)
    checked_precheck()
    definitions = initialize()
    decision_materials, _ = decision_evidence()
    research = context(workers)
    materials = (
        ('design', WORK / 'protocols/design.md'), ('authorization', WORK / 'protocols/authorization.md'),
        ('configurations', WORK / 'protocols/configurations.json'),
        ('candidate-contracts', WORK / 'protocols/candidate_contracts.json'),
        ('definitions', WORK / 'protocols/definitions.json'), ('runner', Path(__file__)),
        ('precheck', WORK / 'others/precheck.json'), ('source', WORK / 'src/strategy.py'),
        ('precheck-mechanism', WORK / 'others/precheck_mechanism.json'),
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
