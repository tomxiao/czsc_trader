"""Reject mutable execution tables that no longer match their DFLS binding."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from dataflows import Dataflows, Dataset, DataSpace, PreparePolicy, ProviderBinding, ProviderConfig

import pandas as pd
import pytest
from strategy_runtime import RuntimeContractError, StrategyCandidate, canonical_sha256

from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
from czsc_trader.backtesting.models import StrategyIdentity, StrategySnapshot
from czsc_trader.backtesting.srt_bridge import build_srt_signal_replay, prepare_srt_input_binding
from test_candidate_runtime_execution import _install_candidate_dataflows


@pytest.fixture
def bound_inputs(candidate_payload, tmp_path, monkeypatch):
    payload, source = candidate_payload
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    features = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0.0, 0.0]})
    flows = _install_candidate_dataflows(monkeypatch, features, daily, base_dir=tmp_path)
    data = _prepare_backtest_execution_data(
        repository_root=tmp_path, symbol="588080.SH", asset_type="etf",
        start=sessions[1].date(), end=sessions[-1].date(), dataflows=flows,
        intraday_frequencies=("30m",),
    )
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    snapshot = StrategySnapshot(
        StrategyIdentity("CANDIDATE", candidate.reference_id, "synthetic"),
        candidate.runtime_identity_sha256, canonical_sha256(payload), payload, runtime_root=source,
    )
    arguments = dict(snapshot=snapshot, execution_data=data, start=sessions[1],
                     end=sessions[-1], repository_root=tmp_path, dataflows=flows)
    binding = prepare_srt_input_binding(**arguments)
    return arguments, binding


@pytest.mark.parametrize("table", ["adjusted_daily", "execution_daily", "execution_intraday"])
def test_modified_execution_dataframe_is_rejected_before_strategy_computation(bound_inputs, table):
    arguments, binding = bound_inputs
    data = arguments["execution_data"]
    getattr(data, table).loc[0, "close"] += 1.0
    with pytest.raises(RuntimeContractError, match=f"dataframe differs.*{table}"):
        build_srt_signal_replay(**arguments, input_binding=binding)


@pytest.mark.parametrize("field, value", [("fingerprint", "0" * 64), ("symbol", "518880.SH"),
                                         ("asset_type", "stock"), ("prepared", None)])
def test_execution_identity_must_match_the_prepared_selection(bound_inputs, field, value):
    arguments, binding = bound_inputs
    if field == "prepared":
        value = replace(arguments["execution_data"].prepared, preparation_id=uuid4())
    arguments["execution_data"] = replace(arguments["execution_data"], **{field: value})
    with pytest.raises((RuntimeContractError, ValueError)):
        build_srt_signal_replay(**arguments, input_binding=binding)


def test_unchanged_bound_execution_tables_remain_replayable(bound_inputs):
    arguments, binding = bound_inputs
    data = arguments["execution_data"]
    minute = data.requests["execution_30m"]
    assert minute.dataset is Dataset.ETF_UNADJUSTED_INTRADAY
    assert minute.start == data.evaluation_start.date().isoformat()
    assert minute.end == data.evaluation_end.date().isoformat()
    daily = data.requests["adjusted_daily"]
    assert daily.start == "2026-09-14"  # One prior signal session, no fixed calendar-day history.
    instance, signals = build_srt_signal_replay(**arguments, input_binding=binding)
    assert instance.input_binding == binding
    assert not signals.decisions.empty


def test_foreign_space_reference_is_rejected_without_repreparing(bound_inputs, monkeypatch):
    arguments, binding = bound_inputs
    data, flows = arguments["execution_data"], arguments["dataflows"]

    def copy_bound_input(request):
        result = flows.fetch(request, prepared=data.prepared)
        assert result.ready
        return result.dataframe, dict(result.identity.metadata)

    foreign = Dataflows(
        base_dir=arguments["repository_root"], space=DataSpace(Path("data/research")),
        providers=ProviderConfig(bindings={
            request.dataset: ProviderBinding("synthetic", "v1", copy_bound_input)
            for request in data.requests.values()
        }),
    )
    prepared = foreign.prepare(tuple(data.requests.values()), policy=PreparePolicy.REUSE)
    assert prepared.ready
    assert prepared.reference.space_id != data.prepared.space_id
    arguments["execution_data"] = replace(data, prepared=prepared.reference)

    def forbidden(*args, **kwargs):
        pytest.fail("foreign input bindings must fail before preparing replacement data")

    monkeypatch.setattr(flows, "prepare", forbidden)
    with pytest.raises(RuntimeContractError, match="execution input differs"):
        prepare_srt_input_binding(**arguments)
    with pytest.raises(RuntimeContractError, match="execution input differs"):
        build_srt_signal_replay(**arguments, input_binding=binding)


@pytest.mark.parametrize("entry_order_type", ["MARKET", "LIMIT"])
def test_public_backtest_prepares_execution_and_benchmark_requirements(
    candidate_payload, tmp_path, monkeypatch, entry_order_type,
):
    from czsc_trader.application import RepositoryContext, run_backtest
    from czsc_trader.backtesting.service import BacktestRequest
    from czsc_trader.research_tools import (
        EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark,
        NextOpenBuyHold, evaluate_strategy,
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
    context = RepositoryContext.discover(tmp_path, explicit_root=tmp_path)
    candidate = StrategyCandidate("S900", "C0001", payload, source)
    result = run_backtest(
        context, candidate,
        BacktestRequest("588080.SH", "etf", sessions[20].date(), sessions[-1].date(), 100_000, 100),
        run_date=sessions[-1].date(),
    )
    assert result.status == "PASS"
    minutes = [item for item in calls if item.frequency in {"5m", "30m"}]
    if entry_order_type == "MARKET":
        assert not minutes
    else:
        assert minutes
        assert all(item.dataset is Dataset.ETF_UNADJUSTED_INTRADAY for item in minutes)
        assert all(item.start == sessions[20].date().isoformat() for item in minutes)
    adjusted = [item for item in calls if item.dataset is Dataset.ETF_OHLCV]
    assert min(item.start for item in adjusted) == sessions[0].date().isoformat()
    # The same authenticated data may include longer benchmark than execution history.
    data = prepared_data[0]
    assert len(data.adjusted_daily) == 26 and len(data.execution_daily) == 7
    evaluation = evaluate_strategy(EvaluationRequest(
        tmp_path, "synthetic", candidate,
        {"candidate_id": candidate.reference_id,
         "source_files": payload["runtime"]["source_files"],
         "implementation_sha256": payload["runtime"]["source_sha256"]},
        "588080.SH", "etf", (EvaluationWindow("full", sessions[20].date(), sessions[-1].date()),),
        sessions[-1].date(), 100_000, (EvaluationCost("zero_cost", 0.0),), data,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),
    ))
    assert len(evaluation.runs) == 1


def test_limit_execution_rejects_missing_minute_prices(bound_inputs):
    arguments, binding = bound_inputs
    data = arguments["execution_data"]
    arguments["execution_data"] = replace(data, execution_intraday=data.execution_intraday.iloc[:0])
    with pytest.raises(ValueError, match="no required 30m"):
        build_srt_signal_replay(**arguments, input_binding=binding)
