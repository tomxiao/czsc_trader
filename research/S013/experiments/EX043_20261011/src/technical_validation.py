"""Authenticate explicit summary/helper correction without changing runtime."""
from common import ROOT, SRC, PROTOCOLS, read, file_hash
from czsc_trader.research_tools.evidence import EvidenceRef


def technical_check():
    ref=EvidenceRef.from_dict(read(PROTOCOLS/'technical_correction_reference.json'))
    assert file_hash(ref.resolve(ROOT))==ref.sha256
    correction=read(ref.resolve(ROOT))
    assert correction==read(PROTOCOLS/'technical_correction.json')
    assert correction['runtime_changed'] is False and correction['new_account_evaluations']==0
    assert file_hash(PROTOCOLS/'geometry.json')==correction['original_geometry_sha256']
    assert file_hash(PROTOCOLS/'plan.json')==correction['original_plan_sha256']
    for field in ('original_source_files','successor_source_files'):
        for name,digest in correction[field].items():
            assert file_hash(SRC/name)==digest
    return correction
