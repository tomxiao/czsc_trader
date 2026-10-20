"""Explicit S014 stage-four publication helpers; importing performs no writes.

Callers provide actual authenticated results, the predeclared policy, reports,
and user-authorization material. This module never runs a research account or
records stage-five selection/freezing decisions.
"""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from strategy_evaluator import (
    AssessmentCandidate, AssessmentEvidence, CandidateAssessmentRequest,
    CandidateComparisonRequest, ComparisonPolicy, FamilyReturnEvidence,
    ResearchTargets, assess_candidates, compare_candidates,
)
from strategy_manager import CandidateDerivation
from strategy_runtime import ImplementationDependency, StrategyCandidate
from czsc_trader.application import (
    CandidateRegistrationRequest, RepositoryContext, assemble_delivery,
    load_candidate, register_candidate, validate_delivery,
)
from czsc_trader.research_tools import (
    BenchmarkRequirement, CandidateAssessmentDelivery, CandidateEntry,
    CandidateIdentityRef, ConfirmationStatus, DeliveryContent,
    DeliveryDefinition, DeliveryReceipt, DeliveryReference, DeliveryStage,
    DeliveryStatus, DeliveryValidationScope, EvaluationEvidenceRef, EvidenceRef,
    NumericRequirement, PerformanceRequirement,
    TargetMandateBinding, ValidationStatus,
)
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence


def read_account(repository_root: Path, reference: EvidenceRef):
    """Read and independently authenticate a published schema-seven account."""
    if (reference.schema, reference.schema_version) != ('account_evaluation', 7):
        raise ValueError('schema-seven account evidence required')
    data = reference.resolve(repository_root).read_bytes()
    if sha256(data).hexdigest() != reference.sha256:
        raise ValueError('account changed while reading')
    document = json.loads(data)
    validate_evaluation_evidence(document)
    records = tuple(AssessmentEvidence.from_dict(x) for x in document['assessment_evidence'])
    if any(x.experiment_id != reference.experiment.experiment_id
           or not x.candidate.candidate_id.startswith(reference.experiment.strategy_id + '-')
           for x in records):
        raise ValueError('account evidence origin differs')
    return document, records


def read_delivery_content(repository: RepositoryContext, reference: DeliveryReference):
    """Read typed retained content with receipt and JSON-byte authentication.

    This is a local read, not a substitute for validate_delivery(FULL). Public
    assembly and the explicit final validation independently verify all assets.
    """
    root = repository.root / 'research' / reference.strategy_id / 'assets/deliveries' / reference.stage.value / str(reference.revision)
    receipt = DeliveryReceipt.from_dict(json.loads((root / 'receipt.json').read_bytes()))
    if receipt.reference != reference:
        raise ValueError('delivery receipt identity differs')
    document_bytes = (root / 'delivery.json').read_bytes()
    file = next(x for x in receipt.files if x.path == 'delivery.json')
    if sha256(document_bytes).hexdigest() != file.sha256:
        raise ValueError('delivery JSON bytes differ from receipt')
    return DeliveryContent.from_dict(json.loads(document_bytes)['content'])


def family_from_records(records: tuple[AssessmentEvidence, ...], *,
                        candidates: tuple[AssessmentCandidate, ...],
                        selected: AssessmentCandidate, raw_trial_count: int,
                        baseline_window: str, standard_scenario: str,
                        limitations: tuple[str, ...]) -> FamilyReturnEvidence:
    """Build the SE matrix with the exact SE NumPy return calculation.

    The caller chooses the complete defensible study family and explains all
    unavailable/excluded trials; neither count nor selection is inferred here.
    """
    if not candidates or selected not in candidates:
        raise ValueError('family needs explicit members including selected')
    columns, sessions, contexts = [], None, set()
    for candidate in candidates:
        matches = [x for x in records if x.candidate == candidate
                   and x.window_id == baseline_window and x.scenario_id == standard_scenario]
        if len(matches) != 1:
            raise ValueError(f'exactly one baseline account required: {candidate.candidate_id}')
        evidence = matches[0]
        calendar = tuple(x.session for x in evidence.account)
        if sessions is not None and calendar != sessions:
            raise ValueError('family calendars differ')
        sessions = calendar
        contexts.add((evidence.context_sha256, evidence.metric_version, evidence.scenario_context))
        equity = np.asarray([x.equity for x in evidence.account])
        columns.append(equity / np.r_[evidence.initial_cash, equity[:-1]] - 1)
    if len(contexts) != 1:
        raise ValueError('family evaluation contexts differ')
    matrix = np.column_stack(columns)
    return FamilyReturnEvidence(candidates, sessions,
        tuple(tuple(float(x) for x in row) for row in matrix),
        selected, raw_trial_count, limitations)


def _validated_publication(repository, definition, content):
    print('ASSEMBLY_STARTED', definition.stage.value, definition.revision, flush=True)
    receipt = assemble_delivery(repository, definition, content)
    print('ASSEMBLY_PUBLISHED', definition.stage.value, definition.revision, flush=True)
    validation = validate_delivery(repository, receipt.reference,
                                   scope=DeliveryValidationScope.FULL)
    if validation.status is not ValidationStatus.PASS:
        raise ValueError(f'published delivery FULL validation failed: {validation}')
    print('FULL_VALIDATED', definition.stage.value, definition.revision, flush=True)
    return receipt, validation


