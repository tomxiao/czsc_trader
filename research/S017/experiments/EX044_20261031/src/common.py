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
    retained=read(ROOT/'research/S017/experiments/EX042_20261031/others/data_preparation.json')
    value=retained['reference'];prepared=PreparedDataRef(UUID(value['space_id']),UUID(value['preparation_id']),value['manifest_sha256'])
    if prepared.manifest_sha256!='a671f92acb0723e4054b26247bca52d39186c3a0f87e25e70a133b48987a242d':raise ValueError('Training preparation changed')
    save(WORK/'others/data_preparation.json',retained)
    return context(),prepared,None


def candidate(key):
    from strategy import feature_graph, state_schema
    from strategy_runtime import StateRecord
    if key not in PARAMETERS:
        raise ValueError('Only the declared new expression and technical control are allowed')
    source, files = WORK/'src', ('strategy.py',)
    definition = EquityStrategyDefinition(INSTRUMENT, SPEC, 261, 'strategy:step', files,
        equity_source_hash(source, files), json.dumps(PARAMETERS[key]), initial_account=StateRecord((('armed',False),)), contract_version=4,
        computation=StrategyComputation.STATEFUL_STEP, feature_graph=feature_graph(), state_schema=state_schema())
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
