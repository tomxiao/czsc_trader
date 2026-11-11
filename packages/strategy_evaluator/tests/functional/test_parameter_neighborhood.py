"""Contract and exact-boundary tests for complete typed neighborhoods."""

from dataclasses import replace
from fractions import Fraction
import math

import pytest

from strategy_evaluator import research_models as m
from strategy_evaluator.parameter_neighborhood import (
    AdjacentLevels,
    AbsoluteChangeLimit,
    BoundedLocalStep,
    BooleanDomain,
    CategoricalDomain,
    ExplicitValues,
    IntegerDomain,
    NamedParameterValue,
    NeighborhoodConstraintExclusion,
    NeighborhoodRejection,
    NeighborhoodRejectionReason,
    NumericOffsets,
    OrdinalDomain,
    ParameterAxis,
    ParameterNeighborhoodBinding,
    ParameterNeighborhoodContext,
    ParameterNeighborhoodProtocol,
    ParameterNeighborhoodRequest,
    ParameterNeighborhoodResult,
    ParameterNeighborhoodSpace,
    ParameterStepStatus,
    RelativeChangeLimit,
    RealDomain,
    StudyPurpose,
    build_parameter_neighborhood_design,
)


def axis(name="allocation", center=0.95, domain=None, rule=None, path=None, unit="fraction"):
    return ParameterAxis(
        name,
        center,
        domain or RealDomain(0.0, 1.0, False),
        rule or NumericOffsets((-0.05, 0.05)),
        path or (name,),
        unit,
    )


def request(*axes, purpose=StudyPurpose.STRUCTURAL_CONTROL, limit=10000):
    return ParameterNeighborhoodRequest(
        m.AssessmentCandidate("S001-C0001", "a" * 64),
        ParameterNeighborhoodProtocol(purpose, limit),
        ParameterNeighborhoodSpace(axes or (axis(),), "b" * 64, "c" * 64),
    )


def build(req=None, feasibility=lambda values: True):
    return build_parameter_neighborhood_design(req or request(), feasibility=feasibility)


def rows(design):
    return [tuple(v.value for v in p.values) for p in design.points]


def counts(result):
    return {r.reason: r.count for r in result.rejections}


@pytest.mark.risk_cases('SE-15-C01')
def test_weighted_enumeration_preserves_historical_partition_identity(monkeypatch):
    from itertools import product
    from strategy_evaluator import parameter_neighborhood as implementation
    fixed = tuple(ParameterAxis(f'fixed_{i}', True, BooleanDomain(), ExplicitValues((True,)),
        (f'fixed_{i}',), 'structure') for i in range(9))
    req = request(axis(center=0.98), *fixed, limit=10000)
    optimized = build(req)

    def historical(axes):
        rejected = {reason: 0 for reason in NeighborhoodRejectionReason}
        seen, legal = set(), []
        center = implementation._typed_key(item.center for item in axes)
        for values in product(*(implementation._choices(item) for item in axes)):
            if any(value is implementation._OUTSIDE or not implementation._contains(item.domain, value)
                   for item, value in zip(axes, values, strict=True)):
                rejected[NeighborhoodRejectionReason.OUT_OF_DOMAIN] += 1
                continue
            key = implementation._typed_key(values)
            if key in seen:
                rejected[NeighborhoodRejectionReason.DUPLICATE] += 1
                continue
            seen.add(key)
            if key == center:
                rejected[NeighborhoodRejectionReason.CENTER] += 1
                continue
            legal.append(tuple(NamedParameterValue(item.name, value)
                for item, value in zip(axes, values, strict=True)))
        return tuple(legal), rejected

    monkeypatch.setattr(implementation, '_enumerate_domain', historical)
    previous = build(req)
    assert previous.to_dict() == optimized.to_dict()
    assert previous.sha256 == optimized.sha256
    assert optimized.generated_combinations == 3 * 512


@pytest.mark.risk_cases('SE-15-C01')
def test_full_cartesian_typed_mapping_and_determinism():
    req = request(
        axis(), axis("hold", 3, IntegerDomain(1, 30), NumericOffsets((-1, 1)), unit="sessions")
    )
    result = build(req)
    assert result.status is m.ParameterDesignStatus.COMPLETE
    assert result.generated_combinations == 9
    assert result.design.point_count == 8
    assert rows(result.design) == [
        (0.95, 2),
        (0.95, 4),
        (0.9, 3),
        (0.9, 2),
        (0.9, 4),
        (1.0, 3),
        (1.0, 2),
        (1.0, 4),
    ]
    assert all(
        type(p.values[0].value) is float and type(p.values[1].value) is int
        for p in result.design.points
    )
    assert counts(result) == {NeighborhoodRejectionReason.CENTER: 1}
    assert build(req).sha256 == result.sha256
    assert ParameterNeighborhoodResult.from_dict(result.to_dict()) == result
    binding = result.design.bind_point(3)
    assert ParameterNeighborhoodBinding.from_dict(binding.to_dict()) == binding
    assert binding.design_sha256 == result.design.sha256
    assert binding.values == result.design.points[3].values
    with pytest.raises(ValueError):
        result.design.bind_point(True)


