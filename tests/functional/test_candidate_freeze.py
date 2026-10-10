from dataclasses import fields, replace
from hashlib import sha256
import json
import pickle
import shutil

import pytest
from strategy_manager import CandidateEvidence, CandidateKey, StrategyRegistry, StrategyVersion
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyRelease
from czsc_trader.application import (
    assemble_delivery, CandidateInspectionRequest, InspectionReplay, inspect_candidate,
    record_research_decision, freeze_candidate, get_freeze_result, RepositoryContext,
)
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_assessment_delivery import completed as completed, fresh_completed as fresh_completed, prepare


def file_ref(root, path):
    return CandidateEvidence(path.relative_to(root).as_posix(), sha256(path.read_bytes()).hexdigest())


def _build_inspection(completed):
    context, research, request, result, reference = completed
    registration = StrategyRegistry(context.research_registry_root).get_candidate(
        CandidateKey("S900", "C0001"), evidence_root=context.research_root / "S900")
    definition, content = prepare(completed)
    assemble_delivery(context, definition, content)
    delivery_path = context.research_root / "S900/deliveries/ASSESSMENT/1/receipt.json"
    source = context.root / ".tmp/user-confirmation.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('{"message":"synthetic user approval"}')
    selection = record_research_decision(context, f.ResearchDecision(
        "select1", "S900", f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(file_ref(context.root, delivery_path), registration.key,
                                   registration.content_sha256),
        file_ref(context.root, source), "选择合成候选"))
    inspection_request = CandidateInspectionRequest(
        candidate=registration.key, selection=selection,
        protocol=f.InspectionProtocol((f.InspectionCoordinate("full", "standard"),), 1e-7),
        research=research, experiment=reference.evidence.experiment,
        replays=(InspectionReplay(reference, request),), version="v1", parent_version=None,
        change_summary="合成冻结验证", selection_data_cutoff=request.data_cutoff.isoformat(),
        forward_start="2026-09-22", remaining_risks=("合成结果不代表收益证据",))
    return context, inspection_request, source


@pytest.fixture
def fresh_inspection(fresh_completed):
    return _build_inspection(fresh_completed)


@pytest.fixture
def inspection(request, tmp_path, frozen_seed_root):
    from czsc_trader.research_tools._evaluation_workers import pack
    from evaluation_seed_support import relocate_request, restored_context

    seed = frozen_seed_root / "inspection-input"
    data = frozen_seed_root / "inspection-input.pkl"
    if not seed.exists():
        context, inspection_request, _ = request.getfixturevalue("fresh_inspection")
        values = {field.name: getattr(inspection_request, field.name)
                  for field in fields(inspection_request) if field.name != "research"}
        data.write_bytes(pack(values))
        shutil.copytree(context.root, seed)
    root = tmp_path / "inspection-repo"
    shutil.copytree(seed, root)
    values = pickle.loads(data.read_bytes())
    values["replays"] = tuple(replace(replay, reproduction_request=relocate_request(
        replay.reproduction_request, root)) for replay in values["replays"])
    research = restored_context(root)
    return research.repository, CandidateInspectionRequest(research=research, **values), root / ".tmp/user-confirmation.json"


@pytest.fixture
def inspected_candidate(request, tmp_path, frozen_seed_root):
    seed = frozen_seed_root / "inspection"
    report_path = frozen_seed_root / "inspection-report.json"
    if not seed.exists():
        context, inspection_request, _ = request.getfixturevalue("inspection")
        report = inspect_candidate(context, inspection_request)
        assert report.status is f.InspectionStatus.PASS, report.checks
        shutil.copytree(context.root, seed)
        report_path.write_text(json.dumps(report.to_dict()), encoding="utf-8")
    root = tmp_path / "inspected-repo"
    shutil.copytree(seed, root)
    report = f.CandidateInspectionReport.from_dict(json.loads(report_path.read_text(encoding="utf-8")))
    return RepositoryContext.discover(root), report, root / ".tmp/user-confirmation.json"


