"""Exact content dedup; only display-name aliases differ."""
from common import ROOT, SRC, PROTOCOLS, read, file_hash
from native_reference import verified_json


def same_blob(first, second):
    first_value, second_value = first.to_dict(), second.to_dict()
    first_value.pop('name')
    second_value.pop('name')
    return first_value == second_value


def technical_check():
    refs = read(PROTOCOLS / 'publication_correction_references.json')
    correction = verified_json(refs['publication-correction'])
    assert correction['new_account_evaluations'] == correction['account_replays'] == 0
    for name, digest in correction['source_files'].items():
        assert file_hash(SRC / name) == digest
    assert file_hash(ROOT / correction['original_source']) == correction['original_source_sha256']
    verified_json(refs['publication-failure'])
    checks = verified_json(refs['publication-focused-checks'])
    assert checks['status'] == 'PURE_PASS'
