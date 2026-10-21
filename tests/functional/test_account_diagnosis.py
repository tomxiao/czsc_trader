"""Public account diagnosis authenticates retained accounts without executing them."""

from dataclasses import replace
from datetime import date
import json

import pandas as pd
import pytest

from czsc_trader.application.account_diagnosis_service import diagnose_accounts
from czsc_trader.application import create_experiment, publish_evidence
from czsc_trader.application.research_governance_service import ExperimentRequest
from czsc_trader.research_tools.account_diagnosis import (
    AccountDiagnosisRequest,
    AccountRunRef,
    DecisionPopulationRef,
)
from czsc_trader.research_tools.evaluation import EvaluationWindow
from czsc_trader.research_tools.evidence import EvaluationEvidenceWrite, MaterialEvidenceWrite
from strategy_evaluator.account_diagnosis import AccountDiagnosisStatus
from public_backtest_support import request_for_prices


@pytest.fixture
def retained_account(candidate_payload, tmp_path, monkeypatch):
    days = pd.bdate_range("2025-12-29", periods=8)
    prices = pd.DataFrame(
        {
            "dt": days,
            "open": [10.0, 10.0, 5.0, 5.123, 6.123, 6.123, 6.0, 6.0],
            "close": [10.0, 10.0, 5.1, 5.5, 6.123, 6.123, 6.0, 6.0],
        }
    )
    context, request, _ = request_for_prices(
        candidate_payload,
        tmp_path,
        monkeypatch,
        prices,
        flow=[0.1, 0.8, 0.8, 0.8, 0.1, 0.1, 0.1, 0.1],
        hfq_factors=pd.Series([0.3, 0.3, 0.411, 0.411, 0.411, 0.411, 0.411, 0.411]),
    )
    experiment = create_experiment(
        context, ExperimentRequest("Diagnosis", "Accounting", days[-1].date())
    )
    request = context.evaluation.prepare(replace(request, experiment_id=experiment.experiment_id))
    result = context.evaluation.evaluate(request)
    evidence = publish_evidence(
        context, EvaluationEvidenceWrite(experiment, "account", request, result)
    )
    return context, request, result, evidence


def test_authenticated_hfq_account_decomposes_daily_years_and_inherited_window(
    retained_account, monkeypatch
):
    context, request, result, evidence = retained_account
    run = result.runs[0]
    reference = AccountRunRef(evidence, run.identity)
    # A replay attempt would be a contract violation. Diagnosis reads saved facts only.
    monkeypatch.setattr(
        type(context.evaluation), "evaluate", lambda *a, **k: pytest.fail("unexpected replay")
    )
    diagnosis = diagnose_accounts(
        context.repository, AccountDiagnosisRequest(reference, None, request.windows[0])
    )
    assert diagnosis.status is AccountDiagnosisStatus.COMPUTED
    raw = run.execution.account_daily
    expected = raw.iloc[-1].equity - request.initial_cash
    assert diagnosis.reconciliation[0].equity_change == pytest.approx(expected)
    assert diagnosis.reconciliation[0].decomposed_change == pytest.approx(expected)
    daily = diagnosis.pnl_breakdown[0].daily
    fills = run.execution.fills
    assert sum(d.fees for d in daily) == pytest.approx(-fills.fees.sum())
    assert {a.year for a in diagnosis.pnl_breakdown[0].annual} == {2025, 2026}
    assert all(abs(d.residual) < 1e-7 for d in daily)
    bought = fills[fills.side.eq("BUY")].iloc[0]
    entry = next(d for d in daily if d.session == bought.fill_time.date().isoformat())
    close = raw.loc[raw.date.eq(bought.fill_time.normalize()), "close"].iloc[0]
    assert entry.entry == pytest.approx(bought.quantity * (close - bought.price))
    first = next(i for i, row in enumerate(raw.itertuples()) if row.quantity_before > 0)
    window = EvaluationWindow("slice", raw.iloc[first].date.date(), raw.iloc[-1].date.date())
    sliced = diagnose_accounts(context.repository, AccountDiagnosisRequest(reference, None, window))
    assert sliced.status is AccountDiagnosisStatus.COMPUTED
    assert sliced.reconciliation[0].opening_equity == pytest.approx(raw.iloc[first - 1].equity)
    assert sliced.pnl_breakdown[0].daily[0].entry == 0
    assert sliced.pnl_breakdown[0].daily[0].cycle_id is not None
    assert json.loads(json.dumps(sliced.to_dict()))["status"] == "COMPUTED"


