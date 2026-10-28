"""Public US equity path, identity isolation and independent account evidence."""
from dataclasses import asdict, replace
from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import (AssetClass, BarFrequency, EquityProduct, InstrumentId, MarketId,
                       ProviderBinding, ProviderConfig, ProviderKey, SourceRef, TimeInterval, TradingSession)
from dataflows.equity_data import equity_metadata
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, EquityCandidate, ResearchExecutionSpec,
                              UsEquitySpec, equity_implementation_hash)
from strategy_evaluator.equity import audit_equity_account
from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.research_governance_service import (
    create_research_batch, create_research_context, create_experiment, ResearchBatchRequest, ExperimentRequest)
from czsc_trader.application.backtest_service import run_backtest
from czsc_trader.application.evidence_service import publish_evidence
from czsc_trader.research_tools import EquityEvaluationRequest, EquitySources, EvaluationEvidenceWrite


def alternate(history, portfolio):
    return 1 if portfolio.quantity == 0 else 0


def hold(history, portfolio):
    return 1


def setup_equity(tmp_path, decide=alternate, *, cash_policy=CashAvailabilityPolicy.IMMEDIATE_RESEARCH):
    repository = RepositoryContext(tmp_path, tmp_path / "research", tmp_path / "research/registrations", tmp_path / "strategies")
    batch = create_research_batch(repository, ResearchBatchRequest("S999", "Equity fixture", "US:LITE",
                                  {"goal": "fixture"}), actor="DEV", reason="isolated contract test")
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30, AccountPolicy("USD", cash_policy),
                                 1, .01, .01, 0.)
    instrument, source = InstrumentId(MarketId.US, AssetClass.STOCK, "LITE"), SourceRef("fixture", "v1")
    zone = ZoneInfo(instrument.timezone)
    sessions = tuple(TradingSession(date(2026, 10, day), str(zone), (TimeInterval(
        datetime(2026, 10, day, 9, 30, tzinfo=zone), datetime(2026, 10, day, 16, tzinfo=zone)),)) for day in (1, 2))
    grid = [bar for session in sessions for bar in session.bars(BarFrequency.M30)]
    bars = pd.DataFrame({"Date": [b.end for b in grid], "BarStart": [b.start for b in grid],
                         "AvailableDate": [b.end for b in grid], "Open": 10., "High": 10.2,
                         "Low": 9.8, "Close": 10., "Volume": 100., "Amount": 1000.})
    constraints = pd.DataFrame({"Date": [b.start for b in grid], "AvailableDate": [b.start for b in grid],
                                "QuantityStep": 1, "PriceTick": .01, "Tradable": True,
                                "SettlementAt": [grid[-1].end for _ in grid]})
    actions = pd.DataFrame([{"Date": grid[0].start, "AvailableDate": grid[0].start, "EventId": "none",
                             "Kind": "NONE", "Ratio": 1., "CashPerShare": 0., "PayAt": None}])
    products = {EquityProduct.BARS: bars, EquityProduct.CONSTRAINTS: constraints, EquityProduct.ACTIONS: actions,
                EquityProduct.SESSIONS: pd.DataFrame({"Date": [s.segments[0].start for s in sessions],
                "AvailableDate": [s.segments[0].start for s in sessions],
                "SessionDate": [s.session_date.isoformat() for s in sessions]})}
    calls = []

    def fetch(request):
        calls.append(request)
        metadata = equity_metadata(request, sessions, availability_basis="FIXTURE_BAR_CLOSE")
        metadata["no_actions_verified"] = True
        return products[request.parameters.query.product].copy(deep=True), metadata

    config = ProviderConfig(bindings={}, equity_bindings={ProviderKey(product, MarketId.US, source):
                            ProviderBinding("fixture", "v1", fetch) for product in EquityProduct})
    context = create_research_context(repository, batch, providers=config, execution_spec=spec)
    experiment = create_experiment(context, ExperimentRequest("Fixture", "Does isolated US execution work?", date(2026, 10, 28)))
    candidate = EquityCandidate("S999", "C001", instrument, spec.fingerprint, equity_implementation_hash(decide), 1, decide)
    request = EquityEvaluationRequest(experiment, candidate, TimeInterval(grid[1].start, grid[-1].end),
                                      date(2026, 10, 1), EquitySources(source, source, source, source), 1000., .001)
    return context, request, products, calls


