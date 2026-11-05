"""Publish the actual blocked technical result without freezing or rerunning it."""
from pathlib import Path
from hashlib import sha256
import ast
import os
import re

import run_inspection as a
from czsc_trader.application import (RepositoryContext, create_research_context,
    publish_evidence, validate_experiment, assemble_delivery)
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope, ExecutionResources)
from czsc_trader.research_tools import delivery as d
from strategy_manager import freeze_contracts as f


def main():
    repo = RepositoryContext.discover(a.ROOT)
    experiment = ExperimentRef('S018', a.EXP_ROOT.name)
    ctx = create_research_context(repo, ResearchBatchRef('S018'), resources=ExecutionResources(2, 1, 17))
    report = f.CandidateInspectionReport.from_dict(a.read(a.EXP_ROOT / 'others/inspection_report.json'))
    assert validate_inspection(repo.root, report.reference) == report
    assert report.status is f.InspectionStatus.FAIL and report.release is None
    assert report.pte_runtime.status is f.InspectionStatus.NOT_RUN
    assert report.origin.content_sha256 == '186dffc6fe4df3aec1638030d7c0f65d594b6c9578593c39b5676796fe3c5d4a'
    raw = (a.EXP_ROOT / 'report.md').read_bytes()
    assert 'Status: BLOCKED_NATIVE_V4_RELEASE' in raw.decode('utf-8')
    destination = a.ROOT / 'research/S018/deliveries/INSPECTION/1'
    assert not destination.exists() and not (a.EXP_ROOT / 'report_ref.json').exists()
    paths = [a.EXP_ROOT / 'notes.md', *sorted((a.EXP_ROOT / 'src').glob('*.py')),
             *sorted((a.EXP_ROOT / 'protocols').glob('*')),
             *sorted((a.EXP_ROOT / 'others').glob('inspection_*.json'))]
    refs = []
    for path in paths:
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'))
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                assert (path.parent / target.split('#')[0]).exists(), target
        media = {'.json': 'application/json', '.py': 'text/x-python', '.md': 'text/markdown'}[path.suffix]
        refs.append(publish_evidence(ctx, MaterialEvidenceWrite(experiment, path.stem,
                    path.read_bytes(), media, path.suffix[1:])))

    def rebase(match):
        target = (a.EXP_ROOT / match.group(1)).resolve()
        assert target.is_relative_to(a.ROOT) and target.exists(), match.group(1)
        return '](' + Path(os.path.relpath(target, destination)).as_posix() + ')'

    text = re.sub(r'\]\(([^)]+)\)', rebase, raw.decode('utf-8'))
    report_ref = publish_evidence(ctx, ExperimentReportWrite(experiment, sha256(raw).hexdigest(),
        ExperimentOutcome.FAILED, tuple(refs)))
    validation = validate_experiment(repo, ExperimentValidationRequest(experiment,
        ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value == 'PASS'
    pending = ('是否授权切换DEV评审原生V4阶段五平台需求；当前不具备可批准冻结包。',)
    payload = d.CandidateInspectionDelivery(report.reference, (report.selection,), None, pending)
    result = assemble_delivery(repo,
        d.DeliveryDefinition(ResearchBatchRef('S018'), d.DeliveryStage.INSPECTION, 1),
        d.DeliveryContent(payload, d.DeliveryStatus.PARTIAL, (), (),
            ('原生V4包准备失败；行为等价回放及隔离PTE尚未执行；未冻结。',),
            report=text, evidence=tuple([*refs, report_ref])), resources=ExecutionResources(2, 1, 17))
    assert result.validation.status is d.ValidationStatus.PASS
    a.save('others/publication_receipt.json', {'technical_status': report.status.value,
        'report': report_ref.to_dict(), 'experiment_validation': validation.to_dict(),
        'assembly': result.to_dict(), 'freeze': 'NOT_EXECUTED', 'production': 'NOT_TOUCHED'})
    print({'technical': report.status.value, 'delivery': result.receipt.reference.to_dict(),
           'publication_validation': result.validation.status.value, 'scope': result.validation.scope.value}, flush=True)


if __name__ == '__main__':
    main()
