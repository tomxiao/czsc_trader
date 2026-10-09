"""S013 complete stage-four: public capabilities and authenticated source reuse."""
from pathlib import Path
from types import MappingProxyType
from dataclasses import replace
from importlib.metadata import version
import json
import gzip
import pickle
import copyreg
from dataflows import Dataset, ProviderBinding, ProviderConfig
from strategy_runtime import StrategyCandidate, ImplementationDependency
from strategy_manager import CandidateDerivation
from czsc_trader.application import RepositoryContext, create_research_context, load_candidate, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources, EvaluationCost, EvaluationLineage, MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_evaluator import AssessmentEvidence

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
EXPERIMENT = ExperimentRef('S013', SRC.parent.name)
RUNS = ROOT / 'research/S013/assets/runs' / EXPERIMENT.experiment_id
PROTOCOLS = SRC.parent / 'protocols'
REPORTS = SRC.parent / 'others'
CACHE = ROOT / '.tmp/s013-stage4-complete'
DEPENDENCIES = tuple(ImplementationDependency(x, version(x)) for x in ('numpy', 'pandas', 'czsc-strategy-runtime'))

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')

def forbidden(request):
    raise AssertionError('Only existing S013 formal assets are authorized: '+str(request))

def context(workers=4):
    bindings = {x: ProviderBinding(str(x), 'S013-stage4-existing-assets', forbidden) for x in
        (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)}
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S013'),
        providers=ProviderConfig(bindings=bindings), resources=EvaluationResources(workers, 1, 13))

def source(stage, revision):
    return d.DeliveryContent.from_dict(read(ROOT / f'research/S013/assets/deliveries/{stage}/{revision}/delivery.json')['content'])

def reference(stage, revision):
    return d.DeliveryReceipt.from_dict(read(ROOT / f'research/S013/deliveries/{stage}/{revision}/receipt.json')).reference

def centers():
    payload = source('CANDIDATES', 6).payload
    return tuple(e for e in payload.candidates if e.identity.key in payload.handoff)

def facts(ref):
    value = read(ref.resolve(ROOT))
    validate_evaluation_evidence(value)
    return tuple(AssessmentEvidence.from_dict(x) for x in value['assessment_evidence'])

def restore_mapping(value):
    return MappingProxyType(value)

# Identical local helper reducers from immutable EX004--EX007 caches.
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

def center_cache(identifier):
    if identifier.startswith('C90'):
        folder = 's013-contract-upgrade'
    elif identifier.startswith('C1'):
        folder = 's013-stage3-continuation'
    elif identifier.startswith('C2'):
        folder = 's013-buy-confirmation'
    elif identifier.startswith('C3'):
        folder = 's013-cost-confirmation'
    else:
        raise ValueError(identifier)
    return ROOT / '.tmp' / folder / (identifier+'.pkl.gz')

def material(name, path):
    path = Path(path)
    return publish_evidence(context(1), MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(),
        'application/json', path.suffix[1:]))

def request_for(case):
    parent = d.CandidateIdentityRef.from_dict(case['parent'])
    old, _ = cache_read(center_cache(parent.key.candidate_id))
    loaded = load_candidate(RepositoryContext.discover(ROOT), parent.key)
    identity = context(1).runtime.identify(loaded, dependencies=old.dependencies)
    assert identity.content_sha256 == parent.content_sha256
    payload = json.loads(json.dumps(dict(loaded.payload), default=dict))
    payload['parameters'] = case['parameters']
    child = StrategyCandidate('S013', case['candidate_id'], payload, source_root=loaded.source_root)
    new_identity = context(1).runtime.identify(child, dependencies=old.dependencies)
    assert new_identity.source_sha256 == identity.source_sha256 == case['parent_source_sha256']
    assert new_identity.content_sha256 == case['child_content_sha256']
    binding = dict(old.runtime_binding)
    binding['candidate_id'] = child.reference_id
    if case['kind'] == 'PARAMETERS':
        derivation = CandidateDerivation.from_dict(read(RUNS/'lineages.json')[case['candidate_id']])
        costs = (EvaluationCost('baseline', .001, 'FORMAL'),)
        lineage = EvaluationLineage(derivation)
    else:
        costs = tuple(EvaluationCost(k, v, 'STRESS') for k, v in read(PROTOCOLS/'plan.json')['cost_scenarios'].items())
        lineage = old.lineage
    return replace(old, strategy=child, runtime_binding=binding, experiment_id=EXPERIMENT.experiment_id,
        input_bindings={}, costs=costs, lineage=lineage)
