"""Shared research assessment over independently auditable equity event journals."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from strategy_evaluator import research_models as m
from strategy_evaluator import EquityAssessmentFacts
from strategy_evaluator.equity_assessment import canonical_ledger, daily_points
from strategy_evaluator.research_assessment import recompute_historical_assessment


def ledger(days=12):
    """Generate current V4 journals with known 22-cash daily cycle profit."""
    import json
    from dataclasses import asdict
    import pandas as pd
    from dataflows import AssetClass, InstrumentId, MarketId, BarFrequency
    from strategy_runtime import (ResearchExecutionSpec, UsEquitySpec, AccountPolicy,
        CashAvailabilityPolicy, AccountDecision, SellRemainderPolicy)
    from strategy_runtime.account_replay import plan_account_decision
    from strategy_runtime.replay_contracts import ReplayPoint, ExecutionPrecision, ReplayOrder
    from strategy_runtime.contracts import OrderSide, OrderType
    from trading_execution_engine import PortfolioHistoricalExecutor
    spec=ResearchExecutionSpec(UsEquitySpec(),BarFrequency.M30,
        AccountPolicy('USD',CashAvailabilityPolicy.IMMEDIATE_RESEARCH),10,.01,.01,0.)
    instrument=InstrumentId(MarketId.US,AssetClass.STOCK,'TEST')
    events=[]
    for day in range(days):
        at=datetime(2026,10,1,14,tzinfo=timezone.utc)+timedelta(days=day,minutes=30)
        events.extend((dict(Date=at,AvailableDate=at,EventId=f'split-{day}',Kind='SPLIT',Ratio=2.,CashPerShare=0.,PayAt=None),
            dict(Date=at,AvailableDate=at,EventId=f'dividend-{day}',Kind='CASH_DIVIDEND',Ratio=1.,CashPerShare=.1,PayAt=at+timedelta(minutes=90))))
    actions=pd.DataFrame(events)
    executor=PortfolioHistoricalExecutor(specification=spec,initial_cash=10000.,fee_rate=0.,actions=actions,price_basis='RAW')
    bars,rules=[],[]
    for day in range(days):
        base=datetime(2026,10,1,14,tzinfo=timezone.utc)+timedelta(days=day)
        bars.append(dict(Date=base,BarStart=base-timedelta(minutes=30),AvailableDate=base,
            Open=10.,High=10.,Low=10.,Close=10.,Volume=1000.,Amount=10000.))
        for part in range(4):
            start=base+timedelta(minutes=part*30)
            end=start+timedelta(minutes=30)
            price,close=[10.,5.,6.,6.][part],[8.,5.,6.,6.][part]
            row=dict(Date=end,BarStart=start,AvailableDate=end,Open=price,High=max(price,close),Low=min(price,close),Close=close,Volume=1000.,Amount=10000.)
            rule=dict(Date=start,AvailableDate=start,QuantityStep=10,PriceTick=.01,Tradable=True,
                BuySellableAt=start,SettlementAt=end,SellRemainderPolicy='FULL_LIQUIDATION',
                PriceLimitPolicy='EXPLICIT_UNBOUNDED',PriceLimitLower=None,PriceLimitUpper=None)
            point=ReplayPoint(bars[-1]['Date'],start,start,end,start.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
            account=executor.account_snapshot(point,instrument)
            orders=(ReplayOrder(OrderSide.BUY,10,OrderType.LIMIT,10.1),) if part==0 else (ReplayOrder(OrderSide.SELL,20,OrderType.MARKET),) if part==2 else ()
            decision=AccountDecision.from_facts(1. if part<2 else 0.,'explicit synthetic cycle',facts={'part':part},next_watch='next bar',orders=orders,capital_mode='full_available_cash')
            reference=[10.,4.,5.,6.][part]
            proposal=plan_account_decision(decision,point,account,reference,spec,owner='candidate:fixture',
                implementation='1'*64,fee_rate=0.,sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION)
            executor.execute_account_plan(proposal,row,constraint=rule)
            bars.append(row)
            rules.append(rule)
    result=executor.finish()
    def records(frame):
        return json.loads(frame.to_json(orient='records',date_format='iso',date_unit='us'))
    return dict(initial_cash=10000.,fee_rate=0.,account_contract=4,
        specification=json.loads(json.dumps(asdict(spec))),bars=records(pd.DataFrame(bars)),
        constraints=records(pd.DataFrame(rules)),action_facts=records(actions),
        **{name:records(getattr(result,source)) for name,source in (
            ('decisions','decisions'),('orders','orders'),('fills','fills'),('actions','corporate_action_entries'),
            ('account_points','account_points'),('trades','trades'))})


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


def test_equity_shared_assessment_keeps_daily_annualization_and_selects_drawdown():
    daily, intraday = panel(evidence()), panel(evidence("BAR_CLOSE"))
    assert metric(daily, m.ResearchMetric.NET_ANNUAL_RETURN).value == pytest.approx((10264 / 10000) ** (252 / 12) - 1)
    assert metric(intraday, m.ResearchMetric.NET_ANNUAL_RETURN) == metric(daily, m.ResearchMetric.NET_ANNUAL_RETURN)
    assert metric(daily, m.ResearchMetric.DRAWDOWN_MAGNITUDE).value == 0
    assert metric(intraday, m.ResearchMetric.DRAWDOWN_MAGNITUDE).value == pytest.approx(.002)
    assert intraday.rows[0].benchmark.diagnostics[1].value == pytest.approx(.002)
    assert metric(daily, m.ResearchMetric.FREQUENCY_MEDIAN).status is m.DiagnosticStatus.INSUFFICIENT_DATA


def test_equity_concentration_includes_dividend_once_and_explicit_definition():
    assert metric(panel(evidence(concentration="MAX_SINGLE")), m.ResearchMetric.PROFIT_CONCENTRATION).value == pytest.approx(1 / 12)
    assert metric(panel(evidence(concentration="TOP_DECILE")), m.ResearchMetric.PROFIT_CONCENTRATION).value == pytest.approx(2 / 12)
    value = panel(evidence(days=61))
    assert metric(value, m.ResearchMetric.FREQUENCY_MEDIAN).value == 60
    assert metric(value, m.ResearchMetric.FREQUENCY_COVERAGE).value == 1


@pytest.mark.parametrize("mutation", ["cash", "receivable", "cycle", "basis", "daily"])
def test_equity_facts_reject_tampering_and_cannot_use_unverified_sidecars(mutation):
    value = evidence()
    if mutation in {"cash", "receivable", "cycle"}:
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
