"""Independent V4 numerical certification and rejection of coherent-looking corruption."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from execution_channels.instruments import MarketId
from equity_facts_support import manual_ledger, order, bar
from strategy_evaluator.equity import audit_equity_account
from strategy_evaluator.equity_assessment import (
    canonical_ledger,
    read_ledger,
)
from strategy_evaluator.models import ValidationError


def ledger(market=MarketId.US, *, variant="scaling"):
    """Declared outcomes; the independent auditor, not EC, validates them."""
    zone = ZoneInfo("Asia/Shanghai" if market is MarketId.CN else "America/New_York")
    origin = datetime(2026, 10, 8, 9, 30, tzinfo=zone)
    def buy(quantity, **facts):
        return order("BUY", quantity, 10.1, **facts)
    def sell(quantity, **facts):
        return order("SELL", quantity, **facts)
    execution = None
    if variant == "scaling":
        steps = [dict(orders=(buy(100),)), dict(orders=(buy(100), buy(100))),
                 dict(orders=(sell(100),)), dict(orders=(sell(200),), target=0.)]
    elif variant == "fractions":
        # 10000*.25/10 -> 200; 9998*.5/10 -> 400;
        # 9996*.2/10 -> 100 after integer 100-unit rounding.
        steps = [dict(orders=(buy(200),), target=.25, desired=200),
                 dict(orders=(buy(200),), target=.5, desired=400),
                 dict(orders=(sell(300),), target=.2, desired=100),
                 dict(orders=(sell(100),), target=0., desired=0)]
    elif variant == "fullcash":
        steps = [dict(orders=(buy(100), buy(100))),
                 dict(orders=(), target=1., desired=200, mode="full_available_cash"),
                 dict(orders=(sell(200),), target=0., desired=0, mode="full_available_cash")]
    elif variant == "locks":
        steps = [dict(orders=(buy(100),), unlock=origin+timedelta(days=1)),
                 dict(orders=(sell(100, outcome="EXPIRED", reason="INSUFFICIENT_SELLABLE_QUANTITY"),), target=0.),
                 dict(start=origin+timedelta(days=1), orders=(sell(100),), target=0.)]
    elif variant == "volume":
        steps = [dict(orders=(buy(100), buy(100, outcome="EXPIRED", reason="INSUFFICIENT_BAR_VOLUME")), volume=150.),
                 dict(orders=(sell(100),), target=0.)]
    elif variant == "legs":
        steps = [dict(legs=True, orders=(
            order("BUY", 100, checkpoint="OPEN"),
            order("SELL", 100, checkpoint="CLOSE", dependency=0,
                  executed_at=origin+timedelta(minutes=30))))]
    elif variant == "checkpoints":
        closing = origin.replace(hour=15 if market is MarketId.CN else 16, minute=0)
        middle = origin.replace(hour=11, minute=0)
        execution = [bar(origin, volume=150.), bar(middle, price=11.),
                     bar(closing-timedelta(minutes=30), closing, price=12.)]
        steps = [dict(end=closing, close=12., high=12.5, legs=True, orders=(
            order("BUY", 100, checkpoint="OPEN", quote_index=0),
            order("BUY", 100, checkpoint="11:30_CLOSE", quote_index=1, dependency=0,
                  executed_at=middle+timedelta(minutes=30), fill_price=11.),
            order("SELL", 200, checkpoint="CLOSE", quote_index=2, dependency=1,
                  executed_at=closing, fill_price=12.)))]
    elif variant == "budget":
        budget = dict(cycle_id="budget-cycle", target_quantity=300, allocation_fraction=".3",
                      cash_budget="3000", buy_cost_including_fees="0", phase="ACTIVE")
        spent = {**budget, "buy_cost_including_fees": "1001.0"}
        steps = [dict(orders=(order("BUY",100,9., outcome="EXPIRED", reason="LIMIT_NOT_CROSSED"),),
                      mode="signal_cash_fraction", budget_after=budget),
                 dict(orders=(buy(100),), mode="signal_cash_fraction", budget_before=budget, budget_after=budget),
                 dict(orders=(buy(200, outcome="EXPIRED", reason="CYCLE_BUDGET_EXCEEDED"),),
                      mode="signal_cash_fraction", budget_before=spent, budget_after=spent)]
    else:
        raise AssertionError(f"unknown declared fixture {variant}")
    return manual_ledger(steps, market=market, origin=origin, execution_bars=execution,
                         settled=market is MarketId.CN and variant == "scaling")


@pytest.mark.parametrize('market,variant', [
    pytest.param(MarketId.CN, "scaling", id='SE-24-C01'),
    pytest.param(MarketId.US, "scaling", id='SE-24-C02'),
])
@pytest.mark.risk_cases('SE-24-C01', 'SE-24-C02')
def test_independent_v4_audit_certifies_sized_orders_and_explicit_market_rules(market, variant):
    from strategy_evaluator.equity_metrics import summarize_equity_ledger
    source = ledger(market, variant=variant)
    result = audit_equity_account(**source, account_contract=4, decision_contract="FORMAL_V4")
    summarized, audited = asdict(summarize_equity_ledger({**source, "account_contract": 4})), asdict(result)
    # The auditor reconstructs precision before journal JSON rounding; the
    # default summary deliberately uses the recorded fee facts as its answer.
    assert summarized.pop("fees") == pytest.approx(audited.pop("fees"), rel=1e-10, abs=1e-7)
    assert summarized == audited
    assert result.observations == len(source["account_points"])
    assert result.closed_cycles == len(source["trades"])
    if variant == "scaling":
        assert result.fees == pytest.approx(6.0) and result.total_return == pytest.approx(-0.0006)
    elif variant == "events":
        assert result.total_return == pytest.approx(0.0018)


@pytest.fixture(scope="module")
def base_ledger():
    return ledger()


@pytest.mark.parametrize('field', [
    pytest.param("cash", id='SE-24-C03'),
    pytest.param("fee", id='SE-24-C04'),
    pytest.param("quantity", id='SE-24-C05'),
    pytest.param("missing-fill", id='SE-24-C06'),
    pytest.param("missing-decision", id='SE-24-C07'),
])
@pytest.mark.risk_cases('SE-24-C03', 'SE-24-C04', 'SE-24-C05', 'SE-24-C06', 'SE-24-C07')
def test_v4_audit_rejects_corrupted_complete_looking_facts(base_ledger, field):
    source = deepcopy(base_ledger)
    if field == 'cash':
        source['account_points'][0]['cash'] += 1
    elif field == 'fee':
        source['fills'][0]['fees'] += 1
    elif field == 'quantity':
        source['account_points'][0]['quantity'] += 1
    elif field == 'missing-fill':
        source['fills'].pop()
    else:
        source['decisions'].pop()
    with pytest.raises(ValueError):
        audit_equity_account(**source, account_contract=4, decision_contract='FORMAL_V4')


@pytest.mark.parametrize('variant,defect', [
    pytest.param("fractions", "desired", id='SE-26-C01'),
    pytest.param("budget", "budget-reset", id='SE-26-C02'),
    pytest.param("locks", "sellable-time", id='SE-27-C02'),
    pytest.param("checkpoints", "quote-source", id='SE-28-C04'),
    pytest.param("checkpoints", "quote-raw-units", id='SE-28-C05'),
])
@pytest.mark.risk_cases('SE-26-C01', 'SE-26-C02', 'SE-27-C02', 'SE-28-C04', 'SE-28-C05')
def test_v4_audit_rejects_sizing_events_locks_dependencies_and_execution_source_tampering(
    variant, defect
):
    source = ledger(variant=variant)
    # Validate this precise manual journal before its one planned corruption;
    # positive-only variant nodes are no longer repeated in a separate matrix.
    audit_equity_account(**source, account_contract=4, decision_contract='FORMAL_V4')
    if defect == 'desired':
        source['decisions'][0]['plan']['evidence']['desired_quantity'] += 100
    elif defect == 'budget-reset':
        source['decisions'][2]['plan']['cycle_after']['buy_cost_including_fees'] = '0'
    elif defect == 'sellable-time':
        source['constraints'][0]['BuySellableAt'] = source['constraints'][0]['Date']
    elif defect == 'quote-source':
        source['fills'][1]['quote_source'] = 'DECISION_BAR'
    else:
        source['price_basis'] = 'RAW'
    with pytest.raises(ValueError):
        audit_equity_account(**source, account_contract=4, decision_contract='FORMAL_V4')


@pytest.mark.risk_cases('SE-37-C01')
def test_v4_marker_is_a_strict_integer_in_numeric_and_serialized_contracts(base_ledger):
    marker = 4.0
    source = deepcopy(base_ledger)
    with pytest.raises(ValueError):
        audit_equity_account(**source, account_contract=marker, decision_contract="FORMAL_V4")
    source["account_contract"] = marker
    with pytest.raises(ValidationError):
        read_ledger(canonical_ledger(source))


@pytest.mark.risk_cases('SE-37-C02')
def test_current_audit_rejects_retired_or_unlabelled_decision_contract(base_ledger):
    decision_contract = 'FORMAL_V3'
    with pytest.raises(ValueError, match='FORMAL_V4'):
        audit_equity_account(**base_ledger, account_contract=4, decision_contract=decision_contract)


@pytest.mark.risk_cases('SE-27-C01')
def test_SE_27_C01_partial_fill_does_not_satisfy_filled_all_dependency():
    source = ledger(variant="legs")
    source["orders"][0]["status"] = "PARTIAL_FILLED"
    with pytest.raises(ValueError):
        audit_equity_account(**source, account_contract=4, decision_contract="FORMAL_V4")


@pytest.mark.risk_cases('SE-27-C03')
def test_SE_27_C03_trade_settlement_transfers_receivable_without_income():
    source = manual_ledger([dict(orders=(order("BUY", 100, 10.1),)),
                            dict(orders=(order("SELL", 100),), target=0.)], settled=True)
    result = audit_equity_account(**source, account_contract=4, decision_contract="FORMAL_V4")
    assert source["account_entries"][0]["cash_delta"] == 999.
    assert source["account_entries"][0]["receivable_delta"] == -999.
    assert source["account_points"][-1]["equity"] == 9998.
    assert result.total_return == pytest.approx(-.0002)


@pytest.mark.risk_cases('SE-27-C04')
def test_SE_27_C04_hfq_contract_rejects_action_journal():
    with pytest.raises(TypeError, match="actions"):
        audit_equity_account(**ledger(), account_contract=4, decision_contract="FORMAL_V4", actions=[])


@pytest.mark.risk_cases('SE-27-C05')
def test_SE_27_C05_hfq_entries_cannot_include_nontrading_income():
    source = ledger()
    source["account_entries"] = [{"kind": "DIVIDEND_PAYMENT"}]
    with pytest.raises(ValueError, match="only permits trade settlement"):
        audit_equity_account(**source, account_contract=4, decision_contract="FORMAL_V4")
