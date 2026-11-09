"""RSCH ranking priorities and frequency scope through public SE contracts."""

from dataclasses import replace

import pytest

from strategy_evaluator.research_assessment import recompute_historical_assessment as assess_candidates
from strategy_evaluator import research_models as m
from test_research_assessment import candidate, compare, evidence, policy, request, row, values


def metrics(item, **changes):
    return replace(item, diagnostics=tuple(
        replace(x, value=changes[x.metric.value]) if x.metric.value in changes else x
        for x in item.diagnostics
    ))


def tradeoff_rows():
    a = row(candidate(), annual=0.2, drawdown=0.2)
    b = row(candidate("C0002", "b"), annual=0.11, drawdown=0.1)
    return tuple(metrics(x, PARAMETER_RETURN_Q10=0.1, PARAMETER_DRAWDOWN_Q90=0.2)
                 for x in (a, b))


@pytest.mark.risk_cases('SE-10-C01')
def test_layers_precede_robustness_and_frequency():
    a = metrics(row(candidate(), annual=0.2, drawdown=0.1),
                PARAMETER_RETURN_Q10=-0.1, FULL_SAMPLE_FREQUENCY=1.0)
    b = metrics(row(candidate("C0002", "b"), annual=0.1, drawdown=0.2),
                PARAMETER_RETURN_Q10=0.09, FULL_SAMPLE_FREQUENCY=100.0)
    ranked = compare((b, a)).rows
    assert [(x.candidate, x.pareto_layer) for x in ranked] == [(a.candidate, 1), (b.candidate, 2)]


@pytest.mark.risk_cases('SE-10-C04')
def test_frequency_is_last_and_center_metrics_are_not_repeated():
    a, b = tradeoff_rows()
    assert all(x.status is m.ComparisonStatus.TIED for x in compare((a, b)).rows)
    b = metrics(b, FULL_SAMPLE_FREQUENCY=8.0)
    ranked = compare((a, b))
    assert ranked.rows[0].candidate == b.candidate
    assert ranked.pairs[0].decisive_metric is m.ResearchMetric.FULL_SAMPLE_FREQUENCY
    reversed_bins = replace(policy(), bins=tuple(reversed(policy().bins)))
    assert compare((b, a), reversed_bins).rows == ranked.rows
    assert len(ranked.rows[0].bin_values) == 6
    assert m.ComparisonPolicy.from_dict(policy().to_dict()) == policy()


def annual_evidence():
    base = evidence(profits=(10.0, 20.0, 30.0))
    sessions = ("2024-12-27", "2024-12-30", "2024-12-31", "2025-12-31",
                "2026-01-02", "2026-12-31")
    mapping = {x.session: day for x, day in zip(base.account, sessions)}
    return replace(base, frequency_window_days=60,
                   account=tuple(replace(x, session=mapping[x.session]) for x in base.account),
                   fills=tuple(replace(x, session=mapping[x.session]) for x in base.fills),
                   closed_cycles=tuple(replace(x, exit_session=mapping[x.exit_session])
                                       for x in base.closed_cycles),
                   benchmark_equity=(1100.0, 1100.0, 1100.0, 990.0, 990.0, 1089.0))


@pytest.mark.risk_cases('SE-03-C07')
def test_positive_year_frequency_pools_days_and_counts_actual_exit_year():
    base = annual_evidence()
    got = values(assess_candidates(replace(request(), evidence=(base,))))
    # 2024/2026 positive: five actual sessions, two exits. The cross-year trade exits in 2025.
    metric = got[m.ResearchMetric.BENCHMARK_POSITIVE_YEAR_FREQUENCY]
    assert metric.value == 24.0
    assert metric.evaluation_ids == (base.evaluation_id,)
    assert got[m.ResearchMetric.FULL_SAMPLE_FREQUENCY].value == 30.0
    no_positive = replace(base, benchmark_equity=(1000.,) * 6)
    unavailable = values(assess_candidates(replace(request(), evidence=(no_positive,))))
    metric = unavailable[m.ResearchMetric.BENCHMARK_POSITIVE_YEAR_FREQUENCY]
    assert metric.value is None
    assert metric.status is m.DiagnosticStatus.NOT_APPLICABLE
    assert metric.reason == "NO_BENCHMARK_POSITIVE_YEARS"