def test_population_membership_is_explicit_and_unknown_remains_unknown(retained_account):
    context, request, result, evidence = retained_account
    run = result.runs[0]
    decisions = run.execution.decisions.decision_id.tolist()
    payload = {
        "schema_version": 1,
        "population_id": "declared",
        "evaluation_id": run.identity.evaluation_id,
        "memberships": [
            {"decision_id": decisions[0], "member": True},
            {"decision_id": decisions[1], "member": False},
        ],
    }
    population = publish_evidence(
        context,
        MaterialEvidenceWrite(
            evidence.experiment,
            "population",
            json.dumps(payload).encode(),
            "application/json",
            "json",
        ),
    )
    diagnosis = diagnose_accounts(
        context.repository,
        AccountDiagnosisRequest(
            AccountRunRef(evidence, run.identity),
            None,
            request.windows[0],
            (DecisionPopulationRef(population, "declared"),),
        ),
    )
    assert diagnosis.status is AccountDiagnosisStatus.COMPUTED
    assert [d.member for d in diagnosis.decision_coverage[:3]] == [True, False, None]
    assert sum(d.buy_fill for d in diagnosis.decision_coverage) == len(
        run.execution.fills.query("side == 'BUY'")
    )
    assert any(d.holding_decision for d in diagnosis.decision_coverage)
    for summary in diagnosis.coverage_summary:
        assert summary.total == summary.members + summary.nonmembers + summary.unknown
        if summary.unknown:
            assert summary.member_fraction is None


def test_invalid_evidence_and_absent_coordinate_do_not_claim_computed(retained_account):
    context, request, result, evidence = retained_account
    identity = result.runs[0].identity
    missing = replace(identity, environment_sha256="f" * 64)
    diagnosis = diagnose_accounts(
        context.repository,
        AccountDiagnosisRequest(AccountRunRef(evidence, missing), None, request.windows[0]),
    )
    assert diagnosis.status is AccountDiagnosisStatus.INVALID_EVIDENCE
    path = evidence.resolve(context.repository.root)
    path.write_bytes(path.read_bytes() + b" ")
    changed = diagnose_accounts(
        context.repository,
        AccountDiagnosisRequest(AccountRunRef(evidence, identity), None, request.windows[0]),
    )
    assert changed.status is AccountDiagnosisStatus.INVALID_EVIDENCE
    assert "content differs" in changed.issues[0]


def test_pair_comparison_preserves_ids_and_rejects_different_costs(retained_account):
    context, request, result, evidence = retained_account
    reference = AccountRunRef(evidence, result.runs[0].identity)
    identical = diagnose_accounts(
        context.repository, AccountDiagnosisRequest(reference, reference, request.windows[0])
    )
    assert identical.status is AccountDiagnosisStatus.COMPUTED
    assert all(p.equity_difference == 0 for p in identical.daily_paths)
    assert all(p.baseline_cycle_id == p.alternative_cycle_id for p in identical.path_comparison)
    other_request = replace(request, costs=(replace(request.costs[0], one_way_cost=0.002),))
    other_result = context.evaluation.evaluate(other_request)
    other_evidence = publish_evidence(
        context, EvaluationEvidenceWrite(evidence.experiment, "other", other_request, other_result)
    )
    other = AccountRunRef(other_evidence, other_result.runs[0].identity)
    mismatch = diagnose_accounts(
        context.repository, AccountDiagnosisRequest(reference, other, request.windows[0])
    )
    assert mismatch.status is AccountDiagnosisStatus.INCOMPARABLE


