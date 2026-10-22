"""Real two-goal inspection, publication and exact-package freezing."""

from dataclasses import fields, replace
from datetime import date
from hashlib import sha256
import json
import pickle
import shutil

import pandas as pd
import pytest
from strategy_manager import CandidateEvidence, CandidateKey, StrategyRegistry, StrategyVersion, ValidationError
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyRelease

from czsc_trader.application import (
    assemble_delivery, CandidateInspectionRequest, FreezeTarget, InspectionProtocol,
    InspectionReplay, InspectionDataKind, inspect_candidate, describe_inspection_environment,
    record_research_decision, freeze_candidate, get_freeze_result, RepositoryContext,
)
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ResearchBatchRef
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_assessment_delivery import completed as completed, fresh_completed as fresh_completed
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
def fresh_inspection(fresh_completed):
    return _build_inspection(fresh_completed)


@pytest.fixture
def inspection(request, tmp_path, frozen_seed_root):
    from czsc_trader.research_tools._evaluation_workers import pack
    from evaluation_seed_support import restored_context

    seed, data = frozen_seed_root / "inspection-v2-input", frozen_seed_root / "inspection-v2-input.pkl"
    if not seed.exists():
        context, inspection_request, _ = request.getfixturevalue("fresh_inspection")
        values = {field.name: getattr(inspection_request, field.name)
                  for field in fields(inspection_request) if field.name != "research"}
        data.write_bytes(pack((context.root, values)))
        shutil.copytree(context.root, seed)
    root = tmp_path / "inspection-repo"
    shutil.copytree(seed, root)
    original_root, values = pickle.loads(data.read_bytes())
    values["replays"] = tuple(replace(replay, execution_data=replace(replay.execution_data,
        root=root / replay.execution_data.root.relative_to(original_root))) for replay in values["replays"])
    research = restored_context(root)
    environment = describe_inspection_environment(research.repository)
    pte = values["protocol"].pte
    values["protocol"] = replace(values["protocol"], pte=replace(pte,
        environment=replace(pte.environment, platform_build_sha256=environment.platform_build_sha256,
                            pte_contract_version=environment.pte_contract_version,
                            srt_contract_version=environment.srt_contract_version)))
    return research.repository, CandidateInspectionRequest(research=research, **values), root / ".tmp/user-confirmation.json"


@pytest.fixture
def inspected_candidate(request, tmp_path, frozen_seed_root):
    seed, saved = frozen_seed_root / "inspection-v2", frozen_seed_root / "inspection-v2-report.json"
    if not seed.exists():
        context, inspection_request, _ = request.getfixturevalue("inspection")
        report = inspect_candidate(context, inspection_request)
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


def _delivery(context, report, *, revision=1, decisions=(), freeze=None):
    payload = d.CandidateInspectionDelivery(report.reference, decisions, freeze,
        ("Review the exact technical result before approving freeze.",) if freeze is None else ())
    definition = d.DeliveryDefinition(ResearchBatchRef("S900"), d.DeliveryStage.INSPECTION,
                                      revision, schema_version=9)
    content = d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (),
                               report="Synthetic two-goal technical inspection; no economic acceptance claim.")
    return assemble_delivery(context, definition, content).receipt


def test_managed_inspection_freeze_and_idempotent_query(fresh_inspection):
    context, request, source = fresh_inspection
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.PASS, _details(report)
    assert report.behavior_equivalence.status is report.pte_runtime.status is f.InspectionStatus.PASS
    assert not context.strategy_root.exists()
    assert report.reference.resolve(context.root).is_file()
    assert f.CandidateInspectionReport.from_dict(report.to_dict()) == report
    operation = approve(context, report, source)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED, receipt
    assert freeze_candidate(context, operation) == receipt == get_freeze_result(context, operation.request_id)
    version = StrategyRegistry(context.strategy_root).get_version("S900", "v1")
    assert version.schema_version == 5
    assert StrategyVersion.from_dict(version.to_dict()) == version
    assert StrategyRelease.from_mapping(version.to_dict()).release_hash == report.release.release_sha256
    package = context.strategy_root / "S900/releases/v1"
    assert (package / "release_manifest.json").read_bytes() == report.release.manifest.resolve(context.root).read_bytes()
    for item in report.release.files:
        assert (package / item.path).read_bytes() == item.source.resolve(context.root).read_bytes()
    assert receipt.version.package_hash == report.release.package_sha256
    assert not (context.strategy_root / "deployments").exists()
    assert not (context.strategy_root / "freeze_requests").exists()
    with pytest.raises(ValueError, match="different content"):
        freeze_candidate(context, replace(operation, inspection=report.plan.payload))


