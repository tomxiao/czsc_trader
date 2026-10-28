"""Fixed stage-two structure comparisons through formal public research APIs."""
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo
import json
import sys
from hashlib import sha256

from dataflows import PreparedDataRef, ProviderConfig, TimeInterval, InstrumentId, MarketId, AssetClass, SourceRef, BarFrequency
from strategy_runtime import EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash, ResearchExecutionSpec, UsEquitySpec, AccountPolicy, CashAvailabilityPolicy, ExecutionResources
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, publish_evidence_many
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, EquitySources, EquityEvaluationRequest, EquityBuyHold, EvaluationBenchmark, EvaluationEvidenceWrite, MaterialEvidenceWrite, ResearchExecutionSession, ExecutionCheckpointRequest, CheckpointMode

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENT = ExperimentRef('S017', 'EX005_20261028')
BATCH = ResearchBatchRef('S017')
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30, AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
RESOURCES = ExecutionResources(max_workers=3, native_threads_per_worker=1, random_seed=17)
SOURCE = SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028')
INSTRUMENT = InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2, default=str).encode('utf-8'))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def context():
    return create_research_context(REPOSITORY, BATCH, providers=ProviderConfig(bindings={}), execution_spec=SPEC, resources=RESOURCES)


def configurations():
    common = dict(entry_bars=260, exit_bars=26, atr_days=14, atr_multiple=3., stop_fraction=.10,
                  exit_mode='ATR_TRAIL', protect_gain_atr=2.)
    return {
        'C0027': {**common, 'initial_atr_multiple':1., 'profit_protection':False},
        'C0028': {**common, 'initial_atr_multiple':3., 'profit_protection':True},
        'C0029': {**common, 'initial_atr_multiple':1., 'profit_protection':True},
    }


def candidate(key, parameters):
    source = WORK/'src'
    files = ('strategy.py',)
    definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, 'strategy:decide', files,
        equity_source_hash(source, files), json.dumps(parameters), feedback_mode='CONFIRMED_EXECUTION')
    return EquityStrategyCandidate('S017', key, definition, source)


def request(cand, fee=.001, scenario='STANDARD'):
    old = read(ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json')['reference']
    prepared = PreparedDataRef(UUID(old['space_id']), UUID(old['preparation_id']), old['manifest_sha256'])
    tz = ZoneInfo('America/New_York')
    window = TimeInterval(datetime(2019,1,2,9,30,tzinfo=tz), datetime(2025,12,31,16,tzinfo=tz))
    return EquityEvaluationRequest(EXPERIMENT, cand, window, date(2018,11,1), EquitySources(SOURCE,SOURCE,SOURCE,SOURCE),
        100000., fee, prepared=prepared, benchmark=EvaluationBenchmark(EquityBuyHold(SPEC)),
        window_id='DEV_2019_2025', scenario_id=scenario, measurement_tier='STRESS' if fee > .001 else 'FORMAL',
        drawdown_basis='BAR_CLOSE', concentration_basis='MAX_SINGLE', frequency_window_days=60)


def material(research, name, path):
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        'application/json' if path.suffix == '.json' else 'text/plain', path.suffix[1:]))


def run(mode='CREATE'):
    checked = read(WORK/'others/precheck.json')
    if checked['status'] != 'PASS' or checked['strategy_source_sha256'] != sha256((WORK/'src/strategy.py').read_bytes()).hexdigest():
        raise ValueError('focused checks must pass for the exact strategy source before account replay')
    research = context()
    configs = configurations()
    definitions = {key: candidate(key, value) for key, value in configs.items()}
    save(WORK/'protocols/definitions.json', {k: c.definition.to_dict() for k,c in definitions.items()})
    before = {name: material(research, name, path).to_dict() for name,path in (
        ('design', WORK/'protocols/design.md'), ('source', WORK/'src/strategy.py'),
        ('definitions', WORK/'protocols/definitions.json'), ('runner', Path(__file__)),
        ('authorization', WORK/'protocols/authorization.md')) }
    save(WORK/'others/pre_run_evidence.json', before)
    requests = []
    for key,cand in definitions.items():
        requests.append(research.evaluation.prepare(request(cand)))
        print('PREPARED', key, flush=True)
    def progress(event):
        print(json.dumps(asdict(event), default=str), flush=True)
    with ResearchExecutionSession(research, experiment=EXPERIMENT,
            checkpoint=ExecutionCheckpointRequest('trend-risk-floor-v1', CheckpointMode(mode)), on_progress=progress) as execution:
        outcomes = research.evaluation.evaluate_many(tuple(requests), execution=execution)
        status = [{'candidate': r.candidate.candidate_id, 'status': o.status.value, 'error': None if o.error is None else asdict(o.error)} for r,o in zip(requests,outcomes)]
        save(WORK/'others/execution_status.json', status)
        if any(o.status.value != 'SUCCEEDED' for o in outcomes):
            raise RuntimeError(status)
        writes = tuple(EvaluationEvidenceWrite(EXPERIMENT, 'account-'+r.candidate.candidate_id, r, o.result) for r,o in zip(requests,outcomes))
        publications = publish_evidence_many(research, writes, execution=execution)
        if any(p.status.value != 'PUBLISHED' for p in publications):
            save(WORK/'others/publication_errors.json', [asdict(p) for p in publications])
            raise RuntimeError('account publication failed')
        rows = {}
        for r,o,p in zip(requests,outcomes,publications):
            value = o.result.payload
            rows[r.candidate.candidate_id] = {'evidence': p.reference.to_dict(), 'evaluation_identity': value['evaluation_identity'],
                'evaluation_id': value['evaluation_id'], 'request_hash': o.result.request_hash,
                'candidate': value['runs']['candidate']['metrics'], 'buy_hold': value['runs']['buy_hold']['metrics']}
        save(WORK/'others/accounts.json', rows)
        save(WORK/'others/execution_stats.json', asdict(execution.stats))
        print(json.dumps({k: {x:v['candidate'][x] for x in ('annualized_return','bar_max_drawdown','closed_cycles','rolling_60_closed_cycle_median','fees')} for k,v in rows.items()}), flush=True)


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv)>1 else 'CREATE')
