"""Publish completed native implementation and selection diagnostic reports."""
from hashlib import sha256
from pathlib import Path
import json
import sys

from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome)

ROOT = Path(__file__).resolve().parents[5]


def references(value):
    if isinstance(value, dict):
        if value.get('type') == 'EvidenceRef':
            yield EvidenceRef.from_dict(value)
        else:
            for child in value.values():
                yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def main():
    names = sys.argv[1:]
    assert names and set(names) <= {'EX092_20261105', 'EX093_20261105'}
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'))
    for name in names:
        exp = ExperimentRef('S015', name)
        home = exp.resolve(ROOT)
        assert not (home / 'report_ref.json').exists(), 'published reports are immutable'
        refs = []
        for folder in ('src', 'protocols', 'others'):
            for path in sorted((home / folder).glob('*')):
                if not path.is_file() or path.suffix not in ('.py', '.json'):
                    continue
                data = path.read_bytes()
                media = 'text/x-python' if path.suffix == '.py' else 'application/json'
                refs.append(publish_evidence(ctx, MaterialEvidenceWrite(
                    exp, folder + '-' + path.stem, data, media, path.suffix[1:])))
                if path.suffix == '.json':
                    refs.extend(references(json.loads(data)))
        if name == 'EX093_20261105':
            refs.extend(references(json.loads((ROOT / 'research/S015/experiments/EX092_20261105/report_ref.json').read_bytes())))
        refs = tuple(dict.fromkeys(refs))
        for ref in refs:
            assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256
        report = publish_evidence(ctx, ExperimentReportWrite(
            exp, sha256((home / 'report.md').read_bytes()).hexdigest(),
            ExperimentOutcome.COMPLETED, refs))
        print(json.dumps({'experiment': name, 'report': report.to_dict(),
                          'linked_evidence_count': len(refs)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
