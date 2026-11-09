"""Mixed-coordinate Calmar comparisons preserve scale and structural semantics."""

from dataclasses import replace

import pytest

import strategy_evaluator as se
from test_calmar_ranking import assessed, request
from test_research_assessment import candidate


def integer_axis(center=40, domain=None, limit=None):
    return se.ParameterAxis(
        "window", center, domain or se.IntegerDomain(1, 100),
        se.BoundedLocalStep(limit or se.RelativeChangeLimit(.05)), ("window",), "sessions",
    )


def mixed_design(who, *, window=None, mode="repair", categories=("repair", "trend")):
    axes = (
        se.ParameterAxis("fraction", .5, se.RealDomain(0.0, 1.0),
                         se.BoundedLocalStep(se.RelativeChangeLimit(.05)), ("fraction",), "ratio"),
        window or integer_axis(),
        replace(integer_axis(3), name="probe", payload_path=("probe",)),
        se.ParameterAxis("mode", mode, se.CategoricalDomain(categories),
                         se.ExplicitValues((mode,)), ("mode",), "category"),
    )
    return se.build_parameter_neighborhood_design(se.ParameterNeighborhoodRequest(
        who, se.ParameterNeighborhoodProtocol(),
        se.ParameterNeighborhoodSpace(axes, "a" * 64, "b" * 64),
    ), feasibility=lambda values: True).design


@pytest.mark.parametrize('mutation', [
    pytest.param(lambda axis: replace(axis, domain=se.IntegerDomain(1, 100, step=2)), id='SE-19-C02'),
    pytest.param(lambda axis: replace(axis, domain=se.IntegerDomain(1, 100, origin=1)), id='SE-19-C03'),
])
@pytest.mark.risk_cases('SE-19-C02', 'SE-19-C03')
def test_cross_candidate_integer_semantics_cannot_be_silently_mixed(mutation):
    a, b = candidate(), candidate("C0002", "b")
    with pytest.raises(ValueError, match="semantics, domains, units or mapping differ"):
        request(assessed(a, geometry=mixed_design(a)),
                assessed(b, geometry=mixed_design(b, window=mutation(integer_axis()))))


@pytest.mark.risk_cases('SE-19-C04')
def test_fixed_category_value_and_domain_are_part_of_comparison_semantics():
    kwargs = {"mode": "trend"}
    a, b = candidate(), candidate("C0002", "b")
    with pytest.raises(ValueError, match="semantics, domains, units or mapping differ"):
        request(assessed(a, geometry=mixed_design(a)), assessed(b, geometry=mixed_design(b, **kwargs)))
