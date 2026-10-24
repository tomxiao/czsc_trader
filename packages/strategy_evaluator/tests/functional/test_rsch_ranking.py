"""RSCH ranking priorities and frequency scope through public SE contracts."""

from dataclasses import replace

import numpy as np
import pytest

from strategy_evaluator.research_assessment import recompute_historical_assessment as assess_candidates
from strategy_evaluator import research_models as m
from test_research_assessment import candidate, compare, evidence, policy, request, row, values
from test_parameter_perturbation import build, design_request


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


def test_layers_precede_robustness_and_frequency():
    a = metrics(row(candidate(), annual=0.2, drawdown=0.1),
                PARAMETER_RETURN_Q10=-0.1, FULL_SAMPLE_FREQUENCY=1.0)
    b = metrics(row(candidate("C0002", "b"), annual=0.1, drawdown=0.2),
                PARAMETER_RETURN_Q10=0.09, FULL_SAMPLE_FREQUENCY=100.0)
    ranked = compare((b, a)).rows
    assert [(x.candidate, x.pareto_layer) for x in ranked] == [(a.candidate, 1), (b.candidate, 2)]


def test_absolute_perturbed_return_beats_smaller_relative_degradation():
    a, b = tradeoff_rows()
    a = metrics(a, PARAMETER_RETURN_Q10=0.18, PARAMETER_RETURN_DEGRADATION=0.02)
    b = metrics(b, PARAMETER_RETURN_Q10=0.109, PARAMETER_RETURN_DEGRADATION=0.001)
    ranked = compare((b, a))
    assert ranked.rows[0].candidate == a.candidate
    assert ranked.pairs[0].decisive_metric is m.ResearchMetric.PARAMETER_RETURN_Q10


@pytest.mark.parametrize("metric,better,worse", [
    (m.ResearchMetric.PARAMETER_DRAWDOWN_Q90, 0.15, 0.25),
    (m.ResearchMetric.ROLLING_EXCESS_Q10, 0.02, 0.01),
    (m.ResearchMetric.STRESS_ANNUAL_LOSS, -0.02, 0.01),
    (m.ResearchMetric.PROFIT_CONCENTRATION, 0.2, 0.4),
])
def test_each_robustness_item_precedes_frequency(metric, better, worse):
    a, b = tradeoff_rows()
    a = metrics(a, **{metric.value: worse, "FULL_SAMPLE_FREQUENCY": 100.0})
    b = metrics(b, **{metric.value: better, "FULL_SAMPLE_FREQUENCY": 1.0})
    ranked = compare((a, b))
    assert ranked.rows[0].candidate == b.candidate
    assert ranked.pairs[0].decisive_metric is metric


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


def test_relative_degradation_is_diagnostic_only_and_missing_ranking_value_is_not_zero():
    a = row(candidate(), missing=m.ResearchMetric.PARAMETER_RETURN_DEGRADATION)
    assert compare((a,)).rows[0].status is m.ComparisonStatus.RANKED
    missing = row(candidate(), missing=m.ResearchMetric.PARAMETER_RETURN_Q10)
    assert compare((missing,)).rows[0].status is m.ComparisonStatus.INCOMPARABLE
    wrong_window = replace(a, frequency_window_days=30)
    assert "FREQUENCY_WINDOW_DIFFERS" in compare((wrong_window,)).rows[0].reasons