def test_no_research_archives_needed_for_inspection_publication_or_freeze(inspection):
    from czsc_trader.application import validate_delivery

    context, request, source = inspection
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
    for evidence in registration.origin.evidence:
        evidence.resolve(context.research_root / "S900").unlink()
    original_source = context.research_root / "S900/experiments" / registration.origin.experiment_id / "src"
    if original_source.exists():
        shutil.rmtree(original_source)
    for relative in ("assets/deliveries", "deliveries"):
        folder = context.research_root / "S900" / relative
        if folder.exists():
            shutil.rmtree(folder)
    request = replace(request, replays=tuple(replace(x, baseline=None) for x in request.replays))
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.PASS, _details(report)
    assert not hasattr(report.plan, "registration_evidence")
    receipt = _delivery(context, report)
    assert receipt.schema_version == 9
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    assert freeze_candidate(context, approve(context, report, source)).status is f.FreezeStatus.COMMITTED


def test_stage_five_delivery_publishes_report_and_approval(inspected_candidate, monkeypatch):
    from czsc_trader.application import validate_delivery
    import subprocess

    def forbidden_worker(*args, **kwargs):
        raise AssertionError("Publishing, validating and freezing saved inspection cannot rerun workers")

    monkeypatch.setattr(subprocess, "Popen", forbidden_worker)

    context, report, source = inspected_candidate
    first = _delivery(context, report)
    assert validate_delivery(context, first.reference).status is d.ValidationStatus.PASS
    path = context.research_root / "S900/deliveries/INSPECTION/1/report.md"
    original = path.read_bytes()
    operation = approve(context, report, source)
    frozen = freeze_candidate(context, operation)
    second = _delivery(context, report, revision=2, decisions=(operation.approval,), freeze=frozen)
    assert validate_delivery(context, second.reference).status is d.ValidationStatus.PASS
    assert path.read_bytes() == original
    document = json.loads((context.research_root / "S900/assets/deliveries/INSPECTION/2/delivery.json").read_text())
    assert document["schema_version"] == document["definition"]["schema_version"] == 9
    assert document["definition"]["predecessors"] == []


@pytest.mark.parametrize("material", ["source", "payload"])
def test_damaged_candidate_produces_failed_report_without_freezing(inspection, material):
    from czsc_trader.application.research_evidence import validate_inspection

    context, request, _ = inspection
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
    reference = registration.source_files[0] if material == "source" else registration.payload
    target = reference.resolve(context.research_root / "S900")
    target.write_bytes(target.read_bytes() + b"\n# corruption")
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.FAIL
    assert report.pte_runtime.status is f.InspectionStatus.NOT_RUN
    assert validate_inspection(context.root, report.reference) == report
    _assert_not_freezable(context, report)
    assert _delivery(context, report).schema_version == 9


def test_wrong_pte_expectation_fails_real_runtime_and_blocks_freeze(inspection):
    context, request, _ = inspection
    pte = request.protocol.pte
    scenario = pte.scenarios[0]
    wrong = replace(scenario.checkpoints[-1], position_quantity=100)
    scenario = replace(scenario, checkpoints=(*scenario.checkpoints[:-1], wrong))
    request = replace(request, protocol=replace(request.protocol, pte=replace(pte, scenarios=(scenario,))))
    report = inspect_candidate(context, request)
    assert report.behavior_equivalence.status is f.InspectionStatus.PASS
    assert report.pte_runtime.status is f.InspectionStatus.FAIL
    assert report.status is f.InspectionStatus.FAIL
    _assert_not_freezable(context, report)