@pytest.mark.risk_cases('SE-13-C02')
def test_SE_13_C02_integer_center_must_lie_on_declared_grid():
    with pytest.raises(ValueError):
        axis("hold", 3, IntegerDomain(0, 10, 2, 0), NumericOffsets((-2, 2)), unit="sessions")


@pytest.mark.risk_cases('SE-13-C03')
def test_SE_13_C03_real_quantum_is_not_rounded():
    result = build(request(axis(center=.3, domain=RealDomain(0., 1., quantum=.1),
                                rule=NumericOffsets((.1, .05)))))
    assert rows(result.design) == [(.4,)]
    assert counts(result)[NeighborhoodRejectionReason.OUT_OF_DOMAIN] == 1


@pytest.mark.risk_cases('SE-13-C05')
def test_SE_13_C05_changed_category_requires_structural_control():
    category = axis("mode", "mean", CategoricalDomain(("mean", "median")),
                    ExplicitValues(("median",)), unit="category")
    with pytest.raises(ValueError, match="STRUCTURAL_CONTROL"):
        request(category, purpose=StudyPurpose.LOCAL_SENSITIVITY)
    assert rows(build(request(category)).design) == [("median",)]


@pytest.mark.risk_cases('SE-13-C01')
def test_SE_13_C01_boolean_is_not_integer_coordinate():
    with pytest.raises((ValueError, TypeError)):
        axis("hold", True, IntegerDomain(1, 30), NumericOffsets((-1, 1)))


@pytest.mark.risk_cases('SE-13-C06')
def test_SE_13_C06_boolean_domain_rejects_integer_one():
    with pytest.raises((ValueError, TypeError)):
        axis("enabled", True, BooleanDomain(), ExplicitValues((1,)))


@pytest.mark.risk_cases('SE-13-C04')
def test_SE_13_C04_payload_paths_cannot_overlap():
    with pytest.raises(ValueError, match="overlapping"):
        request(axis(path=("risk",)), axis("other", path=("risk", "value")))


@pytest.mark.risk_cases('SE-15-C02')
def test_duplicate_center_and_constraint_rejections_have_exact_accounting():
    calls = []
    req = request(axis(center=0.5, rule=NumericOffsets((0.0, -0.1, -0.1, 0.1))))

    def feasible(values):
        calls.append(values)
        assert isinstance(values[0], NamedParameterValue)
        return values[0].value <= 0.5

    result = build(req, feasible)
    assert rows(result.design) == [(0.4,)]
    assert len(calls) == 3
    assert counts(result) == {
        NeighborhoodRejectionReason.CENTER: 1,
        NeighborhoodRejectionReason.DUPLICATE: 2,
        NeighborhoodRejectionReason.CONSTRAINT: 1,
    }
    assert sum(counts(result).values()) + result.design.point_count == 5
    assert (
        result.constraint_exclusions
        == result.design.constraint_exclusions
        == (NeighborhoodConstraintExclusion((NamedParameterValue("allocation", 0.6),)),)
    )
    assert ParameterNeighborhoodResult.from_dict(result.to_dict()) == result


@pytest.mark.risk_cases('SE-15-C03')
def test_resource_limit_precedes_expansion_and_callback():
    calls = []
    req = request(axis(), axis("other"), limit=8)
    result = build(req, lambda values: calls.append(values) or True)
    assert result.status is m.ParameterDesignStatus.DESIGN_FAILED
    assert result.reason == "COMBINATION_LIMIT_EXCEEDED" and result.design is None
    assert result.generated_combinations == 9 and not calls
    huge = request(axis("level", "a", OrdinalDomain(("a", "b")), AdjacentLevels(10**30)), limit=8)
    assert build(huge).reason == "COMBINATION_LIMIT_EXCEEDED"
    assert (
        build(replace(req, protocol=replace(req.protocol, max_combinations=9))).design.point_count
        == 8
    )


@pytest.mark.risk_cases('SE-15-C05')
def test_SE_15_C05_feasibility_must_return_bool():
    with pytest.raises(TypeError, match='return bool'):
        build(feasibility=lambda values: 1)