def test_request_rejects_untyped_or_foreign_batch_inputs(retained_account):
    _, request, result, evidence = retained_account
    reference = AccountRunRef(evidence, result.runs[0].identity)
    with pytest.raises(TypeError):
        AccountDiagnosisRequest(reference, None, request.windows[0], [])
    foreign = replace(evidence, experiment=replace(evidence.experiment, strategy_id="S901"))
    with pytest.raises(ValueError, match="different batches"):
        AccountRunRef(foreign, result.runs[0].identity)
    with pytest.raises(ValueError, match="ordered"):
        EvaluationWindow("bad", date(2026, 1, 2), date(2026, 1, 1))


@pytest.mark.parametrize("malformation", ["boolean_version", "duplicate_key"])
def test_membership_evidence_rejects_ambiguous_json(retained_account, malformation):
    context, request, result, evidence = retained_account
    payload = {
        "schema_version": True if malformation == "boolean_version" else 1,
        "population_id": "bad",
        "evaluation_id": result.runs[0].identity.evaluation_id,
        "memberships": [],
    }
    encoded = json.dumps(payload)
    if malformation == "duplicate_key":
        encoded = encoded[:-1] + ', "population_id": "bad"}'
    population = publish_evidence(
        context,
        MaterialEvidenceWrite(
            evidence.experiment, "bad-population", encoded.encode(), "application/json", "json"
        ),
    )
    diagnosis = diagnose_accounts(
        context.repository,
        AccountDiagnosisRequest(
            AccountRunRef(evidence, result.runs[0].identity),
            None,
            request.windows[0],
            (DecisionPopulationRef(population, "bad"),),
        ),
    )
    assert diagnosis.status is AccountDiagnosisStatus.INVALID_EVIDENCE


def test_target_without_actual_order_is_not_counted_as_buy_intent(
    candidate_payload, tmp_path, monkeypatch
):
    days = pd.bdate_range("2026-01-05", periods=5)
    prices = pd.DataFrame({"dt": days, "open": 10.0, "close": 10.0})
    context, request, _ = request_for_prices(
        candidate_payload,
        tmp_path,
        monkeypatch,
        prices,
        initial_cash=10.0,
        flow=[0.1, 0.8, 0.8, 0.8, 0.8],
    )
    experiment = create_experiment(
        context, ExperimentRequest("No-order", "Cash too small", days[-1].date())
    )
    request = context.evaluation.prepare(replace(request, experiment_id=experiment.experiment_id))
    result = context.evaluation.evaluate(request)
    run = result.runs[0]
    assert run.execution.orders.empty
    assert run.execution.fills.empty
    assert run.execution.decisions.target_position.eq(1).any()
    evidence = publish_evidence(
        context, EvaluationEvidenceWrite(experiment, "small-account", request, result)
    )
    payload = {
        "schema_version": 1,
        "population_id": "all-unknown",
        "evaluation_id": run.identity.evaluation_id,
        "memberships": [],
    }
    population = publish_evidence(
        context,
        MaterialEvidenceWrite(
            experiment, "membership", json.dumps(payload).encode(), "application/json", "json"
        ),
    )
    diagnosis = diagnose_accounts(
        context.repository,
        AccountDiagnosisRequest(
            AccountRunRef(evidence, run.identity),
            None,
            request.windows[0],
            (DecisionPopulationRef(population, "all-unknown"),),
        ),
    )
    assert diagnosis.status is AccountDiagnosisStatus.COMPUTED
    assert not any(d.buy_intent or d.buy_fill for d in diagnosis.decision_coverage)
    assert diagnosis.reconciliation[0].decomposed_change == 0
