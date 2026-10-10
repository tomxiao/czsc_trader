"""New bounded experiments reuse authenticated centers and public capabilities."""
# ruff: noqa: E402
from pathlib import Path
from dataclasses import replace
from functools import lru_cache
import json
import sys

ROOT = Path(__file__).resolve().parents[5]
OLD = ROOT/'research/S007/experiments/EX003_20261010'
sys.path.insert(0, str(OLD/'src'))
from common import read as read, write as write, cache_read as cache_read
from common import cache_write as cache_write, fingerprint as fingerprint, context as s007_context
from common import DEPENDENCIES as DEPENDENCIES, candidate as s007_candidate
from offline_inputs import supplier
from s013_existing_inputs import reader as s013_reader, supplier as s013_supplier
from czsc_trader.application import (
    RepositoryContext, create_research_context, load_candidate, publish_evidence,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, EvaluationResources, MaterialEvidenceWrite, EvidenceRef,
    EvaluationCost,
)
from czsc_trader.research_tools.context import ExperimentRef
from strategy_manager import CandidateKey
from strategy_runtime import StrategyCandidate
from dataflows import Dataset, ProviderBinding, ProviderConfig

EXPERIMENTS = {'S007': ExperimentRef('S007', 'EX004_20261010'),
               'S013': ExperimentRef('S013', 'EX010_20261010')}
BASE = ROOT/'research/S007/experiments/EX004_20261010'
PROTOCOLS = BASE/'protocols'
CACHE = ROOT/'.tmp/aligned-robustness'


def runs(strategy):
    ex = EXPERIMENTS[strategy]
    return ROOT/f'research/{strategy}/assets/runs/{ex.experiment_id}'


def forbidden(request):
    raise AssertionError('Only previously authenticated native assets authorized: '+str(request))


def context(strategy, workers=4):
    if strategy == 'S007':
        return s007_context(workers, supplier)
    s013_reader()  # Initialize the public reader before the writer's preparation transaction.
    providers = ProviderConfig(bindings={d: ProviderBinding(str(d),
        'S013-stage4-existing-assets', s013_supplier) for d in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
            Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)})
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef(strategy),
        providers=providers, resources=EvaluationResources(workers, 1, 13))


def material(name, path, strategy='S007', mime='application/json'):
    path = Path(path)
    return publish_evidence(context(strategy, 1), MaterialEvidenceWrite(EXPERIMENTS[strategy],
        name, path.read_bytes(), mime, path.suffix[1:]))


@lru_cache(maxsize=2)
def original(strategy):
    if strategy == 'S007':
        bound, result = cache_read(ROOT/'.tmp/s007-four-metrics/center.pkl.gz')
        ref = EvidenceRef.from_dict(read(ROOT/'research/S007/assets/runs/EX003_20261010/center_reference.json'))
    else:
        entry = next(x for x in read(ROOT/'research/S013/assets/runs/EX008_20261010/center_authentication.json')['centers']
                     if x['candidate']['key']['candidate_id'] == 'C2132')
        bound, result = cache_read(ROOT/entry['cache'])
        ref = EvidenceRef.from_dict(entry['formal_account'])
    assert read(ref.resolve(ROOT))['result_hash'] == result.result_hash
    return bound, result, ref


def candidate(strategy, identifier, parameters):
    if strategy == 'S007':
        return s007_candidate(identifier, parameters)
    loaded = load_candidate(RepositoryContext.discover(ROOT), CandidateKey('S013', 'C2132'))
    payload = json.loads(json.dumps(dict(loaded.payload), default=dict))
    payload['parameters'] = parameters
    return StrategyCandidate(strategy, identifier, payload, source_root=loaded.source_root)


def request(strategy, identifier, parameters):
    old, _, _ = original(strategy)
    child = candidate(strategy, identifier, parameters)
    return replace(old, experiment_id=EXPERIMENTS[strategy].experiment_id,
        strategy=child, runtime_binding={'candidate_id': child.reference_id,
            'source_files': list(child.payload['runtime']['source_files']),
            'implementation_sha256': child.payload['runtime']['source_sha256']},
        costs=(EvaluationCost('baseline', .001, 'FORMAL'),), lineage=None, input_bindings={})
