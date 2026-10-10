"""Retain two complete accounts; register only original-four-gate qualifiers."""
from czsc_trader.application import (
    publish_evidence, register_candidate, load_candidate, CandidateRegistrationRequest,
)
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import StrategyRuntime
from common import ROOT, PROTOCOLS, RUNS, CACHE, EXPERIMENT, DEPENDENCIES, context, read, write, cache_read, file_hash


GATES = {'return', 'annual_drawdown', 'frequency', 'negative_buyhold_year_profit'}


def main():
    assert not (RUNS / 'account_references.json').exists()
    analysis, plan = read(RUNS / 'analysis.json'), read(PROTOCOLS / 'plan.json')
    assert analysis['status'] == 'PASS'
    assert analysis['new_business_configurations'] == 4 and analysis['new_account_evaluations'] == 5
    assert analysis['historical_controls_reused'] == 4
    ctx = context(1)
    refs = {label: EvidenceRef.from_dict(value['reference']) for label, value in analysis['control_reuse'].items()}
    assert set(refs) == {'B0-TIME', 'B0-MEAN', 'B0-TIME-CLOSE', 'B0-TIME-BODY'}
    origin, original_ref = analysis['rows']['B0-TIME'], refs['B0-TIME']
    assert origin['candidate_id'] == 'C2132' and origin['qualified'] and all(origin['gates'].values())
    assert file_hash(original_ref.resolve(ROOT)) == original_ref.sha256
    original_key = CandidateKey('S013', 'C2132')
    registered_original = load_candidate(ctx.repository, original_key)
    assert StrategyRuntime().identify(registered_original, dependencies=DEPENDENCIES).content_sha256 == origin['content_sha256']
    registrations = []
    for cfg in plan['configurations']:
        label, row = cfg['label'], analysis['rows'][cfg['label']]
        assert set(row['gates']) == GATES and row['qualified'] == all(row['gates'].values())
        bound, result = cache_read(CACHE / (label + '.pkl.gz'))
        assert bound.strategy.candidate_id == cfg['candidate_id']
        assert result.request_hash == row['request_hash'] and result.result_hash == row['result_hash']
        assert result.runs[0].identity.content_sha256 == cfg['content_sha256'] == row['content_sha256']
        ref = publish_evidence(ctx, EvaluationEvidenceWrite(EXPERIMENT, 'bear-time-category-reentry-' + label.lower(), bound, result))
        refs[label] = ref
        if not row['qualified']:
            continue
        parent = refs[cfg['parent_control']]
        assert file_hash(parent.resolve(ROOT)) == parent.sha256
        # Unqualified MEAN is an intermediate background evidence, never a registry parent.
        background = analysis['rows'][cfg['parent_control']]
        change = {'before': background['mechanism'], 'after': cfg['mechanism'],
                  'background_reference': parent.to_dict(),
                  'background_is_qualified': background['qualified'],
                  'new_entry_gate': 'Strict T Close>previous actual daily Close or T Close>Open, only original flat eligible raw-bear opportunities after last signal bear TIME exit of the selected strict BELOW/ABOVE own entry anchor category and before any new signal entry; direction refusal precedes unchanged score refusal.',
                  'preserved': 'Bull entries and all holding exits unchanged; RAW original ACF or MEAN strict-past-L centered ACF; all13 original numeric coordinates, H units, execution and fees preserved.'}
        derivation = CandidateDerivation(original_key, origin['content_sha256'],
            CandidateKey('S013', cfg['candidate_id']), cfg['content_sha256'], CandidateDerivationKind.IMPLEMENTATION,
            {'mechanism': change, 'numeric_coordinates': 'All13 original numeric values and domains retained; direction choices are fixed categorical mechanisms outside those coordinates.'},
            file_hash(PROTOCOLS / 'plan.json'), CandidateEvidence(original_ref.repository_path, original_ref.sha256))
        record = register_candidate(ctx.repository, CandidateRegistrationRequest(
            bound.strategy, EXPERIMENT, (ref,), DEPENDENCIES, derivation))
        assert StrategyRuntime().identify(load_candidate(ctx.repository, record.key), dependencies=DEPENDENCIES).content_sha256 == cfg['content_sha256']
        registrations.append(record.to_dict())
    assert len(refs) == 8
    write(RUNS / 'account_references.json', {label: ref.to_dict() for label, ref in refs.items()})
    write(RUNS / 'registration.json', {'status': 'PASS', 'new_qualified': len(registrations), 'registrations': registrations,
        'anchor': {'candidate_id': 'C2132', 'content_sha256': origin['content_sha256'], 'reference': original_ref.to_dict()},
        'not_selection': 'No formal stage4 handoff, freeze, PTE or production; original unqualified B0-MEAN remains background evidence only.'})
    print({'published_new_accounts': 4, 'new_qualified': len(registrations)}, flush=True)


if __name__ == '__main__':
    main()
