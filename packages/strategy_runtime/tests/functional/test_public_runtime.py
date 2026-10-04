from __future__ import annotations

import json
from datetime import date, datetime
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataflows, Dataset, DataSpace, ProviderConfig, ProviderBinding, PreparePolicy
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
from strategy_runtime.prepare_cli import main as prepare_main


ROOT = Path(__file__).resolve().parents[4]
ZONE = ZoneInfo("Asia/Shanghai")


def test_prepare_cli_passes_explicit_space_and_credentials(tmp_path, monkeypatch, capsys) -> None:
    observed = {}
    def prepare(**kwargs):
        observed.update(kwargs)
        return {"prepared": True}
    monkeypatch.setattr("strategy_runtime.prepare_cli.prepare_runtime_data", prepare)
    exit_code = prepare_main([
        "--repo-root", str(tmp_path), "--data-dir", str(tmp_path / "context"),
        "--data-space", "data/market", "--symbol", "588080.SH",
        "--release", "S900-v1", "--trading-date", "2026-01-05",
    ])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert isinstance(observed["dataflows"], Dataflows)
    assert observed["policy"] is PreparePolicy.REUSE
    assert (tmp_path / "data/market/assets.sqlite3").is_file()


def _flows(tmp_path, *, flow_value=0.8) -> Dataflows:
    dates = pd.bdate_range(end="2026-09-02", periods=700)
    bars = pd.DataFrame(
        {
            "Date": dates,
            "Flow": flow_value,
            "TotalShare": 100000.0,
            "Open": pd.array([9.4] * len(dates), dtype="Float64"),
            "High": pd.array([9.5] * len(dates), dtype="Float64"),
            "Low": pd.array([9.3] * len(dates), dtype="Float64"),
            "Close": pd.array(
                [9.417734788764953] * len(dates), dtype="Float64"
            ),
            "Volume": pd.array([1000] * len(dates), dtype="Int64"),
            "Amount": pd.array([6000.0] * len(dates), dtype="Float64"),
        }
    )

    def market(request):
        frame = bars.loc[pd.to_datetime(bars["Date"]).between(request.start, request.end)].copy()
        return frame, {
            "vendor": "test",
            "adjustment": "none" if "unadjusted" in request.dataset else "hfq",
            "primary_key": ["Date"],
        }

    def calendar(request):
        days = pd.date_range(request.start, request.end)
        return pd.DataFrame({"Date": days, "IsOpen": (days.dayofweek < 5).astype(int)}), {
            "vendor": "test",
            "primary_key": ["Date"],
        }

    return Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({
        dataset: ProviderBinding("test", "1", provider) for dataset, provider in {
            Dataset.ETF_SHARE_SIZE: market, Dataset.ETF_OHLCV: market,
            Dataset.ETF_UNADJUSTED_DAILY: market, Dataset.TRADING_CALENDAR: calendar,
        }.items()
    }))


def test_public_runtime_prepares_and_plans_without_an_execution_channel(
    tmp_path, monkeypatch, runtime_candidate
) -> None:
    flows = _flows(tmp_path)
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
        strategy.plan_at(
            point=TradingPoint(trading_date, calculated_at),
            portfolio=PortfolioSnapshot(
                "s002-v1",
                "588080.SH",
                Decimal("50000"),
                Decimal("100000"),
                5900,
                7,
                calculated_at,
            ),
            state=ExecutionState(3, calculated_at, 5900),
        )

    prepared = strategy.prepare_data(policy=PreparePolicy.REUSE)
    plan = strategy.plan_at(
        point=TradingPoint(trading_date, calculated_at),
        portfolio=PortfolioSnapshot(
            "s002-v1",
            "588080.SH",
            Decimal("50000"),
            Decimal("100000"),
            5900,
            7,
            calculated_at,
        ),
        state=ExecutionState(3, calculated_at, 5900),
    )

    assert prepared.strategy.reference_id == "S900-C0001"
    for mode in SignalHistoryMode:
        history = strategy.inspect_signals(history_mode=mode)
        explicit = strategy.plan_at(
            point=TradingPoint(trading_date, calculated_at),
            portfolio=PortfolioSnapshot("s002-v1", "588080.SH", Decimal("50000"), Decimal("100000"), 5900, 7, calculated_at),
            state=ExecutionState(3, calculated_at, 5900), history_mode=mode,
        )
        assert explicit.target_position == history.loc[pd.Timestamp(explicit.signal_date), "target_position"]
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

    before_close = datetime(2026, 9, 2, 14, 59, tzinfo=ZONE)
    with pytest.raises(RuntimeContractError, match="precedes the signal-session close"):
        strategy.plan_at(
            point=TradingPoint(trading_date, before_close),
            portfolio=PortfolioSnapshot(
                "s002-v1",
                "588080.SH",
                Decimal("50000"),
                Decimal("100000"),
                5900,
                7,
                before_close,
            ),
            state=ExecutionState(3, before_close, 5900),
        )

    # Replay is bound explicitly and cannot contact a supplier.
    offline = Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({}))
    cached_instance = StrategyRuntime(ROOT / "strategies", dataflows=offline).create(
        StrategyInit(runtime_candidate, window, tmp_path / "replay"))
    cached = cached_instance.prepare_data(binding=strategy.input_binding)
    assert cached == prepared
    assert cached_instance.inspect_signals().equals(strategy.inspect_signals())
    assert cached_instance.prepare_data(binding=strategy.input_binding) == cached
    with pytest.raises(RuntimeContractError, match="already prepared"):
        cached_instance.prepare_data(policy=PreparePolicy.REFRESH)
    with pytest.raises(RuntimeContractError, match="another strategy"):
        StrategyRuntime(ROOT / "strategies", dataflows=offline).create(
            StrategyInit(replace(runtime_candidate, candidate_id="C0002"), window, tmp_path / "other")
        ).prepare_data(binding=strategy.input_binding)


