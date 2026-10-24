"""Variable-cardinality neighborhood acceptance and legacy method isolation."""

from dataclasses import replace

import pytest

from strategy_evaluator import research_models as m
from strategy_evaluator.parameter_neighborhood import (
    ParameterNeighborhoodContext,
    ParameterNeighborhoodProtocol,
    StudyPurpose,
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
    return compare((item,), targets=(goal or target(),)).rows[0].target_checks[0]


@pytest.mark.parametrize("passes,status", [(13, "FAILED"), (14, "PASSED"), (17, "PASSED")])
def test_seventeen_points_require_fourteen_joint_passes(passes, status):
    result = check(neighborhood_row(passes))
    assert result.required_points == 17 and result.minimum_joint_passes == 14
    assert result.valid_points == 17 and result.joint_passes == passes
    assert result.status.value == status
    assert m.ParameterNeighborhoodCheck.from_dict(result.to_dict()) == result


def test_missing_point_does_not_shrink_denominator_or_pass():
    item = neighborhood_row(14)
    missing = replace(item, parameter_performances=item.parameter_performances[:-1])
    result = check(missing)
    assert (result.required_points, result.minimum_joint_passes, result.valid_points) == (
        17,
        14,
        16,
    )
    assert result.status is m.TargetCheckStatus.INDETERMINATE
    assert result.reason == "INCOMPLETE_PARAMETER_COVERAGE"


def test_full_coverage_with_missing_benchmark_stays_indeterminate():
    item = neighborhood_row()
    missing = replace(
        item,
        parameter_performances=tuple(
            replace(x, benchmark_return=None, benchmark_drawdown=None)
            for x in item.parameter_performances
        ),
    )
    result = check(missing)
    assert result.status is m.TargetCheckStatus.INDETERMINATE
    assert result.reason == "INDETERMINATE_PARAMETER_CONDITION"


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


def test_legacy_thirtytwo_twenty_six_contract_is_unchanged():
    for passed, expected in ((25, "FAILED"), (26, "PASSED")):
        result = check(parameter_row(passed), parameter_target())
        assert type(result) is m.ParameterGroupCheck
        assert result.status.value == expected
        assert (result.valid_points, result.joint_passes) == (32, passed)
        assert result.target.minimum_joint_passes == 26
    equivalent_ratio = check(neighborhood_row(26, 32))
    assert equivalent_ratio.minimum_joint_passes == 26
    assert equivalent_ratio.status is m.TargetCheckStatus.PASSED


def test_legacy_and_neighborhood_contracts_cannot_substitute_for_one_another():
    legacy_target = check(neighborhood_row(26, 32), parameter_target())
    assert legacy_target.status is m.TargetCheckStatus.INDETERMINATE
    assert legacy_target.reason == "PARAMETER_DESIGN_MISSING_OR_DIFFERS"
    new_target = check(parameter_row(), target())
    assert new_target.status is m.TargetCheckStatus.INDETERMINATE
    assert new_target.reason == "PARAMETER_NEIGHBORHOOD_MISSING_OR_DIFFERS"
    assert (
        new_target.required_points,
        new_target.minimum_joint_passes,
        new_target.valid_points,
    ) == (0, 0, 0)


def test_missing_context_and_structural_control_do_not_gain_acceptance():
    item = neighborhood_row()
    missing = replace(item, parameter_context=None, parameter_performances=())
    assert check(missing).status is m.TargetCheckStatus.INDETERMINATE
    control = replace(
        item,
        parameter_context=replace(
            item.parameter_context,
            protocol=ParameterNeighborhoodProtocol(purpose=StudyPurpose.STRUCTURAL_CONTROL),
        ),
    )
    result = check(control)
    assert result.status is m.TargetCheckStatus.INDETERMINATE
    assert result.reason == "STRUCTURAL_CONTROL_NOT_ACCEPTANCE"


@pytest.mark.parametrize("numerator,denominator", [(0, 16), (17, 16), (13, 0), (True, 16)])
def test_bad_fraction_rejected_at_target_construction(numerator, denominator):
    with pytest.raises((ValueError, TypeError)):
        target(numerator, denominator)


def test_exact_integer_ceiling_handles_nonbinary_fraction_and_one_point():
    assert check(neighborhood_row(12), target(2, 3)).minimum_joint_passes == 12
    one = check(neighborhood_row(1, 1))
    assert (one.required_points, one.minimum_joint_passes) == (1, 1)
    assert one.status is m.TargetCheckStatus.PASSED
