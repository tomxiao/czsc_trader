from dataclasses import replace
from itertools import permutations

import pytest

from strategy_evaluator import assess_candidates
from strategy_evaluator import research_models as m
from test_research_assessment import candidate, compare, evidence, policy, request, row, values


def partial_policy():
    return replace(
        policy(),
        pareto_basis=m.ParetoBasis.BINNED,
        missing_evidence_policy=m.MissingEvidencePolicy.PREFIX_PARTIAL,
    )


def benchmark(item, annual=0.05, drawdown=0.1, missing=False):
    return replace(
        item,
        benchmark=m.BenchmarkAssessment(
            tuple(
                m.DiagnosticValue(
                    metric,
                    m.MetricUnit.RATIO,
                    m.DiagnosticStatus.INSUFFICIENT_DATA
                    if missing
                    else m.DiagnosticStatus.AVAILABLE,
                    None if missing else value,
                    "MISSING_BENCHMARK" if missing else None,
                    ("b" * 64,),
                )
                for metric, value in zip(m.BENCHMARK_METRICS, (annual, drawdown))
            )
        ),
    )


def checks(item, *targets):
    return compare((item,), targets=targets).rows[0].target_checks


def test_full_sample_frequency_and_benchmark_are_computed_from_accounts():
    base = replace(
        evidence(), frequency_window_days=60, benchmark_equity=(1000.0, 1100.0, 900.0, 1050.0)
    )
    panel = assess_candidates(replace(request(), evidence=(base,)))
    assert panel.formula_version == "research-assessment-v2"
    assert values(panel)[m.ResearchMetric.FULL_SAMPLE_FREQUENCY].value == 30.0
    assert values(panel)[m.ResearchMetric.FREQUENCY_MEDIAN].value is None
    got = {x.metric: x for x in panel.rows[0].benchmark.diagnostics}
    assert got[m.ResearchMetric.NET_ANNUAL_RETURN].value == pytest.approx(1.05**63 - 1)
    assert got[m.ResearchMetric.DRAWDOWN_MAGNITUDE].value == pytest.approx(1 - 900 / 1100)
    assert all(x.evaluation_ids == (base.evaluation_id,) for x in got.values())


@pytest.mark.parametrize(
    "inclusive,expected", [(True, m.TargetCheckStatus.PASSED), (False, m.TargetCheckStatus.FAILED)]
)
def test_constant_and_benchmark_equal_boundaries(inclusive, expected):
    item = benchmark(row(candidate(), annual=0.1, drawdown=0.1))
    targets = (
        m.ResearchTarget(
            "return", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.BenchmarkBound(2.0, inclusive)
        ),
        m.ResearchTarget(
            "dd", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.BenchmarkBound(1.0, inclusive)
        ),
        m.ResearchTarget(
            "constant", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.ConstantBound(0.1, inclusive)
        ),
    )
    result = checks(item, *targets)
    assert all(x.status is expected for x in result)
    assert result[0].resolved_lower == result[1].resolved_upper == 0.1
    assert result[0].evaluation_ids == ("b" * 64,)


@pytest.mark.parametrize(
    "base,annual,expected",
    [
        (0.1, -0.01, m.TargetCheckStatus.NOT_APPLICABLE),
        (0.0, 0.0, m.TargetCheckStatus.FAILED),
        (-0.1, -0.05, m.TargetCheckStatus.FAILED),
        (-0.1, 0.01, m.TargetCheckStatus.PASSED),
    ],
)
def test_conditional_positive_return_preserves_nonpositive_benchmark_branch(base, annual, expected):
    target = m.ResearchTarget(
        "positive",
        m.ResearchMetric.NET_ANNUAL_RETURN,
        lower=m.ConstantBound(0.0, False),
        when=m.BenchmarkCondition(m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.LE, 0.0),
    )
    result = checks(benchmark(row(candidate(), annual=annual), annual=base), target)[0]
    assert result.status is expected
    assert result.condition_observed == base
    missing = checks(benchmark(row(candidate()), missing=True), target)[0]
    assert missing.status is m.TargetCheckStatus.INDETERMINATE
    assert missing.reason == "MISSING_CONDITION_BENCHMARK"


