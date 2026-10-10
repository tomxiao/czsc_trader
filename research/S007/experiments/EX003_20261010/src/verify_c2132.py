"""Reproduce the authenticated C2132 center without changing its configuration."""
from dataclasses import replace
from datetime import date
import importlib.util
from dataflows import Dataset, ProviderBinding, ProviderConfig
from strategy_manager import CandidateKey
from czsc_trader.application import (
    RepositoryContext, create_research_context, create_experiment, ExperimentRequest,
    publish_evidence, load_candidate,
)
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources, EvaluationEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from common import ROOT, PROTOCOLS, RUNS, forbidden, read, write, cache_read, material


def main():
    assert (PROTOCOLS/'plan_reference.json').exists()
    repository = RepositoryContext.discover(ROOT)
    bindings = {d: ProviderBinding(str(d), 'S013-stage4-existing-assets', forbidden) for d in
        (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY,
         Dataset.ETF_UNADJUSTED_INTRADAY)}
    research = create_research_context(repository, ResearchBatchRef('S013'),
        providers=ProviderConfig(bindings=bindings), resources=EvaluationResources(1, 1, 13))
    path = PROTOCOLS/'c2132_experiment.json'
    if path.exists():
        experiment = ExperimentRef.from_dict(read(path))
    else:
        experiment = create_experiment(research, ExperimentRequest(
            'C2132四维诊断中心复算', '核验四维诊断复用的原中心账户身份与完整经济事实。', date(2026, 10, 10)))
        write(path, experiment.to_dict())
    entry = next(x for x in read(ROOT/'research/S013/assets/runs/EX008_20261010/center_authentication.json')['centers']
                 if x['candidate']['key']['candidate_id'] == 'C2132')
    original_ref = EvidenceRef.from_dict(entry['formal_account'])
    original = read(original_ref.resolve(ROOT))
    validate_evaluation_evidence(original)
    old, previous = cache_read(ROOT / entry['cache'])
    loaded = load_candidate(repository, CandidateKey('S013', 'C2132'))
    identity = research.runtime.identify(loaded, dependencies=old.dependencies)
    assert identity.content_sha256 == entry['candidate']['content_sha256']
    assert identity.source_sha256 == entry['source_sha256']
    assert original['result_hash'] == previous.result_hash == entry['result_hash']
    assert original['request_hash'] == previous.request_hash == entry['request_hash']
    bound = research.evaluation.prepare(replace(old, experiment_id=experiment.experiment_id))
    result = research.evaluation.evaluate(bound)
    ref = publish_evidence(research, EvaluationEvidenceWrite(experiment, 'four-diagnostics-c2132-center', bound, result))
    file = ROOT/'research/S013/experiments/EX007_20261009/src/economic_equivalence.py'
    spec = importlib.util.spec_from_file_location('s013_economic_comparison', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    comparison = module.compare_evidence(original, serialize_evaluation_evidence(bound, result))
    proof = {'status': comparison['status'], 'original': original_ref.to_dict(),
             'reproduced': ref.to_dict(), 'content_sha256': identity.content_sha256,
             'source_sha256': identity.source_sha256, 'comparison': comparison,
             'net_cagr': result.runs[0].observation.net_cagr,
             'max_drawdown': result.runs[0].observation.max_drawdown}
    write(RUNS/'c2132_center_reproduction.json', proof)
    write(PROTOCOLS/'c2132_center_reference.json', material('four-diagnostics-c2132-reproduction-proof',
        RUNS/'c2132_center_reproduction.json').to_dict())
    print({'C2132': comparison['status'], 'net_cagr': proof['net_cagr'], 'evidence': ref.to_dict()}, flush=True)


if __name__ == '__main__':
    main()
