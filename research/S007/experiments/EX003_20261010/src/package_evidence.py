"""Publish the bounded diagnostic report and its necessary immutable materials."""
from hashlib import sha256
import re

from czsc_trader.research_tools import EvidenceRef

from common import ROOT, SRC, RUNS, PROTOCOLS, OTHERS, read, write, material, fingerprint
from offline_inputs import sources, WORK


def references(value):
    if isinstance(value, dict):
        if value.get('type') == 'EvidenceRef':
            yield value
        else:
            for child in value.values():
                yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def main():
    assert not (PROTOCOLS/'package_reference.json').exists(), 'Published package is immutable'
    audit = read(RUNS/'independent-final/final-audit.json')
    assert audit['status'] == 'PASS'
    records = sources()[5]
    manifest = {'scope': 'Four diagnostics only; original native pools; no overall ranking',
                'branch': 'codex/s007-v1-robustness',
                'starting_head': '4549aec5315936d4bbcd82c8e8874a16bc1ee236',
                'benchmark_decision': 'PENDING_HUMAN_CONFIRMATION',
                'account_evidence': read(RUNS/'four_diagnostics.json')['formal_account_validation']['references'],
                'materials': [], 'working_files': [],
                'retention': 'EvidenceRef resolves under research/<strategy>/assets/evidence; Git alone does not retain ignored assets. Source/input snapshots are explicitly published.',
                'reproduction': ['src/final_audit.py', 'src/verify.py', 'src/calculate.py'],
                'new_account_generation': ['src/declare.py', 'src/adapt_observation.py',
                                           'src/offline_inputs.py', 'src/run_center.py',
                                           'src/run_neighborhood.py', 'src/verify_c2132.py'],
                'generation_note': 'Original declarations and account runs already exist. Do not overwrite immutable declarations; use a successor experiment for any rerun.',
                'data_assets': ['research/S007/assets/data/assets.sqlite3',
                                'research/S013/assets/data/assets.sqlite3']}
    paths = set(SRC.rglob('*'))
    paths.update(PROTOCOLS.glob('*.json'))
    paths.update(RUNS.glob('*.json'))
    paths.update((RUNS/'independent-audit').glob('*'))
    paths.update((RUNS/'independent-final').glob('*'))
    paths.update(WORK.glob('*'))
    paths.update(ROOT/x for x in audit['sources'])
    paths.update(ROOT/x for x in records['manifests'])
    paths.update(ROOT/'data/raw'/x for x in records['files'])
    paths.update([ROOT/'strategies/S007/versions/v1.json',
                  ROOT/'strategies/S007/releases/v1/runtime_binding.json',
                  ROOT/'strategies/S007/releases/v1/release_manifest.json'])
    report = OTHERS/'report.md'
    paths.add(report)
    for index, path in enumerate(sorted(x for x in paths if x.is_file())):
        relative = path.relative_to(ROOT).as_posix()
        details = fingerprint(path)
        # Existing full account evidence already has an authenticated reference.
        if '/assets/evidence/' in relative or details['bytes'] == 0:
            manifest['working_files'].append(details)
            continue
        mime = {'.py': 'text/x-python', '.md': 'text/markdown',
                '.csv': 'text/csv', '.gz': 'application/gzip'}.get(path.suffix, 'application/json')
        ref = material(f'four-diagnostics-package-{index:03d}-{path.stem}', path, mime).to_dict()
        manifest['materials'].append({**details, 'reference': ref})
    write(PROTOCOLS/'evidence_catalog.json', manifest)
    package = material('four-diagnostics-evidence-catalog', PROTOCOLS/'evidence_catalog.json')
    write(PROTOCOLS/'package_reference.json', package.to_dict())
    all_refs = {value['sha256']: value for value in references(manifest)}
    all_refs[package.sha256] = package.to_dict()
    for value in all_refs.values():
        reference = EvidenceRef.from_dict(value)
        assert sha256(reference.resolve(ROOT).read_bytes()).hexdigest() == reference.sha256
    for item in manifest['working_files']:
        assert fingerprint(ROOT/item['path']) == item
    for target in re.findall(r'\]\(([^)]+)\)', report.read_text(encoding='utf-8')):
        assert not target.startswith(('http', '/')), 'Research document links must be relative'
        assert (report.parent/target).exists(), target
    assert sha256((ROOT/'research/RSCH_AGENT.md').read_bytes()).hexdigest() == '1c9cf46d378ce23f105e2a2e896c42927bca6e861892ffafd3aec61ceb9c4792'
    validation = {'status': 'PASS', 'package': package.to_dict(),
                  'distinct_evidence_hashes_checked': len(all_refs),
                  'source_input_and_result_snapshots': len(manifest['materials']),
                  'report_relative_links': 'PASS', 'independent_numerical_audit': 'PASS',
                  'guide_user_changes_preserved': True,
                  'benchmark_decision': manifest['benchmark_decision']}
    write(RUNS/'package_validation.json', validation)
    write(PROTOCOLS/'package_validation_reference.json', material(
        'four-diagnostics-package-validation', RUNS/'package_validation.json').to_dict())
    print(validation)


if __name__ == '__main__':
    main()
