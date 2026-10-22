"""S011-C9902 two-goal inspection; exact v1 package for explicitly authorized in-place repair."""
import argparse
from dataclasses import asdict
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import cloudpickle
from dataflows import ProviderConfig
from czsc_trader.application import (RepositoryContext, create_research_context, load_candidate,
    publish_evidence, record_research_decision, describe_inspection_environment,
    CandidateInspectionRequest, InspectionReplay, InspectionProtocol, InspectionDataKind,
    FreezeTarget, inspect_candidate, assemble_delivery, validate_delivery, validate_experiment)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvaluationResources,
    EvidenceRef, MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome,
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, LimitBuyHold,
    ExperimentValidationRequest, ExperimentValidationScope)
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey, CandidateEvidence, StrategyRegistry
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyInputBinding
from strategy_runtime.inspection import InspectionControl

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = ExperimentRef('S011', 'EX083_20261022')
EROOT = EXPERIMENT.resolve(ROOT)
KEY = CandidateKey('S011', 'C9902')
CONTENT = 'e3b172664d26eb396528dac9ccc812434c2314b465c25eaf60f459c909fb7a12'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def context(*, preparation=False):
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S011'),
        resources=EvaluationResources(2, 1, 13),
        providers=ProviderConfig(env_file=ROOT / '.env') if preparation else ProviderConfig(bindings={}))


def frozen_hashes():
    paths = [* (ROOT / 'strategies/S011').rglob('*'), ROOT / 'strategies/deployments/S011-v1.json']
    return {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file() and '__pycache__' not in p.parts}


def prepare_inputs():
    ctx = context(preparation=True)
    assert not (EROOT / 'others/inputs.json').exists()
    candidate = load_candidate(ctx.repository, KEY)
    registration = StrategyRegistry(ctx.repository.research_registry_root).get_candidate_registration(KEY)
    assert registration.content_sha256 == CONTENT
    assert not (ROOT / 'strategies/S011/versions/v2.json').exists()
    baseline = EvidenceRef.from_dict(read(ROOT / 'research/S011/experiments/EX080_20261022/others/account_evidence.json'))
    original = read(baseline.resolve(ROOT))
    binding = StrategyInputBinding.from_mapping(original['input_bindings']['restored'])
    request = EvaluationRequest(ROOT, 'EX080_20261022', candidate, {
        'candidate_id': candidate.reference_id, 'source_files': list(candidate.payload['runtime']['source_files']),
        'implementation_sha256': candidate.payload['runtime']['source_sha256']}, '159326.SZ', 'etf',
        (EvaluationWindow('restored', date(2025, 2, 6), date(2026, 10, 21)),), date(2026, 10, 21), 100000.,
        (EvaluationCost('standard', .001),), benchmark=EvaluationBenchmark(LimitBuyHold(100, .01, .001, .1, 1000000)))
    prepared = ctx.evaluation.prepare(request)  # Input preparation only; no new economic evaluation.
    assert prepared.execution_data.fingerprint == original['data_identity']
    assert prepared.input_bindings['restored'].plan.to_dict() == binding.plan.to_dict()
    # Keep the authenticated original preparation reference for baseline identity.
    prepared = ctx.evaluation.prepare(replace(prepared, input_bindings={'restored': binding}))
    snapshot = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'prepared_replay',
        cloudpickle.dumps(prepared), 'application/octet-stream', 'pkl'))
    save(EROOT / 'others/inputs.json', {'snapshot': snapshot.to_dict(), 'baseline': baseline.to_dict(),
        'frozen_before': frozen_hashes(), 'sessions': len(prepared.execution_data.evaluation_sessions)})
    print('INPUTS_READY', len(prepared.execution_data.evaluation_sessions), flush=True)


def inputs():
    saved = read(EROOT / 'others/inputs.json')
    ref = EvidenceRef.from_dict(saved['snapshot'])
    # Authenticated locally authored snapshot, never deserialize untrusted pickle.
    return cloudpickle.loads(ref.resolve(ROOT).read_bytes()), saved


