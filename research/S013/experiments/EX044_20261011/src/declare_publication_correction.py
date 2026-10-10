"""Freeze identical-content name-alias repair before delivery publication."""
import subprocess
from dataclasses import replace
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, OUTPUT, context, read, write, file_hash
from native_reference import verified_json
from publication_validation import same_blob
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    assert not (PROTOCOLS / 'publication_correction_references.json').exists()
    assert not (PROTOCOLS / 'delivery_reference.json').exists()
    subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], cwd=ROOT, check=True)
    plan = read(PROTOCOLS / 'plan.json')
    assert plan['method_reference'] == read(PROTOCOLS / 'method_reference.json')
    verified_json(plan['method_reference'])
    assert file_hash(SRC / 'publish.py') == plan['source_files']['publish.py']
    old = (SRC / 'publish.py').read_text(encoding='utf-8')
    expected = old.replace('"""Immutable descriptive66 delivery, successor of FULL39."""',
                          '"""Explicit publication-only alias dedup correction; native66 unchanged."""')
    expected = expected.replace('import subprocess\n', 'import subprocess\nfrom publication_validation import technical_check, same_blob\n')
    expected = expected.replace('    plan = source_check()\n', '    technical_check()\n    plan = source_check()\n')
    expected = expected.replace("    materials['existing-economic-analysis']", "    materials.update({name: EvidenceRef.from_dict(ref) for name, ref in read(PROTOCOLS / 'publication_correction_references.json').items()})\n    materials['existing-economic-analysis']")
    expected = expected.replace("RUNS / 'reproduction.json'", "RUNS / 'reproduction_v2.json'")
    expected = expected.replace("EXPERIMENT, 'reproduction',", "EXPERIMENT, 'reproduction-v2',")
    expected = expected.replace('            assert evidence[ref.repository_path] == ref',
                                '            assert same_blob(evidence[ref.repository_path], ref)')
    expected = expected.replace("report.read_text(encoding='utf-8') + '\\n## 正式证据引用\\n\\n'", "report.read_text(encoding='utf-8') + '\\n发布v1因同一内容不同名称的引用比较失败；v2只修正内容去重，完整失败和纠正证据保留，零账户重跑。\\n\\n## 正式证据引用\\n\\n'")
    assert expected == (SRC / 'publish_v2.py').read_text(encoding='utf-8')
    first = EvidenceRef.from_dict(plan['method_reference'])
    assert same_blob(first, replace(first, name='different-display-name'))
    rejected = 0
    for key, value in (('sha256', '0'*64), ('media_type', 'text/plain'), ('schema', 'other'), ('schema_version', 99)):
        try:
            altered = replace(first, **{key: value})
        except ValueError:
            # Public EvidenceRef also rejects internally inconsistent metadata.
            altered = None
        if altered is not None:
            assert not same_blob(first, altered)
        rejected += 1
    assert not same_blob(first, replace(first, sha256='0'*64, evidence_id='0'*64 + '.json'))
    rejected += 1
    assert (RUNS / 'research-decision.json').read_bytes() == (RUNS / 'research-conclusion.json').read_bytes()
    assert file_hash(OUTPUT) == file_hash(RUNS / 'complete-native-input-state.json')
    output = read(OUTPUT)
    assert output['status'] == 'PASS' and output['method_reference'] == plan['method_reference']
    assert output['summary']['unique_native_accounts'] == 66
    failure = {'status': 'FAILED', 'stage': 'delivery-evidence-dedup', 'original_source': (SRC / 'publish.py').relative_to(ROOT).as_posix(),
        'original_source_sha256': file_hash(SRC / 'publish.py'), 'error_type': 'AssertionError',
        'expression': 'assert evidence[ref.repository_path] == ref',
        'reason': 'research-decision and research-conclusion exactsame content and path with different display names',
        'identical_content_sha256': file_hash(RUNS / 'research-decision.json'),
        'native_diagnosis_sha256': file_hash(OUTPUT), 'new_account_evaluations': 0, 'account_replays': 0,
        'no_delivery_created': True, 'original_reproduction_sha256': file_hash(RUNS / 'reproduction.json')}
    checks = {'status': 'PURE_PASS', 'display_name_aliases_accepted': 1, 'metadata_differences_rejected': rejected,
        'exact_declared_v1_to_v2_transform': True, 'native_diagnosis_unchanged': True, 'new_account_evaluations': 0}
    correction = {'status': 'DECLARED', 'original_source': failure['original_source'],
        'original_source_sha256': failure['original_source_sha256'],
        'source_files': {name: file_hash(SRC / name) for name in ('publish_v2.py', 'publication_validation.py', 'declare_publication_correction.py')},
        'change': 'Dedup equal blob references permits only name aliases. All other EvidenceRef metadata exact; file hashes verified. Retain original reproduction.json and use reproduction_v2.json. Original publisher and account diagnosis remain immutable.',
        'new_account_evaluations': 0, 'account_replays': 0}
    ctx, refs = context(1), {}
    for name, value in (('publication-failure', failure), ('publication-focused-checks', checks), ('publication-correction', correction)):
        write(PROTOCOLS / (name + '.json'), value)
        ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name,
            (PROTOCOLS / (name + '.json')).read_bytes(), 'application/json', 'json'))
        refs[name] = ref.to_dict()
    refs['original-publication-reproduction'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'reproduction',
        (RUNS / 'reproduction.json').read_bytes(), 'application/json', 'json')).to_dict()
    write(PROTOCOLS / 'publication_correction_references.json', refs)
    print({'publication_correction': 'DECLARED', 'accounts_replayed': 0}, flush=True)


if __name__ == '__main__':
    main()
