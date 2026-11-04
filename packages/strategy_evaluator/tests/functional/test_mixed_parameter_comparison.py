"""Mixed-coordinate Calmar comparisons preserve scale and structural semantics."""

from dataclasses import replace

import pytest

import strategy_evaluator as se
from test_calmar_ranking import assessed, common_contract, request
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


@pytest.mark.parametrize("center,domain,expected", [
    (40, se.IntegerDomain(1, 100), {39, 40, 41}),
    (20, se.IntegerDomain(1, 100), {19, 20, 21}),
    (3, se.IntegerDomain(1, 100), {3}),
    (40, se.IntegerDomain(40, 100), {40, 41}),
    (40, se.IntegerDomain(1, 40), {39, 40}),
    (40, se.IntegerDomain(1, 100, step=2), {38, 40, 42}),
    (41, se.IntegerDomain(1, 101, step=2, origin=1), {39, 41, 43}),
])
def test_integer_nearest_legal_steps_and_fixed_coordinates_preserve_types(center, domain, expected):
    who = candidate()
    design = mixed_design(who, window=integer_axis(center, domain))
    values = {v.value for p in design.points for v in p.values if v.name == "window"}
    assert values == expected
    assert all(type(value) is int for value in values)
    assert {v.value for p in design.points for v in p.values if v.name == "probe"} == {3}
    req = request(assessed(who, geometry=design))
    assert se.CalmarComparisonRequest.from_dict(req.to_dict()) == req
    assert se.compare_candidates(req).rows[0].status is se.ComparisonStatus.RANKED


@pytest.mark.parametrize("mutation", [
    lambda axis: replace(axis, domain=se.IntegerDomain(1, 100, step=2)),
    lambda axis: replace(axis, domain=se.IntegerDomain(1, 100, origin=1)),
    lambda axis: replace(axis, domain=se.IntegerDomain(1, 101)),
    lambda axis: replace(axis, center=40.0, domain=se.RealDomain(1.0, 100.0)),
    lambda axis: replace(axis, unit="days"),
    lambda axis: replace(axis, payload_path=("lookback",)),
])
def test_cross_candidate_integer_semantics_cannot_be_silently_mixed(mutation):
    a, b = candidate(), candidate("C0002", "b")
    with pytest.raises(ValueError, match="semantics, domains, units or mapping differ"):
        request(assessed(a, geometry=mixed_design(a)),
                assessed(b, geometry=mixed_design(b, window=mutation(integer_axis()))))


@pytest.mark.parametrize("kwargs", [
    {"mode": "trend"}, {"categories": ("repair", "trend", "other")},
])
def test_fixed_category_value_and_domain_are_part_of_comparison_semantics(kwargs):
    a, b = candidate(), candidate("C0002", "b")
    with pytest.raises(ValueError, match="semantics, domains, units or mapping differ"):
        request(assessed(a, geometry=mixed_design(a)), assessed(b, geometry=mixed_design(b, **kwargs)))


def test_numeric_centers_may_differ_under_the_same_mixed_contract():
    a, b = candidate(), candidate("C0002", "b")
    req = request(assessed(a, geometry=mixed_design(a)),
                  assessed(b, geometry=mixed_design(b, window=integer_axis(20))))
    assert all(x.status is se.ComparisonStatus.TIED for x in se.compare_candidates(req).rows)


@pytest.mark.parametrize("center", [40.5, 40.0, True, 39])
def test_integer_domain_rejects_fractional_boolean_and_off_grid_centers(center):
    with pytest.raises(ValueError, match="exact typed domain"):
        integer_axis(center, se.IntegerDomain(1, 100, step=2))


@pytest.mark.parametrize("step", [0, -1, 1.5, True])
def test_integer_domain_rejects_invalid_steps(step):
    with pytest.raises((ValueError, TypeError)):
        se.IntegerDomain(1, 100, step=step)


def test_integer_zero_requires_matching_absolute_limit_and_nonzero_matching_relative_limit():
    who = candidate()
    design = mixed_design(who, window=integer_axis(0, se.IntegerDomain(-2, 2), se.AbsoluteChangeLimit(1.0)))
    contract = se.CommonNeighborhoodComparisonContract(
        se.RelativeChangeLimit(.05), (se.ZeroCenterAbsoluteLimit("window", se.AbsoluteChangeLimit(1.0)),),
    )
    assert se.compare_candidates(request(assessed(who, geometry=design), contract=contract)).rows
    for zero_limits in ((), (se.ZeroCenterAbsoluteLimit("window", se.AbsoluteChangeLimit(2.0)),)):
        with pytest.raises(ValueError, match="zero-center axis"):
            replace(contract, zero_limits=zero_limits).authenticate(design)
    wrong = mixed_design(who, window=integer_axis(limit=se.RelativeChangeLimit(.04)))
    with pytest.raises(ValueError, match="nonzero axis"):
        common_contract().authenticate(wrong)


def test_local_sensitivity_rejects_a_changing_category():
    design = mixed_design(candidate())
    mode = replace(design.space.axes[-1], rule=se.ExplicitValues(("repair", "trend")))
    with pytest.raises(ValueError):
        se.ParameterNeighborhoodRequest(design.center, design.protocol,
            replace(design.space, axes=(*design.space.axes[:-1], mode)))


@pytest.mark.parametrize("domain", [
    se.RealDomain(1.0, 100.0, quantum=1.0), se.RealSetDomain((39.0, 40.0, 41.0)),
    se.IntegerSetDomain((39, 40, 41)), se.OrdinalDomain((39, 40, 41)),
])
def test_other_coordinate_families_are_not_implicitly_enabled(domain):
    center = 40.0 if isinstance(domain, (se.RealDomain, se.RealSetDomain)) else 40
    design = mixed_design(candidate(), window=integer_axis(center, domain))
    with pytest.raises(ValueError, match="continuous real, integer or fixed categorical"):
        common_contract().authenticate(design)


def test_declared_mixed_contract_checks_only_axes_and_keeps_original_bindings(monkeypatch):
    design = mixed_design(candidate())
    selected = se.DeclaredParameterPointSet(design, (1, 4, 7), "d" * 64)
    contract = se.DeclaredPointSetComparisonContract("d" * 64, common_contract())
    expected = common_contract().authenticate(design)
    original = selected.bind_point(7)

    def forbidden(*args, **kwargs):
        raise AssertionError("comparison must not rebuild or traverse the source grid")

    monkeypatch.setattr(se, "build_parameter_neighborhood_design", forbidden)
    monkeypatch.setattr(se.ParameterNeighborhoodDesign, "points", property(forbidden), raising=False)
    assert contract.authenticate(selected) == ("d" * 64, expected)
    with pytest.raises(ValueError, match="construction differs"):
        replace(contract, construction_sha256="e" * 64).authenticate(selected)
    with pytest.raises(ValueError, match="full neighborhood"):
        common_contract().authenticate(selected)
    assert original.point_index == 7