@pytest.mark.risk_cases('SE-16-C03')
def test_SE_16_C03_actual_boundary_shape_changes_comparison_identity():
    base = build().design
    boundary = build(request(axis(center=1.0))).design
    interior = build(request(axis(center=.9))).design
    assert base.comparison_sha256 != boundary.comparison_sha256
    assert base.comparison_sha256 == interior.comparison_sha256


@pytest.mark.parametrize('changes', [
    pytest.param({"unit": "other-unit"}, id='SE-16-C04'),
    pytest.param({"path": ("different", "allocation")}, id='SE-16-C05'),
])
@pytest.mark.risk_cases('SE-16-C04', 'SE-16-C05')
def test_axis_business_semantics_change_comparison_identity(changes):
    base = build().design
    changed = build(request(axis(**changes))).design
    assert changed.space.sha256 != base.space.sha256
    assert changed.sha256 != base.sha256
    assert changed.bind_point(0).design_sha256 != base.bind_point(0).design_sha256
    if "path" in changes:
        # A payload location binds a distinct design, while identical business
        # axes and neighborhood geometry remain statistically comparable.
        assert changed.comparison_sha256 == base.comparison_sha256
    else:
        assert changed.comparison_sha256 != base.comparison_sha256


@pytest.mark.risk_cases('SE-16-C02')
def test_SE_16_C02_integer_coordinate_cannot_be_serialized_as_float():
    result = build(request(axis("hold", 3, IntegerDomain(1, 30), NumericOffsets((-1, 1)), unit="sessions")))
    raw = result.to_dict()
    raw["design"]["points"][0]["values"][0]["value"] = 2.0
    with pytest.raises((ValueError, TypeError)):
        ParameterNeighborhoodResult.from_dict(raw)


@pytest.mark.risk_cases('SE-16-C01')
def test_deleted_point_cannot_be_hidden_by_any_rejection_count():
    fake_reason = NeighborhoodRejectionReason.CONSTRAINT
    design = build().design
    forged_counts = {NeighborhoodRejectionReason.CENTER: 1}
    forged_counts[fake_reason] = forged_counts.get(fake_reason, 0) + 1
    rejected = tuple(
        NeighborhoodRejection(r, forged_counts[r])
        for r in NeighborhoodRejectionReason
        if r in forged_counts
    )
    with pytest.raises(ValueError, match="incomplete declared neighborhood"):
        replace(design, points=design.points[:1], rejections=rejected)
    raw = design.to_dict()
    raw["points"] = raw["points"][:1]
    raw["rejections"] = [r.to_dict() for r in rejected]
    with pytest.raises(ValueError, match="incomplete declared neighborhood"):
        type(design).from_dict(raw)


def local_axis(name="hold", center=3, domain=None, limit=None):
    return axis(name, center, domain or IntegerDomain(1, 30),
                BoundedLocalStep(limit or RelativeChangeLimit(0.05)), unit="sessions")


def local_request(*axes):
    return request(*axes, purpose=StudyPurpose.LOCAL_SENSITIVITY)


@pytest.mark.parametrize('center,expected', [
    pytest.param(3, [], id='SE-14-C01'),
    pytest.param(20, [(19,), (21,)], id='SE-14-C02'),
])
@pytest.mark.risk_cases('SE-14-C01', 'SE-14-C02')
def test_bounded_integer_applicability_uses_legal_minimum_and_inclusive_limit(center, expected):
    result = build(local_request(local_axis(center=center)))
    assert rows(result.design) == expected
    assert result.design.is_applicable is bool(expected)
    assert result.status is (m.ParameterDesignStatus.COMPLETE if expected
                            else m.ParameterDesignStatus.NOT_APPLICABLE)
    facts = result.design.axis_applicability[0]
    assert facts.is_applicable is bool(expected)
    assert [x.status for x in facts.decisions] == [
        ParameterStepStatus.INCLUDED if expected else ParameterStepStatus.LIMIT_EXCEEDED
    ] * 2
    assert ParameterNeighborhoodResult.from_dict(result.to_dict()) == result
    assert type(result.design).from_dict(result.design.to_dict()).axis_applicability == (facts,)
    if not expected:
        with pytest.raises(ValueError, match="outside neighborhood"):
            result.design.bind_point(0)




@pytest.mark.risk_cases('SE-14-C07')
def test_bounded_neighbors_follow_declared_domain():
    domain = OrdinalDomain(("low", "medium", "high"))
    center = "medium"
    limit = AbsoluteChangeLimit(1.)
    expected = [("low",), ("high",)]
    if isinstance(domain, OrdinalDomain):
        with pytest.raises(ValueError, match="nonzero numeric business scale"):
            local_axis(center=center, domain=domain)
    result = build(local_request(axis(center=center, domain=domain, rule=BoundedLocalStep(limit))))
    assert rows(result.design) == expected


