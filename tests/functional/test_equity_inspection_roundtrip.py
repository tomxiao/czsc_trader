"""Normal public inspection and exact-package freezing for a synthetic US candidate."""
from datetime import date
from hashlib import sha256
import pytest
from strategy_manager import CandidateEvidence, freeze_contracts as f
from strategy_manager import StrategyRegistry
from strategy_runtime import InspectionControl
from strategy_runtime.deployment import validate_release_package
from czsc_trader.application import (register_candidate, CandidateRegistrationRequest, record_research_decision,
    CandidateInspectionRequest, EquityInspectionReplay, EquityInspectionProtocol, FreezeTarget,
    InspectionDataKind, inspect_candidate, freeze_candidate, get_freeze_result,
    assemble_delivery, validate_delivery)
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.application import publish_evidence
from czsc_trader.application import run_backtest
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.delivery import EvaluationEvidenceRef
from czsc_trader.research_tools import delivery as d
from test_equity_closure import setup_formal_equity
from test_equity_pte import equity_protocol


def test_formal_equity_inspect_freeze_exact_package(tmp_path):
    research, evaluation, _, _ = setup_formal_equity(tmp_path)
    evaluation = research.evaluation.prepare(evaluation)
    context = research.repository
    result = research.evaluation.evaluate(evaluation)
    evidence = publish_evidence(research, EvaluationEvidenceWrite(evaluation.experiment, 'inspection-baseline', evaluation, result))
    register_candidate(context, CandidateRegistrationRequest(evaluation.candidate, evaluation.experiment, (evidence,), ()))
    inspect_freeze(research, evaluation, evidence)


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
        EvaluationEvidenceRef(evidence))
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
    assert run_backtest(research, version, evaluation).payload['runs'] == research.evaluation.evaluate(evaluation).payload['runs']
    source_file = package.source_root / evaluation.candidate.definition.source_files[0]
    original = source_file.read_bytes()
    try:
        source_file.write_bytes(original + b'\n# unexpected frozen source change\n')
        with pytest.raises(Exception, match='differs'):
            run_backtest(research, version, evaluation)
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