def test_multiple_same_metric_targets_and_missing_bound_do_not_pass():
    a = m.ResearchTarget(
        "relative", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.BenchmarkBound(1.5, True)
    )
    b = m.ResearchTarget("positive", a.metric, lower=m.ConstantBound(0.0, False))
    m.ResearchTargets((a, b), 60)
    with pytest.raises(ValueError, match="duplicate"):
        m.ResearchTargets((a, replace(b, target_id=a.target_id)), 60)
    result = compare((benchmark(row(candidate()), missing=True),), targets=(a, b)).rows[0]
    assert result.status is m.ComparisonStatus.INCOMPARABLE
    assert result.target_checks[0].reason == "MISSING_BOUND_BENCHMARK"
    with pytest.raises(TypeError):
        m.ResearchTarget("bad", a.metric, lower=0.1)
    with pytest.raises(TypeError):
        m.ConstantBound(True, True)
    with pytest.raises(ValueError):
        m.ResearchTarget("empty", a.metric, m.ConstantBound(0.1, False), m.ConstantBound(0.1, True))
    with pytest.raises(ValueError):
        m.ResearchTarget(
            "frequency", m.ResearchMetric.FULL_SAMPLE_FREQUENCY, lower=m.BenchmarkBound(1.0, True)
        )


def test_half_up_binning_changes_layer_explicitly_and_handles_negative_ties():
    a, b = (
        row(candidate(), annual=0.125, drawdown=0.1),
        row(candidate("C0002", "b"), annual=0.124, drawdown=0.1),
    )
    p = replace(
        partial_policy(),
        bins=tuple(replace(x, rounding=m.BinRounding.NEAREST_HALF_UP) for x in policy().bins),
    )
    got = compare((a, b), p)
    assert [x.pareto_layer for x in got.rows] == [1, 2]
    even = replace(
        p, bins=tuple(replace(x, rounding=m.BinRounding.NEAREST_HALF_EVEN) for x in p.bins)
    )
    assert [x.pareto_layer for x in compare((a, b), even).rows] == [1, 1]
    negative = replace(
        a,
        diagnostics=tuple(
            replace(x, value=-0.125) if x.metric is m.ResearchMetric.STRESS_ANNUAL_LOSS else x
            for x in a.diagnostics
        ),
    )
    assert compare((negative,), p).rows[0].bin_values[5] == -13


def test_prefix_partial_order_rank_intervals_match_all_linear_extensions():
    a = row(candidate(), degradation=0.01, missing=m.ResearchMetric.STRESS_ANNUAL_LOSS)
    a = replace(a, stress_scenario=None)
    b = row(candidate("C0002", "b"), degradation=0.02)
    c = row(candidate("C0003", "c"), missing=m.ResearchMetric.PARAMETER_RETURN_DEGRADATION)
    rows = (a, b, c)
    result = compare(rows, partial_policy())
    assert len(result.pairs) == 3
    assert sum(x.relation is m.PairwiseRelation.INCOMPARABLE for x in result.pairs) == 2
    assert all(x.pareto_layer == 1 for x in result.rows)
    assert compare(tuple(reversed(rows)), partial_policy()).rows == result.rows
    orders = [
        p
        for p in permutations([a.candidate, b.candidate, c.candidate])
        if p.index(a.candidate) < p.index(b.candidate)
    ]
    for ranked in result.rows:
        positions = [order.index(ranked.candidate) + 1 for order in orders]
        assert (ranked.rank_min, ranked.rank_max) == (min(positions), max(positions))
    assert m.CandidateComparison.from_dict(result.to_dict()) == result
    assert compare((a, b), partial_policy()).rows[0].status is m.ComparisonStatus.RANKED


def test_ties_use_competition_rank_and_never_candidate_id_as_economic_tiebreak():
    a, b, c = (
        row(candidate(), degradation=0.01),
        row(candidate("C0002", "b"), degradation=0.01),
        row(candidate("C0003", "c"), degradation=0.02),
    )
    result = compare((c, b, a), partial_policy())
    assert [x.rank_in_layer for x in result.rows] == [1, 1, 3]
    assert [x.status for x in result.rows] == [
        m.ComparisonStatus.TIED,
        m.ComparisonStatus.TIED,
        m.ComparisonStatus.RANKED,
    ]
