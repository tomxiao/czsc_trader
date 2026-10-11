"""Retain own native segment-context center; register only four-gate-qualified candidate."""
from czsc_trader.application import publish_evidence, register_candidate, load_candidate, CandidateRegistrationRequest
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import StrategyRuntime
from common import ROOT, PROTOCOLS, RUNS, CACHE, EXPERIMENT, DEPENDENCIES, context, read, write, cache_read, file_hash
from precheck import source_check


def main():
    plan = source_check()
    assert not (RUNS / 'account_references.json').exists()
    analysis = read(RUNS / 'analysis.json')
    assert analysis['status'] == 'PASS' and analysis['center_expectation']['status'] == 'PASS'
    ctx = context(1)
    refs = {label: EvidenceRef.from_dict(value['reference']) for label, value in analysis['control_reuse'].items()}
    assert set(refs) == {'B0-TIME', 'B0-COUPLED'}
    cfg, row = plan['configurations'][0], analysis['rows']['N0']
    bound, result = cache_read(CACHE / 'N0.pkl.gz')
    assert result.request_hash == row['request_hash'] and result.result_hash == row['result_hash']
    assert result.runs[0].identity.content_sha256 == cfg['content_sha256']
    ref = publish_evidence(ctx, EvaluationEvidenceWrite(EXPERIMENT, 'segment-context-native-center-n0', bound, result))
    refs['N0'] = ref
    registrations = []
    if row['qualified']:
        parent_ref = refs['B0-COUPLED']
        assert file_hash(parent_ref.resolve(ROOT)) == parent_ref.sha256
        parent_row = analysis['rows']['B0-COUPLED']
        assert parent_row['candidate_id'] == 'C4900' and parent_row['qualified']
        parent_key = CandidateKey('S013', 'C4900')
        assert StrategyRuntime().identify(load_candidate(ctx.repository, parent_key), dependencies=DEPENDENCIES).content_sha256 == parent_row['content_sha256']
        derivation = CandidateDerivation(parent_key, parent_row['content_sha256'], CandidateKey('S013', cfg['candidate_id']),
            cfg['content_sha256'], CandidateDerivationKind.IMPLEMENTATION,
            {'exit_category_context': {'before': 'Final bear TIME price category persists until any entry',
                'after': 'On flat rawbull, clear only category before current decision; final held bear TIME on rawbull stores no category'},
             'active_numeric_coordinates': 'All13 original domains/centers unchanged; actual confirmationL affects both score and strictpast bear ACF baseline',
             'preserved': 'CLOSE/BELOW direction, reason/route/score-context, original H/range/regime exit priorities, execution/cost/data/benchmark'},
            file_hash(PROTOCOLS / 'plan.json'), CandidateEvidence(parent_ref.repository_path, parent_ref.sha256))
        record = register_candidate(ctx.repository, CandidateRegistrationRequest(bound.strategy, EXPERIMENT, (ref,), DEPENDENCIES, derivation))
        assert StrategyRuntime().identify(load_candidate(ctx.repository, record.key), dependencies=DEPENDENCIES).content_sha256 == cfg['content_sha256']
        registrations.append(record.to_dict())
    write(RUNS / 'account_references.json', {label: ref.to_dict() for label, ref in refs.items()})
    write(RUNS / 'registration.json', {'status': 'PASS', 'registrations': registrations, 'new_qualified': len(registrations),
        'implementation_parent': 'C4900 qualifying nativecenter; no stage4selection/freeze/production'})
    print({'published_new_accounts': 1, 'qualified': len(registrations)}, flush=True)


if __name__ == '__main__':
    main()
