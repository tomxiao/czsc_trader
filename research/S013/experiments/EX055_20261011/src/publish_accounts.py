"""Retain own native consensus-acf state center; register only four-gate-qualified candidate."""
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
    assert set(refs) == {'B0-TIME', 'B0-COUPLED', 'B0-RAW-BODY'}
    cfg, row = plan['configurations'][0], analysis['rows']['N0']
    bound, result = cache_read(CACHE / 'N0.pkl.gz')
    assert result.request_hash == row['request_hash'] and result.result_hash == row['result_hash']
    assert result.runs[0].identity.content_sha256 == cfg['content_sha256']
    ref = publish_evidence(ctx, EvaluationEvidenceWrite(EXPERIMENT, 'raw-below-body-acf-recovery-native-center-n0', bound, result))
    refs['N0'] = ref
    registrations = []
    if row['qualified']:
        parent_ref = refs['B0-TIME']
        assert file_hash(parent_ref.resolve(ROOT)) == parent_ref.sha256
        parent_row = analysis['rows']['B0-TIME']
        assert parent_row['candidate_id'] == 'C2132' and parent_row['qualified']
        parent_key = CandidateKey('S013', 'C2132')
        assert StrategyRuntime().identify(load_candidate(ctx.repository, parent_key), dependencies=DEPENDENCIES).content_sha256 == parent_row['content_sha256']
        derivation = CandidateDerivation(parent_key, parent_row['content_sha256'], CandidateKey('S013', cfg['candidate_id']),
            cfg['content_sha256'], CandidateDerivationKind.IMPLEMENTATION,
            {'bear_reentry_gate': {'before': 'Original rawACF20 and confirmation, no conditional price-direction gate',
                'after': 'Only flat rawbear after finalbearTIME BELOW signal anchor and currentClose>Open recovers original ACF failure; original range/momentum and score still required, original ACFpassing opportunities unsuppressed, all holding rules unchanged'},
             'preserved': 'Original13 numeric centers/full domains/same32; all original rawACF/confirmation/state/range/H/exit/execution/data. Category is signal price, not actual netPnL. Fixed direction/category structures are not numerical32 robustness proof.'},
            file_hash(PROTOCOLS / 'plan.json'), CandidateEvidence(parent_ref.repository_path, parent_ref.sha256))
        record = register_candidate(ctx.repository, CandidateRegistrationRequest(bound.strategy, EXPERIMENT, (ref,), DEPENDENCIES, derivation))
        assert StrategyRuntime().identify(load_candidate(ctx.repository, record.key), dependencies=DEPENDENCIES).content_sha256 == cfg['content_sha256']
        registrations.append(record.to_dict())
    write(RUNS / 'account_references.json', {label: ref.to_dict() for label, ref in refs.items()})
    write(RUNS / 'registration.json', {'status': 'PASS', 'registrations': registrations, 'new_qualified': len(registrations),
        'implementation_parent': 'C2132 qualifying nativecenter; no stage4selection/freeze/production'})
    print({'published_new_accounts': 1, 'qualified': len(registrations)}, flush=True)


if __name__ == '__main__':
    main()
