"""Contract and exact-boundary tests for complete typed neighborhoods."""

from dataclasses import replace
import math

import pytest

from strategy_evaluator import research_models as m
from strategy_evaluator.parameter_neighborhood import (
    AdjacentLevels,
    BooleanDomain,
    CategoricalDomain,
    ExplicitValues,
    IntegerDomain,
    IntegerSetDomain,
    NamedParameterValue,
    NeighborhoodConstraintExclusion,
    NeighborhoodRejection,
    NeighborhoodRejectionReason,
    NumericOffsets,
    OrdinalDomain,
    ParameterAxis,
    ParameterKind,
    ParameterNeighborhoodBinding,
    ParameterNeighborhoodContext,
    ParameterNeighborhoodProtocol,
    ParameterNeighborhoodRequest,
    ParameterNeighborhoodResult,
    ParameterNeighborhoodSpace,
    RealDomain,
    RealSetDomain,
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


def request(*axes, purpose=StudyPurpose.LOCAL_SENSITIVITY, limit=10000):
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


def test_integer_only_space_is_supported_without_continuous_coordinate():
    result = build(
        request(axis("hold", 3, IntegerDomain(1, 30), NumericOffsets((-1, 1)), unit="sessions"))
    )
    assert rows(result.design) == [(2,), (4,)]
    assert result.design.space.axes[0].kind is ParameterKind.INTEGER


def test_exact_real_arithmetic_open_boundary_and_no_clipping():
    result = build(
        request(
            axis(
                center=0.1,
                domain=RealDomain(0.0, 0.3, False, False),
                rule=NumericOffsets((-0.1, 0.2, 0.1)),
            )
        )
    )
    assert rows(result.design) == [(0.2,)]
    assert counts(result)[NeighborhoodRejectionReason.OUT_OF_DOMAIN] == 2
    assert 0.3 not in [v[0] for v in rows(result.design)]


def test_quantum_and_step_reject_without_rounding():
    real = build(
        request(
            axis(
                center=0.3,
                domain=RealDomain(0.0, 1.0, quantum=0.1),
                rule=NumericOffsets((0.1, 0.05)),
            )
        )
    )
    assert rows(real.design) == [(0.4,)]
    integer = build(
        request(axis("hold", 3, IntegerDomain(1, 9, 2, 1), NumericOffsets((1, 2)), unit="sessions"))
    )
    assert rows(integer.design) == [(5,)]
    assert counts(integer)[NeighborhoodRejectionReason.OUT_OF_DOMAIN] == 1
    with pytest.raises(ValueError, match="no admissible"):
        RealDomain(0.1, 0.2, quantum=1.0)
    with pytest.raises(ValueError, match="no admissible"):
        IntegerDomain(2, 2, 2, 1)


def test_numeric_sets_remain_numeric_types():
    result = build(
        request(
            axis(domain=RealSetDomain((0.9, 0.95, 1.0))),
            axis(
                "hold", 3, IntegerSetDomain((1, 3, 5)), NumericOffsets((-2, 1, 2)), unit="sessions"
            ),
        )
    )
    assert result.design.space.axes[0].kind is ParameterKind.REAL
    assert result.design.space.axes[1].kind is ParameterKind.INTEGER
    assert result.design.point_count == 8
    assert counts(result)[NeighborhoodRejectionReason.OUT_OF_DOMAIN] == 3


def test_ordinal_adjacency_uses_declared_order_and_reports_boundaries():
    a = axis(
        "speed",
        "slow",
        OrdinalDomain(("slow", "medium", "fast")),
        AdjacentLevels(),
        unit="ordered-level",
    )
    result = build(request(a))
    assert rows(result.design) == [("medium",)]
    assert counts(result)[NeighborhoodRejectionReason.OUT_OF_DOMAIN] == 1
    numeric = axis(
        "threshold", 10, OrdinalDomain((10, 100, 1000)), AdjacentLevels(), unit="ordered-level"
    )
    assert rows(build(request(numeric)).design) == [(100,)]


def test_categories_and_booleans_require_structural_control():
    cat = axis(
        "mode",
        "mean",
        CategoricalDomain(("mean", "median")),
        ExplicitValues(("median",)),
        unit="category",
    )
    flag = axis("enabled", True, BooleanDomain(), ExplicitValues((False,)), unit="boolean")
    with pytest.raises(ValueError, match="STRUCTURAL_CONTROL"):
        request(cat)
    with pytest.raises(ValueError, match="STRUCTURAL_CONTROL"):
        request(flag)
    result = build(request(cat, flag, purpose=StudyPurpose.STRUCTURAL_CONTROL))
    assert rows(result.design) == [("mean", False), ("median", True), ("median", False)]
    assert type(result.design.points[0].values[1].value) is bool
    assert ParameterNeighborhoodResult.from_dict(result.to_dict()) == result


@pytest.mark.parametrize(
    "factory",
    [
        lambda: IntegerDomain(True, 10),
        lambda: RealDomain("0", 1.0),
        lambda: RealDomain(0.0, math.inf),
        lambda: NumericOffsets((False,)),
        lambda: axis("hold", True, IntegerDomain(1, 30), NumericOffsets((-1, 1))),
        lambda: axis("hold", 3, IntegerDomain(1, 30), NumericOffsets((-1.0, 1.0))),
        lambda: axis(rule=ExplicitValues((1,))),
        lambda: axis("enabled", True, BooleanDomain(), ExplicitValues((1,))),
        lambda: OrdinalDomain((1, "two")),
        lambda: RealSetDomain((0.5, 0.5)),
        lambda: IntegerSetDomain((3, 1)),
        lambda: axis(rule=AdjacentLevels()),
    ],
)
def test_bad_types_and_domains_fail_at_construction(factory):
    with pytest.raises((ValueError, TypeError)):
        factory()


def test_paths_must_be_nonempty_unique_and_nonoverlapping():
    with pytest.raises(ValueError):
        ParameterAxis("x", 0.5, RealDomain(0.0, 1.0), NumericOffsets((0.1,)), (), "fraction")
    with pytest.raises(ValueError, match="overlapping"):
        request(axis(path=("risk",)), axis("other", path=("risk", "value")))
    with pytest.raises(ValueError, match="duplicate axis"):
        request(axis(), axis(path=("other",)))


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


def test_empty_neighborhood_and_callback_errors_do_not_return_partial_design():
    result = build(feasibility=lambda values: values[0].value == 0.95)
    assert result.design is None and result.reason == "NO_FEASIBLE_NONCENTER_POINTS"
    assert len(result.constraint_exclusions) == 2
    assert ParameterNeighborhoodResult.from_dict(result.to_dict()) == result
    infeasible = build(feasibility=lambda values: False)
    assert infeasible.design is None and infeasible.reason == "CENTER_VIOLATES_CONSTRAINT"
    with pytest.raises(TypeError, match="return bool"):
        build(feasibility=lambda values: 1)
    with pytest.raises(TypeError, match="callable"):
        build(feasibility=None)
    with pytest.raises(RuntimeError, match="constraint failed"):
        build(feasibility=lambda values: (_ for _ in ()).throw(RuntimeError("constraint failed")))


def test_comparison_identity_contains_actual_boundary_shape_and_semantics():
    base = build().design
    boundary = build(request(axis(center=1.0))).design
    interior = build(request(axis(center=0.9))).design
    assert base.comparison_sha256 != boundary.comparison_sha256
    assert base.comparison_sha256 == interior.comparison_sha256
    for altered in (
        request(axis(unit="other-unit")),
        request(axis(rule=NumericOffsets((-0.01, 0.01)))),
        replace(request(), space=replace(request().space, feasibility_sha256="d" * 64)),
        request(purpose=StudyPurpose.STRUCTURAL_CONTROL),
    ):
        assert build(altered).design.comparison_sha256 != base.comparison_sha256
    context = ParameterNeighborhoodContext(
        base.protocol,
        base.sha256,
        base.space.sha256,
        1,
        base.point_count,
        base.point_count,
        base.comparison_sha256,
    )
    assert ParameterNeighborhoodContext.from_dict(context.to_dict()) == context
    with pytest.raises(ValueError):
        replace(context, valid_points=base.point_count + 1)


def test_mutated_point_and_serialized_type_are_rejected():
    design = build().design
    with pytest.raises(ValueError, match="declared neighborhood"):
        replace(
            design,
            points=(
                replace(design.points[0], values=(NamedParameterValue("allocation", 0.91),)),
                *design.points[1:],
            ),
        )
    raw = request().to_dict()
    raw["space"]["axes"][0]["center"] = 1
    with pytest.raises(ValueError):
        ParameterNeighborhoodRequest.from_dict(raw)


def test_large_real_offset_is_rejected_as_boundary_not_float_crash():
    a = axis(center=1e308, domain=RealDomain(-1e308, 1e308), rule=NumericOffsets((1e308, -1e308)))
    result = build(request(a))
    assert rows(result.design) == [(0.0,)]
    assert counts(result)[NeighborhoodRejectionReason.OUT_OF_DOMAIN] == 1


@pytest.mark.parametrize("fake_reason", tuple(NeighborhoodRejectionReason))
def test_deleted_point_cannot_be_hidden_by_any_rejection_count(fake_reason):
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


def test_fixed_rejection_counts_and_order_are_independently_reconstructed():
    result = build(request(axis(center=1.0, rule=NumericOffsets((0.0, -0.1, 0.1)))))
    design = result.design
    assert counts(result) == {
        NeighborhoodRejectionReason.OUT_OF_DOMAIN: 1,
        NeighborhoodRejectionReason.DUPLICATE: 1,
        NeighborhoodRejectionReason.CENTER: 1,
    }
    for rejected in (
        (NeighborhoodRejection(NeighborhoodRejectionReason.CENTER, 3),),
        (
            NeighborhoodRejection(NeighborhoodRejectionReason.OUT_OF_DOMAIN, 2),
            NeighborhoodRejection(NeighborhoodRejectionReason.CENTER, 1),
        ),
        tuple(reversed(design.rejections)),
    ):
        with pytest.raises(ValueError, match="recomputed rejection"):
            replace(design, rejections=rejected)


def test_constraint_exclusions_cannot_be_missing_duplicate_or_overlapping():
    req = request(axis(center=0.5, rule=NumericOffsets((-0.2, -0.1, 0.1, 0.2))))
    result = build(req, lambda values: values[0].value <= 0.5)
    design = result.design
    assert rows(design) == [(0.3,), (0.4,)]
    assert [x.values[0].value for x in design.constraint_exclusions] == [0.6, 0.7]
    with pytest.raises(ValueError, match="incomplete declared neighborhood"):
        replace(design, constraint_exclusions=design.constraint_exclusions[:1])
    with pytest.raises(ValueError, match="duplicate constraint exclusion"):
        replace(design, constraint_exclusions=(design.constraint_exclusions[0],) * 2)
    with pytest.raises(ValueError, match="overlap"):
        replace(
            design,
            constraint_exclusions=(
                NeighborhoodConstraintExclusion(design.points[0].values),
                design.constraint_exclusions[1],
            ),
        )
    with pytest.raises(ValueError, match="constraint exclusion count"):
        replace(result, constraint_exclusions=())
    with pytest.raises(ValueError, match="accounting differ"):
        replace(result, constraint_exclusions=tuple(reversed(result.constraint_exclusions)))


def test_partition_order_and_excluded_points_are_strict():
    req = request(axis(center=0.5, rule=NumericOffsets((-0.2, -0.1, 0.1, 0.2))))
    design = build(req, lambda values: values[0].value <= 0.5).design
    with pytest.raises(ValueError, match="partition order"):
        replace(
            design, points=tuple(replace(p, index=i) for i, p in enumerate(reversed(design.points)))
        )
    with pytest.raises(ValueError, match="partition order"):
        replace(design, constraint_exclusions=tuple(reversed(design.constraint_exclusions)))
    for value in (0.5, 0.55, 1, True, 1.1):
        with pytest.raises(ValueError):
            replace(
                design,
                constraint_exclusions=(
                    NeighborhoodConstraintExclusion((NamedParameterValue("allocation", value),)),
                    design.constraint_exclusions[1],
                ),
            )
    with pytest.raises(ValueError, match="named point axes"):
        replace(
            design,
            constraint_exclusions=(
                NeighborhoodConstraintExclusion((NamedParameterValue("renamed", 0.6),)),
                design.constraint_exclusions[1],
            ),
        )
