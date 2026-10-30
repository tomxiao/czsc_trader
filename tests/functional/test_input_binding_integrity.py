"""Reject mutable execution tables that no longer match their DFLS binding."""

from dataclasses import replace
from pathlib import Path
import pickle
import shutil
from uuid import uuid4

from dataflows import Dataflows, Dataset, DataSpace, PreparePolicy, ProviderBinding, ProviderConfig

import pandas as pd
import pytest
from strategy_runtime import StrategyCandidate

from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from public_backtest_support import request_for_prices
from evaluation_seed_support import prepare_request
from test_candidate_runtime_execution import _install_candidate_dataflows


@pytest.fixture
def fresh_bound_inputs(candidate_payload, tmp_path, monkeypatch):
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    context, request, flows = request_for_prices(
        candidate_payload, tmp_path, monkeypatch, daily, flow=[0.1, 0.8, 0.8, 0.1, 0.0, 0.0],
    )
    data = _prepare_backtest_execution_data(
        repository_root=tmp_path, symbol="588080.SH", asset_type="etf",
        start=sessions[1].date(), end=sessions[-1].date(), dataflows=flows,
        intraday_frequencies=("30m",),
    )
    return prepare_request(context, replace(request, execution_data=data)), flows


@pytest.fixture
def bound_inputs(request, tmp_path, frozen_seed_root):
    """Each tamper starts with its own copy of publicly prepared, authentic inputs."""
    from czsc_trader.research_tools._evaluation_workers import pack
    from evaluation_seed_support import relocate_request, restored_context

    seed = frozen_seed_root / "bound-execution-inputs"
    data = frozen_seed_root / "bound-execution-inputs.pkl"
    if not seed.exists():
        evaluation, _ = request.getfixturevalue("fresh_bound_inputs")
        data.write_bytes(pack(evaluation))
        shutil.copytree(evaluation.repository_root, seed)
    root = tmp_path / "bound-repo"
    shutil.copytree(seed, root)
    evaluation = relocate_request(pickle.loads(data.read_bytes()), root)
    return evaluation, restored_context(root)


@pytest.mark.parametrize("table", ["adjusted_daily", "execution_daily", "execution_intraday"])
def test_modified_execution_dataframe_is_rejected_before_strategy_computation(bound_inputs, table):
    request, context = bound_inputs
    data = request.execution_data
    getattr(data, table).loc[0, "close"] += 1.0
    with pytest.raises(RuntimeError, match=f"^execution dataframe differs from bound inputs: {table}$"):
        context.evaluation.evaluate(request)


@pytest.mark.parametrize("field, value, error_type, reason", [
    ("fingerprint", "0" * 64, RuntimeError, "execution data fingerprint differs from bound inputs"),
    ("symbol", "518880.SH", ValueError, "formal replay requires matching market execution rules"),
    ("asset_type", "stock", ValueError, "market suspension policy differs from instrument"),
    ("prepared", None, RuntimeError, "execution input differs from bound preparation: price_limits"),
])
def test_execution_identity_must_match_the_prepared_selection(bound_inputs, field, value, error_type, reason):
    request, context = bound_inputs
    if field == "prepared":
        value = replace(request.execution_data.prepared, preparation_id=uuid4())
    request = replace(request, execution_data=replace(request.execution_data, **{field: value}))
    with pytest.raises(error_type, match=f"^{reason}$"):
        context.evaluation.evaluate(request)


def test_unchanged_bound_execution_tables_remain_replayable(bound_inputs):
    request, context = bound_inputs
    data = request.execution_data
    minute = data.requests["execution_30m"]
    assert minute.dataset is Dataset.ETF_UNADJUSTED_INTRADAY
    assert minute.start == data.evaluation_start.date().isoformat()
    assert minute.end == data.evaluation_end.date().isoformat()
    daily = data.requests["adjusted_daily"]
    assert daily.start == "2026-09-14"  # One prior signal session, no fixed calendar-day history.
    result = context.evaluation.evaluate(request)
    assert len(result.runs) == 1
    assert result.execution_data.fingerprint == data.fingerprint
    assert not result.runs[0].signals.decisions.empty