def test_us_public_prepare_evaluate_backtest_publish_are_identical(tmp_path):
    context, request, _, calls = setup_equity(tmp_path)
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    assert len(calls) == 4
    assert run_backtest(context, request.candidate, prepared).content == result.content
    run = result.payload["runs"]["candidate"]
    assert run["metrics"]["closed_cycles"] == 12
    assert run["metrics"]["observations"] == 25
    assert run["metrics"]["sessions"] == 2
    assert run["fills"][0]["quantity"] == 98  # one-share US units, not CN round lots
    assert run["fills"][0]["interval_start"][:10] == run["fills"][1]["interval_start"][:10]
    evidence = publish_evidence(context, EvaluationEvidenceWrite(request.experiment, "account", prepared, result))
    assert evidence.schema == "equity_research" and evidence.schema_version == 1
    assert (context.repository.root / evidence.repository_path).read_bytes() == result.content
    assert len(calls) == 4


def test_equity_cross_market_and_source_revision_fail_before_calculation(tmp_path):
    context, request, _, calls = setup_equity(tmp_path)
    cn = replace(request.candidate, instrument=InstrumentId(MarketId.CN, AssetClass.STOCK, "600722.SH"))
    with pytest.raises(ValueError, match="MARKET_CONTRACT_MISMATCH"):
        context.evaluation.prepare(replace(request, candidate=cn))
    assert not calls
    with pytest.raises(ValueError, match="MARKET_CONTRACT_MISMATCH"):
        context.runtime.create(cn)
    with pytest.raises(ValueError, match="requires EquityCandidate"):
        context.runtime.create(object())
    assert context.runtime.create(request.candidate).specification == context.execution_spec
    bad = replace(request, sources=replace(request.sources, bars=SourceRef("fixture", "v2")))
    outcomes = context.evaluation.evaluate_many((bad, request))
    assert [item.status for item in outcomes] == ["FAILED", "SUCCEEDED"]


def test_settled_only_sale_cannot_fund_same_day_reentry(tmp_path):
    context, request, _, _ = setup_equity(tmp_path, cash_policy=CashAvailabilityPolicy.SETTLED_ONLY)
    result = context.evaluation.evaluate(request).payload["runs"]["candidate"]
    # Residual cash may purchase one share, but unsettled proceeds cannot fund
    # another full-size entry. Once that residual is spent the account waits.
    assert [row["quantity"] for row in result["fills"] if row["side"] == "BUY"] == [98, 1]
    assert result["account_points"][1]["receivable"] > 900
    assert result["account_points"][-1]["receivable"] == 0
    assert result["account_points"][-1]["cash"] > 990


def test_audit_rejects_tampered_account(tmp_path):
    context, request, products, _ = setup_equity(tmp_path)
    run = context.evaluation.evaluate(request).payload["runs"]["candidate"]
    run["account_points"][3]["cash"] += 1
    facts = json.loads(products[EquityProduct.BARS].to_json(orient="records", date_format="iso"))
    with pytest.raises(ValueError, match="audit mismatch: cash"):
        audit_equity_account(initial_cash=request.initial_cash, specification=asdict(context.execution_spec), bars=facts,
                             action_facts=json.loads(products[EquityProduct.ACTIONS].to_json(orient="records", date_format="iso")),
                             constraints=json.loads(products[EquityProduct.CONSTRAINTS].to_json(orient="records", date_format="iso")),
                             fee_rate=request.fee_rate,
                             **{key: run[key] for key in ("decisions", "orders", "fills", "actions", "account_points", "trades")})


