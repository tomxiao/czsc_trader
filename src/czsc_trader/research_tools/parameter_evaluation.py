"""Published parameter designs bound to actual candidate and account identities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
    from .equity_replay_v3 import PreparedAccountEvaluation
    from .execution import ResearchExecutionSession


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
    def create(cls, design: ParameterNeighborhoodDesign,
               center: PreparedAccountEvaluation,
               children: tuple[PreparedAccountEvaluation, ...], *,
               mapping_evidence: EvidenceRef, feasibility_evidence: EvidenceRef, dataflows: Dataflows,
               execution: ResearchExecutionSession | None = None) -> ParameterEvaluationPlan:
        """Authenticate prepared inputs, without evaluating or publishing accounts."""
        from .evaluation import EvaluationRequest
        from .equity_replay_v3 import PreparedAccountEvaluation

        if type(design) is not ParameterNeighborhoodDesign:
            raise TypeError("new parameter plan requires ParameterNeighborhoodDesign; legacy sphere plans are read-only")
        if design.protocol.version != "parameter-cartesian-neighborhood-v2":
            raise ValueError("historical parameter designs are read-only; new plans require neighborhood v2")
        if type(center) is not PreparedAccountEvaluation:
            raise TypeError("parameter plans require session-owned PreparedAccountEvaluation inputs")
        prepared_contracts, prepared_facts = {}, {}
        if type(center) is PreparedAccountEvaluation and type(center.request) is EvaluationRequest:
            from .account_preparation import require_account
            if execution is None:
                raise TypeError('parameter plans require their explicit execution session')
            if type(children) is not tuple or any(type(child) is not PreparedAccountEvaluation for child in children):
                raise TypeError("parameter children require session-owned account handles")
            for handle in (center, *children):
                original = require_account(execution.context.evaluation, handle, execution)
                if type(original) is not EvaluationRequest:
                    raise TypeError("parameter accounts cannot mix execution contracts")
                prepared_contracts[id(handle.request)] = json.loads(handle.contract_content)
                prepared_facts[id(handle.request)] = _account_parameter_facts(handle)
            children = tuple(child.request for child in children)
            center = center.request
            execution = None
        if type(center) is PreparedAccountEvaluation:
            return _create_equity_plan(cls, design, center, children,
                mapping_evidence=mapping_evidence, feasibility_evidence=feasibility_evidence,
                dataflows=dataflows, execution=execution)
        if execution is not None:
            raise TypeError("explicit parameter execution ownership requires prepared V3 requests")
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
        central = prepared_contracts[id(center)]
        if design.center != AssessmentCandidate(center.strategy.reference_id, central["content_sha256"]):
            raise ValueError("parameter design differs from actual center")
        context = central["nonparameter_context_sha256"]
        execution_contract = prepared_facts[id(center)]["execution_contract"]
        values = []
        for child in children:
            contract = prepared_contracts[id(child)]
            if child.strategy.strategy_family_id != center.strategy.strategy_family_id:
                raise ValueError("parameter child belongs to another strategy family")
            if contract["nonparameter_context_sha256"] != context:
                raise ValueError("parameter child nonparameter context differs from center")
            _compare_prepared_inputs(prepared_facts[id(center)]["inputs"],
                prepared_facts[id(child)]["inputs"], dataflows)
            child_execution = prepared_facts[id(child)]["execution_contract"]
            if child_execution != execution_contract:
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


def validate_parameter_request(request: PreparedAccountEvaluation, dataflows: Dataflows, *, execution=None) -> None:
    from .equity_replay_v3 import PreparedAccountEvaluation

    from .evaluation import EvaluationRequest
    if type(request) is not PreparedAccountEvaluation:
        raise TypeError("parameter validation requires a session-owned PreparedAccountEvaluation")
    prepared_contract, prepared_facts = None, None
    if type(request) is PreparedAccountEvaluation and type(request.request) is EvaluationRequest:
        from .account_preparation import require_account
        if execution is None:
            raise TypeError('parameter validation requires its explicit execution session')
        original = require_account(execution.context.evaluation, request, execution)
        prepared_contract = json.loads(request.contract_content)
        prepared_facts = _account_parameter_facts(request)
        request = original
        execution = None
    if type(request) is PreparedAccountEvaluation:
        _verify_equity_inputs(request, dataflows, execution=execution)
        original = request.request
        if original.lineage is not None and original.lineage.parameter_binding is not None:
            _validate_equity_parameter_request(original, dataflows, prepared=request)
        return
    if execution is not None:
        raise TypeError("explicit parameter execution ownership requires prepared V3 requests")
    if request.lineage is None or request.lineage.parameter_binding is None:
        return

    binding = request.lineage.parameter_binding
    plan = read_parameter_plan(binding.plan, request.repository_root)
    if plan.schema_version != 3:
        raise ValueError("historical parameter plans are read-only; new evaluations require schema 3")
    if binding.plan.experiment.strategy_id != request.strategy.strategy_family_id:
        raise ValueError("parameter plan belongs to another strategy family")
    validate_parameter_contract(prepared_contract, plan, binding)
    if _payload_json(request.strategy.payload) != plan.children[binding.point.point_index].payload_json:
        raise ValueError("parameter candidate payload differs from plan")
    if prepared_facts.get("reference_plan_sha256") != binding.plan.sha256:
        raise ValueError("prepared parameter reference differs from its published plan")
    _compare_prepared_inputs(prepared_facts["reference_inputs"], prepared_facts["inputs"], dataflows)
    execution_contract = prepared_facts["execution_contract"]
    if execution_contract != plan.execution_contract_json:
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
    expected = {"kind": "US_EQUITY", "contract_version": definition.contract_version,
                "source_files": list(definition.source_files), "source_sha256": definition.source_sha256}
    if set(payload) != {"runtime", "equity_definition"} or _payload_json(payload["runtime"]) != _payload_json(expected):
        raise ValueError("equity planned runtime descriptor differs from definition")
    return definition.content_identity.content_sha256


def equity_parameter_contract(request):
    """Project authenticated equity request facts onto parameter-plan identity."""
    if request.get("schema") not in ('equity-research/v2', 'equity-research/v3'):
        raise ValueError("equity parameter contract requires formal v2 or v3 request")
    definition = json.loads(_payload_json(request["candidate_definition"]))
    definition.pop("parameters_json")
    nonparameter = {key: value for key, value in request.items() if key not in {
        "experiment", "candidate_id", "implementation_hash", "candidate_identity", "content_sha256",
        "candidate_definition", "lineage",
    }}
    nonparameter["candidate_definition"] = definition
    lineage = request.get("lineage")
    return {
        "schema": request['schema'], "experiment_id": request["experiment"]["experiment_id"],
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


def _verify_equity_inputs(request, dataflows, *, execution=None):
    from .equity_replay_v3 import PreparedAccountEvaluation, _require_prepared, _state
    from .execution import ResearchExecutionSession
    if type(request) is PreparedAccountEvaluation:
        if type(execution) is not ResearchExecutionSession:
            raise TypeError("V3 parameter inputs require their explicit ResearchExecutionSession")
        access = execution.context.evaluation
        if access.data is not dataflows:
            raise ValueError("V3 parameter inputs belong to another data context")
        state = _state(access, execution, request.experiment.experiment_id)
        _require_prepared(state, request)
        data = json.loads(request.snapshot.artifact.content)["data"]
        if dict(request.request.input_binding.expected_identities) != {
                name: value["content_sha256"] for name, value in data.items()}:
            raise ValueError("V3 parameter input binding differs from its authenticated snapshot")
        return
    raise TypeError("equity parameter inputs require session-owned PreparedAccountEvaluation")


def _create_equity_plan(cls, design, center, children, *, mapping_evidence, feasibility_evidence, dataflows, execution=None):
    from .equity_replay_v3 import PreparedAccountEvaluation
    from strategy_runtime.equity import equity_hash
    if type(design) is not ParameterNeighborhoodDesign or design.protocol.version != "parameter-cartesian-neighborhood-v2":
        raise ValueError("new equity parameter plans require neighborhood v2")
    if (type(center) is not PreparedAccountEvaluation or type(children) is not tuple
            or any(type(x) is not PreparedAccountEvaluation for x in children)):
        raise TypeError("equity parameter plans require session-owned PreparedAccountEvaluation inputs")
    if not isinstance(dataflows, Dataflows):
        raise TypeError("equity parameter inputs require Dataflows")
    root = dataflows.binding.base_dir
    mapping_evidence.resolve(root)
    feasibility_evidence.resolve(root)
    originals = tuple(x.request for x in (center, *children))
    if any(x.lineage and x.lineage.parameter_binding for x in originals):
        raise ValueError("create prospective plan before adding point bindings")
    center_value = _equity_candidate(center)
    if design.center != center_value.candidate:
        raise ValueError("equity parameter design differs from actual center")
    central = _equity_contract(center)
    context = equity_parameter_contract(central)["nonparameter_context_sha256"]
    for item in (center, *children):
        _verify_equity_inputs(item, dataflows, execution=execution)
        if item.experiment.strategy_id != center.experiment.strategy_id:
            raise ValueError("equity parameter child belongs to another family")
        if equity_parameter_contract(_equity_contract(item))["nonparameter_context_sha256"] != context:
            raise ValueError("equity parameter child nonparameter context differs")
    return cls(design, center_value, equity_hash(central), context,
        tuple(_equity_candidate(x) for x in children), mapping_evidence, feasibility_evidence,
        (ParameterEvaluationInput(originals[0].window_id, _payload_json({"kind": "US_EQUITY", "binding": originals[0].input_binding.to_dict()})),),
        _equity_policy(center), schema_version=4)


def _validate_equity_parameter_request(request, dataflows, *, prepared):
    binding = request.lineage.parameter_binding
    plan = read_parameter_plan(binding.plan, dataflows.binding.base_dir)
    if plan.schema_version != 4:
        raise ValueError("equity parameter evaluation requires schema 4 plan")
    if binding.plan.experiment.strategy_id != request.experiment.strategy_id:
        raise ValueError("equity parameter plan belongs to another family")
    contract = equity_parameter_contract(_equity_contract(prepared))
    validate_parameter_contract(contract, plan, binding)
    if _equity_candidate(request).payload_json != plan.children[binding.point.point_index].payload_json:
        raise ValueError("equity parameter candidate payload differs from plan")
    if contract["input_bindings"] != {x.window_id: json.loads(x.binding_json) for x in plan.center_inputs}:
        raise ValueError("equity parameter input binding differs from center")
    if _equity_policy(prepared) != plan.execution_contract_json:
        raise ValueError("equity parameter execution contract differs")


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



def prepare_parameter_facts(request, dataflows: Dataflows) -> dict:
    """Capture authenticated comparison facts once, during explicit preparation.

    Row values use the same pandas numerical hashes as DFLS canonical hashing;
    dataframe schema is separately certified. Excluding the RangeIndex lets a
    longer warmup be compared on the exact common range without fetching again.
    """
    from dataflows import canonical_frame_sha256
    import pandas as pd
    memo = {}
    def collect(bindings):
        windows = {}
        for window, binding in bindings.items():
            roles = {}
            for role, query in binding.plan.requests.items():
                contract = json.loads(_payload_json(binding.plan.to_dict()["requests"][role]))
                key = (binding.prepared, _payload_json(contract))
                facts = memo.get(key)
                if facts is None:
                    value = dataflows.fetch(query, prepared=binding.prepared)
                    if not value.ready:
                        raise ValueError("parameter raw input comparison requires complete pinned inputs")
                    frame = pd.DataFrame(value.dataframe, copy=False)
                    dates = pd.to_datetime(frame["Date"], errors="raise")
                    if dates.isna().any():
                        raise ValueError("parameter raw input dates must be finite")
                    rows = zip(dates.map(lambda stamp: stamp.isoformat()),
                        pd.util.hash_pandas_object(frame, index=False).astype("uint64").tolist(), strict=True)
                    facts = {"space": str(binding.prepared.space_id), "request": contract,
                        "source": value.identity.source, "temporal": asdict(value.identity.temporal_contract),
                        "schema": canonical_frame_sha256(frame.iloc[:0].reset_index(drop=True)),
                        "rows": list(rows)}
                    memo[key] = facts
                roles[role] = facts
            windows[window] = roles
        return windows
    reference_inputs, reference = None, None
    if request.lineage is not None and request.lineage.parameter_binding is not None:
        reference = request.lineage.parameter_binding.plan
        plan = read_parameter_plan(reference, request.repository_root)
        central = {item.window_id: StrategyInputBinding.from_mapping(json.loads(item.binding_json))
                   for item in plan.center_inputs}
        # Reject changed source declarations before trying an unrelated product.
        if set(central) != set(request.input_bindings):
            raise ValueError("parameter input windows differ")
        for window, binding in central.items():
            declared = request.input_bindings[window]
            if set(binding.plan.requests) != set(declared.plan.requests):
                raise ValueError("parameter raw input space or roles differ")
            for role in binding.plan.requests:
                contracts = [json.loads(_payload_json(item.plan.to_dict()["requests"][role]))
                             for item in (binding, declared)]
                for contract in contracts:
                    contract.pop("start")
                    if contract["coverage"] is not None:
                        contract["coverage"].pop("minimum_observations")
                        contract["coverage"].pop("minimum_sessions")
                if contracts[0] != contracts[1]:
                    raise ValueError(f"parameter raw input source contract differs: {window}/{role}")
        reference_inputs = collect(central)
    facts = {"execution_contract": _execution_contract(request), "inputs": collect(request.input_bindings)}
    if reference is not None:
        facts["reference_plan_sha256"] = reference.sha256
        facts["reference_inputs"] = reference_inputs
    return facts


def _account_parameter_facts(handle):
    facts = json.loads(handle.snapshot.content).get("parameter_facts")
    if type(facts) is not dict or set(facts) not in (
            {"execution_contract", "inputs"},
            {"execution_contract", "inputs", "reference_plan_sha256", "reference_inputs"}):
        raise ValueError("account preparation lacks authenticated parameter facts")
    return facts


def _compare_prepared_inputs(center, child, dataflows):
    """Compare certified immutable facts only; no source loads or DFLS reads."""
    import pandas as pd
    if not isinstance(dataflows, Dataflows):
        raise TypeError("parameter input comparison requires Dataflows")
    if set(center) != set(child):
        raise ValueError("parameter input windows differ")
    for window, roles in center.items():
        if set(roles) != set(child[window]):
            raise ValueError("parameter raw input space or roles differ")
        for role, original in roles.items():
            current = child[window][role]
            if original["space"] != current["space"] or original["space"] != str(dataflows.binding.space_id):
                raise ValueError("parameter raw input space or roles differ")
            contracts = [json.loads(_payload_json(item["request"])) for item in (original, current)]
            start = max(pd.Timestamp(item.pop("start")) for item in contracts)
            for contract in contracts:
                if contract["coverage"] is not None:
                    contract["coverage"].pop("minimum_observations")
                    contract["coverage"].pop("minimum_sessions")
            if contracts[0] != contracts[1]:
                raise ValueError(f"parameter raw input source contract differs: {window}/{role}")
            selected = [[row for row in item["rows"] if pd.Timestamp(row[0]) >= start]
                        for item in (original, current)]
            if (not selected[0] or selected[0] != selected[1]
                    or any(original[field] != current[field] for field in ("schema", "source", "temporal"))):
                raise ValueError("parameter raw input source or values differ on common range")