def test_foreign_space_reference_is_rejected_without_repreparing(bound_inputs, monkeypatch):
    request, context = bound_inputs
    flows = context.data
    data = request.execution_data

    def copy_bound_input(request):
        result = flows.fetch(request, prepared=data.prepared)
        assert result.ready
        return result.dataframe, dict(result.identity.metadata)

    foreign = Dataflows(
        base_dir=request.repository_root, space=DataSpace(Path("data/research")),
        providers=ProviderConfig(bindings={
            request.dataset: ProviderBinding("synthetic", "v1", copy_bound_input)
            for request in data.requests.values()
        }),
    )
    prepared = foreign.prepare(tuple(data.requests.values()), policy=PreparePolicy.REUSE)
    assert prepared.ready
    assert prepared.reference.space_id != data.prepared.space_id
    request = replace(request, execution_data=replace(data, prepared=prepared.reference))

    def forbidden(*args, **kwargs):
        pytest.fail("foreign input bindings must fail before preparing replacement data")

    monkeypatch.setattr(flows, "prepare", forbidden)
    with pytest.raises(ValueError, match="another data space"):
        context.evaluation.evaluate(request)


@pytest.mark.parametrize("entry_order_type", ["MARKET", "LIMIT"])
def test_public_backtest_prepares_execution_and_benchmark_requirements(
    candidate_payload, tmp_path, monkeypatch, entry_order_type,
):
    from czsc_trader.application import RepositoryContext, run_backtest, create_experiment, ExperimentRequest
    from czsc_trader.research_tools.context import ResearchContext, ResearchBatchRef
    from strategy_runtime import StrategyRuntime
    from czsc_trader.backtesting.service import BacktestRequest
    from czsc_trader.research_tools import (
        EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark,
        NextOpenBuyHold,
    )

    payload, source = candidate_payload
    payload["parameters"]["entry_order_type"] = entry_order_type
    sessions = pd.bdate_range("2026-08-10", periods=26)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    features = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8] * 13})
    flows = _install_candidate_dataflows(monkeypatch, features, daily, base_dir=tmp_path)
    calls = []
    prepare = flows.prepare

    def record(requests, *, policy):
        calls.extend(requests)
        return prepare(requests, policy=policy)

    monkeypatch.setattr(flows, "prepare", record)
    prepared_data = []

    def record_execution(**kwargs):
        value = _prepare_backtest_execution_data(**kwargs)
        prepared_data.append(value)
        return value

    monkeypatch.setattr("czsc_trader.backtesting.service._prepare_backtest_execution_data", record_execution)
    (tmp_path / "src" / "czsc_trader").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='execution-requirements'\n", encoding="utf-8")
    repository = RepositoryContext.discover(tmp_path, explicit_root=tmp_path)
    context = ResearchContext(ResearchBatchRef("S900"), repository, flows, StrategyRuntime(dataflows=flows),
                              EvaluationAccess(dataflows=flows, strategy_id="S900"))
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    result = run_backtest(
        context, candidate,
        BacktestRequest("588080.SH", "etf", sessions[20].date(), sessions[-1].date(), 100_000, 100),
    )
    assert result.manifest["audit"]["status"] == "PASS"
    minutes = [item for item in calls if item.frequency in {"5m", "30m"}]
    assert not minutes  # Daily-range LIMIT fills need no minute observations.
    adjusted = [item for item in calls if item.dataset is Dataset.ETF_OHLCV]
    assert min(item.start for item in adjusted) == sessions[0].date().isoformat()
    # The same authenticated data may include longer benchmark than execution history.
    data = prepared_data[0]
    assert len(data.adjusted_daily) == 26 and len(data.execution_daily) == 7
    experiment = create_experiment(context, ExperimentRequest("Execution requirements",
        "Verify public evaluation after backtest preparation", sessions[-1].date()))
    evaluation = context.evaluation.evaluate(EvaluationRequest(
        tmp_path, experiment.experiment_id, candidate,
        {"candidate_id": candidate.reference_id,
         "source_files": payload["runtime"]["source_files"],
         "implementation_sha256": payload["runtime"]["source_sha256"]},
        "588080.SH", "etf", (EvaluationWindow("full", sessions[20].date(), sessions[-1].date()),),
        sessions[-1].date(), 100_000, (EvaluationCost("zero_cost", 0.0),), data,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),
    ))
    assert len(evaluation.runs) == 1


def test_limit_execution_rejects_tampered_bound_minute_prices(bound_inputs):
    request, context = bound_inputs
    data = request.execution_data
    request = replace(request, execution_data=replace(data, execution_intraday=data.execution_intraday.iloc[:0]))
    with pytest.raises(RuntimeError, match="^execution dataframe differs from bound inputs: execution_intraday$"):
        context.evaluation.evaluate(request)