@pytest.mark.risk_cases('SE-14-C03')
def test_SE_14_C03_zero_center_requires_explicit_absolute_scale():
    with pytest.raises(ValueError, match="nonzero numeric business scale"):
        local_axis(center=0, domain=IntegerDomain(-2, 2))


@pytest.mark.risk_cases('SE-14-C04')
def test_SE_14_C04_zero_center_absolute_scale_keeps_both_directions():
    assert rows(build(local_request(local_axis(center=0, domain=IntegerDomain(-2, 2),
                    limit=AbsoluteChangeLimit(1.0)))).design) == [(-1,), (1,)]


@pytest.mark.risk_cases('SE-14-C05')
def test_SE_14_C05_continuous_endpoints_round_inward():
    center, limit = 0.002002002002001957, RelativeChangeLimit(.05)
    result = build(local_request(local_axis(
        center=center, domain=RealDomain(-0.05, 0.05), limit=limit)))
    assert result.design.point_count == 2
    origin = Fraction(str(center))
    maximum = (abs(origin) * Fraction(str(limit.fraction))
               if isinstance(limit, RelativeChangeLimit) else Fraction(str(limit.amount)))
    for decision in result.design.axis_applicability[0].decisions:
        assert decision.status is ParameterStepStatus.INCLUDED
        change = (Fraction(str(decision.value)) - origin) * decision.direction
        assert 0 < change <= maximum
        assert Fraction(decision.change) == change
        # The chosen endpoint is the closest inward float, not an arbitrary smaller step.
        nearest = float(origin + decision.direction * maximum)
        assert decision.value in (nearest, math.nextafter(nearest, center))
    restored = ParameterNeighborhoodResult.from_dict(result.to_dict())
    assert restored == result and restored.sha256 == result.sha256


@pytest.mark.risk_cases('SE-14-C06')
def test_continuous_endpoint_respects_exact_open_or_closed_domain():
    closed = False
    expected = 1
    result = build(local_request(local_axis(center=1.0,
        domain=RealDomain(0.95, 2.0, lower_closed=closed))))
    assert result.design.point_count == expected
    assert result.design.axis_applicability[0].decisions[0].status is (
        ParameterStepStatus.INCLUDED if closed else ParameterStepStatus.OUT_OF_DOMAIN)


@pytest.mark.risk_cases('SE-15-C04')
def test_empty_or_constraint_excluded_local_space_has_explicit_inapplicability():
    req = replace(local_request(local_axis()), space=ParameterNeighborhoodSpace((), "b" * 64, "c" * 64))
    empty = build(req)
    assert empty.status is m.ParameterDesignStatus.NOT_APPLICABLE
    assert empty.design.axis_applicability == ()
    constrained = build(local_request(local_axis(center=20)), lambda values: values[0].value == 20)
    assert constrained.status is m.ParameterDesignStatus.NOT_APPLICABLE
    assert len(constrained.constraint_exclusions) == 2
    with pytest.raises(ValueError, match="accounting|partition"):
        replace(constrained.design, constraint_exclusions=())
    context = ParameterNeighborhoodContext(empty.design.protocol, empty.design.sha256,
        empty.design.space.sha256, 0, 0, 0, empty.design.comparison_sha256)
    assert not context.is_applicable
    with pytest.raises(ValueError, match="coverage"):
        replace(context, valid_points=1)
    infeasible = build(local_request(local_axis()), lambda values: False)
    assert infeasible.status is m.ParameterDesignStatus.DESIGN_FAILED
    with pytest.raises(ValueError, match="status differs"):
        replace(empty, status=m.ParameterDesignStatus.COMPLETE)




@pytest.mark.risk_cases('SE-33-C03')
def test_SE_33_C03_legacy_neighborhood_retains_identity_and_rejects_current_evaluation():
    from test_neighborhood_assessment import current_request
    from strategy_evaluator import assess_candidates
    old = replace(build().design, protocol=ParameterNeighborhoodProtocol(version='parameter-cartesian-neighborhood-v1'))
    raw = old.to_dict()
    decoded = type(old).from_dict(raw)
    assert decoded.to_dict() == raw and decoded.sha256 == old.sha256
    current = current_request()
    with pytest.raises(ValueError, match='v2|current|protocol|read-only'):
        assess_candidates(replace(current, protocol=replace(current.protocol, parameter_protocol=old.protocol)))

@pytest.mark.risk_cases('SE-33-C05')
def test_SE_33_C05_old_zero_point_design_cannot_gain_new_inapplicability():
    old = replace(build().design, protocol=ParameterNeighborhoodProtocol(version='parameter-cartesian-neighborhood-v1'))
    with pytest.raises(ValueError, match='noncenter point'):
        replace(old, points=())
