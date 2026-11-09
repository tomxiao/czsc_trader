# Risk ownership: TDR-22
"""Real two-goal inspection, publication and exact-package freezing."""

from dataclasses import fields, replace
from datetime import date
from hashlib import sha256
import json
import pickle
import shutil

import pandas as pd
import pytest
from strategy_manager import CandidateEvidence, CandidateKey, StrategyRegistry, ValidationError
from strategy_manager import freeze_contracts as f

from czsc_trader.application import (
    assemble_delivery, CandidateInspectionRequest, FreezeTarget, InspectionProtocol,
    InspectionReplay, InspectionDataKind, inspect_candidate, describe_inspection_environment,
    record_research_decision, freeze_candidate, get_freeze_result, RepositoryContext,
)
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ResearchBatchRef
from managed_evaluation_support import managed_evaluation as managed_evaluation
from assessment_delivery_support import completed as completed, fresh_completed as fresh_completed
from stage5_pte_support import unit_price_protocol


def file_ref(root, path):
    return CandidateEvidence(path.relative_to(root).as_posix(), sha256(path.read_bytes()).hexdigest())


def _details(report):
    return "\n".join(f"{name}: {goal.status}: {case.case_id}: {case.summary}"
                     for name, goal in (("A", report.behavior_equivalence), ("B", report.pte_runtime))
                     for case in goal.cases)


def _build_inspection(completed):
    from czsc_trader.backtesting.srt_bridge import prepare_srt_input_binding

    context, research, evaluation, result, baseline = completed
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(CandidateKey("S900", "C0001"))
    source = context.root / ".tmp/user-confirmation.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('{"message":"synthetic user approval of exact technical test objects"}', encoding="utf-8")
    selection = record_research_decision(context, f.ResearchDecision(
        "select1", "S900", f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(registration.key, registration.content_sha256, registration.record_sha256),
        file_ref(context.root, source), "Select the exact synthetic candidate; no assessment dependency."))
    bindings = {name: prepare_srt_input_binding(
        snapshot=result.runs[0].signals.snapshot, execution_data=evaluation.execution_data,
        start=pd.Timestamp(day), end=pd.Timestamp(day), repository_root=context.root, dataflows=research.data,
    ) for name, day in (("enter", "2026-09-16"), ("hold", "2026-09-17"), ("exit", "2026-09-18"))}
    pte = unit_price_protocol(describe_inspection_environment(context), bindings)
    request = CandidateInspectionRequest(
        candidate=registration.key, selection=selection, research=research, experiment=baseline.evidence.experiment,
        data_kind=InspectionDataKind.SYNTHETIC,
        target=FreezeTarget("v1", None, "Synthetic exact-package freeze", evaluation.data_cutoff, date(2026, 9, 22)),
        protocol=InspectionProtocol("candidate-inspection-v2", "ECONOMIC_V1", 0.0, pte),
        replays=(InspectionReplay(f.InspectionCoordinate("full", "standard"), evaluation.input_bindings["full"],
                                  evaluation.execution_data, evaluation.initial_cash, .001, baseline),),
        remaining_risks=("Synthetic technical scenarios do not certify investment returns.",),
    )
    return context, request, source


@pytest.fixture
def fresh_inspection(fresh_completed, pinned_inspection_environment):
    return _build_inspection(fresh_completed)


@pytest.fixture
def inspection(request, tmp_path, frozen_seed_root, pinned_inspection_environment):
    from czsc_trader.research_tools._evaluation_workers import pack

    seed, data = frozen_seed_root / "inspection-v2-input", frozen_seed_root / "inspection-v2-input.pkl"
    if not seed.exists():
        context, inspection_request, _ = request.getfixturevalue("fresh_inspection")
        values = {field.name: getattr(inspection_request, field.name)
                  for field in fields(inspection_request) if field.name != "research"}
        data.write_bytes(pack((context.root, values)))
        shutil.copytree(context.root, seed)
    root = tmp_path / "inspection-repo"
    shutil.copytree(seed, root)
    inspection_request = _restore_inspection_request(root, frozen_seed_root)
    return inspection_request.research.repository, inspection_request, root / ".tmp/user-confirmation.json"


def _restore_inspection_request(root, frozen_seed_root, *, full_protocol=False):
    """Rebind real prepared inputs to a private copy of the inspected repository."""
    from evaluation_seed_support import restored_context

    data = frozen_seed_root / "inspection-v2-input.pkl"
    original_root, values = pickle.loads(data.read_bytes())
    values["replays"] = tuple(replace(replay, execution_data=replace(replay.execution_data,
        root=root / replay.execution_data.root.relative_to(original_root))) for replay in values["replays"])
    research = restored_context(root)
    environment = describe_inspection_environment(research.repository)
    pte = values["protocol"].pte
    if not full_protocol:
        # One real related fault suffices for publication/admission consumers.
        # The canonical parallel roundtrip runs the complete failure matrix.
        pte = replace(pte, failures=pte.failures[:1])
    values["protocol"] = replace(values["protocol"], pte=replace(pte,
        environment=replace(pte.environment, platform_build_sha256=environment.platform_build_sha256,
                            pte_contract_version=environment.pte_contract_version,
                            srt_contract_version=environment.srt_contract_version)))
    return CandidateInspectionRequest(research=research, **values)