def prepare_protocol():
    from pte_protocol import build_protocol
    assert not (EROOT / 'protocols/inspection.json').exists()
    ctx = context()
    req, saved = inputs()
    candidate = load_candidate(ctx.repository, KEY)
    registration = StrategyRegistry(ctx.repository.research_registry_root).get_candidate_registration(KEY)
    environment = describe_inspection_environment(ctx.repository)
    pte, reasoning = build_protocol(ctx, candidate, req.execution_data, req.input_bindings['restored'], environment)
    source = EROOT / 'others/user_authorization.json'
    save(source, {'source': 'human messages in this Codex conversation', 'received_date': '2026-10-22',
        'user_request_verbatim': '请做原地升级，保持策略ID为S011-v1',
        'user_reply_verbatim': '仅升级 S011-v1 发布包，PTE 另行处理', 'candidate': KEY.to_dict(), 'content_sha256': CONTENT,
        'scope': 'Inspect and install the repaired S011-v1 local publication only; preserve old revision; no production or running PTE changes.'})
    selection = record_research_decision(ctx.repository, f.ResearchDecision(
        'S011-select-C9902-v1-repair-20261022', 'S011', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(KEY, CONTENT, registration.record_sha256),
        CandidateEvidence(source.relative_to(ROOT).as_posix(), sha256(source.read_bytes()).hexdigest()),
        '用户明确授权C9902原地升级本地S011-v1发布包；生产和PTE账户另行处理。'))
    target = FreezeTarget('v1', None, '修复历史输入最低数量：daily/bars为20，market为21；保留原公式、参数、固定起点和交易规则。',
                          date(2026, 10, 21), date(2026, 10, 22))
    save(EROOT / 'others/selection_ref.json', selection.to_dict())
    save(EROOT / 'others/pte_design.json', reasoning)
    save(EROOT / 'protocols/inspection.json', {'candidate': KEY.to_dict(), 'content_sha256': CONTENT,
        'selection': selection.to_dict(), 'target': target.to_dict(),
        'protocol': InspectionProtocol('candidate-inspection-v2', 'ECONOMIC_V1', 0., pte).to_dict(),
        'baseline': saved['baseline'], 'input_snapshot': saved['snapshot'], 'data_kind': 'HISTORICAL',
        'resources': {'timeout_seconds': 600., 'max_workers': 2, 'native_threads_per_worker': 1},
        'remaining_risks': [
            '技术通过不构成新研究选型、绩效验收或独立前向证据。',
            'PTE采用历史输入及合成成交渠道，未验证真实券商连通、流动性或生产生效。',
            'EX078旧格式历史账户未认证；本次原账户对照仅针对EX080的同一C9902当前契约证据。'],
        'stop_rule': 'Preserve formal failures; do not tune candidate, inputs or expectations against PTE outcomes.'})
    refs = {}
    for path in [source, EROOT / 'protocols/inspection.json', EROOT / 'others/pte_design.json', *sorted((EROOT / 'src').glob('*.py'))]:
        ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, path.stem, path.read_bytes(),
            'text/x-python' if path.suffix == '.py' else 'application/json', path.suffix[1:]))
        refs[path.relative_to(EROOT).as_posix()] = ref.to_dict()
    save(EROOT / 'others/prepared.json', {'references': refs})
    print('PROTOCOL_READY', len(pte.scenarios), 'scenarios', len(pte.failures), 'faults', flush=True)


