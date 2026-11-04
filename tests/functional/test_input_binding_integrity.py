"""Explicit historical execution binding rejects altered inputs before replay."""

from dataclasses import replace
from pathlib import Path
import pickle
import shutil
from uuid import uuid4

from dataflows import Dataflows, Dataset, DataSpace, PreparePolicy, ProviderBinding, ProviderConfig

import pandas as pd
import pytest
from strategy_runtime.errors import RuntimeContractError

from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
from public_backtest_support import request_for_prices
from historical_evaluation_support import prepare_historical
from czsc_trader.backtesting.srt_bridge import _validate_execution_binding


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
    return prepare_historical(context, replace(request, execution_data=data)), flows


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
    with pytest.raises(RuntimeContractError, match=f"^execution dataframe differs from bound inputs: {table}$"):
        _validate_execution_binding(context.data, request.execution_data, request.execution_data.prepared)


@pytest.mark.parametrize("field, value, error_type, reason", [
    ("fingerprint", "0" * 64, RuntimeContractError, "execution data fingerprint differs from bound inputs"),
    ("symbol", "518880.SH", RuntimeContractError, "execution input selection differs from instrument: price_limits"),
    ("asset_type", "stock", RuntimeContractError, "execution input list differs from its declared tables"),
    ("prepared", None, RuntimeContractError, "execution input differs from bound preparation: price_limits"),
])
def test_execution_identity_must_match_the_prepared_selection(bound_inputs, field, value, error_type, reason):
    request, context = bound_inputs
    if field == "prepared":
        value = replace(request.execution_data.prepared, preparation_id=uuid4())
    request = replace(request, execution_data=replace(request.execution_data, **{field: value}))
    with pytest.raises(error_type, match=f"^{reason}$"):
        _validate_execution_binding(context.data, request.execution_data, request.execution_data.prepared)


def test_unchanged_bound_execution_tables_remain_replayable(bound_inputs):
    request, context = bound_inputs
    data = request.execution_data
    minute = data.requests["execution_30m"]
    assert minute.dataset is Dataset.ETF_UNADJUSTED_INTRADAY
    assert minute.start == data.evaluation_start.date().isoformat()
    assert minute.end == data.evaluation_end.date().isoformat()
    daily = data.requests["adjusted_daily"]
    assert daily.start == "2026-09-14"  # One prior signal session, no fixed calendar-day history.
    assert _validate_execution_binding(context.data, data, data.prepared) is None


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
    with pytest.raises(RuntimeContractError, match="execution input differs from bound preparation"):
        _validate_execution_binding(context.data, request.execution_data, request.execution_data.prepared)


def test_limit_execution_rejects_tampered_bound_minute_prices(bound_inputs):
    request, context = bound_inputs
    data = request.execution_data
    request = replace(request, execution_data=replace(data, execution_intraday=data.execution_intraday.iloc[:0]))
    with pytest.raises(RuntimeContractError, match="^execution dataframe differs from bound inputs: execution_intraday$"):
        _validate_execution_binding(context.data, request.execution_data, request.execution_data.prepared)
