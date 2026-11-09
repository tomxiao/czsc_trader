"""Shared research assessment over independently auditable equity event journals."""
from dataclasses import replace

import pytest

from strategy_evaluator import research_models as m
from strategy_evaluator import EquityAssessmentFacts
from strategy_evaluator.equity_assessment import canonical_ledger, daily_points
from strategy_evaluator.research_assessment import recompute_historical_assessment


from equity_facts_support import daily_profit_ledger as ledger


def evidence(drawdown="SESSION_CLOSE", concentration="MAX_SINGLE", days=12):
    raw = ledger(days)
    encoded = canonical_ledger(raw)
    facts = EquityAssessmentFacts("US", "America/New_York", "USD", drawdown, concentration, encoded, encoded)
    account = tuple(m.AccountPoint(r["session"], r["cash"], r["quantity"], r["close"], r["equity"])
                    for r in daily_points(raw))
    return m.AssessmentEvidence(m.AssessmentCandidate("S999-C0001", "a" * 64), "EX001_20261028", "b" * 32,
        "c" * 64, "d" * 64, "e" * 64, m.digest((drawdown, concentration)), "full", "standard",
        f"equity-assessment-v4:{drawdown}:{concentration}",
        m.EvaluationScenarioContext(0., "FORMAL", "BuyHold", "BUYHOLD", "f" * 64),
        10000., 10000., 0, 60, account,
        tuple(m.AssessmentFill(r["cycle_id"], r["interval_end"][:10], m.FillSide(r["side"]), r["quantity"], r["price"], 0.)
              for r in raw["fills"]),
        tuple(m.ClosedCycle(r["cycle_id"], r["exit_at"][:10]) for r in raw["trades"]),
        tuple(r.equity for r in account), equity=facts)


def panel(value):
    protocol = m.SelfCheckProtocol("test", "full", "standard", "pressure", 2, 1,
        m.QuantileMethod.LINEAR, 1, 1, 20, 2, 3, 1e-8, pbo_blocks=2, frequency_min_closed_cycles=3)
    return recompute_historical_assessment(m.CandidateAssessmentRequest((value.candidate,), protocol, (), (value,)))


def metric(result, key):
    return next(row for row in result.rows[0].diagnostics if row.metric is key)


@pytest.mark.parametrize('basis,expected_dd', [
    pytest.param('BAR_CLOSE', .002, id='SE-01-C02'),
    pytest.param('SESSION_CLOSE', 0., id='SE-01-C03'),
])
@pytest.mark.risk_cases('SE-01-C02', 'SE-01-C03')
def test_daily_annualization_and_declared_drawdown_sampling(basis, expected_dd):
    got = panel(evidence(basis))
    assert metric(got, m.ResearchMetric.NET_ANNUAL_RETURN).value == pytest.approx((10264/10000)**(252/12)-1)
    assert metric(got, m.ResearchMetric.DRAWDOWN_MAGNITUDE).value == pytest.approx(expected_dd)


@pytest.mark.risk_cases('SE-07-C04')
def test_equity_concentration_includes_dividend_once_and_explicit_definition():
    assert metric(panel(evidence(concentration="MAX_SINGLE")), m.ResearchMetric.PROFIT_CONCENTRATION).value == pytest.approx(1 / 12)
    assert metric(panel(evidence(concentration="TOP_DECILE")), m.ResearchMetric.PROFIT_CONCENTRATION).value == pytest.approx(2 / 12)
    value = panel(evidence(days=61))
    assert metric(value, m.ResearchMetric.FREQUENCY_MEDIAN).value == 60
    assert metric(value, m.ResearchMetric.FREQUENCY_COVERAGE).value == 1


@pytest.mark.risk_cases('SE-38-C03')
def test_compact_observations_preserve_metrics_and_immutable_parsed_values():
    drawdown = "BAR_CLOSE"
    concentration = "MAX_SINGLE"
    from strategy_evaluator.equity_assessment import canonical_observations, read_ledger
    original = evidence(drawdown, concentration)
    compact = canonical_observations(ledger())
    projected = replace(original, equity=replace(original.equity,
        candidate_ledger=compact, benchmark_ledger=compact))
    assert len(compact) < len(original.equity.candidate_ledger) / 4
    assert panel(projected).rows == panel(original).rows
    parsed = read_ledger(compact)
    with pytest.raises(TypeError):
        parsed["account_points"][0]["equity"] = 0.


@pytest.mark.risk_cases('SE-31-C07')
def test_observation_metrics_match_reference_without_auditing_constructors(monkeypatch):
    days = 12
    from dataclasses import asdict
    from strategy_evaluator.equity import audit_equity_account
    from strategy_evaluator import equity_assessment
    from strategy_evaluator.equity_metrics import summarize_equity_ledger
    raw = ledger(days)
    reference = audit_equity_account(**raw)
    def forbidden(*args, **kwargs):
        raise AssertionError("constructing facts must not perform independent accounting")
    monkeypatch.setattr(equity_assessment, "audit_equity_account", forbidden)
    facts = EquityAssessmentFacts("US", "America/New_York", "USD", "BAR_CLOSE", "MAX_SINGLE",
        canonical_ledger(raw), canonical_ledger(raw))
    assert facts.market == "US"
    assert asdict(summarize_equity_ledger(raw)) == asdict(reference)