def test_failed_preparation_is_not_exposed_as_prepared_data(tmp_path, runtime_candidate) -> None:
    strategy = StrategyRuntime(ROOT / "strategies").create(StrategyInit(
        runtime_candidate, TradableWindow(date(2026, 9, 3), date(2026, 9, 3)), tmp_path))
    with pytest.raises(RuntimeContractError, match="host-supplied Dataflows"):
        strategy.prepare_data(policy=PreparePolicy.REUSE)
    assert not (tmp_path / "input-bindings").exists()
    with pytest.raises(RuntimeContractError, match="call prepare_data"):
        strategy.inspect_signals()


def test_explicit_plan_binding_rejects_changed_calendar_and_forged_scope(tmp_path, runtime_candidate) -> None:
    flows = _flows(tmp_path)
    strategy = StrategyRuntime(ROOT / "strategies", dataflows=flows).create(StrategyInit(
        runtime_candidate, TradableWindow(date(2026, 9, 3), date(2026, 9, 3)), tmp_path))
    request = strategy.calendar_request()
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    plan = strategy.plan_inputs(flows.fetch(request, prepared=prepared.reference))
    batch = flows.prepare(tuple(plan.requests.values()), policy=PreparePolicy.REUSE)
    assert batch.ready
    binding = StrategyInputBinding(plan, batch.reference)
    corrupted = StrategyInputBinding(replace(plan, calendar_sha256="0" * 64), batch.reference)
    with pytest.raises(RuntimeContractError, match="bound calendar"):
        strategy.prepare_data(binding=corrupted)
    assert not (tmp_path / "input-bindings").exists()
    strategy.prepare_data(binding=binding)
    assert strategy.input_binding == binding


def test_session_depth_counts_days_before_first_signal() -> None:
    from strategy_runtime.validation import validate_history_depth
    frame = pd.DataFrame({"Date": pd.date_range("2026-01-01 09:31", periods=60, freq="min")})
    with pytest.raises(RuntimeContractError, match="insufficient history"):
        validate_history_depth("minute", 60, frame)


def test_refresh_keeps_old_binding_replayable_and_preserves_historical_files(tmp_path, runtime_candidate) -> None:
    from strategy_runtime import RuntimeExecutionError
    window = TradableWindow(date(2026, 9, 3), date(2026, 9, 3))
    context = tmp_path / "context"
    context.mkdir()
    historical = context / "prepared-data.json"
    historical.write_bytes(b"historical CSV manifest remains immutable")
    first = StrategyRuntime(dataflows=_flows(tmp_path)).create(StrategyInit(runtime_candidate, window, context))
    first_result = first.prepare_data(policy=PreparePolicy.REUSE)
    old_binding = StrategyInputBinding.from_mapping(first.input_binding.to_dict())
    newer = StrategyRuntime(dataflows=_flows(tmp_path, flow_value=0.1)).create(
        StrategyInit(runtime_candidate, window, context))
    newer_result = newer.prepare_data(policy=PreparePolicy.REFRESH)
    assert newer_result.data_identity != first_result.data_identity
    assert historical.read_bytes() == b"historical CSV manifest remains immutable"
    offline = Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({}))
    restored = StrategyRuntime(dataflows=offline).create(StrategyInit(runtime_candidate, window, context))
    assert restored.prepare_data(binding=old_binding) == first_result
    pd.testing.assert_frame_equal(restored.inspect_signals(), first.inspect_signals())
    wrong_space = _flows(tmp_path / "other")
    mismatched = StrategyRuntime(dataflows=wrong_space).create(
        StrategyInit(runtime_candidate, window, tmp_path / "bad-context"))
    with pytest.raises(RuntimeExecutionError, match="another data space"):
        mismatched.prepare_data(binding=old_binding)
    assert not (tmp_path / "bad-context").exists()
