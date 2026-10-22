"""C0031 technical inspection v2; no freezing, deployment, or external channel."""
import argparse
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'

import cloudpickle  # noqa: E402
from dataflows import ProviderConfig  # noqa: E402
from czsc_trader.application import (  # noqa: E402
    RepositoryContext, create_research_context, load_candidate, publish_evidence,
    record_research_decision, describe_inspection_environment, CandidateInspectionRequest,
    InspectionReplay, InspectionProtocol, InspectionDataKind, FreezeTarget, inspect_candidate,
    assemble_delivery, validate_delivery, validate_experiment,
)
from czsc_trader.research_tools import (  # noqa: E402
    ResearchBatchRef, ExperimentRef, EvaluationResources, EvidenceRef, MaterialEvidenceWrite,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope,
)
from czsc_trader.research_tools import delivery as d  # noqa: E402
from strategy_manager import CandidateKey, CandidateEvidence, StrategyRegistry  # noqa: E402
from strategy_manager import freeze_contracts as f  # noqa: E402
from strategy_runtime.inspection import InspectionControl  # noqa: E402
from pte_protocol import build_protocol  # noqa: E402

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = ExperimentRef('S015', 'EX007_20261022')
EROOT = EXPERIMENT.resolve(ROOT)
PREVIOUS = ROOT / 'research/S015/experiments/EX006_20261022'
KEY = CandidateKey('S015', 'C0031')
CONTENT = '6a6e536c6c2f017c43d238633267c05f1f2b9d647aa22d52506d9e8e0a81d580'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'),
        resources=EvaluationResources(2, 1, 13), providers=ProviderConfig(bindings={}))


def material(ctx, name, path, media='application/json', suffix='json'):
    return publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), media, suffix))


def original_inputs():
    # The local pickle was produced by this research, and is authenticated before
    # decoding. It is only an input transport; the new report contains JSON facts.
    refs = read(PREVIOUS / 'others/prepared.json')['references']
    protocol = read(EvidenceRef.from_dict(refs['protocol']).resolve(ROOT))
    snapshot = EvidenceRef.from_dict(refs['replay_requests'])
    assert snapshot.sha256 == protocol['request_snapshot_sha256']
    requests = cloudpickle.loads(snapshot.resolve(ROOT).read_bytes())
    assert len(requests) == len(protocol['references']) == 2
    for req, raw in zip(requests, protocol['references'], strict=True):
        baseline = d.EvaluationEvidenceRef.from_dict(raw)
        saved = read(baseline.evidence.resolve(ROOT))
        identity = saved['request_identity']
        assert identity['content_sha256'] == CONTENT
        assert req.execution_data.fingerprint == identity['data_identity']
        assert {key: binding.to_dict() for key, binding in req.input_bindings.items()} == identity['input_bindings']
        assert req.data_cutoff == date(2026, 10, 21)
        assert req.windows[0].start == date(2025, 1, 2) and req.windows[0].end == date(2026, 10, 21)
        assert len(req.execution_data.evaluation_sessions) == 434
        assert req.initial_cash == 100000 and len(req.costs) == 1
    assert [x.costs[0].one_way_cost for x in requests] == [.001, .002]
    return requests, protocol, snapshot


