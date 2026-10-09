"""S013 EX005: public batch capability, authenticated candidates, bounded data."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import copyreg
import gzip
import json
import pickle
from types import MappingProxyType

from dataflows import Dataset, ProviderBinding, ProviderConfig
from strategy_runtime import StrategyCandidate, implementation_sha256, ImplementationDependency
from czsc_trader.application import RepositoryContext, create_research_context, load_candidate
from czsc_trader.research_tools import (
    ResearchBatchRef, EvaluationResources, EvaluationRequest, EvaluationWindow,
    EvaluationCost, EvaluationBenchmark, NextOpenBuyHold, ExecutionPriceBasis,
)
from czsc_trader.research_tools.context import ExperimentRef
from strategy_manager import CandidateKey

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
EXPERIMENT = ExperimentRef('S013', SRC.parent.name)
SOURCE = SRC / 'strategy_runtime'
FILES = ('strategies/stable_range.py', 'strategies/adaptive_range.py',
         'strategies/range_reversion.py')
RUNS = ROOT / 'research/S013/assets/runs' / EXPERIMENT.experiment_id
PROTOCOLS = SRC.parent / 'protocols'
CACHE = ROOT / '.tmp/s013-stage3-continuation'
DEPENDENCIES = tuple(ImplementationDependency(name, version(name))
                     for name in ('numpy', 'pandas', 'czsc-strategy-runtime'))
SOURCE_CALLS = []


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8', newline='\n')


def forbidden_source(request):
    SOURCE_CALLS.append(str(request))
    raise AssertionError('S013 continuation may only reuse its existing formal assets')


def context(workers=4):
    bindings = {dataset: ProviderBinding(str(dataset), 'S013-stage3-continuation', forbidden_source)
                for dataset in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                                Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)}
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S013'),
        providers=ProviderConfig(bindings=bindings),
        resources=EvaluationResources(workers, 1, 13))


def parent_parameters(identifier='C9023'):
    candidate = load_candidate(RepositoryContext.discover(ROOT), CandidateKey('S013', identifier))
    return json.loads(json.dumps(dict(candidate.payload['parameters']), default=dict))


def candidate(identifier, parameters):
    return StrategyCandidate('S013', identifier, {
        'runtime': {'module': 'strategy_runtime.strategies.stable_range',
                    'qualname': 'StableRange', 'contract_version': 1,
                    'source_files': list(FILES),
                    'source_sha256': implementation_sha256(FILES, source_root=SOURCE)},
        'parameters': parameters}, source_root=SOURCE)


def request(identifier, parameters, execution_data=None, *, costs=None):
    strategy = candidate(identifier, parameters)
    return EvaluationRequest(ROOT, EXPERIMENT.experiment_id, strategy,
        {'candidate_id': strategy.reference_id, 'source_files': list(FILES),
         'implementation_sha256': strategy.payload['runtime']['source_sha256']},
        '510500.SH', 'etf', (EvaluationWindow('full', date(2020, 1, 2), date(2026, 9, 30)),),
        date(2026, 9, 30), 1_000_000,
        costs if costs is not None else (EvaluationCost('baseline', .001, 'FORMAL'),),
        execution_data=execution_data, benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),
        workers=1, frequency_window_days=60, execution_mode='FULL',
        dependencies=DEPENDENCIES, price_basis=ExecutionPriceBasis.HFQ_RESEARCH)


def config_hash(parameters):
    return sha256(json.dumps(parameters, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def restore_mapping(value):
    return MappingProxyType(value)


def reduce_mapping(value):
    return restore_mapping, (dict(value),)


def cache_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wb') as handle:
        writer = pickle.Pickler(handle, protocol=pickle.HIGHEST_PROTOCOL)
        writer.dispatch_table = {**copyreg.dispatch_table, MappingProxyType: reduce_mapping}
        writer.dump(value)


def cache_read(path):
    with gzip.open(path, 'rb') as handle:
        return pickle.load(handle)
