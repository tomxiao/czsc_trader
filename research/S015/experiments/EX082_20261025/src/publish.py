"""Publish the technical adaptation and exact plan awaiting freeze approval."""
from __future__ import annotations

import argparse
from hashlib import sha256
import os
from pathlib import Path
import re

import adapt as a
from czsc_trader.application import assemble_delivery, publish_evidence, validate_experiment
from czsc_trader.research_tools import (
    ResearchBatchRef, EvidenceRef, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope, ExecutionResources,
)
from czsc_trader.research_tools import delivery as d
from strategy_manager import freeze_contracts as f
from strategy_manager import canonical_sha256


def prepare():
    report = f.CandidateInspectionReport.from_dict(a.read(a.OUT / 'inspection_report.json'))
    assert report.origin.content_sha256 == a.read(a.OUT / 'identity.json')['content_sha256']
    assert report.origin.candidate == a.KEY and report.status is f.InspectionStatus.PASS and report.plan
    assert f.CandidateInspectionReport.from_dict(a.read(report.reference.resolve(a.ROOT))) == report
    assert report.selection == f.DecisionReference.from_dict(a.read(a.OUT / 'selection_ref.json'))
    assert a.read(a.OUT / 'results.json')['status'] == 'PASS'
    assert a.read(a.OUT / 'source_change.json')['status'] == 'PASS'
    assert a.read(a.OUT / 'entry_cycle_audit.json')['status'] == 'PASS'
    raw = (a.HOME / 'report.md').read_bytes()
    assert 'Status: TECHNICAL_PASS_AWAITING_FREEZE_APPROVAL' in raw.decode('utf-8')
    paths = [a.HOME / 'report.md', a.HOME / 'notes.md', *sorted((a.HOME / 'src').rglob('*.py')),
        *sorted((a.HOME / 'protocols').glob('*.json')),
        *[p for p in sorted(a.OUT.glob('*.json')) if not p.name.startswith('publication_')]]
    destination = a.ROOT / 'research/S015/deliveries/INSPECTION/4'

    def rebase(match):
        target = match.group(1)
        if '://' in target or target.startswith('#'):
            return match.group(0)
        file_target, separator, fragment = target.partition('#')
        resolved = (a.HOME / file_target).resolve()
        assert resolved.is_relative_to(a.ROOT) and resolved.exists(), target
        return '](' + Path(os.path.relpath(resolved, destination)).as_posix() + separator + fragment + ')'

    text = re.sub(r'\]\(([^)]+)\)', rebase, raw.decode('utf-8'))
    manifest = {p.relative_to(a.ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths}
    return report, raw, text, paths, manifest, canonical_sha256(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'publish'))
    parser.add_argument('--reviewed-input-sha')
    args = parser.parse_args()
    report, raw, text, paths, manifest, digest = prepare()
    if args.mode == 'check':
        print({'status': 'READY', 'input_sha256': digest, 'technical': report.status.value,
               'candidate': report.origin.candidate.to_dict(), 'plan_sha256': report.plan.sha256}, flush=True)
        return
    assert args.reviewed_input_sha == digest
    assert not (a.HOME / 'report_ref.json').exists()
    assert not (a.ROOT / 'research/S015/deliveries/INSPECTION/4').exists()
    ctx = a.context()
    refs = []
    for path in paths:
        assert sha256(path.read_bytes()).hexdigest() == manifest[path.relative_to(a.ROOT).as_posix()]
        if path != a.HOME / 'report.md':
            refs.append(a.material(ctx, path))
    for row in a.read(a.OUT / 'results.json')['rows']:
        refs += [EvidenceRef.from_dict(row['evidence']), EvidenceRef.from_dict(row['old_baseline']['evidence'])]
    for name in ('prepared.json', 'continuation_prepared.json', 'inspection_prepared.json'):
        refs += [EvidenceRef.from_dict(value) for value in a.read(a.OUT / name)['references'].values()]
    refs.append(EvidenceRef.from_dict(a.read(a.OUT / 'prepared.json')['requests']))
    report_ref = publish_evidence(ctx, ExperimentReportWrite(a.EX, sha256(raw).hexdigest(),
        ExperimentOutcome.COMPLETED, tuple(dict.fromkeys(refs))))
    validation = validate_experiment(ctx.repository,
        ExperimentValidationRequest(a.EX, ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value == 'PASS'
    pending = (f'是否批准将S015/C9700内容{report.origin.content_sha256}，按检验{report.sha256}及计划{report.plan.sha256}冻结为S015-v1；不含部署或生产操作。',)
    payload = d.CandidateInspectionDelivery(report.reference, (report.selection,), None, pending)
    assembled = assemble_delivery(ctx.repository,
        d.DeliveryDefinition(ResearchBatchRef('S015'), d.DeliveryStage.INSPECTION, 4),
        d.DeliveryContent(payload, d.DeliveryStatus.PARTIAL, (), (),
            ('技术检验通过；精确冻结计划待用户批准，尚未执行冻结。',), report=text,
            evidence=tuple(dict.fromkeys((*refs, report_ref)))), resources=ExecutionResources(4, 1, 13))
    assert assembled.validation.status is d.ValidationStatus.PASS
    assert assembled.validation.scope is d.DeliveryValidationScope.FULL
    a.save(a.OUT / 'publication_receipt.json', {'status': 'INSPECTION_DELIVERY_FULL_PASS_AWAITING_FREEZE_APPROVAL',
        'input_sha256': digest, 'inputs': manifest, 'report': report_ref.to_dict(),
        'experiment_validation': validation.to_dict(), 'assembly': assembled.to_dict(),
        'freeze': 'NOT_REQUESTED', 'production': 'NOT_TOUCHED'})
    print({'delivery': assembled.receipt.reference.to_dict(), 'validation': 'FULL_PASS',
           'technical': report.status.value, 'pending': 'FREEZE_APPROVAL'}, flush=True)


if __name__ == '__main__':
    main()
