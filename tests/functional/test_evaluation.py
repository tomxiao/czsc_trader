from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from czsc_trader.research_tools import (
    CandidateEvaluationContext,
)
from czsc_trader.research_tools.evaluation import prepare_evaluation_workspace
from czsc_trader.application.context import RepositoryContext
from strategy_evaluator import EvaluationProtocol


def test_formal_evaluation_rejects_data_that_stops_before_development_cutoff(
    minimal_repo: Path, monkeypatch
) -> None:
    protocol = EvaluationProtocol.from_dict(
        {
            "schema_version": 1,
            "standard_version": "opc-v3",
            "experiment_id": "STALE",
            "research_objective": "reject false success",
            "development_cutoff": "2026-09-02",
            "incumbent_id": "BuyHold",
            "incumbent_hash": "a" * 64,
            "decision_windows": ["full"],
            "target_windows": ["full"],
            "execution_policy_hash": "b" * 64,
            "tightened_margins": {},
            "shortlist_limit": 1,
            "target_requirements": [
                {
                    "metric": "full_return",
                    "direction": "maximize",
                    "minimum_improvement": 0.0,
                }
            ],
            "candidate_manifest": "candidate_manifest.json",
        }
    )
    stale = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2026-09-01"]),
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "vol": [1.0],
            "amount": [1.0],
        }
    )

    def load_stale(**request):
        # Match the TDR execution-data boundary instead of accepting any type.
        assert request["end"] == date(2026, 9, 2)
        return SimpleNamespace(
            adjusted_daily=stale,
            execution_daily=stale,
            execution_intraday=pd.DataFrame(),
        )

    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation._prepare_backtest_execution_data",
        load_stale,
    )
    context = CandidateEvaluationContext(
        RepositoryContext.discover(minimal_repo, explicit_root=minimal_repo),
        "588080.SH",
        "etf",
        (("full", (pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02"))),),
    )

    with pytest.raises(ValueError, match="does not reach development cutoff"):
        prepare_evaluation_workspace(context, protocol)


def test_research_evaluate_is_a_non_governance_facade(minimal_repo: Path, monkeypatch) -> None:
    from czsc_trader.application.research_evaluation_service import (
        evaluate_research_request,
    )

    context = RepositoryContext.discover(minimal_repo, explicit_root=minimal_repo)
    experiment = minimal_repo / "experiments" / "S008" / "EX67"
    output = experiment / "artifacts" / "evaluation"
    request_path = experiment / "evaluation_request.json"
    expected_request = object()
    expected_result = object()
    observed = {}

    monkeypatch.setattr(
        "czsc_trader.application.research_evaluation_service._request_path",
        lambda received_context, received_path: (
            observed.update(context=received_context, path=received_path)
            or (request_path, experiment)
        ),
    )
    monkeypatch.setattr(
        "czsc_trader.application.research_evaluation_service._evaluation_request",
        lambda *args, **kwargs: expected_request,
    )
    monkeypatch.setattr(
        "czsc_trader.application.research_evaluation_service.evaluate_strategy",
        lambda request, **kwargs: expected_result if request is expected_request else None,
    )
    monkeypatch.setattr(
        "czsc_trader.application.research_evaluation_service._publish_result",
        lambda received_context, received_experiment, result: (
            output,
            {
                "request_hash": "a" * 64,
                "result_hash": "b" * 64,
                "strategy_identity": "c" * 64,
                "runtime_binding_hash": "d" * 64,
                "data_identity": "e" * 64,
                "execution_mode": "FULL",
                "runs": [{"window_id": "full", "scenario_id": "standard"}],
            },
        ),
    )

    result = evaluate_research_request(context, Path("request.json"))

    assert observed == {
        "context": context,
        "path": Path("request.json"),
    }
    assert result.status == "PASS"
    assert result.command == "research.evaluate"
    assert result.result["run_count"] == 1
    assert result.result["execution_mode"] == "FULL"
    assert result.artifacts == {"directory": "experiments/S008/EX67/artifacts/evaluation"}