def test_missing_bar_fails_instead_of_forward_filling(tmp_path):
    context, request, products, _ = setup_equity(tmp_path)
    products[EquityProduct.BARS] = products[EquityProduct.BARS].drop(index=5)
    with pytest.raises(ValueError, match="independent session grid"):
        context.evaluation.evaluate(request)


def test_split_and_dividend_preserve_entitlements_and_pay_later(tmp_path):
    context, request, products, _ = setup_equity(tmp_path, decide=hold)
    bars = products[EquityProduct.BARS]
    stamp = bars.BarStart.iloc[13]
    pay = bars.Date.iloc[-1]
    bars.loc[13:, ["Open", "High", "Low", "Close"]] /= 2
    products[EquityProduct.ACTIONS] = pd.DataFrame([
        {"Date": stamp, "AvailableDate": stamp, "EventId": "1-split", "Kind": "SPLIT", "Ratio": 2., "CashPerShare": 0., "PayAt": None},
        {"Date": stamp, "AvailableDate": stamp, "EventId": "2-dividend", "Kind": "CASH_DIVIDEND", "Ratio": 1., "CashPerShare": .1, "PayAt": pay},
    ])
    run = context.evaluation.evaluate(request).payload["runs"]["candidate"]
    assert run["account_points"][11]["quantity"] == 98
    assert run["account_points"][12]["quantity"] == 196
    assert run["account_points"][12]["receivable"] == pytest.approx(19.6)
    assert run["account_points"][-1]["receivable"] == 0
    assert run["account_points"][-1]["equity"] == pytest.approx(1018.62)
    assert [row["kind"] for row in run["actions"]] == ["SPLIT", "CASH_DIVIDEND", "DIVIDEND_PAYMENT"]


def test_future_bar_changes_do_not_change_prior_decisions(tmp_path):
    first_context, first_request, _, _ = setup_equity(tmp_path / "first")
    original = first_context.evaluation.evaluate(first_request).payload["runs"]["candidate"]
    context, request, products, _ = setup_equity(tmp_path / "changed")
    products[EquityProduct.BARS].loc[20:, ["Open", "High", "Low", "Close"]] *= 2
    changed = context.evaluation.evaluate(request).payload["runs"]["candidate"]
    assert original["decisions"][:19] == changed["decisions"][:19]
    assert original["account_points"][:19] == changed["account_points"][:19]


def test_failed_transition_rolls_back_and_resubmitted_plan_is_idempotent(tmp_path):
    from strategy_runtime import EquityStrategyInstance
    from trading_execution_engine.equity import EquityHistoricalExecutor
    context, request, products, _ = setup_equity(tmp_path, cash_policy=CashAvailabilityPolicy.SETTLED_ONLY)
    instance = EquityStrategyInstance(request.candidate, context.execution_spec)
    executor = EquityHistoricalExecutor(specification=context.execution_spec, initial_cash=1000., fee_rate=.001,
                                        actions=products[EquityProduct.ACTIONS])
    bars, rules = products[EquityProduct.BARS], products[EquityProduct.CONSTRAINTS]
    plan = instance.plan(bars.iloc[:1], TimeInterval(bars.BarStart.iloc[1], bars.Date.iloc[1]), executor.snapshot(), fee_rate=.001)
    first = executor.execute(plan, bars.iloc[1], constraint=rules.iloc[1])
    assert executor.execute(plan, bars.iloc[1], constraint=rules.iloc[1]) == first
    assert len(executor.rows["fills"]) == 1
    sell = instance.plan(bars.iloc[:2], TimeInterval(bars.BarStart.iloc[2], bars.Date.iloc[2]), first, fee_rate=.001)
    broken = rules.iloc[2].copy()
    broken["SettlementAt"] = None
    with pytest.raises(ValueError, match="settlement"):
        executor.execute(sell, bars.iloc[2], constraint=broken)
    assert executor.snapshot() == first and len(executor.rows["fills"]) == 1
    assert executor.execute(sell, bars.iloc[2], constraint=rules.iloc[2]).quantity == 0


