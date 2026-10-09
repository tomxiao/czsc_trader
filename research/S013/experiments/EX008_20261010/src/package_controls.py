"""Retain authenticated repeat controls separately from canonical assessment facts."""
from hashlib import sha256
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from common import ROOT, RUNS, read, write, material

PROVENANCE_FIELDS = {'attempt_id', 'experiment_id', 'request_sha256', 'result_sha256'}


def control_materials():
    originals = {r['candidate']['key']['candidate_id']: r for r in
                 read(RUNS/'center_authentication.json')['centers']}
    references = []
    diagnostics = []
    for row in read(RUNS/'binding_controls.json')['rows']:
        identifier = row['candidate_id']
        old_ref = EvidenceRef.from_dict(originals[identifier]['formal_account'])
        new_ref = EvidenceRef.from_dict(row['reference'])
        for reference in (old_ref, new_ref):
            assert sha256(reference.resolve(ROOT).read_bytes()).hexdigest() == reference.sha256
        before = read(old_ref.resolve(ROOT))
        after = read(new_ref.resolve(ROOT))
        validate_evaluation_evidence(after)
        original = next(x for x in before['assessment_evidence'] if x['scenario_id'] == 'baseline')
        repeated = after['assessment_evidence'][0]
        differences = {key: {'original': original[key], 'control': repeated[key]}
                       for key in original if original[key] != repeated[key]}
        assert set(differences) == PROVENANCE_FIELDS
        assert original['evaluation_id'] == repeated['evaluation_id']
        assert row['comparison']['status'] == 'PASS'
        diagnostic = {'candidate_id': identifier, 'status': 'PASS',
                      'original_reference': old_ref.to_dict(), 'control_reference': new_ref.to_dict(),
                      'evaluation_id': repeated['evaluation_id'], 'provenance_differences': differences,
                      'other_assessment_fields': 'EXACT_EQUAL', 'economic_comparison': row['comparison']}
        path = RUNS/'packaged_controls'/(identifier+'.json')
        write(path, {'kind': 'authenticated_same_parameter_repeat_control',
                     'purpose': 'Supplemental input-rebinding control, not a replacement baseline or numeric assessment coordinate.',
                     'authentication': diagnostic, 'published_account_evaluation': after})
        references.append(material('stage4-binding-control-account-'+identifier.lower(), path))
        diagnostics.append(diagnostic)
    assert len(references) == 8
    path = RUNS/'assembly_repair.json'
    write(path, {'status': 'PASS', 'failed_publication': 'ASSESSMENT/2 was rejected before publication; no installed revision was altered.',
                 'failure': {'code': 'ASSESSMENT_EVIDENCE', 'message': 'conflicting saved account facts'},
                 'cause': 'Repeat controls share the original economic evaluation ID but have a new experiment/request/result/attempt provenance. Their full facts cannot replace canonical predecessor facts.',
                 'repair': 'Keep all original typed assessment accounts. Retain each authenticated control in a separate supplemental material envelope with its complete original account document and comparison; do not rename fields or alter raw evidence.',
                 'numeric_assessment': 'Unchanged 79 centers and 790 new coordinates; repeat controls excluded from numeric assessment and trial counts.',
                 'rows': diagnostics, 'control_materials': [r.to_dict() for r in references]})
    references.append(material('stage4-assembly-repair', path))
    return tuple(references)