def test_release_signal_divergence_is_detected(candidate_payload, tmp_path, monkeypatch):
    from strategy_runtime import implementation_sha256
    from test_research_contract_upgrade import _evaluation_fixture

    payload, package = candidate_payload
    source = package / payload["runtime"]["source_files"][0]
    original = source.read_text(encoding="utf-8")
    # The actual registered implementation branches on its installed location.
    # Both subprocesses receive these same bytes; no process-local monkeypatch
    # pretends to inject a fault across the worker boundary.
    target = '        return pd.DataFrame({"target_position": target'
    assert target in original
    source.write_text(original.replace(target,
        '        if "releases" in __import__("pathlib").Path(__file__).parts:\n            target = 1.0 - target\n' + target),
        encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        payload["runtime"]["source_files"], source_root=package)
    research, evaluation = _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, prepared=True)
    completed_value = fresh_completed.__wrapped__((research, evaluation))
    context, request, _ = _build_inspection(completed_value)
    report = inspect_candidate(context, request)
    assert report.behavior_equivalence.status is f.InspectionStatus.FAIL
    assert any(case.reason_code is f.InspectionReason.BEHAVIOR_DIFFERENCE
               for case in report.behavior_equivalence.cases), _details(report)
    _assert_not_freezable(context, report)


def test_original_evaluation_is_optional_but_invalid_explicit_reference_fails(inspection):
    context, request, _ = inspection
    replay = request.replays[0]
    changed = replace(replay.baseline, evaluation_ids=("f" * 64,))
    report = inspect_candidate(context, replace(request, replays=(replace(replay, baseline=changed),)))
    assert report.behavior_equivalence.status is f.InspectionStatus.FAIL
    _assert_not_freezable(context, report)


def test_changed_inspected_bytes_rejected_before_freeze(inspected_candidate):
    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    target = report.release.files[0].source.resolve(context.root)
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises((ValueError, ValidationError), match="hash|differs|content"):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND


def test_approval_identity_and_decision_immutability(inspected_candidate):
    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    with pytest.raises(ValueError):
        freeze_candidate(context, replace(operation, approval=report.selection))
    selection = f.ResearchDecision.from_dict(json.loads(report.selection.evidence.resolve(context.root).read_text()))
    assert record_research_decision(context, replace(selection, confirmation_source=file_ref(context.root, source))) == report.selection
    with pytest.raises((ValueError, ValidationError)):
        record_research_decision(context, replace(selection, reason="Changed selection content"))


def test_corrupt_freeze_receipt_does_not_change_runtime_version(inspected_candidate):
    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    freeze_candidate(context, operation)
    path = context.research_root / "S900/freeze_requests/request1/committed.json"
    path.write_text("{malformed")
    receipt = get_freeze_result(context, operation.request_id)
    assert receipt.status is f.FreezeStatus.UNKNOWN
    assert receipt.version is None
    assert freeze_candidate(context, operation) == receipt
    assert StrategyRegistry(context.strategy_root).get_version("S900", "v1").release_id == "S900-v1"


def test_empty_or_duplicate_scenarios_rejected_before_execution(inspection):
    _, request, _ = inspection
    with pytest.raises(ValueError, match="nonempty unique"):
        replace(request, replays=())
    with pytest.raises(ValueError, match="nonempty unique"):
        replace(request, replays=(request.replays[0], request.replays[0]))


def test_repeated_inspection_has_distinct_run_and_immutable_reports(inspection):
    context, request, _ = inspection
    first = inspect_candidate(context, request)
    retained = first.reference.resolve(context.root).read_bytes()
    second = inspect_candidate(context, request)
    assert first.status is second.status is f.InspectionStatus.PASS
    assert first.run_id != second.run_id and first.reference != second.reference
    assert first.reference.resolve(context.root).read_bytes() == retained
    assert first.release.package_sha256 == second.release.package_sha256
