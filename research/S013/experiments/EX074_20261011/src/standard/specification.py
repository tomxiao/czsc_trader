"""Pure exact15D fixed32 specification; no prepared inputs or financial calls."""
# ruff: noqa: E402 -- Bootstrap frozen research module paths before imports.

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import driver as d
from strategy_evaluator import (
    AssessmentCandidate,
    ParameterCoordinate,
    ParameterCoordinateKind,
    ParameterDesignRequest,
    ParameterPerturbationProtocol,
    ParameterSpace,
    build_parameter_perturbation_design,
)
from strategy_runtime import StrategyCandidate, StrategyRuntime

FIRST = 7474


def plain(value):
    return json.loads(json.dumps(value, default=dict))


def get(parameters, name):
    for field in name.split("."):
        parameters = parameters[field]
    return parameters


def materialize(parameters, coordinates, values):
    parameters = deepcopy(parameters)
    for (name, _, _, kind), value in zip(coordinates, values, strict=True):
        parts, target = name.split("."), parameters
        for field in parts[:-1]:
            target = target[field]
        target[parts[-1]] = int(value) if kind == "INTEGER" else float(value)
    return parameters


def feasible(values):
    return bool(values[1] < values[2] and values[5] < values[6])


def prepare():
    root = d.ROOT
    plan = d.read(root / "research/S013/experiments/EX074_20261011/protocols/plan.json")
    assert d.read(d.WORK / "verification.json")["economics"]["qualified"]
    coords = plan["geometry"]["coordinates"]
    original = d.read(d.OLD / "protocols/geometry.json")["coordinates"]
    assert len(coords) == 15 and coords[:13] == original
    assert coords[-2:] == [
        ["pressure_exit.lookback", 1.0, 20.0, "INTEGER"],
        ["pressure_exit.early_hold_cap", 1.0, 60.0, "INTEGER"],
    ]
    mapping = {
        "version": "EX074-15-effective-complete-domains-v1",
        "coordinates": coords,
        "normalisation": "LINEAR full-domain widths",
        "integer_rounding": "HALF_EVEN",
        "new_domain_reasons": "pressure lookback legal1..20; early deadline legal1..60 with effective min(original bearH,cap); no hidden half-H, width contraction, coordinate duplication or outcome selection",
    }
    constraints = {
        "version": "EX074-original-range-order-v1",
        "coordinate_order": coords,
        "constraints": ["bull.entry < bull.exit", "bear.entry < bear.exit"],
        "implementation": "coordinates[1]<coordinates[2] and coordinates[5]<coordinates[6]",
    }
    d.write(HERE / "mapping15.json", mapping)
    d.write(HERE / "feasibility15.json", constraints)
    protocol = ParameterPerturbationProtocol(radius=0.05, point_count=32, seed=13)
    params = plain(plan["payload"]["parameters"])
    space = ParameterSpace(
        tuple(
            ParameterCoordinate(
                name, float(get(params, name)), lo, hi, ParameterCoordinateKind(kind)
            )
            for name, lo, hi, kind in coords
        ),
        d.digest(HERE / "mapping15.json"),
        d.digest(HERE / "feasibility15.json"),
    )
    request = ParameterDesignRequest(
        AssessmentCandidate("S013-C9074", plan["content_sha256"]),
        protocol,
        space,
    )
    result = build_parameter_perturbation_design(request, feasibility=feasible)
    assert result.status.value == "COMPLETE" and len(result.design.points) == 32
    source = root / "research/S013/experiments/EX074_20261011/src/strategy_runtime"
    runtime = StrategyRuntime()
    points = []
    for i, point in enumerate(result.design.points):
        ident = f"C{FIRST + i:04}"
        assert not (root / "research/S013/assets/candidates" / ident).exists()
        assert not (root / "research/registrations/S013/candidates" / (ident + ".json")).exists()
        payload = plain(plan["payload"])
        payload["parameters"] = materialize(params, coords, point.coordinates)
        described = runtime.describe(StrategyCandidate("S013", ident, payload, source))
        assert described.parameters.values["pressure_exit"]["enabled"] is True
        points.append(
            {
                "label": f"P{i:02}",
                "candidate_id": ident,
                "point": point.to_dict(),
                "payload": payload,
                "legal_runtime_described": True,
            }
        )
    unique_payloads = len({json.dumps(x["payload"], sort_keys=True) for x in points})
    assert unique_payloads == 32
    spec = {
        "status": "SOURCE_ONLY_EXACT_POINTS_AWAIT_ROOT_AUTHORIZATION",
        "design": result.design.to_dict(),
        "design_request_sha256": result.request_sha256,
        "coordinates": coords,
        "centre_payload": plain(plan["payload"]),
        "points": points,
        "actual_unique_payloads": unique_payloads,
        "duplicate_payloads": 32 - unique_payloads,
        "integer_coverage": {
            name: dict(Counter(str(get(x["payload"]["parameters"], name)) for x in points))
            for name in ("pressure_exit.lookback", "pressure_exit.early_hold_cap")
        },
        "effective_marked_bear_H": dict(
            Counter(
                str(
                    min(
                        x["payload"]["parameters"]["bear"]["max_hold"],
                        x["payload"]["parameters"]["pressure_exit"]["early_hold_cap"],
                    )
                )
                for x in points
            )
        ),
        "generator_validity": {
            "attempts": result.design.attempts,
            "rejections": [x.to_dict() for x in result.design.rejections],
            "all_full_domain_order_and_integer_valid": True,
        },
        "fee": {
            "label": "FEE",
            "candidate_id": "C9074",
            "unchanged_centre_payload": plain(plan["payload"]),
            "scenario": "stress_20bp_per_side",
            "one_way_cost": 0.002,
            "measurement_tier": "STRESS",
            "parameter_cross": False,
            "one_full_financial_account": 1,
        },
        "budget": {
            "centre_already_completed": 1,
            "conditional_standard32": 32,
            "independent_fee": 1,
            "total_new_financial": 34,
            "technical_repeats": 0,
            "neighbours": 0,
            "baseline_reuse_standard": 33,
            "baseline_reuse_fee": 1,
        },
        "comparison": "15D new vs original13D each standard total normalized L2 .05, seed13; different direction and per-coordinate amplitude. Descriptive absoluteQ10/Q90 comparison, no paired causal or equal geometry claim; numerical coverage does not cover structural hypothesis selection",
        "selection_history": "EX073 seen-pool later2-day evidence selected fixed cap2; EX069/072 selected pressure4. Centre four gates qualify, yet CAGR fell2.7361pp and fullDD increased2.7577pp. Preserve that strong counterevidence; no selecting points, cap/window rescue or hidden new economic gate",
        "integer_noncoverage": "Retain exact standard points. If pressure lookback stays4, report integer lookback robustness untested. No neighbours, replacement, new windows or optimisation",
        "fivechecks": "EX062 latest independentfive: rolling126/step21, bootstrap2000x20/seed13, PBO/DSR unavailable without full family; no extra gate",
        "finance_runs_this_preparation": 0,
        "provider_calls": 0,
        "candidate_registration": 0,
    }
    d.write(HERE / "point_specification15.json", spec)
    print(
        json.dumps(
            {
                "status": spec["status"],
                "unique": unique_payloads,
                "coverage": spec["integer_coverage"],
                "attempts": result.design.attempts,
                "rejections": spec["generator_validity"]["rejections"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    prepare()
