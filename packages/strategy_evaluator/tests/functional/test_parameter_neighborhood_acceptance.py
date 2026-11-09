"""Variable-cardinality neighborhood acceptance and legacy method isolation."""

from dataclasses import replace

import pytest

from strategy_evaluator import research_models as m
from strategy_evaluator.parameter_neighborhood import (
    ParameterNeighborhoodContext,
    ParameterNeighborhoodProtocol,
)
from test_research_acceptance import parameter_row, parameter_target
from test_research_assessment import compare


def target(numerator=13, denominator=16):
    old = parameter_target()
    return m.ParameterNeighborhoodTarget(
        "neighborhood", numerator, denominator, old.joint_targets, old.all_point_targets
    )


def neighborhood_row(passes=14, total=17):
    old = parameter_row(passes)
    context = ParameterNeighborhoodContext(
        ParameterNeighborhoodProtocol(), "a" * 64, "b" * 64, 2, total, total, "c" * 64
    )
    return replace(
        old, parameter_context=context, parameter_performances=old.parameter_performances[:total]
    )


def check(item, goal=None):
    # Exercise current acceptance for neighborhood contexts, retaining explicit
    # historical comparison only for the sphere isolation cases below.
    current = item.parameter_context is None or isinstance(
        item.parameter_context, ParameterNeighborhoodContext
    )
    return compare((item,), targets=(goal or target(),), current=current).rows[0].target_checks[0]


@pytest.mark.parametrize('passes,status', [
    pytest.param(13, "FAILED", id='SE-17-C03'),
    pytest.param(14, "PASSED", id='SE-17-C02'),
])
@pytest.mark.risk_cases('SE-17-C02', 'SE-17-C03')
def test_seventeen_points_require_fourteen_joint_passes(passes, status):
    result = check(neighborhood_row(passes), target(4, 5))
    assert result.required_points == 17 and result.minimum_joint_passes == 14
    assert result.valid_points == 17 and result.joint_passes == passes
    assert result.status.value == status
    assert m.ParameterNeighborhoodCheck.from_dict(result.to_dict()) == result






@pytest.mark.risk_cases('SE-17-C04')
def test_joint_conditions_intersect_on_same_points():
    item = neighborhood_row(14)
    crossed = replace(
        item,
        parameter_performances=tuple(
            replace(x, drawdown=0.1) if x.point_index < 3 else x
            for x in item.parameter_performances
        ),
    )
    result = check(crossed)
    assert result.joint_passes == 11
    assert result.status is m.TargetCheckStatus.FAILED


@pytest.mark.risk_cases('SE-17-C05')
def test_all_point_risk_is_not_replaced_by_joint_pass_fraction():
    item = neighborhood_row(14)
    bad = replace(
        item,
        parameter_performances=(
            *item.parameter_performances[:-1],
            replace(item.parameter_performances[-1], drawdown=0.250001),
        ),
    )
    result = check(bad)
    assert result.joint_passes == 14
    assert result.status is m.TargetCheckStatus.FAILED
    assert result.reason == "PARAMETER_ALL_POINT_TARGET_NOT_MET"
    equal = replace(
        bad,
        parameter_performances=(
            *bad.parameter_performances[:-1],
            replace(bad.parameter_performances[-1], drawdown=0.25),
        ),
    )
    assert check(equal).status is m.TargetCheckStatus.PASSED
    # Known all-point risk failure is retained even if another point is absent.
    partial = replace(bad, parameter_performances=bad.parameter_performances[1:])
    assert check(partial).status is m.TargetCheckStatus.FAILED
