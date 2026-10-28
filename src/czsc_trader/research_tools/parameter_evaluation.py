"""Published parameter designs bound to actual candidate and account identities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import json
from pathlib import Path
from typing import TYPE_CHECKING

from strategy_evaluator import (
    AssessmentCandidate, ParameterPerturbationDesign, ParameterPointBinding,
)
from strategy_evaluator.parameter_neighborhood import (
    ParameterNeighborhoodDesign, ParameterNeighborhoodBinding, StudyPurpose,
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
    point: ParameterNeighborhoodBinding | ParameterPointBinding


@dataclass(frozen=True, slots=True)
class ParameterEvaluationInput(_Record):
    window_id: str
    binding_json: str

    def _validate(self):
        value = json.loads(self.binding_json)
        if value.get("kind") == "US_EQUITY":
            from strategy_runtime.equity_definition import EquityInputBinding
            if set(value) != {"kind", "binding"}:
                raise ValueError("equity parameter input fields differ")
            EquityInputBinding.from_dict(value["binding"])
        else:
            StrategyInputBinding.from_mapping(value)


@dataclass(frozen=True, slots=True)
class ParameterEvaluationPlan(_Record):
    """Complete prospective plan; coordinates are materialized by the researcher."""

    design: ParameterNeighborhoodDesign | ParameterPerturbationDesign
    center: ParameterEvaluationCandidate
    center_request_sha256: str
    nonparameter_context_sha256: str
    children: tuple[ParameterEvaluationCandidate, ...]
    mapping_evidence: EvidenceRef
    feasibility_evidence: EvidenceRef
    center_inputs: tuple[ParameterEvaluationInput, ...]
    execution_contract_json: str
    schema_version: int = 3

    def _validate(self):
        equity = json.loads(self.center.payload_json).get("runtime", {}).get("kind") == "US_EQUITY"
        if self.design.protocol.version == "parameter-cartesian-neighborhood-v2":
            expected = 4 if equity else 3
        else:
            expected = 2 if type(self.design) is ParameterNeighborhoodDesign else 1
        if self.schema_version != expected:
            raise ValueError("parameter evaluation plan schema differs from design kind")
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
        if self.schema_version in (2, 3, 4):
            if self.design.protocol.purpose is not StudyPurpose.LOCAL_SENSITIVITY:
                raise ValueError("parameter evaluation plans require local sensitivity; structural controls are separate")
            _validate_parameter_payloads(self.design, self.center, self.children)
        if self.schema_version in (3, 4) and not self.design.is_applicable:
            if type(_parameter_payload(json.loads(self.center.payload_json)).get("parameters")) is not dict:
                raise ValueError("not-applicable plan requires an explicit parameter object")

    @classmethod
    def create(cls, design: ParameterNeighborhoodDesign, center: EvaluationRequest,
               children: tuple[EvaluationRequest, ...], *, mapping_evidence: EvidenceRef,
               feasibility_evidence: EvidenceRef, dataflows: Dataflows) -> ParameterEvaluationPlan:
        """Authenticate prepared inputs, without evaluating or publishing accounts."""
        from .evaluation import EvaluationRequest, _request_contract
        from .equity_evaluation import EquityEvaluationRequest

        if type(center) is EquityEvaluationRequest:
            return _create_equity_plan(cls, design, center, children,
                mapping_evidence=mapping_evidence, feasibility_evidence=feasibility_evidence, dataflows=dataflows)

        if type(design) is not ParameterNeighborhoodDesign:
            raise TypeError("new parameter plan requires ParameterNeighborhoodDesign; legacy sphere plans are read-only")
        if design.protocol.version != "parameter-cartesian-neighborhood-v2":
            raise ValueError("historical parameter designs are read-only; new plans require neighborhood v2")
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
        if self.schema_version not in (3, 4):
            raise ValueError("historical parameter plans are read-only")
        if not self.design.is_applicable:
            raise ValueError("not-applicable parameter plans have no point to bind")
        if read_parameter_plan(reference, repository_root) != self:
            raise ValueError("published parameter plan differs")
        if reference.experiment.strategy_id != self.design.center.candidate_id.split("-", 1)[0]:
            raise ValueError("published parameter plan belongs to another strategy family")
        return ParameterEvaluationBinding(reference, self.design.bind_point(index))


def read_parameter_plan(reference: EvidenceRef, repository_root: Path) -> ParameterEvaluationPlan:
    if type(reference) is not EvidenceRef or reference.media_type != "application/json":
        raise TypeError("parameter plan requires published JSON EvidenceRef")
    plan = _decode_parameter_plan(reference._read_verified(repository_root)[1])
    plan.mapping_evidence.resolve(repository_root)
    plan.feasibility_evidence.resolve(repository_root)
    return plan


@lru_cache(maxsize=1)
def _decode_parameter_plan(data: bytes) -> ParameterEvaluationPlan:
    """Reuse immutable decoding only; each caller still verifies all evidence bytes."""
    return ParameterEvaluationPlan.from_dict(json.loads(data.decode("utf-8")))


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
    from .equity_evaluation import EquityEvaluationRequest

    if type(request) is EquityEvaluationRequest:
        _validate_equity_parameter_request(request, dataflows)
        return

    binding = request.lineage.parameter_binding
    plan = read_parameter_plan(binding.plan, request.repository_root)
    if plan.schema_version != 3:
        raise ValueError("historical parameter plans are read-only; new evaluations require schema 3")
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


def _parameter_parent(payload: dict, path: tuple[str, ...]) -> tuple[dict, str]:
    """Resolve an existing object leaf below parameters; never create or coerce it."""
    if not path or any(type(part) is not str or not part for part in path):
        raise ValueError("parameter payload path requires nonempty string components")
    node = payload.get("parameters")
    for part in path[:-1]:
        if type(node) is not dict or part not in node:
            raise ValueError(f"parameter payload path does not exist: {path}")
        node = node[part]
    if type(node) is not dict or path[-1] not in node:
        raise ValueError(f"parameter payload path does not exist: {path}")
    return node, path[-1]


def _validate_parameter_payloads(design, center, children) -> None:
    """Authenticate declared typed points against every byte of candidate payloads."""
    original = _parameter_payload(json.loads(center.payload_json))
    axes = design.space.axes
    paths = tuple(axis.payload_path for axis in axes)
    for i, path in enumerate(paths):
        if any(path[:len(other)] == other or other[:len(path)] == path
               for other in paths[:i]):
            raise ValueError("parameter payload paths overlap")
    for axis in axes:
        parent, key = _parameter_parent(original, axis.payload_path)
        if type(parent[key]) is not type(axis.center) or parent[key] != axis.center:
            raise ValueError(f"parameter center payload differs at {axis.payload_path}")
    for point, child in zip(design.points, children, strict=True):
        expected = _parameter_payload(json.loads(center.payload_json))
        if tuple(value.name for value in point.values) != tuple(axis.name for axis in axes):
            raise ValueError("parameter point names differ from declared axes")
        for axis, value in zip(axes, point.values, strict=True):
            parent, key = _parameter_parent(expected, axis.payload_path)
            parent[key] = value.value
        if _payload_json(expected) != _payload_json(_parameter_payload(json.loads(child.payload_json))):
            raise ValueError("parameter child payload differs from declared point mapping; undeclared changes are forbidden")


def parameter_execution_policy(policy: dict) -> dict:
    """Explicit evaluation costs override these strategy fee settings."""
    policy = json.loads(_payload_json(policy))
    settings = policy["settings"]
    if policy["policy_type"] == "FROZEN_RULE":
        settings["capital"].pop("fee_rate", None)
    elif policy["policy_type"] == "INTRADAY_OVERLAY":
        settings.pop("one_way_cost", None)
    return policy


def _parameter_payload(payload):
    """Expose declared equity parameters without weakening whole-payload comparison."""
    if payload.get("runtime", {}).get("kind") != "US_EQUITY":
        return payload
    payload = json.loads(_payload_json(payload))
    if "parameters" in payload:
        raise ValueError("equity parameter payload has ambiguous parameter fields")
    payload["parameters"] = json.loads(payload["equity_definition"].pop("parameters_json"))
    return payload


def equity_planned_identity(payload):
    from strategy_runtime.equity_definition import EquityStrategyDefinition
    definition = EquityStrategyDefinition.from_dict(payload["equity_definition"])
    expected = {"kind": "US_EQUITY", "contract_version": 2,
                "source_files": list(definition.source_files), "source_sha256": definition.source_sha256}
    if set(payload) != {"runtime", "equity_definition"} or _payload_json(payload["runtime"]) != _payload_json(expected):
        raise ValueError("equity planned runtime descriptor differs from definition")
    return definition.content_identity.content_sha256


def equity_parameter_contract(request):
    """Project authenticated v2 request facts onto shared parameter-plan identity."""
    if request.get("schema") != "equity-research/v2":
        raise ValueError("equity parameter contract requires formal v2 request")
    definition = json.loads(_payload_json(request["candidate_definition"]))
    definition.pop("parameters_json")
    nonparameter = {key: value for key, value in request.items() if key not in {
        "experiment", "candidate_id", "implementation_hash", "candidate_identity", "content_sha256",
        "candidate_definition", "lineage",
    }}
    nonparameter["candidate_definition"] = definition
    lineage = request.get("lineage")
    return {
        "schema": "equity-research/v2", "experiment_id": request["experiment"]["experiment_id"],
        "strategy_reference": f"{request['experiment']['strategy_id']}-{request['candidate_id']}",
        "content_sha256": request["content_sha256"], "strategy_identity": request["content_sha256"],
        "nonparameter_context_sha256": canonical_sha256(nonparameter),
        "lineage": None if lineage is None else lineage["derivation"],
        "parameter_binding": None if lineage is None else lineage["parameter_binding"],
        "input_bindings": {request["window_id"]: {"kind": "US_EQUITY", "binding": request["input_binding"]}},
    }


def _equity_contract(request):
    from .equity_evaluation import _json_value
    return _json_value(request.identity(request.candidate.definition.execution_spec))


def _equity_policy(request):
    return _payload_json({"policy": {"policy_type": "US_EQUITY", "settings":
        _equity_contract(request)["specification"]}})


def _equity_candidate(request):
    identity = request.candidate.content_identity.content_sha256
    return ParameterEvaluationCandidate(AssessmentCandidate(
        f"{request.candidate.strategy_id}-{request.candidate.candidate_id}", identity),
        identity, _payload_json(request.candidate.payload))


def _verify_equity_inputs(request, dataflows):
    if request.prepared is None or request.input_binding is None:
        raise ValueError("equity parameter plan requires prepared input binding")
    if request.prepared.space_id != dataflows.binding.space_id:
        raise ValueError("equity parameter input belongs to another data context")
    expected = request.input_binding.expected_identities
    observed = set()
    for role, query in request.request_items(request.candidate.definition.execution_spec):
        result = dataflows.fetch(query, prepared=request.prepared)
        if role in observed or not result.ready or result.identity.content_sha256 != expected.get(role):
            raise ValueError("equity parameter input content differs")
        observed.add(role)
    if observed != set(expected):
        raise ValueError("equity parameter input coverage differs")


def _create_equity_plan(cls, design, center, children, *, mapping_evidence, feasibility_evidence, dataflows):
    from .equity_evaluation import EquityEvaluationRequest
    from strategy_runtime.equity import equity_hash
    if type(design) is not ParameterNeighborhoodDesign or design.protocol.version != "parameter-cartesian-neighborhood-v2":
        raise ValueError("new equity parameter plans require neighborhood v2")
    if not center.formal or type(children) is not tuple or any(type(x) is not EquityEvaluationRequest or not x.formal for x in children):
        raise TypeError("equity parameter plans require formal requests")
    if not isinstance(dataflows, Dataflows):
        raise TypeError("equity parameter inputs require Dataflows")
    root = dataflows.binding.base_dir
    mapping_evidence.resolve(root)
    feasibility_evidence.resolve(root)
    if any(x.lineage and x.lineage.parameter_binding for x in (center, *children)):
        raise ValueError("create prospective plan before adding point bindings")
    center_value = _equity_candidate(center)
    if design.center != center_value.candidate:
        raise ValueError("equity parameter design differs from actual center")
    central = _equity_contract(center)
    context = equity_parameter_contract(central)["nonparameter_context_sha256"]
    for item in (center, *children):
        item.candidate.verify()
        _verify_equity_inputs(item, dataflows)
        if item.experiment.strategy_id != center.experiment.strategy_id:
            raise ValueError("equity parameter child belongs to another family")
        if equity_parameter_contract(_equity_contract(item))["nonparameter_context_sha256"] != context:
            raise ValueError("equity parameter child nonparameter context differs")
    return cls(design, center_value, equity_hash(central), context,
        tuple(_equity_candidate(x) for x in children), mapping_evidence, feasibility_evidence,
        (ParameterEvaluationInput(center.window_id, _payload_json({"kind": "US_EQUITY", "binding": center.input_binding.to_dict()})),),
        _equity_policy(center), schema_version=4)


def _validate_equity_parameter_request(request, dataflows):
    binding = request.lineage.parameter_binding
    plan = read_parameter_plan(binding.plan, dataflows.binding.base_dir)
    if plan.schema_version != 4:
        raise ValueError("equity parameter evaluation requires schema 4 plan")
    if binding.plan.experiment.strategy_id != request.experiment.strategy_id:
        raise ValueError("equity parameter plan belongs to another family")
    contract = equity_parameter_contract(_equity_contract(request))
    validate_parameter_contract(contract, plan, binding)
    if _equity_candidate(request).payload_json != plan.children[binding.point.point_index].payload_json:
        raise ValueError("equity parameter candidate payload differs from plan")
    if contract["input_bindings"] != {x.window_id: json.loads(x.binding_json) for x in plan.center_inputs}:
        raise ValueError("equity parameter input binding differs from center")
    if _equity_policy(request) != plan.execution_contract_json:
        raise ValueError("equity parameter execution contract differs")
    _verify_equity_inputs(request, dataflows)


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
            # The same complete pinned identity and request denote one asset view.
            # Reuse this verified read only within this role comparison.
            new = old if original.prepared == current.prepared else dataflows.fetch(common, prepared=current.prepared)
            if not old.ready or not new.ready:
                raise ValueError("parameter raw input comparison requires complete pinned inputs")
            if (old.identity.content_sha256, old.identity.source, old.identity.temporal_contract) != (
                new.identity.content_sha256, new.identity.source, new.identity.temporal_contract,
            ):
                raise ValueError("parameter raw input source or values differ on common range")