def approve(context, report, source, decision_id="freeze1", request_id="request1"):
    approval = record_research_decision(
        context,
        f.ResearchDecision(
            decision_id,
            "S900",
            f.DecisionAction.APPROVE,
            f.FreezeSubject(
                report.plan.origin.candidate,
                report.plan.origin.content_sha256,
                report.reference,
                report.plan.sha256,
                report.plan.version,
            ),
            file_ref(context.root, source),
            "批准该精确内容冻结",
        ),
    )
    return f.FreezeCandidateRequest(
        f.FreezeRequestId("S900", request_id), report.reference, approval
    )


def test_managed_inspection_freeze_and_idempotent_query(fresh_inspection, monkeypatch):
    from czsc_trader.application import delivery_service

    context, request, source = fresh_inspection
    assert not context.strategy_root.exists()
    replay = request.replays[0]
    with pytest.raises(TypeError):
        InspectionReplay(replay.reference.to_dict(), replay.reproduction_request)
    with pytest.raises(ValueError):
        replace(replay.reference, evidence=replace(replay.reference.evidence, schema="other"))

    def forbidden(_):
        pytest.fail("stage five must not recompute stage four statistics")

    monkeypatch.setattr(delivery_service, "assess_candidates", forbidden)
    monkeypatch.setattr(delivery_service, "compare_candidates", forbidden)
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.PASS, "\n".join(
        x.detail for x in report.checks if x.status is not f.InspectionStatus.PASS
    )
    assert not context.strategy_root.exists()
    assert report.reference.resolve(context.root).is_relative_to(
        context.research_root / "S900/assets/evidence" / request.experiment.experiment_id
    )
    assert f.CandidateInspectionReport.from_dict(report.to_dict()) == report
    operation = approve(context, report, source)
    assert operation.approval.evidence.resolve(context.root).is_relative_to(
        context.research_root / "S900/decisions"
    )
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND
    assert not context.strategy_root.exists()
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED, receipt
    assert (
        freeze_candidate(context, operation)
        == receipt
        == get_freeze_result(context, operation.request_id)
    )
    registry = StrategyRegistry(context.strategy_root)
    version = registry.get_version("S900", "v1")
    assert version.schema_version == 5
    assert not hasattr(version, "origin")
    assert StrategyVersion.from_dict(version.to_dict()) == version
    assert StrategyRelease.from_mapping(version.to_dict()).release_hash == version.release_hash
    assert not hasattr(registry, "validate_version_governance")
    assert not hasattr(registry, "record_research_decision")
    assert registry.validate_all()["versions"] == 1
    assert not (context.strategy_root / "deployments").exists()
    assert not (context.strategy_root / "research_objects").exists()
    assert not (context.strategy_root / "research_decisions").exists()
    assert not (context.strategy_root / "freeze_requests").exists()
    with pytest.raises(ValueError, match="different content"):
        freeze_candidate(context, replace(operation, inspection=report.plan.payload))


def test_missing_coverage_never_passes_or_freezes(inspection):
    context, request, source = inspection
    report = inspect_candidate(context, replace(request, replays=()))
    assert report.status is f.InspectionStatus.INCOMPLETE
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="complete passing"):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND








def test_approval_identity_and_version_conflicts(inspected_candidate):
    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="matching approval"):
        freeze_candidate(context, replace(operation, approval=report.selection))
    assert freeze_candidate(context, operation).status is f.FreezeStatus.COMMITTED
    with pytest.raises(ValueError, match="does not match"):
        record_research_decision(
            context,
            f.ResearchDecision(
                "wrong",
                "S900",
                f.DecisionAction.APPROVE,
                f.FreezeSubject(
                    report.plan.origin.candidate,
                    "f" * 64,
                    report.reference,
                    report.plan.sha256,
                    "v1",
                ),
                file_ref(context.root, source),
                "mismatched candidate content",
            ),
        )


def test_changed_inspected_file_is_rejected(inspected_candidate):
    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    file = report.plan.source_files[0].source.resolve(context.root)
    file.write_bytes(file.read_bytes() + b"\n# altered\n")
    from strategy_manager import ValidationError

    with pytest.raises(ValidationError, match="hash differs"):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND




