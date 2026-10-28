"""Publish the research diagnosis without a new prototype panel or replay."""
from hashlib import sha256
import json

from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentOutcome, ExperimentReportWrite,
    ExperimentValidationRequest, ExperimentValidationScope, MaterialEvidenceWrite,
)
from diagnose import WORK, EXPERIMENT, REPOSITORY, PRIOR


def main():
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))
    numeric = read(WORK / 'others/numeric_analysis.json')
    synthesis = read(WORK / 'others/synthesis.json')
    checks = read(WORK / 'others/partition_validation.json')
    assert numeric['status'] == synthesis['status'] == checks['status'] == 'PASS'
    assert numeric['new_strategy_evaluations'] == 0
    assert numeric['source_sha256'] == sha256((WORK / 'src/diagnose.py').read_bytes()).hexdigest()
    research = PRIOR.RUN.context()
    refs = [EvidenceRef.from_dict(r) for r in synthesis['sources']]
    refs += [EvidenceRef.from_dict(r['account_reference']) for r in synthesis['records'].values()]
    refs += [EvidenceRef.from_dict(r['evidence']) for r in numeric['diagnoses'].values()]
    for relative in (
        'protocols/design.md', 'notes.md', 'src/diagnose.py', 'src/synthesis.py',
        'src/validate_partition.py', 'src/publish.py', 'others/numeric_analysis.json',
        'others/synthesis.json', 'others/partition_validation.json',
    ):
        path = WORK / relative
        refs.append(publish_evidence(research, MaterialEvidenceWrite(
            EXPERIMENT, relative.replace('/', '-'), path.read_bytes(),
            'application/json' if path.suffix == '.json' else 'text/plain', path.suffix[1:])))
    refs = tuple(dict.fromkeys(refs))
    report = (WORK / 'report.md').read_bytes()
    reference = publish_evidence(research, ExperimentReportWrite(
        EXPERIMENT, sha256(report).hexdigest(), ExperimentOutcome.COMPLETED, refs))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(
        EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    result = {'report': reference.to_dict(), 'validation': validation.to_dict(),
              'evidence': [r.to_dict() for r in refs], 'new_account_evaluations': 0,
              'new_public_diagnoses': 3, 'prototype_panel_unchanged': True}
    (WORK / 'others/publication.json').write_bytes(json.dumps(result, ensure_ascii=False, indent=2).encode())
    if validation.status.value != 'PASS':
        raise RuntimeError('diagnostic report publication validation failed')
    print('EX006 REPORT_PUBLICATION PASS', flush=True)


if __name__ == '__main__':
    main()
