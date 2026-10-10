"""Publish necessary snapshots and validate linked immutable research evidence."""
from hashlib import sha256
import re

from czsc_trader.research_tools import EvidenceRef
from aligned_common import ROOT, BASE, PROTOCOLS, runs, read, write, material, fingerprint


def refs(value):
    if isinstance(value, dict):
        if value.get('type') == 'EvidenceRef':
            yield value
        else:
            for child in value.values():
                yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)


def main():
    assert not (PROTOCOLS/'package_reference.json').exists()
    assert read(runs('S007')/'results-audit.json')['status'] == 'PASS'
    snapshots = []
    collected = read(runs('S007')/'aligned_results.json')['references']
    for name in ('domain-audit', 'geometry-audit', 'results-audit', 'numeric-comparison'):
        path = runs('S007')/(name+'.json')
        snapshots.append({'path': path.relative_to(ROOT).as_posix(),
                          'reference': material('aligned-'+name, path).to_dict()})
    write(PROTOCOLS/'audit_references.json', snapshots)
    # Include original input/method package rather than claiming Git retains data.
    predecessor = read(ROOT/'research/S007/experiments/EX003_20261010/protocols/package_reference.json')
    collected.append(predecessor)
    paths = list((BASE/'src').glob('*.py'))+list(PROTOCOLS.glob('*.json'))+list((BASE/'others').glob('*'))
    for strategy in ('S007', 'S013'):
        paths += list(runs(strategy).glob('*.json'))
        paths += list(runs(strategy).glob('*.csv'))
        paths += list(runs(strategy).glob('*.md'))
        for shard in sorted(runs(strategy).glob('shard-*')):
            paths += list(shard.glob('*.json'))
    # Hash and retain historical domain sources used by independent reconstruction.
    for path, expected in read(runs('S007')/'domain-audit.json')['source_sha256'].items():
        source = ROOT/path
        assert sha256(source.read_bytes()).hexdigest() == expected
        paths.append(source)
    for index, path in enumerate(sorted(set(x for x in paths if x.is_file()))):
        mime = {'.py': 'text/x-python', '.md': 'text/markdown', '.png': 'image/png',
                '.csv': 'text/csv', '.gz': 'application/gzip'}.get(path.suffix, 'application/json')
        ref = material(f'aligned-package-{index:03d}-{path.stem}', path, mime=mime).to_dict()
        snapshots.append({**fingerprint(path), 'reference': ref})
        if path.suffix == '.json':
            collected += list(refs(read(path)))
    catalog = {'version': 'aligned-distance-package-v1', 'status': 'COMPUTATION_AND_AUDITS_PASS',
        'plan': read(PROTOCOLS/'plan_reference.json'), 'snapshots': snapshots,
        'account_and_related_references': collected, 'predecessor_input_method_package': predecessor,
        'reproduction': ['src/domain_audit.py', 'src/geometry_audit.py', 'src/results_audit.py', 'src/analyze.py'],
        'permission_boundary': 'Current branch local research only; no new data/cutoff, platform/prod/frozen/PTE/merge/tag/push',
        'asset_retention': 'Ignored research/S007/assets and research/S013/assets must be retained independently of Git. Prior source/input package and native data identities are linked; no entire adjacent batch archive is asserted.',
        'benchmark_decision': 'Prior S007 executable-BH main-table choice remains pending and does not enter these parameter CAGR/DD diagnostics'}
    write(PROTOCOLS/'evidence_catalog.json', catalog)
    ref = material('aligned-evidence-catalog', PROTOCOLS/'evidence_catalog.json')
    write(PROTOCOLS/'package_reference.json', ref.to_dict())
    validation = {'status': 'PASS', 'package': ref.to_dict(), 'unique_refs_checked': 0,
                  'local_sources_current': True, 'report_links_relative_and_exist': True}
    unique = {x['sha256']: x for x in refs(catalog)}
    unique[ref.sha256] = ref.to_dict()
    for value in unique.values():
        reference = EvidenceRef.from_dict(value)
        assert sha256(reference.resolve(ROOT).read_bytes()).hexdigest() == reference.sha256
    validation['unique_refs_checked'] = len(unique)
    report = BASE/'others/report.md'
    for target in re.findall(r'\]\(([^)]+)\)', report.read_text(encoding='utf-8')):
        assert not target.startswith(('/', 'http', 'file:'))
        # This last reference is written immediately after the catalog check.
        assert (report.parent/target).exists() or target == '../protocols/package_validation_reference.json', target
    assert sha256((ROOT/'research/RSCH_AGENT.md').read_bytes()).hexdigest() == '1c9cf46d378ce23f105e2a2e896c42927bca6e861892ffafd3aec61ceb9c4792'
    write(runs('S007')/'package_validation.json', validation)
    write(PROTOCOLS/'package_validation_reference.json', material('aligned-package-validation',
        runs('S007')/'package_validation.json').to_dict())
    assert (PROTOCOLS/'package_validation_reference.json').exists()
    print(validation, flush=True)


if __name__ == '__main__':
    main()