def test_stage_five_delivery_publishes_report_and_approval(inspection):
    from czsc_trader.application import publish_evidence, validate_delivery
    from czsc_trader.research_tools.context import ResearchBatchRef
    from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
    from czsc_trader.research_tools import delivery as d
    context, request, source = inspection
    report = inspect_candidate(context, request)
    reference = publish_evidence(request.research, MaterialEvidenceWrite(request.experiment,
        "technical_inspection", json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode(), "application/json", "json"))
    selection = f.ResearchDecision.from_dict(json.loads(report.selection.evidence.resolve(context.root).read_text(encoding="utf-8")))
    assessment = d.DeliveryReceipt.from_dict(json.loads(selection.subject.delivery.resolve(context.root).read_text(encoding="utf-8"))).reference
    payload = d.CandidateInspectionDelivery(assessment, report, reference, (), None, ("是否批准冻结",))
    definition = d.DeliveryDefinition(ResearchBatchRef("S900"), d.DeliveryStage.INSPECTION, 1,
                                      predecessors=(assessment,))
    content = d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (),
                                report="合成技术检验报告：检验通过，等待用户冻结决定。")
    first = assemble_delivery(context, definition, content)
    assert validate_delivery(context, first.reference).status is d.ValidationStatus.PASS
    old = (context.research_root / "S900/deliveries/INSPECTION/1/report.md").read_bytes()
    operation = approve(context, report, source)
    frozen = freeze_candidate(context, operation)
    second = assemble_delivery(context, replace(definition, revision=2,
        predecessors=(assessment, first.reference)), replace(content,
        payload=replace(payload, decisions=(operation.approval,), freeze=frozen, pending_decisions=())))
    assert validate_delivery(context, second.reference).status is d.ValidationStatus.PASS
    assert (context.research_root / "S900/deliveries/INSPECTION/1/report.md").read_bytes() == old


@pytest.mark.parametrize("failure", ["source", "payload", "runtime", "environment", "empty", "plan", "materialize"])
def test_inspection_preparation_failures_publish_failed_reports(inspection, monkeypatch, failure):
    from czsc_trader.application import inspection_service, publish_evidence, validate_delivery
    from czsc_trader.application.research_evidence import validate_inspection
    from czsc_trader.research_tools.context import ResearchBatchRef
    from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
    from czsc_trader.research_tools import delivery as d
    from strategy_runtime import StrategyRuntime
    from strategy_runtime.errors import RuntimeCompatibilityError

    context, request, source = inspection
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
    root = context.research_root / request.candidate.strategy_id
    if failure in {"source", "payload"}:
        reference = registration.source_files[0] if failure == "source" else registration.payload
        reference.resolve(root).unlink()
    elif failure in {"runtime", "environment", "empty"}:
        def unavailable(*args, **kwargs):
            if failure == "empty":
                raise RuntimeError()
            if failure == "environment":
                raise KeyError("SYNTHETIC_STRATEGY_ENVIRONMENT")
            raise RuntimeCompatibilityError("synthetic imported dependency is unavailable")
        monkeypatch.setattr(StrategyRuntime, "describe", unavailable)
    else:
        def unavailable(*args, **kwargs):
            raise OSError(f"synthetic {failure} failure")
        monkeypatch.setattr(inspection_service, "_copy_plan" if failure == "plan" else "_materialize", unavailable)
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.FAIL
    assert report.origin.candidate == request.candidate
    assert report.origin.registration_sha256 == registration.record_sha256
    assert (report.plan is not None) == (failure == "materialize")
    checks = {item.check: item.status for item in report.checks}
    failed = f.InspectionCheck.CONTENT if failure in {"source", "payload", "runtime", "environment", "empty"} else f.InspectionCheck.PACKAGE
    assert checks[failed] is f.InspectionStatus.FAIL
    if failure in {"plan", "materialize"}:
        assert checks[f.InspectionCheck.CONTENT] is f.InspectionStatus.PASS
    assert all(status is f.InspectionStatus.INCOMPLETE for kind, status in checks.items()
               if kind is not failed and kind is not f.InspectionCheck.CONTENT)
    assert validate_inspection(context.root, report.reference) == report
    assert f.CandidateInspectionReport.from_dict(report.to_dict()) == report
    operation = f.FreezeCandidateRequest(f.FreezeRequestId("S900", "failed-inspection"), report.reference, report.selection)
    with pytest.raises(ValueError, match="complete passing|matching approval"):
        freeze_candidate(context, operation)
    assert not context.strategy_root.exists()
    if failure == "source":
        with pytest.raises(ValueError, match="requires an inspected plan"):
            record_research_decision(context, f.ResearchDecision(
                "invalid-freeze", "S900", f.DecisionAction.APPROVE,
                f.FreezeSubject(report.origin.candidate, report.origin.content_sha256,
                                report.reference, "f" * 64, "v1"),
                file_ref(context.root, source), "不能批准缺失计划"))
    # Preserve every preparation failure as an independent node. The two report
    # shapes (absent/present plan) own the full blocked-delivery roundtrip.
    if failure not in {"source", "materialize"}:
        return
    selected = f.ResearchDecision.from_dict(json.loads(report.selection.evidence.resolve(context.root).read_text(encoding="utf-8")))
    assessment = d.DeliveryReceipt.from_dict(json.loads(selected.subject.delivery.resolve(context.root).read_text(encoding="utf-8"))).reference
    evidence = publish_evidence(request.research, MaterialEvidenceWrite(request.experiment,
        "failed_inspection", json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode(), "application/json", "json"))
    payload = d.CandidateInspectionDelivery(assessment, report, evidence, (), None, ("修复检验环境后重试",))
    definition = d.DeliveryDefinition(ResearchBatchRef("S900"), d.DeliveryStage.INSPECTION, 1,
                                      predecessors=(assessment,))
    content = d.DeliveryContent(payload, d.DeliveryStatus.BLOCKED, (), (),
                               ("技术检验失败",), report=f"检验失败：{failure}；等待补齐环境或材料。")
    receipt = assemble_delivery(context, definition, content)
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS


