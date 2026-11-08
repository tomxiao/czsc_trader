"""Public US equity path, identity isolation and independent account evidence."""

from equity_test_support import hold, setup_equity, replay_payload, account_research, current_account_request
from dataclasses import asdict, replace
import json

import pandas as pd
import pytest
from dataflows import (AssetClass, EquityProduct, InstrumentId, MarketId,
                       SourceRef, TimeInterval)
from strategy_runtime import (CashAvailabilityPolicy)
from strategy_evaluator.equity import audit_equity_account
from czsc_trader.application.backtest_service import run_backtest
from czsc_trader.research_tools import EvaluationEvidenceWrite


def test_us_public_prepare_evaluate_publish_uses_current_contract(tmp_path):
    context, request, _, calls = setup_equity(tmp_path)
    with account_research(context, request) as (prepared, result, payload, execution):
        run = payload["runs"]["candidate"]
        assert run["metrics"]["closed_cycles"] == 12
        assert run["metrics"]["observations"] == 25
        assert run["fills"][0]["quantity"] == 98
        assert run["fills"][0]["interval_start"][:10] == run["fills"][1]["interval_start"][:10]
        from czsc_trader.application import publish_evidence_many
        outcome, = publish_evidence_many(context, (EvaluationEvidenceWrite(request.experiment, "account", prepared, result),), execution=execution)
        assert outcome.reference.schema_version == 4
        assert outcome.reference.resolve(context.repository.root).read_bytes() == result.content
    assert len(calls) == 3
    assert not hasattr(context.evaluation, "evaluate")
    current = current_account_request(context,request)
    with pytest.raises(TypeError, match="session|Session|prepare"):
        run_backtest(context, current.candidate, current)


def test_equity_cross_market_and_source_revision_fail_before_calculation(tmp_path):
    from equity_test_support import setup_account_research
    context, request, _, calls = setup_account_research(tmp_path)
    with pytest.raises(ValueError, match="MARKET_CONTRACT_MISMATCH"):
        replace(request.candidate.definition,instrument=InstrumentId(MarketId.CN,AssetClass.STOCK,"600722.SH"))
    assert not calls
    bad = replace(request, sources=replace(request.sources, bars=SourceRef("fixture", "v2")))
    with pytest.raises(ValueError, match="preparation failed"):
        replay_payload(context, bad)


def test_settled_only_sale_cannot_fund_same_day_reentry(tmp_path):
    context, request, _, _ = setup_equity(tmp_path, cash_policy=CashAvailabilityPolicy.SETTLED_ONLY)
    # Once residual cash is exhausted, unsettled proceeds cannot be spent.
    # The approved model blocks rather than silently altering the intent.
    with pytest.raises(ValueError, match='INSUFFICIENT_LOT'):
        replay_payload(context, request)


def test_audit_rejects_tampered_account(tmp_path):
    context, request, products, _ = setup_equity(tmp_path)
    payload = replay_payload(context, request)
    run = payload["runs"]["candidate"]
    run["account_points"][3]["cash"] += 1
    facts = json.loads(products[EquityProduct.BARS].to_json(orient="records", date_format="iso"))
    with pytest.raises(ValueError, match="cash"):
        audit_equity_account(initial_cash=request.initial_cash, specification=asdict(context.execution_spec), bars=facts,
                             price_basis="HFQ", quantity_basis="SIMULATED_INTEGER_UNITS",
                             constraints=payload["audit_inputs"]["constraints"],
                             fee_rate=request.fee_rate,account_contract=4,decision_contract="FORMAL_V4",
                             **{key: run[key] for key in ("decisions", "orders", "fills", "account_entries", "account_points", "trades")})


def test_missing_bar_fails_instead_of_forward_filling(tmp_path):
    context, request, products, _ = setup_equity(tmp_path)
    products[EquityProduct.BARS] = products[EquityProduct.BARS].drop(index=5)
    with pytest.raises(ValueError, match="independent session grid"):
        replay_payload(context, request)


def test_hfq_account_has_no_corporate_action_input_or_income(tmp_path):
    context, request, _, calls = setup_equity(tmp_path, decide=hold)
    with account_research(context, request) as (_, result, payload, _):
        assert payload['request']['price_basis'] == 'HFQ'
        assert payload['request']['quantity_basis'] == 'SIMULATED_INTEGER_UNITS'
        source = json.loads(next(item.content for item in result.artifacts if item.kind == 'equity_input'))
        assert 'actions' not in source['products']
        for run in payload['runs'].values():
            assert {point['quantity'] for point in run['account_points']} == {98}
            assert not run['account_entries']
            assert run['account_points'][-1]['equity'] == pytest.approx(999.02)
    assert {q.parameters.query.product for q in calls} == set(EquityProduct)



