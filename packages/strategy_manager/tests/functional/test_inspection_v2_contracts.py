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


@pytest.mark.risk_cases('SM-07-C01')
def test_SM_07_C01_complete_report_roundtrip(report):
    restored = CandidateInspectionReport.from_dict(report.to_dict())
    assert restored == report
    assert restored.status is InspectionStatus.PASS
    assert restored.sha256 == report.sha256
    assert restored.plan.selection_data_cutoff == date(2026, 10, 21)


@pytest.mark.risk_cases('SM-08-C01')
def test_SM_08_C01_selection_is_bound_to_registration(report):
    selection = CandidateSelectionSubject(report.origin.candidate, "b" * 64, "c" * 64)
    assert CandidateSelectionSubject.from_dict(selection.to_dict()) == selection
    assert replace(selection, registration_sha256="d" * 64).sha256 != selection.sha256


@pytest.mark.risk_cases('SM-07-C06')
def test_missing_required_output_cannot_claim_pass(report):
    field = "release"
    assert replace(report, **{field: None}).status is InspectionStatus.INCOMPLETE


@pytest.mark.parametrize('field,reason,status,expected', [
    pytest.param("behavior_equivalence", InspectionReason.BEHAVIOR_DIFFERENCE, InspectionStatus.FAIL, InspectionStatus.FAIL, id='SM-07-C02'),
    pytest.param("pte_runtime", InspectionReason.PTE_FAILURE, InspectionStatus.FAIL, InspectionStatus.FAIL, id='SM-07-C03'),
    pytest.param("behavior_equivalence", InspectionReason.BEHAVIOR_DIFFERENCE, InspectionStatus.NOT_RUN, InspectionStatus.INCOMPLETE, id='SM-07-C04'),
    pytest.param("pte_runtime", InspectionReason.PTE_FAILURE, InspectionStatus.NOT_RUN, InspectionStatus.INCOMPLETE, id='SM-07-C05'),
])
@pytest.mark.risk_cases('SM-07-C02', 'SM-07-C03', 'SM-07-C04', 'SM-07-C05')
def test_goal_status_propagates(report, field, reason, status, expected):
    cases = () if status is InspectionStatus.NOT_RUN else (
        InspectionCaseResult(field, status, reason, "goal comparison differed", (report.request,)),
    )
    goal = InspectionGoalResult(status, cases, () if not cases else (report.request,))
    assert replace(report, **{field: goal}).status is expected






@pytest.mark.risk_cases('SM-07-C08')
def test_SM_07_C08_unknown_report_field_rejected(report):
    value = report.to_dict()
    value["checks"] = []
    with pytest.raises(ValueError, match="fields/type"):
        CandidateInspectionReport.from_dict(value)


@pytest.mark.risk_cases('SM-07-C07')
def test_SM_07_C07_retired_report_rejected(report):
    with pytest.raises(ValueError, match="unsupported"):
        replace(report, schema_version=1)




@pytest.mark.risk_cases('SM-09-C02')
def test_SM_09_C02_release_rejects_duplicate_installation_path(report):
    with pytest.raises(ValueError, match="unique"):
        replace(report.release, files=report.release.files * 2)






@pytest.mark.risk_cases('SM-09-C01')
def test_SM_09_C01_plan_requires_typed_date(report):
    with pytest.raises(TypeError, match="date"):
        replace(report.plan, forward_start="2026-10-22")


@pytest.mark.risk_cases('SM-09-C04')
def test_SM_09_C04_forward_starts_strictly_after_selection(report):
    with pytest.raises(ValueError, match="follow"):
        replace(report.plan, forward_start=report.plan.selection_data_cutoff)