def inspect():
    assert not (EROOT / 'others/inspection_report.json').exists()
    ctx = context()
    req, saved = inputs()
    refs = read(EROOT / 'others/prepared.json')['references']
    for relative, raw in refs.items():
        ref = EvidenceRef.from_dict(raw)
        assert (EROOT / relative).read_bytes() == ref.resolve(ROOT).read_bytes()
    protocol = read(EROOT / 'protocols/inspection.json')
    t = protocol['target']
    request = CandidateInspectionRequest(KEY, f.DecisionReference.from_dict(protocol['selection']), ctx, EXPERIMENT,
        FreezeTarget(t['version'], t['parent_version'], t['change_summary'], date.fromisoformat(t['selection_data_cutoff']),
                     date.fromisoformat(t['forward_start'])), InspectionProtocol.from_dict(protocol['protocol']),
        (InspectionReplay(f.InspectionCoordinate('restored', 'standard'), req.input_bindings['restored'],
            req.execution_data, 100000., .001, d.EvaluationEvidenceRef(EvidenceRef.from_dict(saved['baseline']))),),
        InspectionDataKind.HISTORICAL, remaining_risks=tuple(protocol['remaining_risks']))
    def progress(event):
        with (EROOT / 'others/progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(asdict(event), ensure_ascii=False) + '\n')
        print(json.dumps(asdict(event), ensure_ascii=False), flush=True)
    started = perf_counter()
    report = inspect_candidate(ctx.repository, request, control=InspectionControl(timeout_seconds=600., max_workers=2, on_progress=progress))
    save(EROOT / 'others/inspection_report.json', report.to_dict())
    assert saved['frozen_before'] == frozen_hashes()
    assert not (ROOT / 'strategies/S011/versions/v2.json').exists()
    save(EROOT / 'others/inspection_summary.json', {'status': report.status.value,
        'behavior_equivalence': report.behavior_equivalence.status.value, 'pte_runtime': report.pte_runtime.status.value,
        'elapsed_seconds': perf_counter() - started, 'inspection_sha256': report.sha256,
        'plan_sha256': report.plan.sha256 if report.plan else None,
        'release_sha256': report.release.release_sha256 if report.release else None,
        'package_sha256': report.release.package_sha256 if report.release else None,
        'frozen_v1_unchanged': True, 'v1_upgrade_installed': False, 'production': 'NOT_TOUCHED'})
    if report.plan:
        save(EROOT / 'others/freeze_plan.json', report.plan.to_dict())
        save(EROOT / 'others/freeze_approval_subject.json', f.FreezeSubject(KEY, CONTENT, report.reference,
            report.plan.sha256, report.plan.version).to_dict())
    print(json.dumps(read(EROOT / 'others/inspection_summary.json'), ensure_ascii=False), flush=True)


def publish():
    ctx = context()
    report = f.CandidateInspectionReport.from_dict(read(EROOT / 'others/inspection_report.json'))
    refs = [EvidenceRef.from_dict(x) for x in read(EROOT / 'others/prepared.json')['references'].values()]
    for path in sorted((EROOT / 'others').glob('*.json')):
        refs.append(publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, path.stem, path.read_bytes(), 'application/json', 'json')))
    passing = report.status is f.InspectionStatus.PASS
    text = (EROOT / 'report.md').read_text(encoding='utf-8')
    assert 'Status: IN_PROGRESS' not in text
    ref = publish_evidence(ctx, ExperimentReportWrite(EXPERIMENT, sha256((EROOT / 'report.md').read_bytes()).hexdigest(),
        ExperimentOutcome.COMPLETED if passing else ExperimentOutcome.INCOMPLETE, tuple(dict.fromkeys(refs))))
    stage = ROOT / 'research/S011/deliveries/INSPECTION'
    revision = max([int(p.name) for p in stage.iterdir() if p.name.isdigit()] if stage.exists() else [0]) + 1
    pending = ('本次仅授权本地S011-v1原地升级；PTE生产切换另行批准。',) if passing else ('技术检验未通过，当前不可冻结。',)
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ResearchBatchRef('S011'), d.DeliveryStage.INSPECTION, revision, schema_version=9),
        d.DeliveryContent(d.CandidateInspectionDelivery(report.reference, (report.selection,), None, pending),
            d.DeliveryStatus.COMPLETE if passing else d.DeliveryStatus.BLOCKED, (), (), () if passing else ('技术检验未通过',),
            report=text.replace('](others/', '](../../../experiments/EX083_20261022/others/'), evidence=(*dict.fromkeys(refs), ref)))
    checked = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    published = validate_experiment(ctx.repository, ExperimentValidationRequest(EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(EROOT / 'others/delivery_validation.json', {'delivery': receipt.reference.to_dict(), 'full': checked.to_dict(), 'experiment': published.to_dict()})
    assert checked.status.value == published.status.value == 'PASS'
    print('DELIVERY', receipt.reference.to_dict(), 'FULL=PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('inputs', 'protocol', 'inspect', 'publish'))
    {'inputs': prepare_inputs, 'protocol': prepare_protocol, 'inspect': inspect, 'publish': publish}[parser.parse_args().mode]()
