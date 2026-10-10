"""Authenticate the declared date-unit-only successor and immutable original failure."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, read, file_hash
from czsc_trader.research_tools.evidence import EvidenceRef


def technical_check():
    ref = EvidenceRef.from_dict(read(PROTOCOLS / 'technical_correction_reference.json'))
    assert ref.experiment == EXPERIMENT and file_hash(ref.resolve(ROOT)) == ref.sha256
    method = read(ref.resolve(ROOT))
    assert read(PROTOCOLS / 'technical_correction.json') == method
    assert method['new_account_evaluations'] == 0 and method['runtime_changed'] is False
    for name, digest in method['source_files'].items():
        assert file_hash(SRC / name) == digest
    for name, digest in method['original_source_files'].items():
        assert file_hash(SRC / name) == digest
    for name, digest in method['external_source_files'].items():
        assert file_hash(ROOT / name) == digest
    assert file_hash(ROOT / method['failure_path']) == method['failure_sha256']
    assert file_hash(PROTOCOLS / 'plan.json') == method['original_plan_sha256']
    return method
