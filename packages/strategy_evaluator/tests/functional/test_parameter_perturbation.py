from dataclasses import replace
import math

import pytest

from strategy_evaluator import (
    ParameterDesignRequest,
    ParameterSpace,
    ParameterCoordinate,
    ParameterCoordinateKind,
    ParameterPerturbationProtocol,
)
from strategy_evaluator import research_models as m
from test_research_assessment import candidate, evidence, protocol


def design_request(dimension=8, count=32, radius=0.05):
    coordinates = tuple(
        ParameterCoordinate(str(i), 5.0, 0.0, 10.0, ParameterCoordinateKind.CONTINUOUS)
        for i in range(dimension)
    )
    return ParameterDesignRequest(
        candidate(),
        ParameterPerturbationProtocol(radius=radius, point_count=count),
        ParameterSpace(coordinates, "a" * 64, "b" * 64),
    )


def build(request=None):
    """Synthetic historical sphere records; never call the retired sampling API."""
    req = request or design_request()
    count, radius = req.protocol.point_count, req.protocol.radius
    points = tuple(m.ParameterPerturbationPoint(i, (
        5.0 + 10 * radius * math.cos(2 * math.pi * i / count),
        5.0 + 10 * radius * math.sin(2 * math.pi * i / count),
        *((5.0,) * (len(req.space.coordinates) - 2)),
    ), radius) for i in range(count))
    design = m.ParameterPerturbationDesign(req.center, req.protocol, req.space, points, count, ())
    return m.ParameterDesignResult(req.sha256, m.ParameterDesignStatus.COMPLETE, design, count, (), None)


def bound_request():
    import strategy_evaluator as se
    design = se.build_parameter_neighborhood_design(se.ParameterNeighborhoodRequest(candidate(),
        se.ParameterNeighborhoodProtocol(), se.ParameterNeighborhoodSpace((se.ParameterAxis('hold', 20,
            se.IntegerDomain(1, 30), se.BoundedLocalStep(se.RelativeChangeLimit(.05)), ('hold',), 'sessions'),),
            'a' * 64, 'b' * 64)), feasibility=lambda _: True).design
    center, a, b = candidate(), candidate("C0002", "b"), candidate("C0003", "c")
    links = tuple(
        m.PerturbationLink(center, child, 1.0, "e" * 64, design.bind_point(i))
        for i, child in enumerate((a, b))
    )
    items = (
        evidence(center),
        evidence(center, scenario="pressure"),
        *(
            replace(
                evidence(link.child, (5.0, 10.0), parent=center),
                parameter_point=link.parameter_point,
            )
            for link in links
        ),
    )
    return m.CandidateAssessmentRequest(
        (center,),
        replace(protocol(), parameter_protocol=design.protocol),
        links,
        items,
        parameter_designs=(design,),
    )


@pytest.mark.risk_cases('SE-33-C02')
def test_historical_sphere_record_roundtrip_radius_and_accounting():
    dimension = 8
    result = build(design_request(dimension))
    assert m.ParameterDesignResult.from_dict(result.to_dict()) == result
    import strategy_evaluator as se
    from strategy_evaluator import parameter_perturbation
    assert not hasattr(se, "build_parameter_perturbation_design")
    assert not hasattr(parameter_perturbation, "build_parameter_perturbation_design")
    for point in result.design.points:
        distance = math.sqrt(sum(((v - 5.0) / 10.0) ** 2 for v in point.coordinates))
        assert distance == pytest.approx(0.05, abs=1e-15)
    with pytest.raises(ValueError, match="radius"):
        replace(result.design, points=(replace(result.design.points[0], actual_radius=0.1), *result.design.points[1:]))
    with pytest.raises(ValueError, match="accounting"):
        replace(result, attempts=0)
