"""Historical diagnostics and tradable targets through public evaluation."""
from dataclasses import replace

import pandas as pd
import pytest
from strategy_runtime import implementation_sha256
from czsc_trader.application import create_experiment
from czsc_trader.application.research_governance_service import ExperimentRequest
from czsc_trader.research_tools import ResearchExecutionSession
from public_backtest_support import request_for_prices


def _evaluate(context, request):
    experiment = create_experiment(context, ExperimentRequest("Bridge fixture", "Evaluate causal history", request.data_cutoff))
    request = replace(request, experiment_id=experiment.experiment_id)
    with ResearchExecutionSession(context, experiment=experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        return outcome


def _history_request(candidate_payload, tmp_path, monkeypatch, *, invalid_target=False):
    payload, source = candidate_payload
    path = source / "strategies/candidate_fixture.py"
    text = path.read_text(encoding="utf-8")
    if invalid_target:
        text = text.replace('        return pd.DataFrame(', '        target.iloc[-1] = float("nan")\n        return pd.DataFrame(')
    else:
        text = text.replace('"fixture_signal": target}', '"fixture_signal": target, "base_score": float("nan"), "confirmation_score": 0.1}')
    path.write_text(text, encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        payload["runtime"]["source_files"], source_root=source,
    )
    dates = pd.bdate_range("2026-09-14", periods=3)
    daily = pd.DataFrame({"dt": dates, "open": 1., "close": 1.})
    return request_for_prices(candidate_payload, tmp_path, monkeypatch, daily)[:2]


def test_srt_history_allows_unavailable_diagnostics_during_warmup(candidate_payload, tmp_path, monkeypatch):
    context, request = _history_request(candidate_payload, tmp_path, monkeypatch)
    outcome = _evaluate(context, request)
    assert outcome.result is not None, outcome.error
    result = outcome.result
    assert len(result.runs) == 1
    assert len(result.runs[0].signals.decisions) == 2
    assert result.runs[0].signals.decisions["factor_score"].isna().all()
    assert result.runs[0].execution.account_daily["equity"].eq(request.initial_cash).all()


def test_srt_history_rejects_unavailable_target_position(candidate_payload, tmp_path, monkeypatch):
    context, request = _history_request(candidate_payload, tmp_path, monkeypatch, invalid_target=True)
    outcome = _evaluate(context, request)
    assert outcome.status.value == "FAILED"
    assert outcome.error.code == "RuntimeContractError" and "target positions" in outcome.error.message


@pytest.mark.parametrize("fractional_mode", [True, False])
def test_public_evaluation_fractional_targets_require_explicit_equity_mode(
    candidate_payload, tmp_path, monkeypatch, fractional_mode,
):
    payload, source = candidate_payload
    path = source / "strategies/candidate_fixture.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("target = (values > threshold).astype(float)", "target = values.astype(float)")
    if fractional_mode:
        text = text.replace('"mode": "full_available_cash"', '"mode": "target_equity_fraction", "allocation_fraction": 1.0')
        text = text.replace('"target_scope": "entry_cycle"', '"target_scope": "decision"')
    path.write_text(text, encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        payload["runtime"]["source_files"], source_root=source,
    )
    dates = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": dates, "open": 1., "close": 1.})
    context, request, _ = request_for_prices(
        candidate_payload, tmp_path, monkeypatch, daily,
        flow=[.25, .75, .25, .5, 0., 0.], cost=0.,
    )
    if not fractional_mode:
        outcome = _evaluate(context, request)
        assert outcome.status.value == "FAILED"
        assert outcome.error.code == "RuntimeContractError" and "binary" in outcome.error.message
        return
    outcome = _evaluate(context, request)
    assert outcome.result is not None, outcome.error
    run = outcome.result.runs[0]
    assert run.signals.decisions.target_position.tolist() == [.25, .75, .25, .5, 0.]
    assert run.execution.account_daily.target_position.tolist() == [.25, .75, .25, .5, 0.]
    assert run.execution.account_daily.quantity.tolist() == [25_000, 75_000, 25_000, 50_000, 0]
    assert run.execution.fills.side.tolist() == ["BUY", "BUY", "SELL", "BUY", "SELL"]
    assert run.execution.account_daily.equity.eq(100_000).all()
    assert len(run.execution.trades) == 1
    assert run.execution.trades.iloc[0]["status"] == "CLOSED"
    assert run.execution.fills.cycle_id.nunique() == 1