def test_runtime_deployment_is_independent_of_research_commit_marker(inspected_candidate):
    from czsc_trader.application import deploy_strategy, validate_release_package
    from strategy_runtime import load_strategy_deployment

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    receipt = freeze_candidate(context, operation)
    validate_release_package(context, "S900-v1")
    # This is an isolated synthetic repository, never a production deployment.
    deploy_strategy(context, "S900-v1")
    assert (
        load_strategy_deployment(context.strategy_root, "S900-v1").release_hash
        == receipt.version.release_hash
    )
    marker = context.research_root / "S900/freeze_requests/request1/committed.json"
    marker.rename(marker.with_name("simulated-lost-commit.json"))
    assert load_strategy_deployment(context.strategy_root, "S900-v1").release_hash == receipt.version.release_hash


def test_inspection_can_be_repeated_inside_same_experiment(inspection):
    context, request, _ = inspection
    first = inspect_candidate(context, request)
    second = inspect_candidate(context, request)
    assert first.status is second.status is f.InspectionStatus.PASS
    assert first.reference.resolve(context.root).is_file()
    assert second.reference.resolve(context.root).is_file()
    assert not (context.research_root / "S900/experiments" / request.experiment.experiment_id / "experiment_manifest.json").exists()


def test_corrupt_research_commit_does_not_change_runtime_version(inspected_candidate):

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    freeze_candidate(context, operation)
    path = context.research_root / "S900/freeze_requests/request1/committed.json"
    path.write_text("{malformed")
    receipt = get_freeze_result(context, operation.request_id)
    assert receipt.status is f.FreezeStatus.UNKNOWN
    assert receipt.version is None
    assert "cannot be verified" in receipt.reason
    assert freeze_candidate(context, operation) == receipt
    assert StrategyRegistry(context.strategy_root).get_version("S900", "v1").release_id == "S900-v1"


def test_release_signal_divergence_blocks_freeze(inspection, monkeypatch):
    from strategy_runtime import StrategyInstance

    context, request, source = inspection
    original = StrategyInstance.inspect_signals

    def divergent(instance):
        frame = original(instance)
        if instance.definition.identity_kind == "RELEASE":
            frame = frame.copy()
            frame["target_position"] = 1.0 - frame["target_position"]
        return frame

    monkeypatch.setattr(StrategyInstance, "inspect_signals", divergent)
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.FAIL
    assert (
        next(x for x in report.checks if x.check is f.InspectionCheck.SIGNAL_EQUIVALENCE).status
        is f.InspectionStatus.FAIL
    )
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="complete passing"):
        freeze_candidate(context, operation)