def test_positive_latency_delays_which_bar_is_observable(tmp_path):
    context, request, products, _ = setup_equity(tmp_path)
    spec = replace(context.execution_spec, data_latency_seconds=1)
    from czsc_trader.research_tools.evaluation_access import EvaluationAccess
    access = EvaluationAccess(dataflows=context.data, strategy_id="S999", execution_spec=spec)
    candidate = replace(request.candidate, execution_spec_hash=spec.fingerprint)
    with pytest.raises(ValueError, match="warmup"):
        access.evaluate(replace(request, candidate=candidate))
    bars = products[EquityProduct.BARS]
    delayed = replace(request, candidate=candidate, window=TimeInterval(bars.BarStart.iloc[2], bars.Date.iloc[-1]))
    run = access.evaluate(delayed).payload["runs"]["candidate"]
    assert pd.Timestamp(run["decisions"][0]["observed_through"]) == bars.Date.iloc[0]


@pytest.mark.parametrize("defect", ["missing_constraint", "late_constraint", "no_volume"])
def test_execution_requires_current_trading_constraints_and_volume(tmp_path, defect):
    context, request, products, _ = setup_equity(tmp_path)
    if defect == "missing_constraint":
        products[EquityProduct.CONSTRAINTS] = products[EquityProduct.CONSTRAINTS].drop(index=3)
        with pytest.raises(ValueError, match="every execution interval"):
            context.evaluation.evaluate(request)
    elif defect == "late_constraint":
        rules = products[EquityProduct.CONSTRAINTS]
        rules.loc[3, "AvailableDate"] += pd.Timedelta(seconds=1)
        with pytest.raises(ValueError, match="unavailable"):
            context.evaluation.evaluate(request)
    else:
        products[EquityProduct.BARS]["Volume"] = 0.
        run = context.evaluation.evaluate(request).payload["runs"]["candidate"]
        assert not run["fills"]
        assert all(row["reason"] == "INSUFFICIENT_BAR_VOLUME" for row in run["orders"])
        assert run["metrics"]["total_return"] == 0


def test_payment_in_session_gap_precedes_next_day_split(tmp_path):
    context, request, products, _ = setup_equity(tmp_path, decide=hold)
    bars = products[EquityProduct.BARS]
    ex, split = bars.BarStart.iloc[4], bars.BarStart.iloc[13]
    pay = bars.Date.iloc[12] + pd.Timedelta(hours=1)
    bars.loc[13:, ["Open", "High", "Low", "Close"]] /= 2
    products[EquityProduct.ACTIONS] = pd.DataFrame([
        {"Date": ex, "AvailableDate": ex, "EventId": "div", "Kind": "CASH_DIVIDEND", "Ratio": 1., "CashPerShare": .1, "PayAt": pay},
        {"Date": split, "AvailableDate": split, "EventId": "split", "Kind": "SPLIT", "Ratio": 2., "CashPerShare": 0., "PayAt": None},
    ])
    run = context.evaluation.evaluate(request).payload["runs"]["candidate"]
    assert [row["kind"] for row in run["actions"]] == ["CASH_DIVIDEND", "DIVIDEND_PAYMENT", "SPLIT"]
    assert run["account_points"][-1]["equity"] == pytest.approx(1008.82)


def test_publication_rejects_truncated_account_even_with_intact_request_hash(tmp_path):
    from czsc_trader.research_tools import EquityEvaluationResult
    context, request, _, _ = setup_equity(tmp_path)
    prepared = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(prepared)
    payload = result.payload
    payload["runs"]["candidate"]["account_points"].pop()
    altered = EquityEvaluationResult(result.request_hash, json.dumps(payload).encode())
    with pytest.raises(ValueError, match="evaluation window"):
        publish_evidence(context, EvaluationEvidenceWrite(request.experiment, "altered", prepared, altered))
