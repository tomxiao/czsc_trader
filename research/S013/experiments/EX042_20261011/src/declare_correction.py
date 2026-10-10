"""Keep the original failed diagnostic and freeze a single date-comparison correction."""
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def main():
    assert not (PROTOCOLS / 'technical_correction_reference.json').exists()
    assert not (ROOT / '.tmp/ex042-diagnosis/anchors_v2.json').exists()
    plan = read(PROTOCOLS / 'plan.json')
    for name, digest in plan['source_files'].items():
        assert file_hash(SRC / name) == digest
    temporary_failure = ROOT / '.tmp/ex042-diagnosis/anchors.json'
    assert read(temporary_failure)['status'] == 'FAILED' and read(temporary_failure)['new_account_evaluations'] == 0
    failure = PROTOCOLS / 'diagnosis_failure.json'
    assert not failure.exists()
    failure.write_bytes(temporary_failure.read_bytes())
    proof = read(ROOT / '.tmp/ex042-date-v2/focused.json')
    assert proof['status'] == 'PURE_PASS' and proof['date_precision_cases'] == 9
    method = {'name': 'S013-EX042-exact-native-date-unit-comparison-v2',
        'new_account_evaluations': 0, 'runtime_changed': False,
        'change': 'At one account.date versus signal valid_session Index comparison only, convert both DatetimeIndexes to ns before exact equality. Native date values/order/count/all covered years are unchanged; different or missing sessions still fail. No timestamp rounding, date deletion, state or financial comparison change.',
        'failure_path': failure.relative_to(ROOT).as_posix(), 'failure_sha256': file_hash(failure),
        'original_plan_sha256': file_hash(PROTOCOLS / 'plan.json'),
        'original_source_files': plan['source_files'], 'external_source_files': plan['external_source_files'],
        'source_files': {name: file_hash(SRC / name) for name in ('anchor_diagnosis_v2.py', 'native_diagnosis_v2.py',
            'focused_checks_v2.py', 'technical_validation.py', 'declare_correction.py')},
        'focused_proof': proof,
        'pure_checks_source': {'path': '.tmp/ex042-date-v2/focused_checks.py',
            'sha256': file_hash(ROOT / '.tmp/ex042-date-v2/focused_checks.py'),
            'source': (ROOT / '.tmp/ex042-date-v2/focused_checks.py').read_text(encoding='utf-8')},
        'unchanged': 'All anchor/state/category/statistics functions AST identical. Actual_cash differs only in one exact date-comparison dtype normalization. Original method, failure and native37 evidence retained; no new or rerun complete account, policy/data/13-domain/four-gate change.',
        'limits': 'Technical diagnostic correction only; no economic improvement inferred.'}
    write(PROTOCOLS / 'technical_correction.json', method)
    ctx = context(1)
    refs = {}
    for name, path in (('original-diagnostic-failure', failure),
                       ('focused-date-correction', ROOT / '.tmp/ex042-date-v2/focused.json'),
                       ('explicit-technical-correction', PROTOCOLS / 'technical_correction.json')):
        refs[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), 'application/json', 'json')).to_dict()
    write(PROTOCOLS / 'technical_correction_reference.json', refs['explicit-technical-correction'])
    write(PROTOCOLS / 'technical_proof_references.json', refs)
    print({'technical_correction': 'DECLARED', 'new_evaluations': 0}, flush=True)


if __name__ == '__main__':
    main()
