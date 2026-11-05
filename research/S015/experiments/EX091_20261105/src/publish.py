"""Publish the standard-account migration and the separate fee-context audit."""
from hashlib import sha256
from pathlib import Path
import json

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
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'))
    predecessor = []
    for name in ('EX090_20261105', 'EX091_20261105'):
        exp = ExperimentRef('S015', name)
        home = exp.resolve(ROOT)
        assert not (home / 'report_ref.json').exists(), 'published reports are immutable'
        refs = list(predecessor)
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
        refs = tuple(dict.fromkeys(refs))
        for ref in refs:
            assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256
        report = publish_evidence(ctx, ExperimentReportWrite(
            exp, sha256((home / 'report.md').read_bytes()).hexdigest(),
            ExperimentOutcome.COMPLETED, refs))
        predecessor.append(report)
        print(json.dumps({'experiment': name, 'report': report.to_dict(),
                          'linked_evidence_count': len(refs)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
