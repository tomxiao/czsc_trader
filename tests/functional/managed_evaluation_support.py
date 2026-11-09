"""Account evaluation contracts independent of experimental process tracking."""
from pathlib import Path
import json
import pickle
import shutil

import pandas as pd
import pytest
from dataflows import DataSpace
from strategy_runtime import StrategyCandidate, StrategyRuntime

from czsc_trader.application.context import RepositoryContext
from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
from czsc_trader.research_tools.context import ResearchBatchRef, ResearchContext, ExperimentRef
from historical_evaluation_support import EvaluationRequest
from czsc_trader.research_tools.evaluation import (
    EvaluationWindow,
    EvaluationCost,
)
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark, NextOpenBuyHold
from test_candidate_runtime_execution import _install_candidate_dataflows


@pytest.fixture
def fresh_managed_evaluation(candidate_payload, tmp_path, monkeypatch):
    return _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, prepared=True)


@pytest.fixture
def managed_evaluation(request, tmp_path, frozen_seed_root, monkeypatch):
    """Reuse execution inputs, but leave strategy binding/evaluation to each test."""
    from czsc_trader.research_tools._evaluation_workers import pack
    from evaluation_seed_support import relocate_request
    from public_backtest_support import research_context

    seed = frozen_seed_root / "managed-evaluation-inputs"
    data = frozen_seed_root / "managed-evaluation-inputs.pkl"
    if not seed.exists():
        context, evaluation = request.getfixturevalue("fresh_managed_evaluation")
        assert not evaluation.input_bindings
        data.write_bytes(pack(evaluation))
        shutil.copytree(context.repository.root, seed)
    root = tmp_path / "evaluation-repo"
    shutil.copytree(seed, root)
    evaluation = relocate_request(pickle.loads(data.read_bytes()), root)
    flows = _evaluation_flows(root, monkeypatch)
    return research_context(RepositoryContext.discover(root), flows), evaluation


@pytest.fixture
def unprepared_evaluation(candidate_payload, tmp_path, monkeypatch):
    return _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, prepared=False)


def _evaluation_flows(root, monkeypatch):
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1., "close": 1.})
    inputs = pd.DataFrame({"Date": sessions, "Flow": [.1, .8, .8, .1, 0., 0.]})
    return _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=root,
                                       space=DataSpace(Path("research/S900/assets/data")))


def _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, *, prepared):
    payload, package = candidate_payload
    (tmp_path / "src/czsc_trader").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    repository = RepositoryContext.discover(tmp_path)
    experiment = ExperimentRef("S900", "EX001_20261007")
    folder = experiment.resolve(tmp_path)
    (folder / "src").mkdir(parents=True)
    (folder / "experiment.json").write_text(json.dumps(experiment.to_dict()), encoding="utf-8")
    runtime_root = folder / "src/strategy_runtime"
    shutil.copytree(package, runtime_root)
    sessions = pd.bdate_range("2026-09-14", periods=6)
    flows = _evaluation_flows(tmp_path, monkeypatch)
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