def publish_candidate_successor(repository: RepositoryContext, *,
        candidate: StrategyCandidate, account_reference: EvidenceRef,
        derivation: CandidateDerivation, dependencies: tuple[ImplementationDependency, ...],
        source_candidates: DeliveryReference, revision: int,
        predecessors: tuple[DeliveryReference, ...],
        equivalence_evidence: EvidenceRef, authorization_evidence: EvidenceRef,
        hypothesis: str, judgment: str, conclusion: str, report: str,
        additional_evidence: tuple[EvidenceRef, ...] = ()):
    """Register the technical successor and retain all 69 historical entries.

    Invoke only after the caller verifies the actual full-account equivalence
    evidence and original annual economic targets. Historical candidates and
    search histories remain intact; the handoff contains only the successor.
    """
    prior = read_delivery_content(repository, source_candidates)
    if source_candidates.stage is not DeliveryStage.CANDIDATES:
        raise ValueError('candidate predecessor required')
    if len(prior.payload.candidates) != 69:
        raise ValueError('expected the 69-entry S014 stage-three predecessor')
    _, records = read_account(repository.root, account_reference)
    registration = register_candidate(repository, CandidateRegistrationRequest(
        candidate, account_reference.experiment, (account_reference,), dependencies, derivation))
    loaded = load_candidate(repository, registration.key)
    if loaded.runtime_identity_sha256 != candidate.runtime_identity_sha256:
        raise ValueError('registered successor runtime identity differs')
    if any(x.candidate != AssessmentCandidate(candidate.reference_id, registration.content_sha256)
           for x in records):
        raise ValueError('successor account identity differs')
    entry = CandidateEntry(CandidateIdentityRef(registration.key, registration.content_sha256),
                           hypothesis, judgment, (EvaluationEvidenceRef(account_reference),))
    payload = replace(prior.payload, candidates=prior.payload.candidates + (entry,),
                      handoff=(registration.key,), conclusion=conclusion)
    evidence = tuple(dict.fromkeys(prior.evidence + (equivalence_evidence,
        authorization_evidence) + additional_evidence))
    # Prior scalar facts describe its 69-entry snapshot and must not become
    # current claims (for example, the old "stage four not executed" fact).
    content = DeliveryContent(payload, DeliveryStatus.COMPLETE, (), (),
                              report=report, evidence=evidence)
    receipt, validation = _validated_publication(repository,
        DeliveryDefinition(source_candidates.batch, DeliveryStage.CANDIDATES,
                           revision, predecessors), content)
    return registration, receipt, validation


def publish_assessment(repository: RepositoryContext, *,
        request: CandidateAssessmentRequest, policy: ComparisonPolicy,
        source_candidates: DeliveryReference, source_mandate: DeliveryReference,
        revision: int, parameter_plans: tuple[EvidenceRef, ...],
        evidence: tuple[EvidenceRef, ...], contrary_evidence: tuple[EvidenceRef, ...],
        recommendation: str, pending_decisions: tuple[str, ...], report: str,
        incomplete_items: tuple[str, ...] = ()):
    """Compute the declared SE diagnostics/ranking and publish exact facts.

    Annual user goals require a separate caller-supplied numeric audit in
    evidence/report; SE does not turn annual goals into aggregate substitutes.
    """
    mandate = read_delivery_content(repository, source_mandate).payload
    targets, bindings, frequency, benchmark = [], [], None, None
    for item in mandate.items:
        if item.confirmation.status is not ConfirmationStatus.CONFIRMED:
            continue
        requirement = item.requirement
        if isinstance(requirement, PerformanceRequirement):
            for target in requirement.targets:
                targets.append(target)
                bindings.append(TargetMandateBinding(target.target_id, item.item_id))
        elif isinstance(requirement, NumericRequirement) and requirement.metric == 'frequency_window_days':
            if requirement.lower != requirement.upper or requirement.lower is None:
                raise ValueError('frequency window must be a confirmed exact session count')
            frequency = (item.item_id, int(requirement.lower))
        elif isinstance(requirement, BenchmarkRequirement):
            if benchmark is not None:
                raise ValueError('multiple confirmed benchmark mandates')
            benchmark = item.item_id
    if frequency is None or benchmark is None:
        raise ValueError('confirmed S014 frequency and benchmark mandates required')
    panel = assess_candidates(request)
    comparison_request = CandidateComparisonRequest(request.centers,
        ResearchTargets(tuple(targets), frequency[1]), panel, policy)
    comparison = compare_candidates(comparison_request)
    payload = CandidateAssessmentDelivery(source_candidates, source_mandate,
        request, panel, comparison_request, comparison, tuple(bindings), frequency[0],
        benchmark, recommendation, contrary_evidence, pending_decisions, parameter_plans)
    status = DeliveryStatus.PARTIAL if incomplete_items else DeliveryStatus.COMPLETE
    content = DeliveryContent(payload, status, (), (), incomplete_items,
                              report=report, evidence=evidence)
    receipt, validation = _validated_publication(repository,
        DeliveryDefinition(source_candidates.batch, DeliveryStage.ASSESSMENT,
                           revision, (source_candidates, source_mandate)), content)
    return receipt, validation, panel, comparison
