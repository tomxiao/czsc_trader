"""Authenticate preserved execution fault and explicit zero-replay recovery."""
from common import ROOT, SRC, PROTOCOLS, read, file_hash
from czsc_trader.research_tools.evidence import EvidenceRef


def parameter_execution_check():
    ref=EvidenceRef.from_dict(read(PROTOCOLS/'parameter_execution_correction_reference.json'))
    assert file_hash(ref.resolve(ROOT))==ref.sha256
    value=read(ref.resolve(ROOT))
    assert value==read(PROTOCOLS/'parameter_execution_correction.json')
    assert value['runtime_changed'] is False and value['new_account_evaluations_for_recovery']==0
    for name,digest in value['preserved_files'].items():
        assert file_hash(ROOT/name)==digest
    for name,digest in value['successor_source_files'].items():
        assert file_hash(SRC/name)==digest
    return value
