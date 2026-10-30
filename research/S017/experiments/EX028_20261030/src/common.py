"""Public S017 context and retained-data access for EX028."""
# ruff: noqa: E402
import json
import os
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp/s017-research' / WORK.name
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(SCRATCH)
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'

from dataflows import (PreparedDataRef, ProviderConfig, TimeInterval, InstrumentId, MarketId,
    AssetClass, SourceRef, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery)
from strategy_runtime import (ResearchExecutionSpec, UsEquitySpec, AccountPolicy,
    CashAvailabilityPolicy, ExecutionResources, EquityStrategyDefinition, EquityStrategyCandidate,
    equity_source_hash)
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef,
    MaterialEvidenceWrite, EquityEvaluationRequest, EquitySources, EvaluationBenchmark, EquityBuyHold)

REPOSITORY = RepositoryContext.discover(ROOT)
BATCH = ResearchBatchRef('S017')
EXPERIMENT = ExperimentRef('S017', WORK.name)
NAMES = ('S017-M012', 'S017-M013', 'S017-M014')
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
SOURCE = SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028')
INSTRUMENT = InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE')
PREP = ROOT / 'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json'


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding='utf-8')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def authenticate(value):
    reference = EvidenceRef.from_dict(value)
    path = reference.resolve(ROOT)
    if digest(path) != reference.sha256:
        raise ValueError('Retained evidence changed')
    return path


def context(workers=2):
    return create_research_context(REPOSITORY, BATCH, providers=ProviderConfig(bindings={}),
        execution_spec=SPEC, resources=ExecutionResources(max_workers=workers,
            native_threads_per_worker=1, random_seed=17))


def prepared():
    value = read(PREP)['reference']
    if value['manifest_sha256'] != 'bdba8f6a3e9475ed62a3295bdcccd6bb2286f5e081ec44b79811c1bcb72dce93':
        raise ValueError('Original S017 preparation changed')
    return PreparedDataRef(UUID(value['space_id']), UUID(value['preparation_id']), value['manifest_sha256'])


def fetch():
    research = context()
    expected = {r['product']: r['sha256'] for r in read(PREP)['items']}
    frames, identities = {}, {}
    for product in EquityProduct:
        item = research.data.fetch(EquityDataRequest(INSTRUMENT, SOURCE,
            EquityQuery(product, date(2018, 11, 1), date(2025, 12, 31), BarFrequency.M30)), prepared=prepared())
        if not item.ready or item.identity.content_sha256 != expected[product.value]:
            raise ValueError('Prepared product unavailable or changed: ' + product.value)
        frames[product.name] = item.dataframe.reset_index(drop=True)
        identities[product.name] = {'rows': len(item.dataframe), 'sha256': item.identity.content_sha256}
    bars, constraints = frames['BARS'], frames['CONSTRAINTS']
    if (len(bars) != 23298 or not bars.BarStatus.eq('OBSERVED').all()
            or not bars.AvailableDate.eq(bars.Date).all() or not bars.Date.is_monotonic_increasing
            or bars.Date.duplicated().any() or not frames['ACTIONS'].Kind.eq('NONE').all()
            or not bars.BarStart.equals(constraints.Date) or not (constraints.AvailableDate <= constraints.Date).all()
            or not constraints.QuantityStep.eq(1).all() or not constraints.PriceTick.eq(.01).all()
            or bars.Date.dt.tz_convert('America/New_York').max().date() > date(2025, 12, 31)):
        raise ValueError('Prepared contract or authorized window changed')
    return bars, constraints, identities


def material(research, name, path):
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        {'.json': 'application/json', '.gz': 'application/gzip'}.get(path.suffix, 'text/plain'), path.suffix[1:]))


def candidate(key, parameters):
    if (parameters.get('entry_mechanism') not in NAMES or parameters.get('max_holding_bars') not in (6, 13)
            or set(parameters) != {'entry_mechanism', 'max_holding_bars'}):
        raise ValueError('Unapproved short-cycle prototype')
    source, files = WORK/'src', ('strategy.py',)
    definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, 'strategy:decide', files,
        equity_source_hash(source, files), json.dumps(parameters), feedback_mode='CONFIRMED_EXECUTION',
        session_context=False, auxiliary_inputs=())
    return EquityStrategyCandidate('S017', key, definition, source)


def request(cand):
    zone = ZoneInfo('America/New_York')
    return EquityEvaluationRequest(EXPERIMENT, cand,
        TimeInterval(datetime(2019, 1, 2, 9, 30, tzinfo=zone), datetime(2025, 12, 31, 16, tzinfo=zone)),
        date(2018, 11, 1), EquitySources(SOURCE, SOURCE, SOURCE, SOURCE), 100000., .001,
        prepared=prepared(), benchmark=EvaluationBenchmark(EquityBuyHold(SPEC)), window_id='DEV_2019_2025',
        scenario_id='STANDARD', measurement_tier='FORMAL', drawdown_basis='BAR_CLOSE',
        concentration_basis='MAX_SINGLE', frequency_window_days=60)
