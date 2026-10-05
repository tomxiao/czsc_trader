"""Research-owned immutable decisions, inspection evidence and approval validation."""

from dataclasses import replace
from hashlib import sha256

from strategy_manager import freeze_contracts as f
from strategy_manager.candidates import CandidateRegistration
from strategy_manager.models import StrategyVersion, canonical_sha256
from strategy_manager.write_lock import RegistryWriteLock
from strategy_manager.freeze_store import _bytes, _read, _durable
from .research_paths import resolve_evidence, evidence_root
from .research_storage import require_research_write
from .delivery_service import _resolve


def read_decision(context, ref):
    if type(ref) is not f.DecisionReference:
        raise TypeError("decision requires DecisionReference")
    decision = f.ResearchDecision.from_dict(_read(resolve_evidence(context, ref.evidence)))
    if ref.decision_id != decision.decision_id:
        raise ValueError("decision identity differs")
    if (
        type(decision.confirmation_source) is not f.ResearchEvidenceRef
        or ref.evidence.owner != f.ResearchEvidenceOwner(decision.strategy_id)
        or decision.confirmation_source.owner != ref.evidence.owner
    ):
        raise ValueError("decision evidence owner differs")
    resolve_evidence(context, decision.confirmation_source)
    return decision


def record_decision(context, decision):
    owner = f.ResearchEvidenceOwner(decision.strategy_id)
    if type(decision.confirmation_source) is not f.ResearchEvidenceRef:
        raise TypeError("persisted confirmation requires ResearchEvidenceRef")
    resolve_evidence(context, decision.confirmation_source)
    ref = f.DecisionReference(
        decision.decision_id,
        f.ResearchEvidenceRef(
            owner,
            f"decisions/{decision.decision_id}.json",
            sha256(_bytes(decision.to_dict())).hexdigest(),
        ),
    )
    path = _resolve(evidence_root(context, owner), ref.evidence.path)
    if not path.exists():
        require_research_write(context, path)
    with RegistryWriteLock(context.root / ".tmp/research-locks" / decision.strategy_id).hold():
        if path.exists():
            resolve_evidence(context, ref.evidence)
        else:
            require_research_write(context, path)
            _durable(path, decision.to_dict(), temporary_root=context.root / ".tmp/research")
    return ref


def validate_inspection(context, reference):
    report = f.CandidateInspectionReport.from_dict(_read(resolve_evidence(context, reference)))
    if report.reference != reference:
        raise ValueError("inspection reference differs from report owner")
    plan = report.plan
    for ref in (
        plan.origin.registration,
        plan.payload,
        plan.runtime_binding,
        *plan.registration_evidence,
        *(x.source for x in plan.source_files),
        *(ref for check in report.checks for ref in check.evidence),
    ):
        if type(ref) is not f.ResearchEvidenceRef or ref.owner != report.owner:
            raise ValueError("inspection evidence owner differs")
    registration = CandidateRegistration.from_dict(_read(resolve_evidence(context, plan.origin.registration)))
    if (
        registration.key != plan.origin.candidate
        or registration.content_sha256 != plan.origin.content_sha256
        or registration.record_sha256 != plan.origin.registration_sha256
        or registration.payload.sha256 != plan.payload.sha256
        or registration.origin.experiment_id != plan.source_experiment
    ):
        raise ValueError("inspection registration origin differs")
    required = {registration.origin.preflight.sha256}
    if registration.derivation:
        required.add(registration.derivation.evidence.sha256)
    if {ref.sha256 for ref in plan.registration_evidence} != required:
        raise ValueError("inspection registration evidence closure differs")
    selection = read_decision(context, report.selection)
    if (
        selection.action is not f.DecisionAction.APPROVE
        or type(selection.subject) is not f.CandidateSelectionSubject
        or selection.subject.candidate != plan.origin.candidate
        or selection.subject.content_sha256 != plan.origin.content_sha256
    ):
        raise ValueError("inspection selection differs")
    for ref in (
        plan.payload,
        plan.runtime_binding,
        *plan.registration_evidence,
        *(x.source for x in plan.source_files),
    ):
        resolve_evidence(context, ref)
    for check in report.checks:
        for ref in check.evidence:
            resolve_evidence(context, ref)
    return report


def validate_approval(context, request):
    report = validate_inspection(context, request.inspection)
    approval = read_decision(context, request.approval)
    plan = report.plan
    expected = f.FreezeSubject(
        plan.origin.candidate,
        plan.origin.content_sha256,
        request.inspection,
        plan.sha256,
        plan.version,
    )
    if (
        report.status is not f.InspectionStatus.PASS
        or approval.action is not f.DecisionAction.APPROVE
        or approval.subject != expected
        or request.request_id.strategy_id != plan.origin.candidate.strategy_id
    ):
        raise ValueError("freeze requires matching approval and complete passing inspection")
    return report


def build_version(context, request):
    report = validate_approval(context, request)
    plan = report.plan
    candidate = plan.origin.candidate
    version = StrategyVersion(
        5,
        candidate.strategy_id,
        plan.version,
        f"{candidate.strategy_id}-{plan.version}",
        plan.parent_version,
        plan.change_summary,
        plan.source_experiment,
        candidate.candidate_id,
        plan.selection_data_cutoff,
        plan.forward_start,
        _read(resolve_evidence(context, plan.payload)),
        "0" * 64,
    )
    return StrategyVersion.from_dict(
        replace(version, release_hash=canonical_sha256(version.release_payload())).to_dict()
    )
