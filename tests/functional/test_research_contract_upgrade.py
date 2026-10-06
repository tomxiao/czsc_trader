"""Account evaluation contracts independent of experimental process tracking."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import shutil

import pandas as pd
import pytest
from dataflows import DataSpace, Dataflows, ProviderConfig
from strategy_runtime import StrategyCandidate, StrategyRuntime

from czsc_trader.application.context import RepositoryContext
from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
from czsc_trader.research_tools.context import ResearchBatchRef, ResearchContext, ExperimentRef
from czsc_trader.research_tools.evaluation import (
    EvaluationRequest, EvaluationWindow,
    EvaluationCost, serialize_evaluation_evidence, validate_evaluation_evidence,
)
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark, NextOpenBuyHold
from test_candidate_runtime_execution import _install_candidate_dataflows


@pytest.fixture
def managed_evaluation(candidate_payload, tmp_path, monkeypatch):
    return _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, prepared=True)


@pytest.fixture
def unprepared_evaluation(candidate_payload, tmp_path, monkeypatch):
    return _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, prepared=False)


def _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, *, prepared):
    payload, package = candidate_payload
    (tmp_path / "src/czsc_trader").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    repository = RepositoryContext.discover(tmp_path)
    experiment = ExperimentRef("S900", "EX001_20261007")
    folder = experiment.resolve(tmp_path)
    (folder / "work").mkdir(parents=True)
    (folder / "experiment.json").write_text(json.dumps(experiment.to_dict()), encoding="utf-8")
    runtime_root = folder / "work/strategy_runtime"
    shutil.copytree(package, runtime_root)
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1., "close": 1.})
    inputs = pd.DataFrame({"Date": sessions, "Flow": [.1, .8, .8, .1, 0., 0.]})
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=tmp_path,
                                        space=DataSpace(Path("research/S900/data")))
    context = ResearchContext(ResearchBatchRef("S900"), repository, flows,
                              StrategyRuntime(dataflows=flows),
                              EvaluationAccess(dataflows=flows, strategy_id="S900"))
    data = (_prepare_backtest_execution_data(repository_root=tmp_path,
        symbol="588080.SH", asset_type="etf", start=sessions[1].date(),
        end=sessions[-1].date(), intraday_frequencies=("30m",), dataflows=flows)
        if prepared else None)
    candidate = StrategyCandidate("S900", "C0001", payload, runtime_root)
    request = EvaluationRequest(tmp_path, experiment.experiment_id, candidate,
        {"candidate_id": candidate.reference_id,
         "source_files": list(payload["runtime"]["source_files"]),
         "implementation_sha256": payload["runtime"]["source_sha256"]},
        "588080.SH", "etf", (EvaluationWindow("full", sessions[1].date(), sessions[-1].date()),),
        sessions[-1].date(), 100_000, (EvaluationCost("standard", .001),), data,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)))
    return context, request


def test_repeated_account_computation_is_reusable_without_process_records(managed_evaluation):
    context, request = managed_evaluation
    one = context.evaluation.evaluate(request)
    two = context.evaluation.evaluate(request)
    assert one.result_hash == two.result_hash
    assert not hasattr(one, "attempt_id")
    assert not list(context.repository.root.rglob("execution_receipt.json"))
    assert not list(context.repository.root.rglob("record.json"))
    assert not (context.repository.root / "data/backtest").exists()


def test_preparation_uses_only_batch_data_space(unprepared_evaluation):
    context, request = unprepared_evaluation
    bound = context.evaluation.prepare(request)
    assert bound.execution_data.prepared.space_id == context.data.binding.space_id
    assert all(binding.prepared.space_id == context.data.binding.space_id
               for binding in bound.input_bindings.values())
    result = context.evaluation.evaluate(bound)
    assert result.request_hash
    foreign = Dataflows(base_dir=context.repository.root, space=DataSpace(Path("research/S901/data")),
                        providers=ProviderConfig(bindings={}))
    with pytest.raises(ValueError, match="another data space"):
        EvaluationAccess(dataflows=foreign).evaluate(bound)


def test_published_account_evidence_authenticates_result_and_ledgers(managed_evaluation):
    context, request = managed_evaluation
    request = context.evaluation.prepare(request)
    result = context.evaluation.evaluate(request)
    payload = serialize_evaluation_evidence(request, result)
    validate_evaluation_evidence(payload)
    encoded = json.loads(json.dumps(payload))
    validate_evaluation_evidence(encoded)
    changed = deepcopy(encoded)
    changed["runs"][0]["ledgers"]["account_daily"]["data"][-1]["equity"] += 1
    with pytest.raises(ValueError, match="differs"):
        validate_evaluation_evidence(changed)
    with pytest.raises(ValueError, match="identity differs"):
        serialize_evaluation_evidence(replace(request, initial_cash=200_000), result)
