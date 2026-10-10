"""Bounded S007-v1 diagnostics through the public research capabilities."""
from pathlib import Path
from datetime import date
from importlib.metadata import version
from copy import deepcopy
import json
from hashlib import sha256
from types import MappingProxyType
import gzip
import pickle
import copyreg

from dataflows import Dataset, ProviderBinding, ProviderConfig
from strategy_runtime import StrategyCandidate, ImplementationDependency, implementation_sha256
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import (
    ResearchBatchRef, EvaluationResources, EvaluationRequest, EvaluationWindow,
    EvaluationCost, EvaluationBenchmark, NextOpenBuyHold, MaterialEvidenceWrite,
)
from czsc_trader.research_tools.context import ExperimentRef

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
EXPERIMENT = ExperimentRef('S007', SRC.parent.name)
PROTOCOLS = SRC.parent / 'protocols'
OTHERS = SRC.parent / 'others'
RUNS = ROOT / 'research/S007/assets/runs' / EXPERIMENT.experiment_id
FROZEN_SOURCE = ROOT / 'strategies/S007/releases/v1/runtime/strategy_runtime'
SOURCE = SRC / 'strategy_runtime'
DEPENDENCIES = tuple(ImplementationDependency(x, version(x)) for x in
                     ('numpy', 'pandas', 'czsc-strategy-runtime'))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                    encoding='utf-8', newline='\n')


def fingerprint(path):
    path = Path(path)
    return {'path': path.relative_to(ROOT).as_posix(),
            'sha256': sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def restore_mapping(value):
    return MappingProxyType(value)


_mapping = restore_mapping


def reduce_mapping(value):
    return restore_mapping, (dict(value),)


def cache_read(path):
    with gzip.open(path, 'rb') as stream:
        return pickle.load(stream)


def cache_write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wb') as stream:
        writer = pickle.Pickler(stream, protocol=pickle.HIGHEST_PROTOCOL)
        writer.dispatch_table = {**copyreg.dispatch_table, MappingProxyType: reduce_mapping}
        writer.dump(value)


def payload():
    value = read(ROOT / 'strategies/S007/versions/v1.json')['strategy_payload']
    value['runtime']['module'] = 'strategy_runtime.strategies.s007_diagnostic'
    value['runtime']['qualname'] = 'S007Diagnostic'
    value['runtime']['source_files'].append('strategies/s007_diagnostic.py')
    value['runtime']['source_sha256'] = implementation_sha256(
        value['runtime']['source_files'], source_root=SOURCE)
    return value


def candidate(identifier='C9000', parameters=None):
    value = deepcopy(payload())
    if parameters is not None:
        value['parameters'] = parameters
    return StrategyCandidate('S007', identifier, value, source_root=SOURCE)


def forbidden(request):
    raise AssertionError('Only authenticated existing S007 inputs through 2026-09-02: '+str(request))


def context(workers=4, supplier=None):
    datasets = (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
                Dataset.STRATEGY_FEATURE_EVIDENCE)
    providers = ProviderConfig(bindings={d: ProviderBinding(
        's007-authenticated-development-inputs', 'EX003-v1', supplier or forbidden) for d in datasets})
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S007'),
        providers=providers, resources=EvaluationResources(workers, 1, 13))


def request(case=None, execution_data=None):
    strategy = candidate() if case is None else candidate(case['candidate_id'], case['parameters'])
    costs = (EvaluationCost('baseline', .001, 'FORMAL'),)
    if case is None:
        costs += (EvaluationCost('stress_20bp_per_side', .002, 'STRESS'),)
    return EvaluationRequest(ROOT, EXPERIMENT.experiment_id, strategy,
        {'candidate_id': strategy.reference_id,
         'source_files': list(strategy.payload['runtime']['source_files']),
         'implementation_sha256': strategy.payload['runtime']['source_sha256']},
        '588080.SH', 'etf', (EvaluationWindow('full', date(2021, 1, 5), date(2026, 9, 2)),),
        date(2026, 9, 2), 100_000., costs, execution_data=execution_data,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)), dependencies=DEPENDENCIES)


def material(name, path, mime='application/json'):
    path = Path(path)
    return publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT, name,
        path.read_bytes(), mime, path.suffix[1:]))
