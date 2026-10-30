"""S017 public contexts and explicitly versioned same-contract V4 rules."""
# ruff: noqa: E402
import copy
from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp/s017-research' / WORK.name
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(SCRATCH)
os.environ['MPLCONFIGDIR'] = str(SCRATCH / 'matplotlib')
for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import pandas as pd
from dataflows import (PreparedDataRef, ProviderConfig, ProviderKey, ProviderBinding,
    TimeInterval, InstrumentId, MarketId, AssetClass, SourceRef, BarFrequency,
    EquityDataRequest, EquityProduct, EquityQuery, PreparePolicy)
from strategy_runtime import (ResearchExecutionSpec, UsEquitySpec, AccountPolicy,
    CashAvailabilityPolicy, ExecutionResources, EquityStrategyDefinition,
    EquityStrategyCandidate, equity_source_hash, StrategyComputation)
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef,
    MaterialEvidenceWrite, EquityEvaluationRequest, EquitySources, EvaluationBenchmark, EquityBuyHold)

REPOSITORY = RepositoryContext.discover(ROOT)
BATCH = ResearchBatchRef('S017')
EXPERIMENT = ExperimentRef('S017', WORK.name)
SPEC = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
    AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
SOURCE = SourceRef('futu', 's017-development-gap-known-interruptions-v1-20261028')
RULE_SOURCE = SourceRef('s017-research-rules', 'same-approved-us-assumptions-v4-ex032-v1')
INSTRUMENT = InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE')
PREP = ROOT / 'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json'
PARAMETERS = {'C0061': {'entry_mechanism': 'S017-M008', 'max_holding_bars': 65},
              'C0062': {'entry_mechanism': 'S017-M005', 'max_holding_bars': 65}}


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False),
                    encoding='utf-8', newline='\n')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def authenticate(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != 'S017':
        raise ValueError('Cross-batch evidence refused')
    path = ref.resolve(ROOT)
    if digest(path) != ref.sha256:
        raise ValueError('Evidence changed during read')
    return path


def context(workers=2, bindings=None):
    return create_research_context(REPOSITORY, BATCH,
        providers=ProviderConfig(bindings={}, equity_bindings={} if bindings is None else bindings),
        execution_spec=SPEC, resources=ExecutionResources(workers, 1, 17))


def original_products():
    reference = read(PREP)['reference']
    if reference['manifest_sha256'] != 'bdba8f6a3e9475ed62a3295bdcccd6bb2286f5e081ec44b79811c1bcb72dce93':
        raise ValueError('Original preparation changed')
    prepared = PreparedDataRef(UUID(reference['space_id']), UUID(reference['preparation_id']), reference['manifest_sha256'])
    expected = {r['product']: r['sha256'] for r in read(PREP)['items']}
    research = context()
    products = {}
    for product in EquityProduct:
        result = research.data.fetch(EquityDataRequest(INSTRUMENT, SOURCE,
            EquityQuery(product, date(2018, 11, 1), date(2025, 12, 31), BarFrequency.M30)), prepared=prepared)
        if not result.ready or result.identity.content_sha256 != expected[product.value]:
            raise ValueError('Original product unavailable or changed: ' + product.value)
        products[product.name] = result
    bars, constraints = products['BARS'].dataframe, products['CONSTRAINTS'].dataframe
    if (len(bars) != 23298 or not bars.BarStatus.eq('OBSERVED').all()
            or not bars.AvailableDate.eq(bars.Date).all() or not bars.Date.is_monotonic_increasing
            or bars.Date.duplicated().any() or not products['ACTIONS'].dataframe.Kind.eq('NONE').all()
            or not bars.BarStart.equals(constraints.Date) or not (constraints.AvailableDate <= constraints.Date).all()
            or not constraints.QuantityStep.eq(1).all() or not constraints.PriceTick.eq(.01).all()
            or bars.Date.dt.tz_convert('America/New_York').max().date() > date(2025, 12, 31)):
        raise ValueError('Original economic assumptions or authorized window changed')
    return products


def explicit_rules(frame):
    result = pd.DataFrame(frame, copy=True)
    result['PriceLimitPolicy'] = 'EXPLICIT_UNBOUNDED'
    result['PriceLimitLower'], result['PriceLimitUpper'] = None, None
    result['BuySellableAt'] = result.Date
    result['SellRemainderPolicy'] = 'STRICT_STEP'
    result['SettlementAt'] = result.Date
    return result


def prepare_data():
    products = original_products()
    frames = {name: pd.DataFrame(value.dataframe, copy=True) for name, value in products.items()}
    frames['CONSTRAINTS'] = explicit_rules(frames['CONSTRAINTS'])
    meta = {name: copy.deepcopy(dict(value.identity.metadata)) for name, value in products.items()}
    meta['CONSTRAINTS'].update(vendor=RULE_SOURCE.provider, source_revision=RULE_SOURCE.revision,
        constraint_contract='DATED_EQUITY_RULES_V1',
        rule_basis='EXPLICIT_EXISTING_RESEARCH_ASSUMPTIONS_NOT_HISTORICAL_BROKER_FACTS',
        immediate_time_basis='INTERVAL_START_RESEARCH_ASSUMPTION_NOT_REAL_SETTLEMENT',
        parent_source=asdict(SOURCE), parent_content_sha256=products['CONSTRAINTS'].identity.content_sha256,
        derivation_source_sha256=digest(WORK/'src/common.py'))

    def fetch(request):
        p = request.parameters
        expected_source = RULE_SOURCE if p.query.product is EquityProduct.CONSTRAINTS else SOURCE
        if (p.instrument != INSTRUMENT or p.source != expected_source or p.query.frequency is not BarFrequency.M30
                or p.query.start != date(2018, 11, 1) or p.query.end != date(2025, 12, 31)):
            raise ValueError('Retained provider only serves the exact authorized preparation')
        return pd.DataFrame(frames[p.query.product.name], copy=True), copy.deepcopy(meta[p.query.product.name])

    bindings = {}
    requests = []
    for product in EquityProduct:
        source = RULE_SOURCE if product is EquityProduct.CONSTRAINTS else SOURCE
        bindings[ProviderKey(product, MarketId.US, source)] = ProviderBinding(source.provider, source.revision, fetch)
        requests.append(EquityDataRequest(INSTRUMENT, source,
            EquityQuery(product, date(2018, 11, 1), date(2025, 12, 31), BarFrequency.M30)))
    research = context(bindings=bindings)
    prepared = research.data.prepare(tuple(requests), policy=PreparePolicy.REUSE)
    status = {'status': prepared.status.value, 'items': [
        {'product': item.request.parameters.query.product.value, 'status': item.status.value,
         'error': None if item.error is None else asdict(item.error),
         'sha256': None if item.identity is None else item.identity.content_sha256} for item in prepared.items]}
    save(WORK/'others/data_preparation_status.json', status)
    if not prepared.ready:
        raise ValueError('V4 explicit preparation incomplete; no account may run')
    source_hashes = {name: value.identity.content_sha256 for name, value in products.items()}
    for item in prepared.items:
        name = item.request.parameters.query.product.name
        if name != 'CONSTRAINTS' and item.identity.content_sha256 != source_hashes[name]:
            raise ValueError('Primary historical source changed: ' + name)
    value = asdict(prepared.reference)
    value = {k: str(v) for k, v in value.items()}
    save(WORK/'others/data_preparation.json', {'reference': value, 'original_reference': read(PREP)['reference'],
        'original_product_sha256': source_hashes, 'status': status,
        'new_constraints_source': asdict(RULE_SOURCE), 'new_external_downloads': 0,
        'rule_semantics': 'Explicit representation of the previously approved full-cash US research model; no new historical evidence attestation.'})
    return research, prepared.reference, products


def candidate(key):
    from strategy import feature_graph, state_schema
    if key not in PARAMETERS:
        raise ValueError('Only the declared new expression and technical control are allowed')
    source, files = WORK/'src', ('strategy.py',)
    definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, 'strategy:step', files,
        equity_source_hash(source, files), json.dumps(PARAMETERS[key]), contract_version=4,
        computation=StrategyComputation.STATEFUL_STEP, feature_graph=feature_graph(), state_schema=state_schema())
    return EquityStrategyCandidate('S017', key, definition, source)


def request(cand, prepared):
    zone = ZoneInfo('America/New_York')
    return EquityEvaluationRequest(EXPERIMENT, cand,
        TimeInterval(datetime(2019, 1, 2, 9, 30, tzinfo=zone), datetime(2025, 12, 31, 16, tzinfo=zone)),
        date(2018, 11, 1), EquitySources(SOURCE, SOURCE, SOURCE, RULE_SOURCE), 100000., .001,
        prepared=prepared, benchmark=EvaluationBenchmark(EquityBuyHold(SPEC)), window_id='DEV_2019_2025',
        scenario_id='STANDARD', measurement_tier='FORMAL', drawdown_basis='BAR_CLOSE',
        concentration_basis='MAX_SINGLE', frequency_window_days=60)


def material(research, name, path):
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        {'.json': 'application/json', '.md': 'text/markdown', '.py': 'text/x-python', '.png': 'image/png', '.gz': 'application/gzip'}[path.suffix], path.suffix[1:]))
