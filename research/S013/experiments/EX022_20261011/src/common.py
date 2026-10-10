"""S013-only public capabilities and persisted reproduction for the approved matrix."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
import copyreg
import gzip
import json
import os
import pickle

from dataflows import Dataset, ProviderBinding, ProviderConfig
from strategy_runtime import StrategyCandidate, ImplementationDependency
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import (
    ResearchBatchRef, EvaluationResources, EvaluationRequest, EvaluationWindow,
    EvaluationCost, EvaluationBenchmark, LimitBuyHold, ExecutionPriceBasis,
)
from czsc_trader.research_tools.context import ExperimentRef

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
EXPERIMENT = ExperimentRef('S013', SRC.parent.name)
SOURCE = SRC / 'strategy_runtime'
PROTOCOLS = SRC.parent / 'protocols'
RUNS = ROOT / 'research/S013/assets/runs' / EXPERIMENT.experiment_id
CACHE = ROOT / '.tmp/s013-mechanism-EX022'
WORKERS = max(1, (os.cpu_count() or 1)//2)
DEPENDENCIES = tuple(ImplementationDependency(x, version(x))
    for x in ('numpy', 'pandas', 'czsc-strategy-runtime'))
SOURCE_CALLS = []

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                    encoding='utf-8', newline='\n')

def forbidden(request):
    SOURCE_CALLS.append(str(request))
    raise RuntimeError('Only existing S013 formal assets authorized: '+str(request))

def context(workers=WORKERS):
    bindings = {x: ProviderBinding(str(x), 'S013-EX022-existing-only', forbidden)
        for x in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                  Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)}
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S013'),
        providers=ProviderConfig(bindings=bindings), resources=EvaluationResources(workers, 1, 13))

def benchmark():
    return EvaluationBenchmark(LimitBuyHold(lot_size=100, premium=.01, price_tick=.001,
        price_limit_ratio=.1, maximum_order_quantity=1_000_000))

def candidate(config):
    source = SRC/config['source_directory'] if 'source_directory' in config else SOURCE
    return StrategyCandidate('S013', config['candidate_id'], config['payload'], source)

def request(config):
    strategy = candidate(config)
    return EvaluationRequest(ROOT, EXPERIMENT.experiment_id, strategy,
        {'candidate_id': strategy.reference_id,
         'source_files': list(strategy.payload['runtime']['source_files']),
         'implementation_sha256': strategy.payload['runtime']['source_sha256']},
        '510500.SH', 'etf', (EvaluationWindow('full', date(2020, 1, 2), date(2026, 9, 30)),),
        date(2026, 9, 30), 1_000_000, (EvaluationCost('baseline', .001, 'FORMAL'),),
        benchmark=benchmark(), workers=1, frequency_window_days=60, execution_mode='FULL',
        dependencies=DEPENDENCIES, price_basis=ExecutionPriceBasis.HFQ_RESEARCH)

def restore_mapping(value):
    return MappingProxyType(value)

def reduce_mapping(value):
    return restore_mapping, (dict(value),)

def cache_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wb') as stream:
        writer = pickle.Pickler(stream, protocol=pickle.HIGHEST_PROTOCOL)
        writer.dispatch_table = {**copyreg.dispatch_table, MappingProxyType: reduce_mapping}
        writer.dump(value)

def cache_read(path):
    with gzip.open(path, 'rb') as stream:
        return pickle.load(stream)

def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()