@pytest.mark.parametrize("check", [f.InspectionCheck.LEDGER_AUDIT, f.InspectionCheck.LEDGER_EQUIVALENCE])
def test_failed_ledger_gate_blocks_freeze(inspection, monkeypatch, check):
    from czsc_trader.application import inspection_service
    from strategy_evaluator import AuditStatus, LedgerComparisonStatus

    context, request, source = inspection
    name = "audit_replay" if check is f.InspectionCheck.LEDGER_AUDIT else "compare_ledgers"
    original = getattr(inspection_service, name)
    calls = []
    def failed(*args, **kwargs):
        value = original(*args, **kwargs)
        calls.append(value)
        if check is f.InspectionCheck.LEDGER_AUDIT:
            assert value.status is AuditStatus.PASS
            return replace(value, status=AuditStatus.FAIL, reason_codes=("INJECTED_LEDGER_FAILURE",))
        assert value.status is LedgerComparisonStatus.EQUIVALENT
        return replace(value, status=LedgerComparisonStatus.DIFFERENT)
    monkeypatch.setattr(inspection_service, name, failed)
    report = inspect_candidate(context, request)
    assert len(calls) == 2  # archived/current and candidate/frozen checks both ran
    checks = {item.check: item.status for item in report.checks}
    assert checks[check] is f.InspectionStatus.FAIL
    assert checks[f.InspectionCheck.REPRODUCTION] is f.InspectionStatus.PASS
    assert checks[f.InspectionCheck.SIGNAL_EQUIVALENCE] is f.InspectionStatus.PASS
    assert report.status is f.InspectionStatus.FAIL
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="complete passing"):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND
    assert not context.strategy_root.exists()


def test_invalid_package_reports_failure_and_decisions_are_immutable(inspected_candidate):
    from strategy_manager import ValidationError

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    binding_path = report.plan.runtime_binding.resolve(context.root)
    binding_path.write_bytes(binding_path.read_bytes() + b" ")
    with pytest.raises(ValidationError, match="hash"):
        freeze_candidate(context, operation)
    selection = f.ResearchDecision.from_dict(json.loads(report.selection.evidence.resolve(context.root).read_text(encoding="utf-8")))
    repeated = replace(selection, confirmation_source=file_ref(context.root, source))
    assert record_research_decision(context, repeated) == report.selection
    with pytest.raises(ValidationError, match="hash differs"):
        record_research_decision(context, replace(repeated, reason="changed decision content"))


@pytest.mark.parametrize("field", ["evaluation", "artifact"])
def test_inspection_rejects_reference_identity_mismatch(inspection, field):
    context, request, _ = inspection
    replay = request.replays[0]
    ref = replay.reference
    if field == "evaluation":
        ref = replace(ref, evaluation_ids=("f" * 64,))
    else:
        ref = replace(ref, evidence=replace(ref.evidence, sha256="f" * 64, evidence_id=f"{'f' * 64}.json"))
    altered = replace(request, replays=(replace(replay, reference=ref),))
    if field == "evaluation":
        with pytest.raises(ValueError, match="reference assessment identity differs"):
            inspect_candidate(context, altered)
    else:
        report = inspect_candidate(context, altered)
        assert report.status is f.InspectionStatus.FAIL
        assert next(x for x in report.checks if x.check is f.InspectionCheck.REPRODUCTION).status is f.InspectionStatus.FAIL


