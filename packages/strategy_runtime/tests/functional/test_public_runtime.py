from __future__ import annotations
import json
import shutil
from copy import deepcopy
from datetime import date, datetime
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import pytest
from czsc_trader.application.ec_boundary import session_execution_plan
from execution_channels.serialization import from_record, to_record
from execution_channels.session_contracts import (
    PortfolioSnapshot as ChannelPortfolio,
    ExecutionState as ChannelState,
)
from dataflows import Dataflows, DataSpace, ProviderConfig, PreparePolicy, canonical_frame_sha256
from strategy_runtime import (
    ExecutionState,
    PortfolioSnapshot,
    RuntimeContractError,
    StrategyInit,
    StrategyInputBinding,
    StrategyRuntime,
    SignalHistoryMode,
    TradableWindow,
    TradingPoint,
)
from packages.strategy_runtime.tests.session_runtime_support import _flows

ROOT = Path(__file__).resolve().parents[4]
ZONE = ZoneInfo("Asia/Shanghai")


def test_SRT_11_C01_public_runtime_prepares_and_plans_without_an_execution_channel(
    tmp_path, monkeypatch, runtime_candidate
) -> None:
    flows = _flows(tmp_path)
    admitted = []
    fetch = flows.fetch

    def observe_fetch(*args, **kwargs):
        result = fetch(*args, **kwargs)
        admitted.append(
            (
                result.dataframe,
                deepcopy(result.dataframe.attrs),
                canonical_frame_sha256(result.dataframe),
            )
        )
        return result

    monkeypatch.setattr(flows, "fetch", observe_fetch)
    trading_date = date(2026, 9, 3)
    strategy = StrategyRuntime(ROOT / "strategies", dataflows=flows).create(
        StrategyInit(
            runtime_candidate,
            TradableWindow(trading_date, trading_date),
            tmp_path,
        )
    )
    calculated_at = datetime(2026, 9, 2, 22, 14, tzinfo=ZONE)
    with pytest.raises(RuntimeContractError, match="call prepare_data"):
        session_execution_plan(
            strategy.propose_at(point=TradingPoint(trading_date, calculated_at)),
            from_record(
                ChannelPortfolio,
                to_record(
                    PortfolioSnapshot(
                        "s002-v1",
                        "588080.SH",
                        Decimal("50000"),
                        Decimal("100000"),
                        5900,
                        7,
                        calculated_at,
                    )
                ),
            ),
            from_record(ChannelState, to_record(ExecutionState(3, calculated_at, 5900))),
        )

    prepared = strategy.prepare_data(policy=PreparePolicy.REUSE)
    plan = session_execution_plan(
        strategy.propose_at(point=TradingPoint(trading_date, calculated_at)),
        from_record(
            ChannelPortfolio,
            to_record(
                PortfolioSnapshot(
                    "s002-v1",
                    "588080.SH",
                    Decimal("50000"),
                    Decimal("100000"),
                    5900,
                    7,
                    calculated_at,
                )
            ),
        ),
        from_record(ChannelState, to_record(ExecutionState(3, calculated_at, 5900))),
    )

    assert prepared.strategy.reference_id == "S900-C0001"
    assert len(prepared.data_identity) == 64
    for mode in SignalHistoryMode:
        history = strategy.inspect_signals(history_mode=mode)
        explicit = session_execution_plan(
            strategy.propose_at(point=TradingPoint(trading_date, calculated_at), history_mode=mode),
            from_record(
                ChannelPortfolio,
                to_record(
                    PortfolioSnapshot(
                        "s002-v1",
                        "588080.SH",
                        Decimal("50000"),
                        Decimal("100000"),
                        5900,
                        7,
                        calculated_at,
                    )
                ),
            ),
            from_record(ChannelState, to_record(ExecutionState(3, calculated_at, 5900))),
        )
        assert (
            explicit.target_position
            == history.loc[pd.Timestamp(explicit.signal_date), "target_position"]
        )
        if mode is SignalHistoryMode.CONTINUOUS:
            assert explicit.plan_identity == plan.plan_identity
        history.loc[:, "target_position"] = 99
        assert strategy.inspect_signals(history_mode=mode).target_position.lt(99).all()
    with pytest.raises(RuntimeContractError, match="SignalHistoryMode"):
        strategy.inspect_signals(history_mode="WINDOW")
    assert prepared.available_through == date(2026, 9, 2)
    window = TradableWindow(trading_date, trading_date)
    manifest_path = tmp_path / "input-bindings" / f"{strategy.input_binding.identity}.json"
    assert manifest_path.is_file()
    assert b"\r" not in manifest_path.read_bytes()
    assert not tuple(tmp_path.rglob("*.csv.gz"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert StrategyInputBinding.from_mapping(manifest["binding"]) == strategy.input_binding
    assert plan.strategy.reference_id == "S900-C0001"
    assert plan.expected_portfolio_revision == 7
    assert plan.expected_state_revision == 3
    assert plan.actual_quantity == 5900
    assert plan.signal_identity != plan.plan_identity
    assert plan.trading_date == trading_date
    assert {order.order_type.value for order in plan.orders} <= {"LIMIT", "MARKET"}
    assert {leg.order.order_type.value for leg in plan.legs} <= {"LIMIT", "MARKET"}
    # Pricing copies exclude DFLS evidence; admitted inputs retain their evidence and identity.
    pricing = strategy._prepared_data._pricing
    assert pricing.adjusted_daily.attrs == pricing.execution_daily.attrs == {}
    assert any("ohlcv_quality_evidence" in attrs for _, attrs, _ in admitted)
    assert all(
        frame.attrs == attrs and canonical_frame_sha256(frame) == identity
        for frame, attrs, identity in admitted
    )
    # An exported price history is defensive; cached plan prices keep their exact identity.
    exported_prices = strategy.inspect_price_history()
    assert plan.references.signal_price == Decimal(
        str(
            exported_prices.loc[
                exported_prices.dt.eq(pd.Timestamp(plan.signal_date)), "close"
            ].iloc[0]
        )
    )
    exported_prices.loc[:, "close"] = 99.0
    repeated = session_execution_plan(
        strategy.propose_at(point=TradingPoint(trading_date, calculated_at)),
        from_record(
            ChannelPortfolio,
            to_record(
                PortfolioSnapshot(
                    "s002-v1",
                    "588080.SH",
                    Decimal("50000"),
                    Decimal("100000"),
                    5900,
                    7,
                    calculated_at,
                )
            ),
        ),
        from_record(ChannelState, to_record(ExecutionState(3, calculated_at, 5900))),
    )
    assert repeated == plan

    before_close = datetime(2026, 9, 2, 14, 59, tzinfo=ZONE)
    with pytest.raises(RuntimeContractError, match="precedes the signal-session close"):
        session_execution_plan(
            strategy.propose_at(point=TradingPoint(trading_date, before_close)),
            from_record(
                ChannelPortfolio,
                to_record(
                    PortfolioSnapshot(
                        "s002-v1",
                        "588080.SH",
                        Decimal("50000"),
                        Decimal("100000"),
                        5900,
                        7,
                        before_close,
                    )
                ),
            ),
            from_record(ChannelState, to_record(ExecutionState(3, before_close, 5900))),
        )

    # Replay is bound explicitly and cannot contact a supplier.
    offline = Dataflows(
        base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({})
    )
    cached_instance = StrategyRuntime(ROOT / "strategies", dataflows=offline).create(
        StrategyInit(runtime_candidate, window, tmp_path / "replay")
    )
    cached = cached_instance.prepare_data(binding=strategy.input_binding)
    assert cached == prepared
    assert cached_instance.inspect_signals().equals(strategy.inspect_signals())
    assert cached_instance.prepare_data(binding=strategy.input_binding) == cached
    with pytest.raises(RuntimeContractError, match="already prepared"):
        cached_instance.prepare_data(policy=PreparePolicy.REFRESH)
    with pytest.raises(RuntimeContractError, match="another strategy"):
        StrategyRuntime(ROOT / "strategies", dataflows=offline).create(
            StrategyInit(
                replace(runtime_candidate, candidate_id="C0002"), window, tmp_path / "other"
            )
        ).prepare_data(binding=strategy.input_binding)


def test_SRT_11_C03_failed_preparation_is_not_exposed_as_prepared_data(
    tmp_path, runtime_candidate
) -> None:
    strategy = StrategyRuntime(ROOT / "strategies").create(
        StrategyInit(
            runtime_candidate, TradableWindow(date(2026, 9, 3), date(2026, 9, 3)), tmp_path
        )
    )
    with pytest.raises(RuntimeContractError, match="host-supplied Dataflows"):
        strategy.prepare_data(policy=PreparePolicy.REUSE)
    assert not (tmp_path / "input-bindings").exists()
    with pytest.raises(RuntimeContractError, match="call prepare_data"):
        strategy.inspect_signals()


@pytest.fixture(scope="module")
def plan_binding_seed(frozen_seed_root, runtime_candidate_seed):
    """Publicly prepare valid immutable assets once for plan-tampering cases."""
    root = frozen_seed_root / "srt-plan-binding"
    flows = _flows(root)
    strategy = StrategyRuntime(ROOT / "strategies", dataflows=flows).create(
        StrategyInit(
            runtime_candidate_seed,
            TradableWindow(date(2026, 9, 3), date(2026, 9, 3)),
            root / "context",
        )
    )
    request = strategy.calendar_request()
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    plan = strategy.plan_inputs(flows.fetch(request, prepared=prepared.reference))
    for name, item in plan.requests.items():
        if name == plan.calendar_name:
            assert item.coverage is None
        else:
            assert item.coverage.minimum_sessions == 1
            assert item.coverage.observations_through == "2026-09-02"
            assert item.coverage.maximum_start_lag_days is None
    batch = flows.prepare(tuple(plan.requests.values()), policy=PreparePolicy.REUSE)
    assert batch.ready
    binding = StrategyInputBinding(plan, batch.reference)
    strategy.prepare_data(binding=binding)
    return root / "assets", binding


@pytest.mark.parametrize(
    "corruption",
    [
        "calendar_sha256",
        "calculation_dates",
    ],
    ids=["SRT-11-C04", "SRT-11-C05"],
)
def test_explicit_plan_binding_rejects_changed_calendar_and_forged_scope(
    tmp_path,
    runtime_candidate,
    plan_binding_seed,
    corruption,
) -> None:
    assets, binding = plan_binding_seed
    shutil.copytree(assets, tmp_path / "assets")
    # Each case owns the database and context. No provider can repair or replace
    # a copied preparation, and the actual derived-plan authentication runs.
    flows = Dataflows(
        base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({})
    )
    strategy = StrategyRuntime(ROOT / "strategies", dataflows=flows).create(
        StrategyInit(runtime_candidate, binding.plan.tradable_window, tmp_path / "context")
    )
    plan = binding.plan
    if corruption == "calendar_sha256":
        changed = replace(plan, calendar_sha256="0" * 64)
    elif corruption == "signal_dates":
        changed = replace(plan, signal_dates={date(2026, 9, 3): date(2026, 9, 1)})
    elif corruption == "calculation_dates":
        changed = replace(plan, calculation_dates=(date(2026, 9, 1), *plan.calculation_dates))
    else:
        request = plan.requests["flow"]
        requests = {
            **plan.requests,
            "flow": replace(request, coverage=replace(request.coverage, minimum_sessions=2)),
        }
        changed = replace(plan, requests=requests)
    if corruption in {"signal_dates", "calculation_dates"}:
        assert changed.calendar_sha256 == plan.calendar_sha256
        assert changed.requests == plan.requests
    corrupted = StrategyInputBinding(changed, binding.prepared)
    with pytest.raises(RuntimeContractError, match="bound calendar or calculation plan differs"):
        strategy.prepare_data(binding=corrupted)
    assert not (tmp_path / "context/input-bindings").exists()
    with pytest.raises(RuntimeContractError, match="call prepare_data"):
        strategy.inspect_signals()
    strategy.prepare_data(binding=binding)
    assert strategy.input_binding == binding


def test_SRT_11_C02_refresh_keeps_old_binding_replayable_and_preserves_historical_files(
    tmp_path, runtime_candidate
) -> None:
    from strategy_runtime import RuntimeExecutionError

    window = TradableWindow(date(2026, 9, 3), date(2026, 9, 3))
    context = tmp_path / "context"
    context.mkdir()
    historical = context / "prepared-data.json"
    historical.write_bytes(b"historical CSV manifest remains immutable")
    first = StrategyRuntime(dataflows=_flows(tmp_path)).create(
        StrategyInit(runtime_candidate, window, context)
    )
    first_result = first.prepare_data(policy=PreparePolicy.REUSE)
    old_binding = StrategyInputBinding.from_mapping(first.input_binding.to_dict())
    newer = StrategyRuntime(dataflows=_flows(tmp_path, flow_value=0.1)).create(
        StrategyInit(runtime_candidate, window, context)
    )
    newer_result = newer.prepare_data(policy=PreparePolicy.REFRESH)
    assert newer_result.data_identity != first_result.data_identity
    assert historical.read_bytes() == b"historical CSV manifest remains immutable"
    offline = Dataflows(
        base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({})
    )
    restored = StrategyRuntime(dataflows=offline).create(
        StrategyInit(runtime_candidate, window, context)
    )
    assert restored.prepare_data(binding=old_binding) == first_result
    pd.testing.assert_frame_equal(restored.inspect_signals(), first.inspect_signals())
    wrong_space = _flows(tmp_path / "other")
    mismatched = StrategyRuntime(dataflows=wrong_space).create(
        StrategyInit(runtime_candidate, window, tmp_path / "bad-context")
    )
    with pytest.raises(RuntimeExecutionError, match="another data space"):
        mismatched.prepare_data(binding=old_binding)
    assert not (tmp_path / "bad-context").exists()


def test_SRT_12_C02_prepared_batch_accounts_reuse_facts_without_supplier_or_storage_io(
    tmp_path,
    monkeypatch,
    runtime_candidate,
    plan_binding_seed,
):
    assets, binding = plan_binding_seed
    shutil.copytree(assets, tmp_path / "assets")
    flows = Dataflows(
        base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({})
    )
    strategy = StrategyRuntime(ROOT / "strategies", dataflows=flows).create(
        StrategyInit(
            runtime_candidate,
            TradableWindow(date(2026, 9, 3), date(2026, 9, 3)),
            tmp_path / "in-memory",
        )
    )
    strategy.prepare_data(binding=binding, persist=False)
    assert not (tmp_path / "in-memory" / "input-bindings").exists()
    with pytest.raises(RuntimeContractError, match="WINDOW history"):
        strategy.fork_for_replay(execution_policy=strategy.execution_policy)
    expected = strategy.inspect_signals()

    def forbidden(*args, **kwargs):
        pytest.fail("prepared account replay must not access suppliers or persist bindings")

    monkeypatch.setattr(flows, "fetch", forbidden)
    monkeypatch.setattr("strategy_runtime.strategy.save_prepared_inputs", forbidden)
    first = strategy.fork_for_replay(execution_policy=strategy.execution_policy)
    second = strategy.fork_for_replay(execution_policy=strategy.execution_policy)
    exported = first.inspect_signals()
    exported.loc[:, "target_position"] = 99.0
    pd.testing.assert_frame_equal(second.inspect_signals(), expected)
    pd.testing.assert_frame_equal(strategy.inspect_signals(), expected)
    assert first is not second and first.execution_policy == strategy.execution_policy
    with pytest.raises(RuntimeContractError, match="cannot calculate new history"):
        first.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS)


@pytest.fixture
def prepared_memory_strategy(tmp_path, runtime_candidate, plan_binding_seed):
    assets, binding = plan_binding_seed
    shutil.copytree(assets, tmp_path / "assets")
    flows = Dataflows(
        base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({})
    )
    strategy = StrategyRuntime(dataflows=flows).create(
        StrategyInit(runtime_candidate, binding.plan.tradable_window, tmp_path / "context")
    )
    result = strategy.prepare_data(binding=binding, persist=False)
    return strategy, result, tmp_path / "context"


def test_SRT_12_C01_nonpersistent_preparation_keeps_authentication(prepared_memory_strategy):
    strategy, result, context = prepared_memory_strategy
    assert result.available_through == date(2026, 9, 2)
    assert strategy.input_binding is not None and not (context / "input-bindings").exists()


def test_SRT_12_C03_uncomputed_mode_cannot_be_forked(prepared_memory_strategy):
    strategy, _, _ = prepared_memory_strategy
    with pytest.raises(RuntimeContractError, match="WINDOW history"):
        strategy.fork_for_replay(execution_policy=strategy.execution_policy)


def test_SRT_12_C04_fee_overlay_preserves_original_definition(prepared_memory_strategy):
    from strategy_runtime.models import ExecutionPolicy

    strategy, _, _ = prepared_memory_strategy
    strategy.inspect_signals()
    original = strategy.execution_policy
    settings = dict(original.settings)
    settings["capital"] = {**dict(settings["capital"]), "fee_rate": 0.002}
    alternate = ExecutionPolicy(original.policy_type, settings)
    fork = strategy.fork_for_replay(execution_policy=alternate)
    assert fork.execution_policy == alternate and strategy.execution_policy == original
    assert fork.definition == strategy.definition and fork.identity == strategy.identity