@pytest.fixture
def inspected_candidate(request, tmp_path, frozen_seed_root):
    from strategy_runtime import InspectionControl

    seed, saved = frozen_seed_root / "inspection-v2", frozen_seed_root / "inspection-v2-report.json"
    if not seed.exists():
        context, inspection_request, _ = request.getfixturevalue("inspection")
        # This real serial run also supplies the canonical roundtrip's first
        # report. Every consumer receives its own copy before any mutation.
        report = inspect_candidate(context, inspection_request, control=InspectionControl(max_workers=1))
        assert report.status is f.InspectionStatus.PASS, _details(report)
        shutil.copytree(context.root, seed)
        saved.write_text(json.dumps(report.to_dict()), encoding="utf-8")
    root = tmp_path / "inspected-repo"
    shutil.copytree(seed, root)
    report = f.CandidateInspectionReport.from_dict(json.loads(saved.read_text(encoding="utf-8")))
    return RepositoryContext.discover(root), report, root / ".tmp/user-confirmation.json"


def approve(context, report, source, decision_id="freeze1", request_id="request1"):
    approval = record_research_decision(context, f.ResearchDecision(
        decision_id, "S900", f.DecisionAction.APPROVE,
        f.FreezeSubject(report.origin.candidate, report.origin.content_sha256, report.reference,
                        report.plan.sha256, report.plan.version),
        file_ref(context.root, source), "Approve this precise inspected plan and package."))
    return f.FreezeCandidateRequest(f.FreezeRequestId("S900", request_id), report.reference, approval)


def _assert_not_freezable(context, report):
    operation = f.FreezeCandidateRequest(f.FreezeRequestId("S900", "failed-inspection"), report.reference, report.selection)
    with pytest.raises(ValueError):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND
    assert not context.strategy_root.exists()


def _delivery(context, report, *, revision=1, decisions=(), freeze=None, pending_decisions=None):
    payload = d.CandidateInspectionDelivery(report.reference, decisions, freeze,
        pending_decisions if pending_decisions is not None else
        (("Review the exact technical result before approving freeze.",) if freeze is None else ()))
    definition = d.DeliveryDefinition(ResearchBatchRef("S900"), d.DeliveryStage.INSPECTION,
                                      revision, schema_version=9)
    content = d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (),
                               report="Synthetic two-goal technical inspection; no economic acceptance claim.")
    return assemble_delivery(context, definition, content).receipt


def test_TDR_22_C03_changed_inspected_bytes_rejected_before_freeze(inspected_candidate):
    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    target = report.release.files[0].source.resolve(context.root)
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises((ValueError, ValidationError), match="hash|differs|content"):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND


@pytest.mark.parametrize('change', ['reason', 'confirmation'], ids=['TDR-22-C07', 'TDR-22-C08'])
def test_approval_identity_and_decision_immutability(inspected_candidate, change):
    context, report, source = inspected_candidate
    selection = f.ResearchDecision.from_dict(json.loads(report.selection.evidence.resolve(context.root).read_text()))
    assert record_research_decision(context, replace(selection, confirmation_source=file_ref(context.root, source))) == report.selection
    before = report.selection.evidence.resolve(context.root).read_bytes()
    if change == 'reason':
        changed = replace(selection, reason='Changed selection content')
    else:
        confirmation = source.with_name('different-confirmation.json')
        confirmation.write_bytes(b'{"approval":"different source"}')
        changed = replace(selection, confirmation_source=file_ref(context.root, confirmation))
    with pytest.raises((ValueError, ValidationError)):
        record_research_decision(context, changed)

    assert report.selection.evidence.resolve(context.root).read_bytes() == before






def test_TDR_22_C01_unapproved_selection_cannot_create_version(inspected_candidate):
    context, report, _ = inspected_candidate
    operation = f.FreezeCandidateRequest(f.FreezeRequestId('S900', 'unapproved'), report.reference, report.selection)
    with pytest.raises(ValueError):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND
    assert not context.strategy_root.exists()


def test_TDR_22_C02_approval_must_match_exact_inspected_plan(inspected_candidate):
    context, report, source = inspected_candidate
    decision = f.ResearchDecision('wrong-plan', 'S900', f.DecisionAction.APPROVE,
        f.FreezeSubject(report.origin.candidate, report.origin.content_sha256,
            report.reference, 'f' * 64, report.plan.version),
        file_ref(context.root, source), 'Approve a different package plan')
    before = {p.relative_to(context.root): p.read_bytes() for p in context.root.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='does not match inspected plan'):
        record_research_decision(context, decision)
    assert {p.relative_to(context.root): p.read_bytes() for p in context.root.rglob('*') if p.is_file()} == before
    assert not context.strategy_root.exists()


def test_TDR_20_C01_missing_scenario_rejected_before_execution(inspection):
    _, request, _ = inspection
    with pytest.raises(ValueError, match='nonempty unique'):
        replace(request, replays=())