def prepare():
    if (EROOT / 'others/prepared.json').exists():
        raise RuntimeError('Preparation already retained')
    ctx = context()
    registry = StrategyRegistry(ctx.repository.research_registry_root)
    registration = registry.get_candidate_registration(KEY)
    assert registration.content_sha256 == CONTENT
    assert not (ROOT / 'strategies/S015').exists(), 'An existing version requires review'
    candidate = load_candidate(ctx.repository, KEY)
    requests, old, snapshot = original_inputs()
    environment = describe_inspection_environment(ctx.repository)
    pte, reasoning = build_protocol(ctx, candidate, requests[0].execution_data,
                                    requests[0].input_bindings['full'], environment)
    protocol = InspectionProtocol('candidate-inspection-v2', 'ECONOMIC_V1', 0., pte)
    authorization = {
        'source': 'human messages in this Codex conversation', 'received_date': '2026-10-22',
        'selection_verbatim': '确认选择C0031进入阶段五，请你主导执行',
        'continuation_verbatim': '同意，请继续',
        'continuation_context': '合并开发分支回研究分支，切换RSCH按新契约执行C0031阶段五',
        'scope': 'C0031 unchanged; two-goal inspection and exact freeze-plan preparation; no freeze approval.',
        'candidate': KEY.to_dict(), 'content_sha256': CONTENT,
    }
    save(EROOT / 'others/user_authorization.json', authorization)
    source = EROOT / 'others/user_authorization.json'
    selection = record_research_decision(ctx.repository, f.ResearchDecision(
        'S015-select-C0031-v2-20261022', 'S015', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(KEY, CONTENT, registration.record_sha256),
        CandidateEvidence(source.relative_to(ROOT).as_posix(), sha256(source.read_bytes()).hexdigest()),
        '按已确认选型以schema2记录同一C0031内容；不新增研究选择，不批准冻结或部署。'))
    save(EROOT / 'others/selection_ref.json', selection.to_dict())
    save(EROOT / 'others/pte_design.json', reasoning)
    save(EROOT / 'protocols/inspection.json', {
        'purpose': 'Two technical goals, not research audit or new performance evidence',
        'candidate': KEY.to_dict(), 'content_sha256': CONTENT,
        'registration_sha256': registration.record_sha256, 'selection': selection.to_dict(),
        'protocol': protocol.to_dict(), 'data_kind': 'HISTORICAL',
        'replay_input_snapshot': snapshot.to_dict(), 'baselines': old['references'],
        'target': FreezeTarget('v1', None, '首次冻结计划：保持C0031原始实现、参数及周期资金合同。',
                               date(2026, 10, 21), date(2026, 10, 22)).to_dict(),
        'resources': {'timeout_seconds': 600., 'max_workers': 2, 'native_threads': 1},
        'remaining_risks': old['remaining_risks'] + [
            'PTE使用历史输入及独立合成成交渠道；通过仅覆盖声明场景，不证明真实券商连通、流动性或生产已启用。'],
        'stop_rule': 'Preserve every formal failure; never tune candidate, inputs, tolerance or checkpoints against observed PTE output.',
    })
    refs = {'input_snapshot': snapshot}
    for name, path in (('authorization', source), ('protocol', EROOT / 'protocols/inspection.json'),
                       ('pte_design', EROOT / 'others/pte_design.json'),
                       ('design_review', EROOT / 'others/design_review.json')):
        refs[name] = material(ctx, name, path)
    for path in sorted((EROOT / 'src').glob('*.py')):
        refs['source_' + path.stem] = material(ctx, 'source_' + path.stem, path, 'text/x-python', 'py')
    save(EROOT / 'others/prepared.json', {'status': 'READY', 'references': {k: v.to_dict() for k, v in refs.items()},
        'source_hashes': {p.name: sha256(p.read_bytes()).hexdigest() for p in (EROOT / 'src').glob('*.py')}})
    print(json.dumps({'prepared': 'READY', 'experiment': EXPERIMENT.experiment_id,
                      'A_coordinates': 2, 'B_scenarios': len(pte.scenarios), 'B_failures': len(pte.failures)}, ensure_ascii=False), flush=True)


