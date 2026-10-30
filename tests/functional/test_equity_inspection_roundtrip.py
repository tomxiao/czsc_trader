"""Normal public inspection and exact-package freezing for a synthetic US candidate."""
from datetime import date
from hashlib import sha256
import json
import pytest
from strategy_manager import CandidateEvidence, CandidateRegistration, CandidateRegistrationOrigin, freeze_contracts as f
from strategy_manager import StrategyRegistry
from strategy_runtime import InspectionControl
from strategy_runtime.deployment import validate_release_package
from czsc_trader.application import (record_research_decision,register_candidate,CandidateRegistrationRequest,
    CandidateInspectionRequest, EquityInspectionReplay, EquityInspectionProtocol, FreezeTarget,
    InspectionDataKind, inspect_candidate, freeze_candidate, get_freeze_result,
    assemble_delivery, validate_delivery)
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.application import run_backtest
from czsc_trader.research_tools.delivery import EvaluationEvidenceRef
from czsc_trader.research_tools import delivery as d
from equity_test_support import setup_formal_equity
from test_equity_pte import equity_protocol, prepare_inspection_inputs


@pytest.mark.parametrize('auxiliary', [False, True], ids=['primary', 'auxiliary-session'])
def test_formal_equity_inspect_freeze_exact_package(tmp_path, auxiliary):
    from equity_test_support import setup_auxiliary
    research, evaluation, _, _ = (setup_auxiliary(tmp_path, same_source=True) if auxiliary
                                  else setup_formal_equity(tmp_path))
    evaluation = prepare_inspection_inputs(research, evaluation)
    with pytest.raises(ValueError,match='account contract 4'):
        register_candidate(research.repository,CandidateRegistrationRequest(evaluation.candidate,evaluation.experiment,(),()))
    seed_registered_frozen_candidate(research,evaluation)
    inspect_freeze(research, evaluation, None)


def seed_registered_frozen_candidate(research,evaluation):
    """Install an existing V2 registration through SM, not a retired research API."""
    candidate=evaluation.candidate
    identity=candidate.content_identity
    root=research.repository.research_root/candidate.strategy_id
    prefix=f'assets/candidates/{candidate.candidate_id}'
    source_root=f'{prefix}/source/strategy_runtime'
    def write(relative,content):
        path=root/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
        return CandidateEvidence(relative,sha256(content).hexdigest())
    payload=write(f'{prefix}/payload.json',json.dumps(candidate.payload,sort_keys=True,separators=(',',':')).encode())
    sources=tuple(write(f'{source_root}/{name}',(candidate.source_root/name).read_bytes())
        for name in candidate.definition.source_files)
    record=CandidateRegistration(candidate.key,identity.content_sha256,identity.source_sha256,
        identity.dependency_sha256,payload,sources,source_root,
        tuple((item.name,item.version) for item in candidate.definition.dependencies),
        CandidateRegistrationOrigin(evaluation.experiment.experiment_id,()))
    StrategyRegistry(research.repository.research_registry_root).register_candidate(record,evidence_root=root)


def test_equity_inspection_requires_complete_auxiliary_identity(tmp_path):
    from dataclasses import replace
    from equity_test_support import setup_auxiliary
    research, evaluation, _, _ = setup_auxiliary(tmp_path)
    evaluation = prepare_inspection_inputs(research, evaluation)
    replay = EquityInspectionReplay(f.InspectionCoordinate('main', 'standard'), evaluation.input_binding,
        evaluation.requests(research.execution_spec), evaluation.window, evaluation.initial_cash, evaluation.fee_rate)
    assert len(replay.requests) == 6
    with pytest.raises(ValueError, match='exact primary and auxiliary'):
        replace(replay, requests=replay.requests[:-1])
    with pytest.raises(ValueError, match='exact primary and auxiliary'):
        replace(replay, requests=replay.requests + replay.requests[-1:])