def test_inspection_rejects_tampered_result_evidence(inspection):
    context, request, _ = inspection
    path = request.replays[0].reference.evidence.resolve(context.root)
    path.write_bytes(path.read_bytes() + b" ")
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.FAIL
    assert next(x for x in report.checks if x.check is f.InspectionCheck.CONTENT).status is f.InspectionStatus.FAIL


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_unavailable_independent_replay_reference_reports_failure(inspection, damage):
    from czsc_trader.application import publish_evidence
    from czsc_trader.application.research_evidence import validate_inspection
    from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
    from czsc_trader.research_tools.delivery import EvaluationEvidenceRef

    context, request, _ = inspection
    replay = request.replays[0]
    # Retain the same authenticated account JSON with different whitespace, so
    # content-addressed publication does not reuse the registered support file.
    original = replay.reference.evidence.resolve(context.root).read_bytes()
    evidence = publish_evidence(request.research, MaterialEvidenceWrite(
        request.experiment, "independent_inspection_reference", original + b"\n",
        "application/json", "json"))
    evidence = replace(evidence, schema="account_evaluation", schema_version=6)
    assert evidence.repository_path != replay.reference.evidence.repository_path
    reference = EvaluationEvidenceRef(evidence, replay.reference.evaluation_ids)
    path = evidence.resolve(context.root)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b" ")
    report = inspect_candidate(context, replace(request, replays=(replace(replay, reference=reference),)))
    checks = {item.check: item.status for item in report.checks}
    assert checks[f.InspectionCheck.CONTENT] is f.InspectionStatus.PASS
    assert checks[f.InspectionCheck.REPRODUCTION] is f.InspectionStatus.FAIL
    assert report.status is f.InspectionStatus.FAIL
    assert validate_inspection(context.root, report.reference) == report
    operation = f.FreezeCandidateRequest(f.FreezeRequestId("S900", "unavailable-baseline"),
                                       report.reference, report.selection)
    with pytest.raises(ValueError, match="complete passing"):
        freeze_candidate(context, operation)
    assert not context.strategy_root.exists()


def test_published_signal_restoration_preserves_precision_units_and_nulls(candidate_payload, tmp_path, monkeypatch):
    from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
    from strategy_runtime import implementation_sha256
    from test_research_contract_upgrade import _evaluation_fixture

    payload, package = candidate_payload
    source = package / payload["runtime"]["source_files"][0]
    source.write_text(source.read_text(encoding="utf-8").replace(
        '"fixture_signal": target}',
        '"fixture_signal": target, "factor_score": 0.12345678901234567, "regime": None}'),
        encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        payload["runtime"]["source_files"], source_root=package)
    execution, request = _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, prepared=True)
    completed = fresh_completed.__wrapped__((execution, request))
    context, request, _ = _build_inspection(completed)
    request = replace(request, protocol=replace(request.protocol, tolerance=0.0))
    result = completed[3]
    value = serialize_evaluation_evidence(completed[2], result)
    assert result.runs[0].signals.decisions["factor_score"].eq(0.12345678901234567).all()
    assert all(row["factor_score"] == 0.12345678901234567 and row["regime"] is None
               for row in value["runs"][0]["signals"]["data"])
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.PASS, report.checks
    assert next(item for item in report.checks if item.check is f.InspectionCheck.SIGNAL_EQUIVALENCE).status is f.InspectionStatus.PASS


def test_static_runtime_failure_stops_account_reproduction(inspection, monkeypatch):
    from strategy_runtime import StrategyRuntime, RuntimeCompatibilityError

    context, request, source = inspection
    describe = StrategyRuntime.describe

    def incompatible(runtime, identity, **kwargs):
        if isinstance(identity, StrategyRelease):
            raise RuntimeCompatibilityError("synthetic release mismatch")
        return describe(runtime, identity, **kwargs)

    monkeypatch.setattr(StrategyRuntime, "describe", incompatible)
    report = inspect_candidate(context, request)
    checks = {x.check: x for x in report.checks}
    assert report.status is f.InspectionStatus.FAIL
    assert checks[f.InspectionCheck.RUNTIME].status is f.InspectionStatus.FAIL
    for check in (f.InspectionCheck.COVERAGE, f.InspectionCheck.REPRODUCTION,
                  f.InspectionCheck.LEDGER_AUDIT, f.InspectionCheck.SIGNAL_EQUIVALENCE,
                  f.InspectionCheck.LEDGER_EQUIVALENCE):
        assert checks[check].status is f.InspectionStatus.INCOMPLETE
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="complete passing"):
        freeze_candidate(context, operation)
    assert not context.strategy_root.exists()




def test_reproduction_cutoff_conflict_starts_no_evaluation(inspection):
    from datetime import timedelta

    context, request, _ = inspection
    replay = request.replays[0]
    cutoff = replay.reproduction_request.data_cutoff - timedelta(days=1)
    replay = replace(replay, reproduction_request=replace(replay.reproduction_request, data_cutoff=cutoff))
    report = inspect_candidate(context, replace(request, replays=(replay,)))
    assert report.status is f.InspectionStatus.FAIL
    assert any("execution data identity differs" in x.detail for x in report.checks)
    assert not context.strategy_root.exists()