def test_future_bar_changes_do_not_change_prior_decisions(tmp_path):
    first_context, first_request, _, _ = setup_equity(tmp_path / "first")
    original = replay_payload(first_context, first_request)["runs"]["candidate"]
    context, request, products, _ = setup_equity(tmp_path / "changed")
    products[EquityProduct.BARS].loc[20:, ["Open", "High", "Low", "Close"]] *= 2
    changed = replay_payload(context, request)["runs"]["candidate"]
    assert original["decisions"][:19] == changed["decisions"][:19]
    assert original["account_points"][:19] == changed["account_points"][:19]




def test_positive_latency_delays_which_bar_is_observable(tmp_path):
    context, request, products, _ = setup_equity(tmp_path)
    spec = replace(context.execution_spec, data_latency_seconds=1)
    from czsc_trader.research_tools.evaluation_access import EvaluationAccess
    from strategy_runtime import StrategyRuntime
    access = EvaluationAccess(dataflows=context.data, strategy_id="S999", execution_spec=spec,
                              resources=context.evaluation.resources)
    context = replace(context, runtime=StrategyRuntime(execution_spec=spec), evaluation=access, execution_spec=spec)
    candidate = replace(request.candidate, execution_spec_hash=spec.fingerprint)
    with pytest.raises(ValueError, match="WARMUP_INSUFFICIENT"):
        replay_payload(replace(context, evaluation=access, execution_spec=spec), replace(request, candidate=candidate))
    bars = products[EquityProduct.BARS]
    delayed = replace(request, candidate=candidate, window=TimeInterval(
        bars.BarStart.iloc[2].to_pydatetime(), bars.Date.iloc[-1].to_pydatetime()))
    run = replay_payload(replace(context, evaluation=access, execution_spec=spec), delayed)["runs"]["candidate"]
    assert pd.Timestamp(run["decisions"][0]["observed_through"]) == bars.Date.iloc[0]


@pytest.mark.parametrize("defect", ["missing_constraint", "late_constraint", "no_volume"])
def test_execution_requires_current_trading_constraints_and_volume(tmp_path, defect):
    context, request, products, _ = setup_equity(tmp_path)
    if defect == "missing_constraint":
        products[EquityProduct.TRADING_FACTS] = products[EquityProduct.TRADING_FACTS].drop(index=3)
        with pytest.raises(ValueError, match="every execution interval"):
            replay_payload(context, request)
    elif defect == "late_constraint":
        rules = products[EquityProduct.TRADING_FACTS]
        rules.loc[3, "AvailableDate"] += pd.Timedelta(seconds=1)
        with pytest.raises(ValueError, match="unavailable"):
            replay_payload(context, request)
    else:
        products[EquityProduct.BARS]["Volume"] = 0.
        run = replay_payload(context, request)["runs"]["candidate"]
        assert not run["fills"]
        assert all(row["reason"] == "INSUFFICIENT_BAR_VOLUME" for row in run["orders"])
        assert run["metrics"]["total_return"] == 0


def test_old_raw_result_cannot_be_read_as_hfq_evidence(tmp_path):
    from czsc_trader.research_tools.equity_replay import validate_result_structure
    context, request, _, _ = setup_equity(tmp_path, decide=hold)
    with account_research(context, request) as (_, result, _, _):
        payload = result.payload
        payload['request']['price_basis'] = 'RAW'
        with pytest.raises(ValueError, match='HFQ simulated units'):
            validate_result_structure(payload)



def test_publication_rejects_truncated_account_even_with_intact_request_hash(tmp_path):
    from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult, EquityArtifact
    from czsc_trader.application import publish_evidence_many
    context, request, _, _ = setup_equity(tmp_path)
    with account_research(context, request) as (prepared, result, payload, execution):
        artifacts = list(result.artifacts)
        index = next(i for i, item in enumerate(artifacts) if item.sha256 == result.payload["candidate_ref"]["sha256"])
        value = json.loads(artifacts[index].content)
        value["run"]["account_points"].pop()
        artifacts[index] = EquityArtifact(artifacts[index].kind, json.dumps(value).encode())
        with pytest.raises(ValueError):
            altered = EquityEvaluationResult(result.request_hash, result.content, tuple(artifacts))
            publish_evidence_many(context, (EvaluationEvidenceWrite(request.experiment, "altered", prepared, altered),), execution=execution)