def inspect_freeze(research, evaluation, evidence, *, assessment_ref=None):
    """Continue an already registered synthetic candidate through the public R7 path."""
    context = research.repository
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(evaluation.candidate.key)
    confirmation = context.root / '.tmp' / 'engineering-approval.json'
    confirmation.parent.mkdir(exist_ok=True)
    confirmation.write_text('{"scope":"isolated synthetic engineering test"}', encoding='utf-8')
    source = CandidateEvidence(confirmation.relative_to(context.root).as_posix(), sha256(confirmation.read_bytes()).hexdigest())
    selection = record_research_decision(context, f.ResearchDecision('select-equity', 'S999', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(registration.key, registration.content_sha256, registration.record_sha256),
        source, 'Select synthetic fixture only'))
    replay = EquityInspectionReplay(f.InspectionCoordinate('main', 'standard'), evaluation.input_binding,
        evaluation.requests(research.execution_spec), evaluation.window, evaluation.initial_cash, evaluation.fee_rate,
        None if evidence is None else EvaluationEvidenceRef(evidence))
    protocol = EquityInspectionProtocol('candidate-inspection-v2', 'ECONOMIC_V1', 0., equity_protocol(research, evaluation))
    request = CandidateInspectionRequest(registration.key, selection, research, evaluation.experiment,
        FreezeTarget('v1', None, 'synthetic US closure', date(2026,10,2), date(2026,10,3)), protocol, (replay,), InspectionDataKind.SYNTHETIC)
    cancelled = inspect_candidate(context, request, control=InspectionControl(max_workers=1, cancelled=lambda: True))
    assert cancelled.status is f.InspectionStatus.INCOMPLETE
    assert validate_inspection(context.root, cancelled.reference) == cancelled
    blocked = f.FreezeCandidateRequest(f.FreezeRequestId('S999', 'cancelled-fixture'), cancelled.reference, selection)
    with pytest.raises(ValueError):
        freeze_candidate(context, blocked)
    report = inspect_candidate(context, request, control=InspectionControl(max_workers=1))
    assert report.status is f.InspectionStatus.PASS, '\n'.join(
        f'{goal.status}: {case.case_id}: {case.summary}' for goal in (report.behavior_equivalence, report.pte_runtime)
        for case in goal.cases)
    assert validate_inspection(context.root, report.reference) == report
    approval = record_research_decision(context, f.ResearchDecision('freeze-equity', 'S999', f.DecisionAction.APPROVE,
        f.FreezeSubject(report.origin.candidate, report.origin.content_sha256, report.reference, report.plan.sha256, 'v1'),
        source, 'Approve exact synthetic inspected package'))
    operation = f.FreezeCandidateRequest(f.FreezeRequestId('S999', 'equity-fixture'), report.reference, approval)
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED
    assert freeze_candidate(context, operation) == receipt == get_freeze_result(context, operation.request_id)
    package = validate_release_package(context.strategy_root, 'S999-v1')
    assert package.package_sha256 == report.release.package_sha256
    version = StrategyRegistry(context.strategy_root).get_version('S999', 'v1')
    with pytest.raises(ValueError, match='explicit equity context cannot execute'):
        run_backtest(research, version, evaluation)
    source_file = package.source_root / evaluation.candidate.definition.source_files[0]
    original = source_file.read_bytes()
    try:
        source_file.write_bytes(original + b'\n# unexpected frozen source change\n')
        with pytest.raises(Exception, match='differs|hash|source'):
            validate_release_package(context.strategy_root, 'S999-v1')
    finally:
        source_file.write_bytes(original)
    if assessment_ref is not None:
        assert validate_delivery(context, assessment_ref).status is d.ValidationStatus.PASS
    delivery = assemble_delivery(context, d.DeliveryDefinition(research.batch, d.DeliveryStage.INSPECTION, 1,
        schema_version=9),
        d.DeliveryContent(d.CandidateInspectionDelivery(report.reference, (selection, approval), receipt, ()),
            d.DeliveryStatus.COMPLETE, (), (),
            report='Synthetic US technical inspection and exact-package freeze; no economic acceptance claim.'))
    assert delivery.validation.status is d.ValidationStatus.PASS
    assert validate_delivery(context, delivery.receipt.reference).status is d.ValidationStatus.PASS
    return report, receipt, delivery.receipt
