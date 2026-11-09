from dataclasses import replace
from itertools import permutations

import pytest

from strategy_evaluator import research_models as m
from test_research_assessment import candidate, compare, policy, row


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


@pytest.mark.parametrize('inclusive,expected', [
    pytest.param(True, m.TargetCheckStatus.PASSED, id='SE-04-C01'),
    pytest.param(False, m.TargetCheckStatus.FAILED, id='SE-04-C02'),
])
@pytest.mark.risk_cases('SE-04-C01', 'SE-04-C02')
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


@pytest.mark.risk_cases('SE-04-C03')
def test_SE_04_C03_negative_benchmark_obeys_only_declared_condition():
    target = m.ResearchTarget("positive-benchmark-only", m.ResearchMetric.NET_ANNUAL_RETURN,
        lower=m.ConstantBound(0., False),
        when=m.BenchmarkCondition(m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.GT, 0.))
    result = checks(benchmark(row(candidate(), annual=-.05), annual=-.1), target)[0]
    assert result.status is m.TargetCheckStatus.NOT_APPLICABLE
    assert result.condition_observed == -.1


@pytest.mark.risk_cases('SE-04-C04')
def test_SE_04_C04_same_metric_must_satisfy_upper_and_lower_bound():
    target = m.ResearchTarget("interval", m.ResearchMetric.NET_ANNUAL_RETURN,
                             lower=m.ConstantBound(0., True), upper=m.ConstantBound(.05, True))
    result = checks(benchmark(row(candidate(), annual=.1)), target)[0]
    assert result.observed == .1
    assert result.status is m.TargetCheckStatus.FAILED




@pytest.mark.risk_cases('SE-10-C03')
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
    assert compare((negative,), p).rows[0].bin_values[3] == -13


@pytest.mark.risk_cases('SE-12-C02')
def test_prefix_partial_order_rank_intervals_match_all_linear_extensions():
    a = row(candidate(), degradation=0.01, missing=m.ResearchMetric.STRESS_ANNUAL_LOSS)
    a = replace(a, stress_scenario=None)
    b = row(candidate("C0002", "b"), degradation=0.02)
    c = row(candidate("C0003", "c"), missing=m.ResearchMetric.PARAMETER_RETURN_Q10)
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


@pytest.mark.risk_cases('SE-12-C03')
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
