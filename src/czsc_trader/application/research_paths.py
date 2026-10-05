"""Resolve caller-declared locations without inspecting a research directory layout."""

from strategy_manager import CandidateEvidence, CandidateKey, ResearchEvidenceRef

from .delivery_service import _resolve, _experiment_path
from ..research_tools.delivery import ExperimentOwner
from ..research_tools.workspace import ResearchWorkspace


def workspace(context):
    if type(context.research_workspace) is not ResearchWorkspace:
        raise ValueError("explicit ResearchWorkspace is required")
    return context.research_workspace


def registry_root(context):
    return _resolve(context.root, workspace(context).registry_path)


def evidence_location(context, owner):
    for location in workspace(context).evidence:
        if location.owner == owner:
            return location
    raise ValueError("research evidence owner location is not declared")


def evidence_root(context, owner):
    return _resolve(context.root, evidence_location(context, owner).path)


def resolve_evidence(context, ref):
    if type(ref) is ResearchEvidenceRef:
        return ref.resolve(context.root, location=evidence_location(context, ref.owner))
    if type(ref) is CandidateEvidence:
        _resolve(context.root, ref.path)
        return ref.resolve(context.root)
    raise TypeError("evidence requires ResearchEvidenceRef or CandidateEvidence")


def candidate_root(context, key, *, experiment_id=None):
    if type(key) is not CandidateKey:
        raise TypeError("candidate location requires CandidateKey")
    for location in workspace(context).candidates:
        if location.key == key:
            if experiment_id is not None and experiment_id != location.experiment_id:
                raise ValueError("candidate location experiment differs from origin")
            return _experiment_path(context, ExperimentOwner(key.strategy_id, location.experiment_id))
    raise ValueError("candidate location is not declared")


def journal_root(context, request_id):
    for location in workspace(context).freeze_journals:
        if location.strategy_id == request_id.strategy_id:
            return _resolve(context.root, location.path)
    raise ValueError("freeze journal location is not declared")
