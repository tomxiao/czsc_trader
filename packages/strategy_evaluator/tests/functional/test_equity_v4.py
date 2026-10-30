"""Independent V4 numerical certification and rejection of coherent-looking corruption."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
import json
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import pandas as pd
import pytest

from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId
from strategy_runtime import (
    AccountPolicy,
    CashAvailabilityPolicy,
    ResearchExecutionSpec,
    CnEquitySpec,
    UsEquitySpec,
)
from strategy_runtime.account_strategy import AccountDecision, SellRemainderPolicy
from strategy_runtime.account_replay import plan_account_decision
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.entry_cycle import EntryCyclePhase
from strategy_runtime.replay_contracts import (
    ReplayOrder,
    ReplayLeg,
    ReplayPoint,
    ExecutionPrecision,
    CycleBudget,
)
from trading_execution_engine import PortfolioHistoricalExecutor
from strategy_evaluator.equity import audit_equity_account
from strategy_evaluator.equity_assessment import (
    canonical_ledger,
    read_ledger,
    validate_equity_facts,
)
from strategy_evaluator.models import ValidationError


def ledger(market=MarketId.US, *, variant="scaling"):
    zone = ZoneInfo("Asia/Shanghai" if market is MarketId.CN else "America/New_York")
    origin = datetime(2026, 10, 8, 9, 30, tzinfo=zone)
    spec = ResearchExecutionSpec(
        CnEquitySpec() if market is MarketId.CN else UsEquitySpec(),
        BarFrequency.DAILY if variant in {"checkpoints", "midpayment"} else BarFrequency.M30,
        AccountPolicy(
            "CNY" if market is MarketId.CN else "USD",
            CashAvailabilityPolicy.SETTLED_ONLY
            if variant == "events"
            else CashAvailabilityPolicy.IMMEDIATE_RESEARCH,
        ),
        100,
        0.01,
        0.01,
        0.0,
    )
    instrument = InstrumentId(
        market, AssetClass.STOCK, "600000.SH" if market is MarketId.CN else "LITE"
    )
    event_at = origin + timedelta(days=1)
    if variant in {"events", "odd"}:
        actions = pd.DataFrame(
            [
                dict(
                    Date=event_at,
                    AvailableDate=event_at,
                    EventId="split",
                    Kind="SPLIT",
                    Ratio=1.5 if variant == "odd" else 2.0,
                    CashPerShare=0.0,
                    PayAt=None,
                ),
                dict(
                    Date=event_at,
                    AvailableDate=event_at,
                    EventId="cash",
                    Kind="CASH_DIVIDEND",
                    Ratio=1.0,
                    CashPerShare=0.1,
                    PayAt=event_at + timedelta(minutes=30),
                ),
            ]
        )
    elif variant == "midpayment":
        actions = pd.DataFrame(
            [
                dict(
                    Date=event_at,
                    AvailableDate=event_at,
                    EventId="cash",
                    Kind="CASH_DIVIDEND",
                    Ratio=1.0,
                    CashPerShare=2.0,
                    PayAt=event_at.replace(hour=11, minute=0),
                )
            ]
        )
    else:
        actions = pd.DataFrame(
            [
                dict(
                    Date=origin,
                    AvailableDate=origin,
                    EventId="none",
                    Kind="NONE",
                    Ratio=1.0,
                    CashPerShare=0.0,
                    PayAt=None,
                )
            ]
        )
    bars, rules = [], []

    def quote(stamp, price=10.0, volume=10000.0):
        end = stamp + timedelta(minutes=30)
        return dict(
            BarStart=stamp,
            Date=end,
            AvailableDate=end,
            Open=price,
            High=price * 1.02,
            Low=price * 0.98,
            Close=price,
            Volume=volume,
            Amount=price * volume,
        )

    execution = None
    if variant in {"checkpoints", "midpayment"}:
        quoted_day = event_at if variant == "midpayment" else origin
        closing = quoted_day.replace(hour=15 if market is MarketId.CN else 16, minute=0)
        execution = [
            quote(quoted_day, volume=150.0),
            quote(quoted_day.replace(hour=11, minute=0), price=11.0),
            quote(closing - timedelta(minutes=30), price=12.0),
        ]
        if variant == "midpayment":
            execution = [
                quote(origin),
                quote(origin.replace(hour=11, minute=0), price=11.0),
                quote(
                    origin.replace(hour=closing.hour, minute=0) - timedelta(minutes=30), price=12.0
                ),
            ] + execution
    executor = PortfolioHistoricalExecutor(
        specification=spec,
        initial_cash=10000.0,
        fee_rate=0.001,
        actions=actions,
        price_basis="RAW",
        execution_bars=None if execution is None else pd.DataFrame(execution),
    )
    bars.append(
        quote(
            origin - timedelta(days=1)
            if variant in {"checkpoints", "midpayment"}
            else origin - timedelta(minutes=30)
        )
    )

    def run(
        stamp,
        *,
        orders=(),
        target=1.0,
        legs=(),
        mode="target_equity_fraction",
        budget=None,
        price=10.0,
        volume=10000.0,
        unlock=None,
    ):
        row = quote(stamp, price, volume)
        if variant in {"checkpoints", "midpayment"}:
            end = stamp.replace(hour=closing.hour, minute=0)
            row.update(Date=end, AvailableDate=end, Close=12.0, High=12.5)
        rule = dict(
            Date=stamp,
            AvailableDate=stamp,
            QuantityStep=100,
            PriceTick=0.01,
            Tradable=True,
            BuySellableAt=stamp if unlock is None else unlock,
            SettlementAt=stamp + timedelta(days=1),
            SellRemainderPolicy="FULL_LIQUIDATION",
            PriceLimitPolicy="EXPLICIT_UNBOUNDED",
            PriceLimitLower=None,
            PriceLimitUpper=None,
        )
        observed = bars[-1]["Date"]
        point = ReplayPoint(
            observed,
            stamp,
            stamp,
            row["Date"],
            stamp.date().isoformat(),
            ExecutionPrecision.BAR_INTERVAL,
        )
        account = executor.account_snapshot(point, instrument)
        decision = AccountDecision.from_facts(
            target,
            "synthetic independent audit fixture",
            facts={"target": target},
            next_watch="next causal observation",
            orders=orders,
            legs=legs,
            capital_mode=mode,
            cycle_before=executor.cycle_budget if mode == "signal_cash_fraction" else None,
            cycle_after=budget,
        )
        reference = bars[-1]["Close"]
        if variant in {"events", "odd"} and observed <= event_at <= stamp:
            reference /= 1.5 if variant == "odd" else 2
        proposal = plan_account_decision(
            decision,
            point,
            account,
            reference,
            spec,
            owner="candidate:fixture",
            implementation="1" * 64,
            fee_rate=0.001,
            sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION,
        )
        executor.execute_account_plan(proposal, row, constraint=rule)
        bars.append(row)
        rules.append(rule)

    def order(side, quantity, price=None):
        return ReplayOrder(
            side, quantity, OrderType.MARKET if price is None else OrderType.LIMIT, price
        )

    if variant == "scaling":
        run(origin, orders=(order(OrderSide.BUY, 100, 10.1),))
        run(
            origin + timedelta(minutes=30),
            orders=(order(OrderSide.BUY, 100, 10.1), order(OrderSide.BUY, 100, 10.1)),
        )
        run(origin + timedelta(minutes=60), orders=(order(OrderSide.SELL, 100),))
        run(origin + timedelta(minutes=90), orders=(order(OrderSide.SELL, 200),), target=0.0)
    elif variant == "fractions":
        for index, target in enumerate((0.25, 0.5, 0.2, 0.0)):
            run(origin + timedelta(minutes=index * 30), target=target)
    elif variant == "fullcash":
        run(origin, orders=(order(OrderSide.BUY, 100, 10.1), order(OrderSide.BUY, 100, 10.1)))
        run(origin + timedelta(minutes=30), target=1.0, mode="full_available_cash")
        run(origin + timedelta(minutes=60), target=0.0, mode="full_available_cash")
    elif variant == "checkpoints":
        legs = (
            ReplayLeg(0, order(OrderSide.BUY, 100), "OPEN", origin, closing),
            ReplayLeg(1, order(OrderSide.BUY, 100), "11:30_CLOSE", origin, closing, 0, "FILLED"),
            ReplayLeg(2, order(OrderSide.SELL, 200), "CLOSE", origin, closing, 1, "FILLED"),
        )
        run(origin, legs=legs)
    elif variant == "midpayment":
        run(origin, orders=(order(OrderSide.BUY, 900, 10.1),))
        run(
            event_at,
            legs=(ReplayLeg(0, order(OrderSide.BUY, 100), "11:30_CLOSE", event_at, closing),),
        )
    elif variant == "events":
        run(origin, orders=(order(OrderSide.BUY, 100, 10.1),))
        run(event_at, orders=(order(OrderSide.SELL, 200),), target=0.0, price=5.0)
        run(event_at + timedelta(days=1), target=0.0, price=5.0)
    elif variant == "odd":
        run(origin, orders=(order(OrderSide.BUY, 100, 10.1),))
        run(event_at, orders=(order(OrderSide.SELL, 150),), target=0.0, price=10.0 / 1.5)
    elif variant == "locks":
        run(origin, orders=(order(OrderSide.BUY, 100, 10.1),), unlock=origin + timedelta(days=1))
        run(origin + timedelta(minutes=30), orders=(order(OrderSide.SELL, 100),), target=0.0)
        run(origin + timedelta(days=1), orders=(order(OrderSide.SELL, 100),), target=0.0)
    elif variant == "legs":
        end = origin + timedelta(minutes=30)
        legs = (
            ReplayLeg(0, order(OrderSide.BUY, 100), "OPEN", origin, end),
            ReplayLeg(1, order(OrderSide.SELL, 100), "CLOSE", origin, end, 0, "FILLED"),
        )
        run(origin, legs=legs)
    elif variant == "volume":
        run(
            origin,
            orders=(order(OrderSide.BUY, 100, 10.1), order(OrderSide.BUY, 100, 10.1)),
            volume=150.0,
        )
        run(origin + timedelta(minutes=30), orders=(order(OrderSide.SELL, 100),), target=0.0)
    elif variant == "budget":
        budget = CycleBudget(
            "budget-cycle",
            300,
            Decimal(".3"),
            Decimal("3000"),
            Decimal("0"),
            EntryCyclePhase.ACTIVE,
        )
        run(
            origin,
            orders=(order(OrderSide.BUY, 100, 9.0),),
            mode="signal_cash_fraction",
            budget=budget,
        )
        run(
            origin + timedelta(minutes=30),
            orders=(order(OrderSide.BUY, 100, 10.1),),
            mode="signal_cash_fraction",
            budget=budget,
        )
        active = executor.cycle_budget
        run(
            origin + timedelta(minutes=60),
            orders=(order(OrderSide.BUY, 200, 10.1),),
            mode="signal_cash_fraction",
            budget=active,
        )
    result = executor.finish()

    def records(frame):
        return json.loads(frame.to_json(orient="records", date_format="iso", date_unit="us"))

    result = dict(
        initial_cash=10000.0,
        specification=json.loads(json.dumps(asdict(spec))),
        bars=records(pd.DataFrame(bars)),
        constraints=records(pd.DataFrame(rules)),
        decisions=records(result.decisions),
        orders=records(result.orders),
        fills=records(result.fills),
        actions=records(result.corporate_action_entries),
        account_points=records(result.account_points),
        trades=records(result.trades),
        action_facts=records(actions),
        fee_rate=0.001,
    )
    if execution is not None:
        result["execution_bars"] = records(pd.DataFrame(execution))
    return result


@pytest.mark.parametrize("market", [MarketId.CN, MarketId.US])
@pytest.mark.parametrize(
    "variant",
    [
        "scaling",
        "fractions",
        "events",
        "odd",
        "locks",
        "legs",
        "volume",
        "budget",
        "fullcash",
        "checkpoints",
    ],
)
def test_independent_v4_audit_certifies_sized_orders_and_explicit_market_rules(market, variant):
    source = ledger(market, variant=variant)
    result = audit_equity_account(**source, account_contract=4, decision_contract="FORMAL_V4")
    assert result.observations == len(source["account_points"])
    assert result.closed_cycles == len(source["trades"])
    if variant == "scaling":
        assert result.fees == pytest.approx(6.0) and result.total_return == pytest.approx(-0.0006)
    elif variant == "events":
        assert result.total_return == pytest.approx(0.0018)


@pytest.fixture(scope="module")
def base_ledger():
    return ledger()


@pytest.mark.parametrize(
    "field",
    [
        "cash",
        "quantity",
        "fee",
        "price",
        "target",
        "observed",
        "available",
        "order-status",
        "expired",
        "limit",
        "volume",
        "identity",
        "revision",
        "cycle-cost",
        "cycle-income",
        "missing-fill",
        "missing-decision",
        "sizing",
    ],
)
def test_v4_audit_rejects_corrupted_complete_looking_facts(base_ledger, field):
    source = deepcopy(base_ledger)
    if field == "cash":
        source["account_points"][0]["cash"] += 1
    elif field == "quantity":
        source["account_points"][0]["quantity"] += 1
    elif field == "fee":
        source["fills"][0]["fees"] += 1
    elif field == "price":
        source["fills"][0]["price"] += 0.01
    elif field == "target":
        source["decisions"][0]["target_quantity"] += 100
    elif field == "observed":
        source["decisions"][0]["observed_through"] = source["decisions"][0]["execution_end"]
    elif field == "available":
        source["bars"][0]["AvailableDate"] = source["account_points"][-1]["time"]
    elif field == "order-status":
        source["orders"][0]["reason"] = "NOT_TRADABLE"
    elif field == "expired":
        source["orders"][0]["status"] = "EXPIRED"
    elif field == "limit":
        source["orders"][0]["limit_price"] = 9.0
    elif field == "volume":
        source["bars"][1]["Volume"] = 1.0
    elif field == "identity":
        source["fills"][0]["cycle_id"] = "forged"
    elif field == "revision":
        source["account_points"][0]["account_revision"] = 2
    elif field == "cycle-cost":
        source["trades"][0]["cost"] += 1
    elif field == "cycle-income":
        source["trades"][0]["income"] += 1
    elif field == "missing-fill":
        source["fills"].pop()
    elif field == "missing-decision":
        source["decisions"].pop()
    else:
        source["decisions"][0]["plan"]["evidence"].pop("sizing")
    with pytest.raises(ValueError):
        audit_equity_account(**source, account_contract=4, decision_contract="FORMAL_V4")


@pytest.mark.parametrize(
    "variant,defect",
    [
        ("fractions", "desired"),
        ("fractions", "reference"),
        ("fractions", "fraction"),
        ("fullcash", "residual-target"),
        ("events", "entitlement"),
        ("events", "payment"),
        ("events", "missing-event"),
        ("events", "pay-time"),
        ("locks", "sellable-time"),
        ("checkpoints", "quote-source"),
        ("checkpoints", "quote-volume"),
        ("checkpoints", "missing-quote"),
        ("checkpoints", "quote-range"),
        ("checkpoints", "quote-raw-units"),
        ("checkpoints", "reversed-checkpoint"),
        ("legs", "dependency-status"),
        ("budget", "budget-reset"),
    ],
)
def test_v4_audit_rejects_sizing_events_locks_dependencies_and_execution_source_tampering(
    variant, defect
):
    source = ledger(variant=variant)
    if defect in {"desired", "residual-target"}:
        index = 1 if defect == "residual-target" else 0
        source["decisions"][index]["plan"]["evidence"]["desired_quantity"] += 100
    elif defect == "reference":
        source["decisions"][0]["plan"]["evidence"]["reference_price"] += 1
    elif defect == "fraction":
        source["decisions"][0]["plan"]["evidence"]["target"] = 0.99
        source["decisions"][0]["target"] = 0.99
    elif defect == "entitlement":
        source["action_facts"][1]["CashPerShare"] += 0.1
    elif defect == "payment":
        source["actions"][-1]["cash_delta"] += 1
    elif defect == "missing-event":
        source["action_facts"].pop()
    elif defect == "pay-time":
        source["action_facts"][1]["PayAt"] = source["account_points"][-1]["time"]
    elif defect == "sellable-time":
        source["constraints"][0]["BuySellableAt"] = source["constraints"][0]["Date"]
    elif defect == "quote-source":
        source["fills"][1]["quote_source"] = "DECISION_BAR"
    elif defect == "quote-volume":
        source["execution_bars"][0]["Volume"] = 50
    elif defect == "missing-quote":
        source["execution_bars"].pop(1)
    elif defect == "quote-range":
        source["execution_bars"][1]["High"] = 20.0
    elif defect == "quote-raw-units":
        source["execution_bars"][0]["Open"] += 0.01
    elif defect == "reversed-checkpoint":
        source["decisions"][0]["plan"]["legs"][0]["checkpoint"] = "CLOSE"
        source["orders"][0]["checkpoint"] = "CLOSE"
    elif defect == "dependency-status":
        source["decisions"][0]["plan"]["legs"][1]["dependency_required_status"] = "EXPIRED"
        source["orders"][1]["dependency_required_status"] = "EXPIRED"
    elif defect == "budget-reset":
        source["decisions"][2]["plan"]["cycle_after"]["buy_cost_including_fees"] = "0"
    with pytest.raises(ValueError):
        audit_equity_account(**source, account_contract=4, decision_contract="FORMAL_V4")


@pytest.mark.parametrize("market", [MarketId.CN, MarketId.US])
def test_checkpoint_can_spend_only_dividend_cash_paid_before_its_exact_quote(market):
    source = ledger(market, variant="midpayment")
    assert len(source["fills"]) == 2
    assert source["fills"][-1]["price"] == 11.0
    assert source["account_points"][0]["cash"] < 1101
    result = audit_equity_account(**source, account_contract=4, decision_contract="FORMAL_V4")
    assert result.total_return == pytest.approx(0.36899)
    for defect in ("early-journal", "late-source", "duplicate-payment", "missing-payment"):
        damaged = deepcopy(source)
        if defect == "early-journal":
            damaged["actions"][-1]["time"] = damaged["constraints"][-1]["Date"]
        elif defect == "late-source":
            damaged["action_facts"][0]["PayAt"] = damaged["account_points"][-1]["time"]
        elif defect == "duplicate-payment":
            damaged["actions"].append(dict(damaged["actions"][-1]))
        else:
            damaged["actions"].pop()
        with pytest.raises(ValueError):
            audit_equity_account(**damaged, account_contract=4, decision_contract="FORMAL_V4")


@pytest.mark.parametrize("marker", [4.0, True, False, "4", None])
def test_v4_marker_is_a_strict_integer_in_numeric_and_serialized_contracts(base_ledger, marker):
    source = deepcopy(base_ledger)
    with pytest.raises(ValueError):
        audit_equity_account(**source, account_contract=marker, decision_contract="FORMAL_V4")
    source["account_contract"] = marker
    with pytest.raises(ValidationError):
        read_ledger(canonical_ledger(source))


@pytest.mark.parametrize(
    "market,contracts",
    [
        ("CN", (None, None)),
        ("CN", (4, None)),
        ("CN", (None, 4)),
        ("US", (4, None)),
        ("US", (None, 4)),
    ],
)
def test_assessment_rejects_legacy_cn_or_mismatched_candidate_benchmark_contracts(
    base_ledger, market, contracts
):
    candidate, benchmark = deepcopy(base_ledger), deepcopy(base_ledger)
    for rows, contract in zip((candidate, benchmark), contracts):
        if contract is not None:
            rows["account_contract"] = contract
    facts = SimpleNamespace(
        market=market,
        timezone="Asia/Shanghai" if market == "CN" else "America/New_York",
        currency="CNY" if market == "CN" else "USD",
        drawdown_basis="BAR_CLOSE",
        concentration_basis="MAX_SINGLE",
        candidate_ledger=canonical_ledger(candidate),
        benchmark_ledger=canonical_ledger(benchmark),
    )
    with pytest.raises(ValidationError, match="contracts"):
        validate_equity_facts(facts)
