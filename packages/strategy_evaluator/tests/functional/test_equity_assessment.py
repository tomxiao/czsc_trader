"""Shared research assessment over independently auditable equity event journals."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from strategy_evaluator import research_models as m
from strategy_evaluator import EquityAssessmentFacts
from strategy_evaluator.equity_assessment import canonical_ledger, daily_points
from strategy_evaluator.research_assessment import recompute_historical_assessment


def ledger(days=12):
    initial, cash = 10000.0, 10000.0
    result = {key: [] for key in ("bars", "decisions", "orders", "fills", "actions", "account_points", "trades", "action_facts", "constraints")}
    result.update(initial_cash=initial, fee_rate=0.0, specification={
        "market": {"rule_version": "US_EQUITY_V1"}, "slippage_bp": 0,
        "inclusive_touch": False, "data_latency_seconds": 0, "price_tick": .01,
        "quantity_step": 10, "buy_premium": 99.,
        "account": {"currency": "USD", "cash_availability": "IMMEDIATE_RESEARCH"}})
    for day in range(days):
        base = datetime(2026, 10, 1, 14, tzinfo=timezone.utc) + timedelta(days=day)
        session = base.date().isoformat()
        cycle = f"cycle-{day}"
        opening = cash
        # A conservative limit consumes the declared full budget in ten-share
        # steps; actual opening fills still improve to the observed price.
        result["bars"].append(dict(Date=base.isoformat(), BarStart=(base - timedelta(minutes=30)).isoformat(),
            AvailableDate=base.isoformat(), Open=10., High=10., Low=10., Close=10., Volume=1000.))
        for part in range(4):
            revision = day * 4 + part
            start, end = base + timedelta(minutes=part * 30), base + timedelta(minutes=(part + 1) * 30)
            start, end = start.isoformat(), end.isoformat()
            identity = f"decision-{revision}"
            price = [10., 5., 6., 6.][part]
            close = [8., 5., 6., 6.][part]
            side = ["BUY", "HOLD", "SELL", "HOLD"][part]
            qty = [10, 0, 20, 0][part]
            result["bars"].append(dict(Date=end, BarStart=start, AvailableDate=end,
                Open=price, High=max(price, close), Low=min(price, close), Close=close, Volume=1000.))
            result["constraints"].append(dict(Date=start, AvailableDate=start, Tradable=True, QuantityStep=10, PriceTick=.01))
            result["decisions"].append(dict(decision_id=identity, observed_through=start,
                decision_at=start, execution_start=start, execution_end=end, portfolio_revision=revision, side=side,
                target=[1., 1., 0., 0.][part], reference_price=[10., 4., 5., 6.][part], quantity=qty,
                limit_price=1000. if side == "BUY" else None))
            if qty:
                result["orders"].append(dict(order_id=identity, decision_id=identity, side=side,
                    quantity=qty, status="FILLED", reason="FILLED", valid_start=start, valid_end=end,
                    limit_price=1000. if side == "BUY" else None))
                result["fills"].append(dict(fill_id=identity, order_id=identity, cycle_id=cycle,
                    account_revision=revision, side=side, quantity=qty, price=price, fees=0.,
                    interval_start=start, interval_end=end, time_precision="MODEL_BAR_OPEN"))
            if part == 1:
                for kind, name, ratio, dividend in (("SPLIT", "split", 2., 0.), ("CASH_DIVIDEND", "dividend", 1., .1)):
                    event = f"{name}-{day}"
                    result["action_facts"].append(dict(EventId=event, Kind=kind, Date=start, AvailableDate=start,
                        Ratio=ratio, CashPerShare=dividend, PayAt=(base + timedelta(hours=2)).isoformat() if dividend else None))
                    result["actions"].append(dict(event_id=event, kind=kind, account_revision=revision, time=start,
                        quantity_before=10 if kind == "SPLIT" else 20, quantity_after=20, amount=2. if dividend else 0.,
                        cash_delta=0., receivable_delta=2. if dividend else 0.))
            if part == 3:
                result["actions"].append(dict(event_id=f"dividend-{day}", kind="DIVIDEND_PAYMENT",
                    account_revision=revision, time=end, quantity_before=0, quantity_after=0,
                    amount=2., cash_delta=2., receivable_delta=-2.))
            balances = [(opening - 100, 10, 0.), (opening - 100, 20, 2.),
                        (opening + 20, 0, 2.), (opening + 22, 0, 0.)]
            cash, held, receivable = balances[part]
            result["account_points"].append(dict(time=end, session=session, account_revision=revision,
                decision_id=identity, cash=cash, quantity=held, receivable=receivable, close=close,
                equity=cash + receivable + held * close))
            if part == 2:
                result["trades"].append(dict(cycle_id=cycle, entry_at=base.isoformat(), exit_at=end,
                    cost=100., income=122., net_pnl=22., net_return=.22, status="CLOSED"))
    return result


def evidence(drawdown="SESSION_CLOSE", concentration="MAX_SINGLE", days=12):
    raw = ledger(days)
    encoded = canonical_ledger(raw)
    facts = EquityAssessmentFacts("US", "America/New_York", "USD", drawdown, concentration, encoded, encoded)
    account = tuple(m.AccountPoint(r["session"], r["cash"], r["quantity"], r["close"], r["equity"])
                    for r in daily_points(raw))
    return m.AssessmentEvidence(m.AssessmentCandidate("S999-C0001", "a" * 64), "EX001_20261028", "b" * 32,
        "c" * 64, "d" * 64, "e" * 64, m.digest((drawdown, concentration)), "full", "standard",
        f"equity-assessment-v2:{drawdown}:{concentration}",
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


def metric(value, key):
    return next(row for row in panel(value).rows[0].diagnostics if row.metric is key)


def test_equity_shared_assessment_keeps_daily_annualization_and_selects_drawdown():
    daily, intraday = evidence(), evidence("BAR_CLOSE")
    assert metric(daily, m.ResearchMetric.NET_ANNUAL_RETURN).value == pytest.approx((10264 / 10000) ** (252 / 12) - 1)
    assert metric(intraday, m.ResearchMetric.NET_ANNUAL_RETURN) == metric(daily, m.ResearchMetric.NET_ANNUAL_RETURN)
    assert metric(daily, m.ResearchMetric.DRAWDOWN_MAGNITUDE).value == 0
    assert metric(intraday, m.ResearchMetric.DRAWDOWN_MAGNITUDE).value == pytest.approx(.002)
    assert panel(intraday).rows[0].benchmark.diagnostics[1].value == pytest.approx(.002)
    assert metric(daily, m.ResearchMetric.FREQUENCY_MEDIAN).status is m.DiagnosticStatus.INSUFFICIENT_DATA


def test_equity_concentration_includes_dividend_once_and_explicit_definition():
    assert metric(evidence(concentration="MAX_SINGLE"), m.ResearchMetric.PROFIT_CONCENTRATION).value == pytest.approx(1 / 12)
    assert metric(evidence(concentration="TOP_DECILE"), m.ResearchMetric.PROFIT_CONCENTRATION).value == pytest.approx(2 / 12)
    value = evidence(days=61)
    assert metric(value, m.ResearchMetric.FREQUENCY_MEDIAN).value == 60
    assert metric(value, m.ResearchMetric.FREQUENCY_COVERAGE).value == 1


@pytest.mark.parametrize("mutation", ["cash", "receivable", "cycle", "basis", "daily"])
def test_equity_facts_reject_tampering_and_cannot_use_unverified_sidecars(mutation):
    value = evidence()
    raw = ledger()
    if mutation in {"cash", "receivable"}:
        raw["account_points"][1][mutation] += 1
    elif mutation == "cycle":
        raw["trades"][0]["net_pnl"] += 1
    elif mutation == "basis":
        with pytest.raises(ValueError, match="drawdown basis"):
            replace(value.equity, drawdown_basis="TICK")
        return
    elif mutation == "daily":
        with pytest.raises(ValueError, match="daily account differs"):
            replace(value, account=(replace(value.account[0], cash=value.account[0].cash + 1), *value.account[1:]))
        return
    with pytest.raises(ValueError, match="audit mismatch"):
        replace(value.equity, candidate_ledger=canonical_ledger(raw))


def test_equity_facts_roundtrip_and_legacy_serialization_has_no_new_fields():
    value = evidence()
    assert m.AssessmentEvidence.from_dict(value.to_dict()) == value
    legacy = replace(value, equity=None, metric_version="legacy")
    assert "equity" not in legacy.to_dict()
    assert m.AssessmentEvidence.from_dict(legacy.to_dict()) == legacy
