"""Publish the unchanged technical report with explicit forward-runtime blocker."""
from __future__ import annotations

import argparse
from hashlib import sha256
import os
from pathlib import Path
import re

from run_inspection import ROOT, HOME, OUT, EX, CONTENT, context, read, save, material
from czsc_trader.application import assemble_delivery, validate_experiment
from czsc_trader.research_tools import (
    ResearchBatchRef, EvidenceRef,
    ExperimentValidationRequest, ExperimentValidationScope, ExecutionResources,
)
from czsc_trader.research_tools import delivery as d
from strategy_manager import freeze_contracts as f


def prepare():
    report = f.CandidateInspectionReport.from_dict(read(OUT / 'inspection_report_v2.json'))
    assert report.origin.content_sha256 == CONTENT
    assert f.CandidateInspectionReport.from_dict(read(OUT / 'inspection_report.json')).status is f.InspectionStatus.FAIL
    assert (OUT / 'protocol_correction.json').exists()
    assert f.CandidateInspectionReport.from_dict(read(report.reference.resolve(ROOT))) == report
    assert report.selection == f.DecisionReference.from_dict(read(OUT / 'selection_ref.json'))
    assert read(OUT / 'forward_boundary.json')['status'] == 'FORWARD_RUNTIME_BLOCKED'
    raw = (HOME / 'report.md').read_bytes()
    assert 'Status: IN_PROGRESS' not in raw.decode('utf-8')
    assert '2026-10-21' in raw.decode('utf-8') and '暂不建议冻结' in raw.decode('utf-8')
    paths = [OUT / 'publication_attempt1.json', HOME / 'report.md', HOME / 'notes.md', *sorted((HOME / 'src').glob('*.py')),
             *sorted((HOME / 'protocols').glob('*.json')),
             *[p for p in sorted(OUT.glob('*.json')) if not p.name.startswith('publication_')]]
    manifest = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths}
    from strategy_manager import canonical_sha256
    digest = canonical_sha256(manifest)
    return report, raw, paths, manifest, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'publish'))
    parser.add_argument('--reviewed-input-sha')
    args = parser.parse_args()
    report, raw, paths, manifest, digest = prepare()
    if args.mode == 'check':
        print({'status': 'READY_FOR_REVIEW', 'input_sha256': digest,
               'technical': report.status.value, 'forward_runtime': 'BLOCKED', 'freeze': 'NOT_REQUESTED'}, flush=True)
        return
    assert args.reviewed_input_sha == digest
    assert not (ROOT / 'research/S015/deliveries/INSPECTION/3').exists()
    assert (HOME / 'report_ref.json').exists()
    ctx = context()
    refs = {k: EvidenceRef.from_dict(v) for k, v in read(OUT / 'input_refs.json').items()}
    for path in paths:
        assert sha256(path.read_bytes()).hexdigest() == manifest[path.relative_to(ROOT).as_posix()]
        if path != HOME / 'report.md':
            refs[path.relative_to(HOME).as_posix()] = material(ctx, path)
    report_ref = EvidenceRef.from_dict(read(HOME / 'report_ref.json')['report'])
    snapshot = read(report_ref.resolve(ROOT))
    assert snapshot['report_sha256'] == sha256(raw).hexdigest()
    validation = validate_experiment(ctx.repository,
        ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value == 'PASS'
    pending = ('是否授权在保持交易逻辑和参数不变的前提下，生成解除研究日期上界的可前瞻运行候选，核对历史行为等价并重新执行阶段五；当前C9304暂不建议冻结。',)
    if report.status is not f.InspectionStatus.PASS:
        pending += ('审阅已保留的技术失败原因，批准相应修复范围后再检验；不能更改检查预期掩盖失败。',)
    payload = d.CandidateInspectionDelivery(report.reference, (report.selection,), None, pending)
    destination = ROOT / 'research/S015/deliveries/INSPECTION/3'

    def rebase(match):
        target = match.group(1)
        if '://' in target or target.startswith('#'):
            return match.group(0)
        file_target, separator, fragment = target.partition('#')
        resolved = (HOME / file_target).resolve()
        assert resolved.is_relative_to(ROOT) and resolved.exists(), target
        return '](' + Path(os.path.relpath(resolved, destination)).as_posix() + separator + fragment + ')'

    text = re.sub(r'\]\(([^)]+)\)', rebase, raw.decode('utf-8'))
    blockers = ('原候选运行日期上界为2026-10-21，不能规划前瞻窗口；需独立获批的候选修订。',)
    if report.status is not f.InspectionStatus.PASS:
        blockers += ('正式技术检验存在失败或未完成检查，见原报告。',)
    result = assemble_delivery(ctx.repository,
        d.DeliveryDefinition(ResearchBatchRef('S015'), d.DeliveryStage.INSPECTION, 3),
        d.DeliveryContent(payload, d.DeliveryStatus.BLOCKED, (), (), blockers,
                          report=text, evidence=tuple(dict.fromkeys((*refs.values(), report_ref)))),
        resources=ExecutionResources(4, 1, 13))
    assert result.validation.status is d.ValidationStatus.PASS
    assert result.validation.scope is d.DeliveryValidationScope.FULL
    save(OUT / 'publication_receipt_v3.json', {
        'status': 'BLOCKED_INSPECTION_DELIVERY_FULL_PASS', 'input_sha256': digest,
        'inputs': manifest, 'assembly': result.to_dict(), 'experiment_validation': validation.to_dict(),
        'report': report_ref.to_dict(), 'technical_report_status': report.status.value,
        'forward_runtime': 'BLOCKED', 'freeze': 'NOT_REQUESTED',
    })
    print({'delivery': result.receipt.reference.to_dict(), 'validation': 'FULL_PASS',
           'technical': report.status.value, 'business_status': 'BLOCKED'}, flush=True)


if __name__ == '__main__':
    main()
