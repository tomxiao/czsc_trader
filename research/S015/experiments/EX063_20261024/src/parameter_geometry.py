"""S015 stage-four pre-account geometry: unchanged 5%/32-point public SE method.

Only the declared active coordinates of these sixteen centers are admitted.
No market data, account evaluation, publication or result-based filtering occurs.
Allocation's executable domain is (0, 1]; its finite normalization envelope is
[0, 1], with zero excluded by the pure feasibility predicate. Integer domains
are the already implemented domains, not a neighborhood enlarged for sampling.
"""

from __future__ import annotations

from hashlib import sha256
import inspect
import itertools
import math

from strategy_evaluator import (
    ParameterCoordinate,
    ParameterCoordinateKind,
    ParameterDesignRequest,
    ParameterPerturbationProtocol,
    ParameterSpace,
    build_parameter_perturbation_design,
)


DOMAINS = {
    "allocation": (0.0, 1.0),
    "lookback": (2.0, 10.0),
    "hold": (1.0, 30.0),
    "confirmation": (1.0, 5.0),
}


def coordinate_names(parameters):
    if parameters["mode"] != "center_below" or parameters["center_kind"] != "mean":
        raise ValueError("This design supports only the handed-off mean-center-below family")
    if parameters["exit_mode"] not in ("fixed", "confirmed_guard"):
        raise ValueError("Exit mode outside reviewed geometry scope")
    names = ("allocation", "lookback", "hold")
    if parameters["exit_mode"] == "confirmed_guard":
        names += ("confirmation",)
    return names


def mapping(parameters, coordinates):
    """Map only active coordinates; keep every other payload parameter fixed."""
    names = coordinate_names(parameters)
    if len(names) != len(coordinates):
        raise ValueError("Coordinate count differs from active parameter space")
    mapped = dict(parameters)
    for name, value in zip(names, coordinates, strict=True):
        if name != "allocation" and not float(value).is_integer():
            raise ValueError("Integer coordinates cannot be silently rounded")
        mapped[name] = float(value) if name == "allocation" else int(value)
    return mapped


def feasibility(parameters, coordinates):
    """Pure predeclared executable-domain constraints; no economic observations."""
    mapped = mapping(parameters, coordinates)
    if not 0.0 < mapped["allocation"] <= 1.0:
        return False
    for name in coordinate_names(parameters)[1:]:
        lower, upper = DOMAINS[name]
        if not lower <= mapped[name] <= upper:
            return False
    # Existing runtime validation keeps this payload constraint even for fixed exit.
    if "max_hold" in mapped and not mapped["hold"] <= mapped["max_hold"] <= 30:
        return False
    return True


def analytic_points(parameters, radius=0.05):
    """Enumerate the real sphere's finite intersections with the integer lattice.

    One continuous coordinate gives at most two solutions per feasible integer
    tuple. Values here explain geometry only: they are not a replacement design
    and must never be bound/evaluated as the prescribed 32-point sample.
    """
    names = coordinate_names(parameters)
    integer_names = names[1:]
    choices = []
    for name in integer_names:
        lower, upper = DOMAINS[name]
        width = upper - lower
        choices.append(
            [
                v
                for v in range(int(lower), int(upper) + 1)
                if abs(v - parameters[name]) / width <= radius
            ]
        )
    points = []
    for integers in itertools.product(*choices):
        squared = sum(
            ((v - parameters[name]) / (DOMAINS[name][1] - DOMAINS[name][0])) ** 2
            for name, v in zip(integer_names, integers, strict=True)
        )
        remaining = radius * radius - squared
        if remaining < 0:
            continue
        step = math.sqrt(remaining)
        for sign in (-1, 1) if step else (0,):
            values = (parameters["allocation"] + sign * step, *integers)
            if feasibility(parameters, values):
                points.append(list(values))
    return points


def build_geometry(centers: list[dict], identity_by_id: dict):
    """Return JSON-safe requests/results and impossibility evidence for all centers.

    Each center is {candidate_id, parameters}; additional row fields are ignored.
    identity_by_id[candidate_id] is the authenticated public AssessmentCandidate.
    This function deliberately runs the prescribed public sampler, with its
    unchanged default radius/count/seed/budget, and never creates accounts.
    """
    protocol = ParameterPerturbationProtocol()
    mapping_source = "\n".join(
        ["DOMAINS = " + repr(DOMAINS), inspect.getsource(coordinate_names), inspect.getsource(mapping)]
    )
    feasibility_source = mapping_source + "\n" + inspect.getsource(feasibility)
    rows = []
    ids = [x["candidate_id"] for x in centers]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("A nonempty unique explicit center scope is required")
    for center in centers:
        key, parameters = center["candidate_id"], center["parameters"]
        identity = identity_by_id[key]
        if identity.candidate_id != f"S015-{key}":
            raise ValueError("Candidate identity differs from selected center")
        names = coordinate_names(parameters)
        coordinates = tuple(
            ParameterCoordinate(
                name,
                float(parameters[name]),
                *DOMAINS[name],
                ParameterCoordinateKind.CONTINUOUS
                if name == "allocation"
                else ParameterCoordinateKind.INTEGER,
            )
            for name in names
        )
        request = ParameterDesignRequest(
            identity,
            protocol,
            ParameterSpace(
                coordinates,
                sha256(mapping_source.encode("utf-8")).hexdigest(),
                sha256(feasibility_source.encode("utf-8")).hexdigest(),
            ),
        )
        result = build_parameter_perturbation_design(
            request, feasibility=lambda values, p=parameters: feasibility(p, values)
        )
        intersections = analytic_points(parameters, protocol.radius)
        rows.append(
            {
                "candidate_id": key,
                "active_coordinates": list(names),
                "fixed_payload_parameters": {k: v for k, v in parameters.items() if k not in names},
                "request": request.to_dict(),
                "result": result.to_dict(),
                "mathematical_feasible_point_count": len(intersections),
                "mathematical_points_explanation_only": intersections,
                "sampler_accepted_float_tuples": result.attempts
                - sum(x.count for x in result.rejections),
                "float_note": "Different floating-point encodings near one mathematical point do not create independent or economically meaningful perturbations.",
            }
        )
    return {
        "status": "GEOMETRY_EVALUATED_NO_ACCOUNTS",
        "protocol": protocol.to_dict(),
        "mapping_source": mapping_source,
        "feasibility_source": feasibility_source,
        "domain_basis": {
            "allocation": "Existing runtime (0,1], represented by [0,1] envelope plus pure >0 constraint",
            "lookback": "Existing integer 2..10; minimum normalized nonzero step=1/8 > 0.05",
            "hold": "Existing integer 1..30; only center-1/center/center+1 fit radius 0.05",
            "confirmation": "Existing guard integer 1..5; minimum step=1/4 > 0.05; absent from fixed exits",
            "excluded": "concentration, failure_buffer, max_hold, start and categorical rules remain fixed; none added as inactive continuous coordinates",
        },
        "rows": rows,
        "limitations": [
            "At most six mathematical points per center, before upper-bound truncation; 32 distinct real points are impossible in the unchanged reviewed domains.",
            "Failure of this design is not a measured strategy loss or a new economic acceptance threshold.",
            "No radius/domain relaxation, inactive coordinate, partial quantile, account, registry write or publication is produced.",
        ],
    }