def inspect():
    if (EROOT / 'others/inspection_report.json').exists():
        raise RuntimeError('Inspection already retained; use a new experiment for successor evidence')
    ctx = context()
    prepared = read(EROOT / 'others/prepared.json')
    for name, digest in prepared['source_hashes'].items():
        assert sha256((EROOT / 'src' / name).read_bytes()).hexdigest() == digest
    protocol_path = EvidenceRef.from_dict(prepared['references']['protocol']).resolve(ROOT)
    saved = read(protocol_path)
    requests, _, _ = original_inputs()
    replays = tuple(InspectionReplay(f.InspectionCoordinate(req.windows[0].window_id, req.costs[0].scenario_id),
        req.input_bindings['full'], req.execution_data, req.initial_cash, req.costs[0].one_way_cost,
        d.EvaluationEvidenceRef.from_dict(raw)) for req, raw in zip(requests, saved['baselines'], strict=True))
    target = saved['target']
    request = CandidateInspectionRequest(KEY, f.DecisionReference.from_dict(saved['selection']), ctx, EXPERIMENT,
        FreezeTarget(target['version'], target['parent_version'], target['change_summary'],
                     date.fromisoformat(target['selection_data_cutoff']), date.fromisoformat(target['forward_start'])),
        InspectionProtocol.from_dict(saved['protocol']), replays, InspectionDataKind.HISTORICAL,
        remaining_risks=tuple(saved['remaining_risks']))
    started = perf_counter()
    def progress(event):
        value = asdict(event)
        with (EROOT / 'others/progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        print(json.dumps(value, ensure_ascii=False), flush=True)
    report = inspect_candidate(ctx.repository, request, control=InspectionControl(
        timeout_seconds=600., max_workers=2, on_progress=progress))
    save(EROOT / 'others/inspection_report.json', report.to_dict())
    save(EROOT / 'others/inspection_summary.json', {
        'status': report.status.value, 'behavior_equivalence': report.behavior_equivalence.status.value,
        'pte_runtime': report.pte_runtime.status.value, 'elapsed_seconds': perf_counter() - started,
        'inspection_sha256': report.sha256,
        'plan_sha256': report.plan.sha256 if report.plan else None,
        'release_sha256': report.release.release_sha256 if report.release else None,
        'package_sha256': report.release.package_sha256 if report.release else None,
        'freeze': 'NOT_REQUESTED', 'production': 'NOT_TOUCHED',
    })
    if report.plan:
        save(EROOT / 'others/freeze_plan.json', report.plan.to_dict())
        save(EROOT / 'others/freeze_approval_subject.json', f.FreezeSubject(KEY, CONTENT, report.reference,
            report.plan.sha256, report.plan.version).to_dict())
    print(json.dumps(read(EROOT / 'others/inspection_summary.json'), ensure_ascii=False), flush=True)


def publish():
    ctx = context()
    if (ROOT / 'research/S015/deliveries/INSPECTION/2').exists():
        raise RuntimeError('Delivery revision already exists')
    report = f.CandidateInspectionReport.from_dict(read(EROOT / 'others/inspection_report.json'))
    assert report.reference.resolve(ROOT).is_file()
    raw = (EROOT / 'report.md').read_bytes()
    if 'Status: IN_PROGRESS' in raw.decode('utf-8'):
        raise RuntimeError('RSCH report must be completed before publication')
    refs = {k: EvidenceRef.from_dict(v) for k, v in read(EROOT / 'others/prepared.json')['references'].items()}
    for name in ('inspection_report', 'inspection_summary', 'selection_ref', 'review'):
        refs[name] = material(ctx, name, EROOT / 'others' / f'{name}.json')
    if report.plan:
        for name in ('freeze_plan', 'freeze_approval_subject'):
            refs[name] = material(ctx, name, EROOT / 'others' / f'{name}.json')
    passing = report.status is f.InspectionStatus.PASS
    report_ref = publish_evidence(ctx, ExperimentReportWrite(EXPERIMENT, sha256(raw).hexdigest(),
        ExperimentOutcome.COMPLETED if passing else ExperimentOutcome.INCOMPLETE, tuple(refs.values())))
    pending = ('请批准本报告列明的C0031内容、检验报告、精确计划及S015-v1后执行冻结；部署和PTE启用另行授权。',) if passing else (
        '技术检验未通过；请审阅失败证据及处理建议，当前不可冻结。',)
    payload = d.CandidateInspectionDelivery(report.reference, (report.selection,), None, pending)
    text = raw.decode('utf-8').replace('](others/', '](../../../experiments/EX007_20261022/others/').replace(
        '](protocols/', '](../../../experiments/EX007_20261022/protocols/').replace('](src/', '](../../../experiments/EX007_20261022/src/')
    started = perf_counter()
    receipt = assemble_delivery(ctx.repository,
        d.DeliveryDefinition(ResearchBatchRef('S015'), d.DeliveryStage.INSPECTION, 2, schema_version=9),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE if passing else d.DeliveryStatus.BLOCKED,
            (), (), () if passing else ('技术检验未通过',), report=text, evidence=(*refs.values(), report_ref)))
    assembly_seconds = perf_counter() - started
    started = perf_counter()
    checked = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    full_seconds = perf_counter() - started
    publication = validate_experiment(ctx.repository, ExperimentValidationRequest(EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(EROOT / 'others/delivery_validation.json', {'delivery': receipt.reference.to_dict(),
        'full': checked.to_dict(), 'experiment': publication.to_dict(), 'report': report_ref.to_dict(),
        'assembly_seconds': assembly_seconds, 'full_validation_seconds': full_seconds,
        'freeze': 'PENDING_EXACT_USER_APPROVAL' if passing else 'BLOCKED'})
    assert checked.status.value == publication.status.value == 'PASS'
    print(json.dumps({'delivery': receipt.reference.to_dict(), 'FULL': checked.status.value,
        'REPORT_PUBLICATION': publication.status.value, 'assembly_seconds': assembly_seconds,
        'full_validation_seconds': full_seconds}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'inspect', 'publish'))
    mode = parser.parse_args().mode
    {'prepare': prepare, 'inspect': inspect, 'publish': publish}[mode]()
