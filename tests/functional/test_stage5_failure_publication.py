"""Control and storage failures cannot manufacture a passing/published result."""
from dataclasses import replace
import pytest
from strategy_manager import freeze_contracts as f
from strategy_runtime.inspection import InspectionControl
from czsc_trader.application import inspect_candidate, InspectionPublicationError
from czsc_trader.application.research_evidence import validate_inspection
from test_candidate_freeze import inspection as inspection
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def test_cancel_before_preparation_publishes_incomplete_report(inspection):
    context, request, _ = inspection
    report = inspect_candidate(context, request, control=InspectionControl(cancelled=lambda: True))
    assert report.status is f.InspectionStatus.INCOMPLETE
    assert report.plan is report.release is None
    assert report.pte_runtime.status is f.InspectionStatus.NOT_RUN
    assert report.behavior_equivalence.cases[0].reason_code is f.InspectionReason.CANCELLED
    assert validate_inspection(context.root, report.reference) == report
    assert not (context.root / ".tmp/strategy-inspection" / report.run_id).exists()


def test_progress_callback_exception_is_recorded_as_execution_error(inspection):
    context, request, _ = inspection
    def broken(_):
        raise RuntimeError("consumer failure")
    report = inspect_candidate(context, request, control=InspectionControl(on_progress=broken))
    assert report.status is f.InspectionStatus.FAIL
    assert report.behavior_equivalence.cases[0].reason_code is f.InspectionReason.EXECUTION_ERROR
    assert "consumer failure" in report.behavior_equivalence.cases[0].summary
    assert validate_inspection(context.root, report.reference) == report
    assert not (context.root / ".tmp/strategy-inspection" / report.run_id).exists()


def test_storage_failure_raises_publication_error_without_report(inspection, monkeypatch):
    context, request, _ = inspection
    from czsc_trader.application import evidence_service
    def denied(*args):
        raise OSError("synthetic storage unavailable")
    monkeypatch.setattr(evidence_service, "_publish_bytes", denied)
    with pytest.raises(InspectionPublicationError, match="storage unavailable") as caught:
        inspect_candidate(context, request)
    assert caught.value.phase == "PERSIST"
    assert caught.value.report_reference is None
    assert caught.value.partial_evidence == ()
    assert tuple((context.root / ".tmp/strategy-inspection").iterdir())


def test_environment_mismatch_cannot_start_execution(inspection):
    context, request, _ = inspection
    pte = request.protocol.pte
    request = replace(request, protocol=replace(request.protocol, pte=replace(pte,
        environment=replace(pte.environment, platform_build_sha256="a" * 64))))
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.FAIL
    assert report.plan is None
    assert report.pte_runtime.status is f.InspectionStatus.NOT_RUN
    assert report.behavior_equivalence.cases[0].reason_code is f.InspectionReason.ENVIRONMENT_MISMATCH
    assert validate_inspection(context.root, report.reference) == report


def test_cleanup_failure_retains_the_confirmed_published_report(inspection, monkeypatch):
    context, request, _ = inspection
    from czsc_trader.application import inspection_service
    def denied(path):
        raise OSError("synthetic cleanup unavailable")
    with monkeypatch.context() as scoped:
        scoped.setattr(inspection_service.shutil, "rmtree", denied)
        with pytest.raises(InspectionPublicationError, match="cleanup unavailable") as caught:
            inspect_candidate(context, request, control=InspectionControl(cancelled=lambda: True))
    assert caught.value.phase == "CLEANUP"
    assert caught.value.report_reference is not None
    report = validate_inspection(context.root, caught.value.report_reference)
    assert report.status is f.InspectionStatus.INCOMPLETE
    assert (context.root / ".tmp/strategy-inspection" / report.run_id).is_dir()


def test_execution_frame_cannot_disagree_with_admitted_dfls_asset(inspection):
    context, request, _ = inspection
    replay = request.replays[0]
    data = replay.execution_data
    changed = data.execution_daily.copy(deep=True)
    changed.loc[0, "close"] += .01
    request = replace(request, replays=(replace(replay, execution_data=replace(data, execution_daily=changed)),))
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.FAIL
    assert report.behavior_equivalence.cases[0].reason_code is f.InspectionReason.INPUT_MISMATCH
    assert report.pte_runtime.status is f.InspectionStatus.NOT_RUN
    assert validate_inspection(context.root, report.reference) == report
