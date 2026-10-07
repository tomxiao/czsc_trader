from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import date, datetime
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import pandas as pd
import pytest
from dataflows import Dataflows, Dataset, DataSpace, ProviderConfig, ProviderBinding, PreparePolicy, canonical_frame_sha256
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence, verify_daily_sessions
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
    # The fixture strategy needs one prior session; five dates also cover the
    # latest-available cutoff scenario without unrelated multi-year history.
    dates = pd.bdate_range(end="2026-09-02", periods=5)
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
            "Amount": pd.array([9400.0] * len(dates), dtype="Float64"),
        }
    )

    def market(request):
        frame = bars.loc[pd.to_datetime(bars["Date"]).between(request.start, request.end)].copy()
        metadata = {
            "vendor": "test",
            "adjustment": "none" if "unadjusted" in request.dataset else "hfq",
            "primary_key": ["Date"],
        }
        if request.dataset in {Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY}:
            pro = SimpleNamespace(
                fund_basic=lambda **kwargs: pd.DataFrame({
                    "ts_code": [request.symbol], "list_date": [dates[0].strftime("%Y%m%d")],
                }),
                trade_cal=lambda **kwargs: pd.DataFrame({
                    "cal_date": pd.date_range(kwargs["start_date"], kwargs["end_date"]).strftime("%Y%m%d"),
                    "is_open": (pd.date_range(kwargs["start_date"], kwargs["end_date"]).dayofweek < 5).astype(int),
                }),
            )
            coverage = verify_daily_sessions(pro, request.symbol, frame,
                start=request.start, end=request.end)
            quality = build_quality_evidence(frame, expected_dates=coverage["expected_dates"])
            metadata.update(daily_session_coverage=coverage,
                ohlcv_quality_evidence=bind_quality_frame(quality, frame,
                    adjustment=metadata["adjustment"]))
            frame.attrs = {name: metadata[name] for name in
                           ("daily_session_coverage", "ohlcv_quality_evidence")}
        return frame, metadata

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
    admitted = []
    fetch = flows.fetch

    def observe_fetch(*args, **kwargs):
        result = fetch(*args, **kwargs)
        admitted.append((result.dataframe, deepcopy(result.dataframe.attrs),
                         canonical_frame_sha256(result.dataframe)))
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
    # Pricing copies exclude DFLS evidence; admitted inputs retain their evidence and identity.
    pricing = strategy._prepared_data._pricing
    assert pricing.adjusted_daily.attrs == pricing.execution_daily.attrs == {}
    assert any("ohlcv_quality_evidence" in attrs for _, attrs, _ in admitted)
    assert all(frame.attrs == attrs and canonical_frame_sha256(frame) == identity
               for frame, attrs, identity in admitted)
    # An exported price history is defensive; cached plan prices keep their exact identity.
    exported_prices = strategy.inspect_price_history()
    assert plan.references.signal_price == Decimal(str(
        exported_prices.loc[exported_prices.dt.eq(pd.Timestamp(plan.signal_date)), "close"].iloc[0]
    ))
    exported_prices.loc[:, "close"] = 99.0
    repeated = strategy.plan_at(
        point=TradingPoint(trading_date, calculated_at),
        portfolio=PortfolioSnapshot("s002-v1", "588080.SH", Decimal("50000"), Decimal("100000"), 5900, 7, calculated_at),
        state=ExecutionState(3, calculated_at, 5900),
    )
    assert repeated == plan

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


@pytest.fixture(scope="module")
def plan_binding_seed(frozen_seed_root, runtime_candidate_seed):
    """Publicly prepare valid immutable assets once for plan-tampering cases."""
    root = frozen_seed_root / "srt-plan-binding"
    flows = _flows(root)
    strategy = StrategyRuntime(ROOT / "strategies", dataflows=flows).create(StrategyInit(
        runtime_candidate_seed, TradableWindow(date(2026, 9, 3), date(2026, 9, 3)), root / "context"))
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


@pytest.mark.parametrize("corruption", ["calendar_sha256", "signal_dates", "calculation_dates"])
def test_explicit_plan_binding_rejects_changed_calendar_and_forged_scope(
    tmp_path, runtime_candidate, plan_binding_seed, corruption,
) -> None:
    assets, binding = plan_binding_seed
    shutil.copytree(assets, tmp_path / "assets")
    # Each case owns the database and context. No provider can repair or replace
    # a copied preparation, and the actual derived-plan authentication runs.
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({}))
    strategy = StrategyRuntime(ROOT / "strategies", dataflows=flows).create(StrategyInit(
        runtime_candidate, binding.plan.tradable_window, tmp_path / "context"))
    plan = binding.plan
    if corruption == "calendar_sha256":
        changed = replace(plan, calendar_sha256="0" * 64)
    elif corruption == "signal_dates":
        changed = replace(plan, signal_dates={date(2026, 9, 3): date(2026, 9, 1)})
    else:
        changed = replace(plan, calculation_dates=(date(2026, 9, 1), *plan.calculation_dates))
    if corruption != "calendar_sha256":
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


def test_latest_available_request_carries_source_freshness_into_preparation(
    tmp_path, runtime_candidate,
) -> None:
    from strategy_runtime import implementation_sha256

    descriptor = dict(runtime_candidate.payload["runtime"])
    source = runtime_candidate.source_root / descriptor["source_files"][0]
    source.write_text(source.read_text(encoding="utf-8").replace(
        "CutoffRule.SIGNAL_SESSION,", "CutoffRule.LATEST_AVAILABLE,\n                3,",
    ), encoding="utf-8")
    descriptor["source_sha256"] = implementation_sha256(
        tuple(descriptor["source_files"]), source_root=runtime_candidate.source_root,
    )
    candidate = replace(runtime_candidate, payload={**runtime_candidate.payload, "runtime": descriptor})
    flows = _flows(tmp_path)
    strategy = StrategyRuntime(dataflows=flows).create(StrategyInit(
        candidate, TradableWindow(date(2026, 9, 3), date(2026, 9, 3)), tmp_path / "context",
    ))
    request = strategy.calendar_request()
    calendars = flows.prepare((request,), policy=PreparePolicy.REUSE)
    plan = strategy.plan_inputs(flows.fetch(request, prepared=calendars.reference))
    assert plan.requests["market"].required_cutoff == "2026-08-30"
    assert plan.requests["market"].coverage.observations_through == "2026-09-02"
    batch = flows.prepare(tuple(plan.requests.values()), policy=PreparePolicy.REUSE)
    assert batch.ready
    prepared = strategy.prepare_data(binding=StrategyInputBinding(plan, batch.reference))
    assert prepared.available_through == date(2026, 9, 2)


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
