"""Stage-five records admit only the two-goal protocol and persistent identities."""
from dataclasses import replace
from datetime import date

import pytest

from strategy_manager import (
    CandidateKey, CandidateOrigin, CandidateSelectionSubject, CandidateInspectionReport,
    DecisionReference, FreezeFile, FreezePlan, InspectedRelease, InspectionCaseResult,
    InspectionGoalResult, InspectionReason, InspectionStatus, ResearchEvidenceOwner,
    ResearchEvidenceRef,
)


@pytest.fixture
def report():
    owner = ResearchEvidenceOwner("S900", "EX001_20261022")
    evidence = ResearchEvidenceRef(owner, "inspection/" + "a" * 64, "a" * 64)
    origin = CandidateOrigin(CandidateKey("S900", "C0001"), "b" * 64, evidence)
    plan = FreezePlan(origin, "v1", None, "technical inspection", "EX001_20261022",
                      date(2026, 10, 21), date(2026, 10, 22), evidence,
                      (FreezeFile("strategies/example.py", evidence),), evidence)
    release = InspectedRelease(evidence, evidence, (FreezeFile("runtime_binding.json", evidence),),
                               "c" * 64, "d" * 64)
    case = InspectionCaseResult("equivalence", InspectionStatus.PASS, InspectionReason.OK,
                                "complete declared comparison", (evidence,))
    goal = InspectionGoalResult(InspectionStatus.PASS, (case,), (evidence,))
    return CandidateInspectionReport("3f5f1", owner, origin, DecisionReference("select", evidence),
                                     evidence, evidence, evidence, plan, release, goal, goal,
                                     evidence, ())


def test_new_records_roundtrip_and_bind_registration(report):
    restored = CandidateInspectionReport.from_dict(report.to_dict())
    assert restored == report
    assert restored.status is InspectionStatus.PASS
    assert restored.sha256 == report.sha256
    assert restored.plan.selection_data_cutoff == date(2026, 10, 21)
    selection = CandidateSelectionSubject(report.origin.candidate, "b" * 64, "c" * 64)
    assert CandidateSelectionSubject.from_dict(selection.to_dict()) == selection
    assert replace(selection, registration_sha256="d" * 64).sha256 != selection.sha256


@pytest.mark.parametrize("field", ["plan", "release", "environment"])
def test_missing_required_output_cannot_claim_pass(report, field):
    assert replace(report, **{field: None}).status is InspectionStatus.INCOMPLETE


def test_not_run_and_failed_goals_are_distinct(report):
    absent = InspectionGoalResult(InspectionStatus.NOT_RUN, (), ())
    assert replace(report, pte_runtime=absent).status is InspectionStatus.INCOMPLETE
    case = InspectionCaseResult("pte", InspectionStatus.FAIL, InspectionReason.PTE_FAILURE,
                                "restart comparison differed", (report.request,))
    failed = InspectionGoalResult(InspectionStatus.FAIL, (case,), (report.request,))
    assert replace(report, pte_runtime=failed).status is InspectionStatus.FAIL
    with pytest.raises(ValueError, match="failed case"):
        InspectionGoalResult(InspectionStatus.INCOMPLETE, (case,), ())
    with pytest.raises(ValueError, match="passing goal"):
        InspectionGoalResult(InspectionStatus.PASS, (), ())


def test_old_or_unknown_fields_are_not_interpreted_as_new_report(report):
    value = report.to_dict()
    value["checks"] = []
    with pytest.raises(ValueError, match="fields/type"):
        CandidateInspectionReport.from_dict(value)
    with pytest.raises(ValueError, match="unsupported"):
        replace(report, schema_version=1)
    selection = CandidateSelectionSubject(report.origin.candidate, "b" * 64, "c" * 64).to_dict()
    selection.pop("registration_sha256")
    selection["delivery"] = report.request.to_dict()
    with pytest.raises(ValueError, match="fields/type"):
        CandidateSelectionSubject.from_dict(selection)


def test_release_snapshot_and_plan_reject_ambiguous_or_legacy_content(report):
    with pytest.raises(ValueError, match="unique"):
        replace(report.release, files=report.release.files * 2)
    with pytest.raises(ValueError, match="manifest"):
        replace(report.release, files=(FreezeFile("release_manifest.json", report.request),))
    with pytest.raises(ValueError, match="unsupported"):
        replace(report.plan, schema_version=1)
    with pytest.raises(TypeError, match="date"):
        replace(report.plan, forward_start="2026-10-22")
    with pytest.raises(ValueError, match="follow"):
        replace(report.plan, forward_start=report.plan.selection_data_cutoff)