def test_frequency_scope_and_protocol_versions_are_explicit():
    positive = m.ResearchMetric.BENCHMARK_POSITIVE_YEAR_FREQUENCY
    target = m.ResearchTarget("frequency", positive, lower=m.ConstantBound(4.0, True))
    independent = compare((row(candidate()),), targets=(target,))
    assert independent.rows[0].target_checks[0].status is m.TargetCheckStatus.FAILED
    matched = policy(frequency_metric=positive)
    result = compare((metrics(row(candidate()), BENCHMARK_POSITIVE_YEAR_FREQUENCY=4.0),),
                     matched, targets=(target,))
    assert result.rows[0].target_checks[0].status is m.TargetCheckStatus.PASSED
    with pytest.raises(ValueError, match="eight bins"):
        replace(matched, bins=(*matched.bins, policy().bins[-1]))
    with pytest.raises(ValueError, match="invalid ranking bin"):
        m.MetricBinSpec(m.ResearchMetric.PARAMETER_RETURN_DEGRADATION, 0.01, 0.0,
                        m.BinRounding.FLOOR)
    with pytest.raises(ValueError, match="unsupported ranking formula"):
        replace(matched, formula_version="research-ranking-v1")
    serialized = matched.to_dict()
    del serialized["formula_version"]
    with pytest.raises(ValueError, match="fields differ"):
        m.ComparisonPolicy.from_dict(serialized)
    with pytest.raises(ValueError, match="adjacent priority"):
        m.ComparisonVariant("bad-swap", matched.bins, 5)
    with pytest.raises(ValueError, match="sensitivity frequency"):
        replace(matched, sensitivities=(m.ComparisonVariant("wrong-frequency", policy().bins),))


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


def test_positive_year_frequency_pools_days_and_counts_actual_exit_year():
    base = annual_evidence()
    got = values(assess_candidates(replace(request(), evidence=(base,))))
    # 2024/2026 positive: five actual sessions, two exits. The cross-year trade exits in 2025.
    metric = got[m.ResearchMetric.BENCHMARK_POSITIVE_YEAR_FREQUENCY]
    assert metric.value == 24.0
    assert metric.evaluation_ids == (base.evaluation_id,)
    assert got[m.ResearchMetric.FULL_SAMPLE_FREQUENCY].value == 30.0


@pytest.mark.parametrize("benchmark,status,reason", [
    ((), m.DiagnosticStatus.INSUFFICIENT_DATA, "MISSING_BENCHMARK"),
    ((1000.0,) * 6, m.DiagnosticStatus.NOT_APPLICABLE, "NO_BENCHMARK_POSITIVE_YEARS"),
    ((999.0, 999.0, 999.0, 998.0, 998.0, 997.0),
     m.DiagnosticStatus.NOT_APPLICABLE, "NO_BENCHMARK_POSITIVE_YEARS"),
])
def test_no_positive_year_evidence_is_not_zero_or_full_sample_fallback(benchmark, status, reason):
    base = replace(annual_evidence(), benchmark_equity=benchmark)
    got = values(assess_candidates(replace(request(), evidence=(base,))))
    metric = got[m.ResearchMetric.BENCHMARK_POSITIVE_YEAR_FREQUENCY]
    assert (metric.value, metric.status, metric.reason) == (None, status, reason)
    assert got[m.ResearchMetric.FULL_SAMPLE_FREQUENCY].value == 30.0


def test_standard_32_point_absolute_quantiles_require_every_prescribed_point():
    design = build(design_request(2, 32)).design
    center = candidate()
    links = tuple(m.PerturbationLink(
        center, m.AssessmentCandidate(f"S900-C{i + 100:04d}", m.digest(i)),
        1.0, "e" * 64, design.bind_point(i)
    ) for i in range(32))
    neighbors = tuple(replace(evidence(x.child, (-float(i), 10.0), parent=center),
                              parameter_point=x.parameter_point) for i, x in enumerate(links))
    req = m.CandidateAssessmentRequest(
        (center,), replace(request().protocol, parameter_protocol=design.protocol),
        links, (evidence(center), *neighbors), parameter_designs=(design,)
    )
    got = values(assess_candidates(req))
    annuals = [((1010.0 - i) / 1000.0) ** 63 - 1 for i in range(32)]
    assert got[m.ResearchMetric.PARAMETER_RETURN_Q10].value == pytest.approx(
        np.quantile(annuals, 0.1, method="linear"))
    assert got[m.ResearchMetric.PARAMETER_RETURN_Q10].value < 0
    assert got[m.ResearchMetric.PARAMETER_DRAWDOWN_Q90].value == pytest.approx(0.0279)
    incomplete = assess_candidates(replace(req, evidence=req.evidence[:-1]))
    assert incomplete.rows[0].parameter_context.valid_points == 31
    for metric in (m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90):
        assert values(incomplete)[metric].value is None
    with pytest.raises(ValueError, match="complete coverage"):
        replace(incomplete.rows[0], diagnostics=assess_candidates(req).rows[0].diagnostics)
