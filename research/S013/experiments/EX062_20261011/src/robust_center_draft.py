"""EX062 prospective fixed-center draft; CLI never prepares or evaluates accounts.

Budget, source hashes, candidate IDs and method must be formally frozen before
calling the public TDR stage functions. No experiment creation/registration API.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import math
from pathlib import Path
from types import MappingProxyType

import numpy as np
import optuna
from strategy_evaluator import (
    AssessmentCandidate, ParameterCoordinate, ParameterCoordinateKind,
    ParameterDesignRequest, ParameterPerturbationProtocol, ParameterSpace,
    build_parameter_perturbation_design,
)
from strategy_manager import (
    CandidateDerivation, CandidateDerivationKind, CandidateEvidence, CandidateKey,
)
from strategy_runtime import StrategyCandidate, canonical_sha256
from dataflows import Dataset, ProviderBinding, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvaluationLineage, ParameterEvaluationPlan
from czsc_trader.research_tools import EvaluationResources, ResearchBatchRef
from czsc_trader.research_tools.evaluation import (
    serialize_evaluation_evidence, validate_evaluation_evidence,
)

ROOT = next(path for path in Path(__file__).resolve().parents if (path / "pyproject.toml").exists())
EX058 = ROOT / "research/S013/experiments/EX058_20261011"
MECHANISM = "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY"
PROTOCOL = ParameterPerturbationProtocol(radius=.05, point_count=32, seed=13)
GATES = ("return", "annual_drawdown", "frequency", "negative_buyhold_year_profit")


def restore_mapping(value):
    return MappingProxyType(value)


def plain(value):
    return json.loads(json.dumps(value, default=dict, allow_nan=False))


def get_path(parameters, name):
    for part in name.split("."):
        parameters = parameters[part]
    return parameters


def set_path(parameters, name, value):
    parts = name.split(".")
    for part in parts[:-1]:
        parameters = parameters[part]
    parameters[parts[-1]] = value


def materialize(base, coordinates, values):
    result = deepcopy(plain(base))
    if len(coordinates) != 13 or len(values) != 13:
        raise ValueError("All original 13 coordinates are required")
    for (name, low, high, kind), value in zip(coordinates, values, strict=True):
        if isinstance(value, bool) or not math.isfinite(float(value)) or not low <= value <= high:
            raise ValueError("Nonfinite/out-of-domain coordinate: " + name)
        if kind == "INTEGER" and not float(value).is_integer():
            raise ValueError("Noninteger coordinate: " + name)
        if kind not in {"INTEGER", "CONTINUOUS"}:
            raise ValueError("Unknown coordinate type")
        set_path(result, name, int(value) if kind == "INTEGER" else float(value))
    vector = [get_path(result, name) for name, *_ in coordinates]
    if not feasible(vector) or result.get("mechanism") != MECHANISM:
        raise ValueError("Changed mechanism or invalid entry/exit ordering")
    return result


def feasible(values):
    return bool(values[1] < values[2] and values[5] < values[6])


@dataclass(frozen=True)
class CenterProposal:
    label: str
    parameters_json: str
    existing_candidate: str | None
    aliases: tuple[str, ...] = ()

    @property
    def parameters(self):
        return json.loads(self.parameters_json)


def fixed_queue(base, p00, p20, coordinates):
    """No performance read: exact endpoints plus .25/.5/.75 full-vector chords."""
    def encoded(parameters):
        return json.dumps(plain(parameters), sort_keys=True, separators=(",", ":"), allow_nan=False)

    samples = [("BASE", base, "C8880"), ("P00", p00, "C8840"), ("P20", p20, "C8860")]
    b = np.array([get_path(base, name) for name, *_ in coordinates], dtype=float)
    for endpoint_label, endpoint in (("P00", p00), ("P20", p20)):
        e = np.array([get_path(endpoint, name) for name, *_ in coordinates], dtype=float)
        for alpha in (.25, .5, .75):
            vector = b + alpha * (e - b)
            for index, (_, _, _, kind) in enumerate(coordinates):
                if kind == "INTEGER":
                    vector[index] = np.rint(vector[index])  # HALF_EVEN; no truncation.
            samples.append((f"{endpoint_label}-A{alpha:g}", materialize(base, coordinates, vector), None))
    output, by_payload = [], {}
    for label, parameters, native_id in samples:
        vector = [get_path(parameters, name) for name, *_ in coordinates]
        authenticated = materialize(base, coordinates, vector)
        if plain(parameters) != authenticated:
            raise ValueError("Endpoint changed non-coordinate parameters")
        key = encoded(authenticated)
        if key in by_payload:
            index = by_payload[key]
            old = output[index]
            output[index] = replace(old, aliases=(*old.aliases, label))
        else:
            by_payload[key] = len(output)
            output.append(CenterProposal(label, key, native_id))
    return tuple(output)


def queue_study(proposals):
    """In-memory prototype only; root must persist study+queue before any account."""
    if not proposals:
        raise ValueError("Empty frozen queue")
    study = optuna.create_study(directions=("maximize", "maximize", "minimize"),
                               sampler=optuna.samplers.RandomSampler(seed=13))
    for index in range(len(proposals)):
        study.enqueue_trial({"center_index": index})
    return study


def design_for(strategy, identity, coordinates, mapping_ref, feasibility_ref):
    space = ParameterSpace(tuple(ParameterCoordinate(
        name, float(get_path(strategy.payload["parameters"], name)), low, high,
        ParameterCoordinateKind(kind),
    ) for name, low, high, kind in coordinates), mapping_ref.sha256, feasibility_ref.sha256)
    outcome = build_parameter_perturbation_design(ParameterDesignRequest(
        AssessmentCandidate(strategy.reference_id, identity.content_sha256), PROTOCOL, space,
    ), feasibility=feasible)
    if outcome.status.value != "COMPLETE":
        raise RuntimeError("Incomplete SE design; preserve failure, no point replacement")
    return outcome.design


def metadata_queue():
    """Read only prospective geometry/payload metadata, never native results."""
    geometry = json.loads((EX058 / "protocols/geometry.json").read_text(encoding="utf-8-sig"))
    mechanism = json.loads((EX058 / "protocols/plan.json").read_text(encoding="utf-8-sig"))
    plans = json.loads((EX058 / "protocols/parameter_plans.json").read_text(encoding="utf-8-sig"))
    config = next(item for item in mechanism["configurations"] if item["candidate_id"] == "C8880")
    record = next(item for item in plans["centers"] if item["control_key"] == "N0")
    if record["candidate_id"] != "C8880" or record["design"]["center"]["candidate_id"] != "S013-C8880":
        raise ValueError("Frozen parameter cohort must be actual C8880, never an aliased native N0")
    coordinates = geometry["coordinates"]
    base = config["payload"]["parameters"]
    endpoints = [materialize(base, coordinates, record["design"]["points"][index]["coordinates"])
                 for index in (0, 20)]
    return fixed_queue(base, *endpoints, coordinates), coordinates, config, record


def plan_center_view(native):
    """Prospective-plan view only; NEVER serialize/evaluate it as reused account.

    Existing P00/P20 have old point bindings, which plan.create rejects. Preserve
    their derivation, remove only parameter_binding from this separate view. The
    original native request/result/ref and its original binding remain unchanged.
    """
    if native.lineage is None or native.lineage.parameter_binding is None:
        return native
    return replace(native, lineage=EvaluationLineage(native.lineage.derivation))


def authenticate_native(ctx, native, result, reference):
    if reference.experiment.strategy_id != "S013":
        raise ValueError("Only S013 native reuse is authorized")
    path = reference.resolve(ROOT)
    if sha256(path.read_bytes()).hexdigest() != reference.sha256:
        raise ValueError("Formal native evidence SHA mismatch")
    formal = json.loads(path.read_text(encoding="utf-8-sig"))
    validate_evaluation_evidence(formal)
    if serialize_evaluation_evidence(native, result) != formal:
        raise ValueError("Entire public serialized native evidence differs")
    identity = ctx.runtime.identify(native.strategy, dependencies=native.dependencies)
    if (result.strategy_identity != native.strategy.runtime_identity_sha256
            or result.runtime_binding_hash != canonical_sha256(native.runtime_binding)
            or result.data_identity != native.execution_data.fingerprint
            or any(run.identity.content_sha256 != identity.content_sha256 for run in result.runs)):
        raise ValueError("Native runtime/content/binding/data identity mismatch")
    return identity


def require_frozen_method(reference):
    """No prospective invocation can pass until root has published exact method."""
    path = reference.resolve(ROOT)
    if reference.experiment.strategy_id != "S013" or reference.experiment.experiment_id != "EX062_20261011":
        raise ValueError("Expected exact S013 EX062 method reference")
    if sha256(path.read_bytes()).hexdigest() != reference.sha256:
        raise ValueError("Method SHA mismatch")
    method = json.loads(path.read_text(encoding="utf-8-sig"))
    required = {"queue", "sources", "candidate_reservation", "ranking", "budget",
                "fixed_contract", "reuse_mapping", "failure_policy", "public_se"}
    if method.get("status") != "FROZEN_FOR_EXECUTION" or not required.issubset(method):
        raise ValueError("Search method incomplete/unfrozen")
    if method["public_se"] != PROTOCOL.to_dict():
        raise ValueError("Original full-domain public SE protocol changed")
    for relative, digest in method["sources"].items():
        file = (ROOT / relative).resolve()
        if not file.is_relative_to(ROOT) or sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError("Frozen source SHA mismatch: " + relative)
    return method


def existing_only_context(method_ref, workers=1):
    require_frozen_method(method_ref)
    def forbidden(request):
        raise RuntimeError("EX062 existing S013 prepared assets only; provider forbidden: " + str(request))
    bindings = {dataset: ProviderBinding(str(dataset), "S013-EX062-existing-only", forbidden)
                for dataset in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                                Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)}
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S013"),
        providers=ProviderConfig(bindings=bindings), resources=EvaluationResources(workers, 1, 13))


def prepare_new_center(ctx, original, parameters, identifier, method_ref, parent_ref):
    method = require_frozen_method(method_ref)
    CandidateKey("S013", identifier)
    if identifier not in method["candidate_reservation"]:
        raise ValueError("Center ID outside frozen reservation")
    payload = plain(original.strategy.payload)
    payload["parameters"] = parameters
    strategy = StrategyCandidate("S013", identifier, payload, original.strategy.source_root)
    before = ctx.runtime.identify(original.strategy, dependencies=original.dependencies)
    after = ctx.runtime.identify(strategy, dependencies=original.dependencies)
    changes = {name: {"before": get_path(original.strategy.payload["parameters"], name),
                      "after": get_path(parameters, name)} for name, *_ in method["coordinates"]
               if get_path(original.strategy.payload["parameters"], name) != get_path(parameters, name)}
    lineage = EvaluationLineage(CandidateDerivation(
        CandidateKey("S013", original.strategy.candidate_id), before.content_sha256,
        CandidateKey("S013", identifier), after.content_sha256, CandidateDerivationKind.PARAMETERS,
        changes, method_ref.sha256, CandidateEvidence(parent_ref.repository_path, parent_ref.sha256)))
    return ctx.evaluation.prepare(replace(original,
        experiment_id=method_ref.experiment.experiment_id, strategy=strategy,
        runtime_binding={**original.runtime_binding, "candidate_id": strategy.reference_id},
        input_bindings={}, lineage=lineage))


def prepare_point_plan(ctx, center_native, design, coordinates, identifiers,
                       mapping_ref, feasibility_ref, method_ref):
    """Future TDR stage. Caller must authenticate old center and method first.

    No old account replay. New points keep frozen source, costs, pricing,
    execution_data and dependencies; prepare rebinds only required signal inputs.
    Provider failure is terminal; frozen existing-only ctx is mandatory.
    """
    method = require_frozen_method(method_ref)
    reservation = method["candidate_reservation"]
    if len(identifiers) != 32 or len(set(identifiers)) != 32:
        raise ValueError("Exactly 32 unique child IDs required")
    center = plan_center_view(center_native)
    children = []
    for point, identifier in zip(design.points, identifiers, strict=True):
        CandidateKey("S013", identifier)
        if identifier not in reservation:
            raise ValueError("ID outside frozen collision-checked reservation")
        if (ROOT / f"research/S013/assets/candidates/{identifier}").exists() or (
                ROOT / f"research/registrations/S013/candidates/{identifier}.json").exists():
            raise ValueError("Candidate ID already occupied")
        payload = plain(center.strategy.payload)
        payload["parameters"] = materialize(payload["parameters"], coordinates, point.coordinates)
        strategy = StrategyCandidate("S013", identifier, payload, center.strategy.source_root)
        child = replace(center, experiment_id=method_ref.experiment.experiment_id,
                        strategy=strategy, runtime_binding={**center.runtime_binding,
                        "candidate_id": strategy.reference_id}, input_bindings={}, lineage=None)
        children.append(ctx.evaluation.prepare(child))
    plan = ParameterEvaluationPlan.create(design, center, tuple(children),
        mapping_evidence=mapping_ref, feasibility_evidence=feasibility_ref, dataflows=ctx.data)
    return center, tuple(children), plan


def bind_points(native_center, center_reference, children, plan, plan_reference):
    """After exact plan publication; existing center reference remains native."""
    result = []
    original = native_center.strategy.payload["parameters"]
    for index, child in enumerate(children):
        changes = {coordinate.name: {"before": get_path(original, coordinate.name),
                                    "after": get_path(child.strategy.payload["parameters"], coordinate.name)}
                   for coordinate in plan.design.space.coordinates
                   if get_path(original, coordinate.name) != get_path(child.strategy.payload["parameters"], coordinate.name)}
        derivation = CandidateDerivation(
            CandidateKey("S013", native_center.strategy.candidate_id), plan.center.candidate.content_sha256,
            CandidateKey("S013", child.strategy.candidate_id), plan.children[index].candidate.content_sha256,
            CandidateDerivationKind.PARAMETERS, changes, PROTOCOL.sha256,
            CandidateEvidence(center_reference.repository_path, center_reference.sha256),
        )
        result.append(replace(child, lineage=EvaluationLineage(derivation,
            plan.bind_point(plan_reference, index, repository_root=ROOT))))
    return tuple(result)


def summarize_panel(center, points):
    """Economic rows must come from authenticated full native accounts, not proxy."""
    if len(points) != 32 or set(center["gates"]) != set(GATES) or any(
            set(point["gates"]) != set(GATES) for point in points):
        raise ValueError("Complete 32 points and original four gates required")
    if any(type(passed) is not bool for row in (center, *points) for passed in row["gates"].values()):
        raise ValueError("Gate result must be explicit bool")
    cagr = np.array([point["net_cagr"] for point in points], dtype=float)
    dd = np.array([point["drawdown"] for point in points], dtype=float)
    if not np.isfinite(cagr).all() or not np.isfinite(dd).all():
        raise ValueError("Nonfinite/failed account is not a finite robustness value")
    q10, q90 = float(np.quantile(cagr, .1, method="linear")), float(np.quantile(dd, .9, method="linear"))
    return {"center_qualified": all(center["gates"].values()),
            "center_gates": center["gates"], "complete_points": 32,
            "joint_pass_count": sum(all(point["gates"].values()) for point in points),
            "gate_pass_counts": {gate: sum(point["gates"][gate] for point in points) for gate in GATES},
            "q10_cagr": q10, "q90_drawdown": q90,
            "return_degradation": max(0., center["net_cagr"] - q10),
            "drawdown_degradation": max(0., q90 - center["drawdown"])}


def selection(rows, baseline_label="BASE"):
    """Absolute-tail preference is ranking, never a new candidate-eligibility gate."""
    baseline = next(row for row in rows if row["label"] == baseline_label)
    qualified = [row for row in rows if row["center_qualified"]]
    preferred = [row for row in qualified if row["label"] != baseline_label
                 and row["q10_cagr"] >= baseline["q10_cagr"]
                 and row["q90_drawdown"] <= baseline["q90_drawdown"]
                 and (row["q10_cagr"] > baseline["q10_cagr"]
                      or row["q90_drawdown"] < baseline["q90_drawdown"])]
    def dominates(a, b):
        x = (a["joint_pass_count"], a["q10_cagr"], -a["q90_drawdown"])
        y = (b["joint_pass_count"], b["q10_cagr"], -b["q90_drawdown"])
        return all(v >= w for v, w in zip(x, y, strict=True)) and any(v > w for v, w in zip(x, y, strict=True))
    ordered = sorted(preferred, key=lambda row: (-row["joint_pass_count"],
                     -row["q10_cagr"], row["q90_drawdown"], row["queue_index"]))
    return {"preferred": ordered[0]["label"] if ordered else None,
            "absolute_tail_improvement_found": bool(preferred),
            "qualified_labels": [row["label"] for row in qualified],
            "pareto_all": [row["label"] for row in rows if not any(dominates(other, row) for other in rows)],
            "relative_degradation_report_only": True,
            "tie_break": "joint count descending, Q10 descending, Q90 ascending, frozen queue order"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true", help="Print draft status; no accounts")
    parser.parse_args()
    print(json.dumps({"status": "DRAFT_NOT_FROZEN", "new_account_evaluations": 0,
                      "preparations": 0, "publications": 0,
                      "next": "Root review/freeze method, queue, reservation and source hashes"}))


if __name__ == "__main__":
    main()
