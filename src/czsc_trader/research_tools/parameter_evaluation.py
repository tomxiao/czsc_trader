"""Published parameter designs bound to actual candidate and account identities."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import TYPE_CHECKING

from strategy_evaluator import (
    AssessmentCandidate, ParameterPerturbationDesign, ParameterPointBinding,
)
from dataflows import Dataflows
from strategy_runtime import canonical_sha256, StrategyInputBinding, StrategyRuntime

from ._records import _Record, _hash, _unique
from .evidence import EvidenceRef

if TYPE_CHECKING:
    from .evaluation import EvaluationRequest


@dataclass(frozen=True, slots=True)
class ParameterEvaluationCandidate(_Record):
    candidate: AssessmentCandidate
    runtime_identity_sha256: str
    payload_json: str

    def _validate(self):
        _hash(self.runtime_identity_sha256)
        payload = json.loads(self.payload_json)
        if type(payload) is not dict or _payload_json(payload) != self.payload_json:
            raise ValueError("parameter candidate requires canonical JSON object payload")


@dataclass(frozen=True, slots=True)
class ParameterEvaluationBinding(_Record):
    plan: EvidenceRef
    point: ParameterPointBinding


@dataclass(frozen=True, slots=True)
class ParameterEvaluationInput(_Record):
    window_id: str
    binding_json: str

    def _validate(self):
        StrategyInputBinding.from_mapping(json.loads(self.binding_json))


@dataclass(frozen=True, slots=True)
class ParameterEvaluationPlan(_Record):
    """Complete prospective plan; coordinates are materialized by the researcher."""

    design: ParameterPerturbationDesign
    center: ParameterEvaluationCandidate
    center_request_sha256: str
    nonparameter_context_sha256: str
    children: tuple[ParameterEvaluationCandidate, ...]
    mapping_evidence: EvidenceRef
    feasibility_evidence: EvidenceRef
    center_inputs: tuple[ParameterEvaluationInput, ...]
    execution_contract_json: str
    schema_version: int = 1

    def _validate(self):
        if self.schema_version != 1:
            raise ValueError("parameter evaluation plan requires schema 1")
        _hash(self.center_request_sha256)
        _hash(self.nonparameter_context_sha256)
        _unique((x.window_id for x in self.center_inputs), "parameter center input window")
        if not self.center_inputs:
            raise ValueError("parameter plan requires prepared center inputs")
        if _payload_json(json.loads(self.execution_contract_json)) != self.execution_contract_json:
            raise ValueError("parameter execution contract must be canonical JSON")
        if self.center.candidate != self.design.center:
            raise ValueError("parameter center payload identity differs from design")
        if (self.mapping_evidence.sha256 != self.design.space.mapping_sha256
            or self.feasibility_evidence.sha256 != self.design.space.feasibility_sha256):
            raise ValueError("parameter mapping or feasibility evidence differs from design")
        if len(self.children) != len(self.design.points):
            raise ValueError("parameter plan must cover every design point")
        _unique((x.candidate.candidate_id for x in self.children), "parameter child candidate")
        _unique((self.design.center.content_sha256,
                 *(x.candidate.content_sha256 for x in self.children)), "parameter candidate content")
        _unique((self.center.payload_json, *(x.payload_json for x in self.children)), "parameter candidate payload")
        if self.design.center.candidate_id in {x.candidate.candidate_id for x in self.children}:
            raise ValueError("parameter center and children must have distinct identities")
        family = self.design.center.candidate_id.split("-", 1)[0]
        if any(x.experiment.strategy_id != family for x in (self.mapping_evidence, self.feasibility_evidence)):
            raise ValueError("parameter mapping and feasibility evidence must belong to center family")
        if any(x.candidate.candidate_id.split("-", 1)[0] != family for x in self.children):
            raise ValueError("parameter children must belong to center strategy family")

    @classmethod
    def create(cls, design: ParameterPerturbationDesign, center: EvaluationRequest,
               children: tuple[EvaluationRequest, ...], *, mapping_evidence: EvidenceRef,
               feasibility_evidence: EvidenceRef, dataflows: Dataflows) -> ParameterEvaluationPlan:
        """Authenticate prepared inputs, without evaluating or publishing accounts."""
        from .evaluation import EvaluationRequest, _request_contract

        if type(design) is not ParameterPerturbationDesign:
            raise TypeError("parameter plan requires ParameterPerturbationDesign")
        if type(children) is not tuple or any(type(x) is not EvaluationRequest for x in children):
            raise TypeError("parameter children require a tuple of EvaluationRequest")
        if type(center) is not EvaluationRequest:
            raise TypeError("parameter center requires EvaluationRequest")
        if not center.input_bindings or any(not x.input_bindings for x in children):
            raise ValueError("parameter plan requires prepared center and child inputs")
        if (not isinstance(dataflows, Dataflows)
            or Path(center.repository_root).resolve() != dataflows.binding.base_dir
            or any(Path(x.repository_root).resolve() != Path(center.repository_root).resolve() for x in children)):
            raise ValueError("parameter plan inputs must use the same repository data context")
        mapping_evidence.resolve(center.repository_root)
        feasibility_evidence.resolve(center.repository_root)
        if any(x.lineage and x.lineage.parameter_binding for x in (center, *children)):
            raise ValueError("create the prospective plan before adding point bindings")
        central = _request_contract(center)[0]
        if design.center != AssessmentCandidate(center.strategy.reference_id, central["content_sha256"]):
            raise ValueError("parameter design differs from actual center")
        context = central["nonparameter_context_sha256"]
        execution_contract = _execution_contract(center)
        values = []
        for child in children:
            contract = _request_contract(child)[0]
            if child.strategy.strategy_family_id != center.strategy.strategy_family_id:
                raise ValueError("parameter child belongs to another strategy family")
            if contract["nonparameter_context_sha256"] != context:
                raise ValueError("parameter child nonparameter context differs from center")
            _compare_raw_inputs(center.input_bindings, child.input_bindings, dataflows)
            if _execution_contract(child) != execution_contract:
                raise ValueError("parameter child SRT execution contract differs from center")
            values.append(ParameterEvaluationCandidate(
                AssessmentCandidate(child.strategy.reference_id, contract["content_sha256"]),
                child.strategy.runtime_identity_sha256,
                _payload_json(child.strategy.payload),
            ))
        actual_center = ParameterEvaluationCandidate(design.center, center.strategy.runtime_identity_sha256,
                                                    _payload_json(center.strategy.payload))
        return cls(design, actual_center, canonical_sha256(central), context, tuple(values),
                   mapping_evidence, feasibility_evidence,
                   tuple(ParameterEvaluationInput(name, _payload_json(binding.to_dict()))
                         for name, binding in sorted(center.input_bindings.items())), execution_contract)

    def bind_point(self, reference: EvidenceRef, index: int, *, repository_root: Path) -> ParameterEvaluationBinding:
        """Bind only after the exact plan bytes have been explicitly published."""
        if read_parameter_plan(reference, repository_root) != self:
            raise ValueError("published parameter plan differs")
        if reference.experiment.strategy_id != self.design.center.candidate_id.split("-", 1)[0]:
            raise ValueError("published parameter plan belongs to another strategy family")
        return ParameterEvaluationBinding(reference, self.design.bind_point(index))


def read_parameter_plan(reference: EvidenceRef, repository_root: Path) -> ParameterEvaluationPlan:
    if type(reference) is not EvidenceRef or reference.media_type != "application/json":
        raise TypeError("parameter plan requires published JSON EvidenceRef")
    plan = ParameterEvaluationPlan.from_dict(json.loads(reference.resolve(repository_root).read_text(encoding="utf-8")))
    plan.mapping_evidence.resolve(repository_root)
    plan.feasibility_evidence.resolve(repository_root)
    return plan


def validate_parameter_contract(contract: dict, plan: ParameterEvaluationPlan,
                                binding: ParameterEvaluationBinding) -> None:
    point = plan.design.bind_point(binding.point.point_index)
    if point != binding.point:
        raise ValueError("parameter binding differs from prescribed design point")
    child = plan.children[binding.point.point_index]
    if (contract["strategy_reference"], contract["content_sha256"], contract["strategy_identity"]) != (
        child.candidate.candidate_id, child.candidate.content_sha256, child.runtime_identity_sha256,
    ):
        raise ValueError("parameter plan differs from actual child content")
    if contract["nonparameter_context_sha256"] != plan.nonparameter_context_sha256:
        raise ValueError("parameter evaluation nonparameter context differs")
    lineage = contract["lineage"]
    if lineage is None or lineage["kind"] != "PARAMETERS":
        raise ValueError("parameter evaluation requires PARAMETERS lineage")
    parent = lineage["parent"]
    if (f"{parent['strategy_id']}-{parent['candidate_id']}", lineage["parent_content_sha256"]) != (
        plan.design.center.candidate_id, plan.design.center.content_sha256,
    ):
        raise ValueError("parameter lineage differs from planned center")
    if (lineage["child_content_sha256"] != child.candidate.content_sha256
        or f"{lineage['child']['strategy_id']}-{lineage['child']['candidate_id']}" != child.candidate.candidate_id):
        raise ValueError("parameter lineage differs from planned child")


def validate_parameter_request(request, dataflows: Dataflows) -> None:
    if request.lineage is None or request.lineage.parameter_binding is None:
        return
    from .evaluation import _request_contract

    binding = request.lineage.parameter_binding
    plan = read_parameter_plan(binding.plan, request.repository_root)
    if binding.plan.experiment.strategy_id != request.strategy.strategy_family_id:
        raise ValueError("parameter plan belongs to another strategy family")
    validate_parameter_contract(_request_contract(request)[0], plan, binding)
    if _payload_json(request.strategy.payload) != plan.children[binding.point.point_index].payload_json:
        raise ValueError("parameter candidate payload differs from plan")
    _compare_raw_inputs({x.window_id: StrategyInputBinding.from_mapping(json.loads(x.binding_json))
                         for x in plan.center_inputs}, request.input_bindings, dataflows)
    if _execution_contract(request) != plan.execution_contract_json:
        raise ValueError("parameter evaluation SRT execution contract differs")


def _payload_json(payload) -> str:
    return json.dumps(payload, default=dict, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def parameter_execution_policy(policy: dict) -> dict:
    """Explicit evaluation costs override these strategy fee settings."""
    policy = json.loads(_payload_json(policy))
    settings = policy["settings"]
    if policy["policy_type"] == "FROZEN_RULE":
        settings["capital"].pop("fee_rate", None)
    elif policy["policy_type"] == "INTRADAY_OVERLAY":
        settings.pop("one_way_cost", None)
    return policy


def _execution_contract(request: EvaluationRequest) -> str:
    definition = StrategyRuntime().describe(request.strategy)
    return _payload_json({
        "policy": parameter_execution_policy({"policy_type": definition.execution.policy_type,
                                               "settings": definition.execution.settings}),
        "decision_output_kind": definition.decision.output_kind,
        "decision_effective_time_rule": definition.decision.effective_time_rule,
        "order_types": definition.capabilities.order_types,
        "checkpoints": definition.capabilities.checkpoints,
    })


def _compare_raw_inputs(center, child, dataflows: Dataflows) -> None:
    """Compare pinned raw source values on their common range; permit lookback extension."""
    if not isinstance(dataflows, Dataflows):
        raise TypeError("parameter input comparison requires Dataflows")
    if set(center) != set(child):
        raise ValueError("parameter input windows differ")
    for window, original in center.items():
        current = child[window]
        if (original.prepared.space_id != current.prepared.space_id
            or original.prepared.space_id != dataflows.binding.space_id
            or set(original.plan.requests) != set(current.plan.requests)):
            raise ValueError("parameter raw input space or roles differ")
        for role, original_request in original.plan.requests.items():
            current_request = current.plan.requests[role]
            original_contract = dict(original.plan.to_dict()["requests"][role])
            current_contract = dict(current.plan.to_dict()["requests"][role])
            original_contract.pop("start")
            current_contract.pop("start")
            for contract in (original_contract, current_contract):
                if contract["coverage"] is not None:
                    contract["coverage"].pop("minimum_observations")
                    contract["coverage"].pop("minimum_sessions")
            if original_contract != current_contract:
                fields = sorted(key for key in original_contract
                                if original_contract[key] != current_contract.get(key))
                raise ValueError(f"parameter raw input source contract differs: {window}/{role}: {fields}")
            coverage = original_request.coverage
            if coverage is not None:
                coverage = replace(coverage,
                    minimum_observations=min(coverage.minimum_observations, current_request.coverage.minimum_observations),
                    minimum_sessions=min(coverage.minimum_sessions, current_request.coverage.minimum_sessions))
            common = replace(original_request, start=max(original_request.start, current_request.start), coverage=coverage)
            old = dataflows.fetch(common, prepared=original.prepared)
            new = dataflows.fetch(common, prepared=current.prepared)
            if not old.ready or not new.ready:
                raise ValueError("parameter raw input comparison requires complete pinned inputs")
            if (old.identity.content_sha256, old.identity.source, old.identity.temporal_contract) != (
                new.identity.content_sha256, new.identity.source, new.identity.temporal_contract,
            ):
                raise ValueError("parameter raw input source or values differ on common range")
