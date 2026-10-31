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
    EquityStrategyCandidate, equity_source_hash, StrategyComputation, EquityAuxiliaryInput)
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
MARKET_INSTRUMENT=InstrumentId(MarketId.US,AssetClass.ETF,'SPY')
MARKET_SOURCE=SourceRef('futu','s017-auxiliary-rth-raw-v1-20261029')
MARKET_INPUT=EquityAuxiliaryInput('market',MARKET_INSTRUMENT,MARKET_SOURCE,BarFrequency.DAILY,20,432000)
PARAMETERS = json.loads((WORK/'protocols/configurations.json').read_bytes())


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


def prepare_data():
    retained=read(ROOT/'research/S017/experiments/EX042_20261031/others/data_preparation.json');v=retained['reference'];main_prepared=PreparedDataRef(UUID(v['space_id']),UUID(v['preparation_id']),v['manifest_sha256'])
    expected={i['product']:i['sha256'] for i in retained['status']['items']};first,last=date(2023,11,1),date(2025,12,31);frames={};metadata={};requests=[];old=context()
    for product in EquityProduct:
        source=RULE_SOURCE if product is EquityProduct.CONSTRAINTS else SOURCE;request=EquityDataRequest(INSTRUMENT,source,EquityQuery(product,first,last,BarFrequency.M30));value=old.data.fetch(request,prepared=main_prepared)
        if not value.ready or value.identity.content_sha256!=expected[product.value]:raise ValueError('Main training cached product changed')
        key=(INSTRUMENT,source,product,BarFrequency.M30);frames[key]=pd.DataFrame(value.dataframe,copy=True);metadata[key]=copy.deepcopy(dict(value.identity.metadata));requests.append(request)
    cache=authenticate(read(WORK/'protocols/spy_cache_reference.json')['reference'])
    if digest(cache)!='75a96386cf19585c60cdb1800bca83b794042cf3ca3e701e76dd578be4d89d32':raise ValueError('Retained auxiliary cache changed')
    aux=read(cache)
    for product in (EquityProduct.BARS,EquityProduct.SESSIONS):
        row=aux[product.name];frame=pd.DataFrame(row['records'],copy=True)
        for field in ('Date','AvailableDate','BarStart'):
            if field in frame:frame[field]=pd.to_datetime(frame[field],utc=True)
        meta=copy.deepcopy(row['metadata']);meta['coverage_start']=first.isoformat();meta['coverage_end']=last.isoformat();meta['sessions']=[x for x in meta['sessions'] if first.isoformat()<=x['session_date']<=last.isoformat()]
        for field in ('research_bar_policy','download_receipts','download_complete'):meta.pop(field,None)
        evidence='Exact previously cached S017 SPY RAW slice, parent='+row['parent_content_sha256']+'; inherited timing/observation assumptions, zero new downloads or historical-verification upgrade'
        meta.update(observation_contract='EXPLICIT_SOURCE_OBSERVATIONS_V1',coverage_evidence=evidence,coverage_evidence_sha256=sha256(evidence.encode()).hexdigest(),cached_subset_only=True,parent_content_sha256=row['parent_content_sha256'])
        key=(MARKET_INSTRUMENT,MARKET_SOURCE,product,BarFrequency.DAILY);frames[key]=frame;metadata[key]=meta;requests.append(EquityDataRequest(MARKET_INSTRUMENT,MARKET_SOURCE,EquityQuery(product,first,last,BarFrequency.DAILY)))
    def fetch(request):
        p=request.parameters;key=(p.instrument,p.source,p.query.product,p.query.frequency)
        if p.query.start!=first or p.query.end!=last or key not in frames:raise ValueError('Only approved cached main/aux exact window')
        return pd.DataFrame(frames[key],copy=True),copy.deepcopy(metadata[key])
    bindings={ProviderKey(product,instrument.market,source):ProviderBinding(source.provider,source.revision,fetch) for instrument,source,product,freq in frames}
    research=context(bindings=bindings);prepared=research.data.prepare(tuple(requests),policy=PreparePolicy.REUSE);items=[]
    for item in prepared.items:
        p=item.request.parameters;items.append({'symbol':p.instrument.symbol,'product':p.query.product.value,'status':item.status.value,'sha256':None if item.identity is None else item.identity.content_sha256,'error':None if item.error is None else {'code':item.error.code,'message':item.error.message,'context':dict(item.error.context)}})
        if item.identity is not None and p.instrument==INSTRUMENT and item.identity.content_sha256!=expected[p.query.product.value]:raise ValueError('Joint prep changed main content')
    save(WORK/'others/data_preparation_status.json',{'status':prepared.status.value,'items':items})
    if not prepared.ready:raise ValueError('Joint cached training preparation not ready')
    reference={k:str(v) for k,v in asdict(prepared.reference).items()};save(WORK/'others/data_preparation.json',{'reference':reference,'parent_main_reference':retained['reference'],'parent_main_sha256':expected,'auxiliary_source':asdict(MARKET_SOURCE),'auxiliary_parent_prepared':{'space_id':'a50f7929-988e-4650-af5c-5baee1cd84eb','preparation_id':'b137fb0b-30bb-4a71-9531-121a367a13dc','manifest_sha256':'e68686001b9286651b40a797c77d54efc4d12e08b27dd097d31dccdc7fd20d2a'},'auxiliary_cache_sha256':digest(cache),'new_external_downloads':0,'warmup_start':first.isoformat(),'last_date':last.isoformat(),'status':{'status':prepared.status.value,'items':items},'limitations':'Same inherited RAW daily timing/observation assumptions, metadata provenance projection only; main contents unchanged, no test data or source-completeness upgrade'})
    return research,prepared.reference,None


def candidate(key):
    from strategy import feature_graph, state_schema
    if key not in PARAMETERS:
        raise ValueError('Only the declared new expression and technical control are allowed')
    source, files = WORK/'src', ('strategy.py',)
    definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 273, 'strategy:step', files,
        equity_source_hash(source, files), json.dumps(PARAMETERS[key]), contract_version=4,
        computation=StrategyComputation.STATEFUL_STEP, feature_graph=feature_graph(), state_schema=state_schema(), auxiliary_inputs=(MARKET_INPUT,))
    return EquityStrategyCandidate('S017', key, definition, source)


def request(cand, prepared):
    zone = ZoneInfo('America/New_York')
    return EquityEvaluationRequest(EXPERIMENT, cand,
        TimeInterval(datetime(2024, 1, 2, 9, 30, tzinfo=zone), datetime(2025, 12, 31, 16, tzinfo=zone)),
        date(2023, 11, 1), EquitySources(SOURCE, SOURCE, SOURCE, RULE_SOURCE), 100000., .001,
        prepared=prepared, benchmark=EvaluationBenchmark(EquityBuyHold(SPEC)), window_id='TRAIN_2024_2025',
        scenario_id='STANDARD', measurement_tier='FORMAL', drawdown_basis='BAR_CLOSE',
        concentration_basis='MAX_SINGLE', frequency_window_days=60)


def material(research, name, path):
    return publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        {'.json': 'application/json', '.md': 'text/markdown', '.py': 'text/x-python', '.png': 'image/png', '.gz': 'application/gzip'}[path.suffix], path.suffix[1:]))
