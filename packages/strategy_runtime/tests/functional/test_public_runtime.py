from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataflows, Dataset
from strategy_runtime import (
    ExecutionState,
    PortfolioSnapshot,
    RuntimeContractError,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    TradableWindow,
    TradingPoint,
)
from strategy_runtime.prepare_cli import main as prepare_main


ROOT = Path(__file__).resolve().parents[4]
ZONE = ZoneInfo("Asia/Shanghai")


def _prepared_manifest(root: Path, window: TradableWindow) -> Path:
    return (
        root
        / "preparations"
        / f"{window.start:%Y%m%d}_{window.end:%Y%m%d}"
        / "prepared-data.json"
    )


def test_prepare_cli_loads_repository_dotenv_without_overriding_process_environment(
    tmp_path, monkeypatch, capsys,
) -> None:
    (tmp_path / ".env").write_text(
        "TUSHARE_TOKEN=repository-token\nSRT_TEST_SETTING=repository-value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TUSHARE_TOKEN", "process-token")
    monkeypatch.delenv("SRT_TEST_SETTING", raising=False)
    observed: dict[str, str] = {}

    def prepare(**kwargs):
        observed["repo_root"] = str(kwargs["repo_root"])
        observed["token"] = os.environ["TUSHARE_TOKEN"]
        observed["setting"] = os.environ["SRT_TEST_SETTING"]
        return {"prepared": True}

    monkeypatch.setattr("strategy_runtime.prepare_cli.prepare_runtime_data", prepare)

    exit_code = prepare_main([
        "--repo-root", str(tmp_path),
        "--data-dir", str(tmp_path / "data"),
        "--symbol", "510500.SH",
        "--release", "S002-v1",
        "--trading-date", "2026-01-05",
    ])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert observed == {
        "repo_root": str(tmp_path),
        "token": "process-token",
        "setting": "repository-value",
    }


def _release(strategy_id: str, version: str) -> StrategyRelease:
    payload = json.loads(
        (ROOT / f"strategies/{strategy_id}/versions/{version}.json").read_text(encoding="utf-8")
    )
    return StrategyRelease.from_mapping(payload)


def _flows() -> Dataflows:
    dates = pd.bdate_range(end="2026-09-02", periods=700)
    bars = pd.DataFrame(
        {
            "Date": dates,
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

    return Dataflows(
        {
            Dataset.ETF_OHLCV.value: market,
            Dataset.ETF_UNADJUSTED_DAILY.value: market,
            Dataset.TRADING_CALENDAR.value: calendar,
        }
    )


def test_public_runtime_prepares_and_plans_without_an_execution_channel(
    tmp_path, monkeypatch
) -> None:
    def unconfigured():
        pytest.fail("runtime must use the host-supplied Dataflows")

    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", unconfigured)
    trading_date = date(2026, 9, 3)
    strategy = StrategyRuntime(ROOT / "strategies", dataflows=_flows()).create(
        StrategyInit(
            _release("S002", "v1"),
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
                "510500.SH",
                Decimal("50000"),
                Decimal("100000"),
                5900,
                7,
                calculated_at,
            ),
            state=ExecutionState(3, calculated_at, 5900),
        )

    prepared = strategy.prepare_data()
    plan = strategy.plan_at(
        point=TradingPoint(trading_date, calculated_at),
        portfolio=PortfolioSnapshot(
            "s002-v1",
            "510500.SH",
            Decimal("50000"),
            Decimal("100000"),
            5900,
            7,
            calculated_at,
        ),
        state=ExecutionState(3, calculated_at, 5900),
    )

    assert prepared.strategy.reference_id == "S002-v1"
    assert prepared.available_through == date(2026, 9, 2)
    window = TradableWindow(trading_date, trading_date)
    manifest_path = _prepared_manifest(tmp_path, window)
    assert (tmp_path / "strategy-space.json").is_file()
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert all(
        value["identity"]["content_sha256"] == value["content_sha256"]
        for value in manifest["inputs"].values()
    )
    assert plan.strategy.reference_id == "S002-v1"
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
                "510500.SH",
                Decimal("50000"),
                Decimal("100000"),
                5900,
                7,
                before_close,
            ),
            state=ExecutionState(3, before_close, 5900),
        )

    monkeypatch.setattr(
        "strategy_runtime.preparation.Dataflows",
        lambda: (_ for _ in ()).throw(AssertionError("cache must be self-contained")),
    )
    cached = (
        StrategyRuntime(ROOT / "strategies")
        .create(
            StrategyInit(
                _release("S002", "v1"),
                TradableWindow(trading_date, trading_date),
                tmp_path,
            )
        )
        .prepare_data()
    )
    assert cached == prepared

    second_window = TradableWindow(date(2026, 9, 2), date(2026, 9, 2))
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: _flows())
    StrategyRuntime(ROOT / "strategies").create(
        StrategyInit(_release("S002", "v1"), second_window, tmp_path)
    ).prepare_data()
    assert _prepared_manifest(tmp_path, second_window).is_file()

    with pytest.raises(RuntimeContractError, match="another strategy"):
        StrategyRuntime(ROOT / "strategies").create(
            StrategyInit(_release("S001", "v1"), second_window, tmp_path)
        ).prepare_data()

    input_file = manifest_path.parent / next(iter(manifest["inputs"].values()))["file"]
    input_file.write_bytes(input_file.read_bytes() + b"changed")
    with pytest.raises(RuntimeContractError, match="file was modified"):
        StrategyRuntime(ROOT / "strategies").create(
            StrategyInit(
                _release("S002", "v1"),
                TradableWindow(trading_date, trading_date),
                tmp_path,
            )
        ).prepare_data()


def test_failed_preparation_is_not_exposed_as_prepared_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "strategy_runtime.preparation.Dataflows",
        lambda: (_ for _ in ()).throw(RuntimeError("DFLS unavailable")),
    )
    strategy = StrategyRuntime(ROOT / "strategies").create(
        StrategyInit(
            _release("S002", "v1"),
            TradableWindow(date(2026, 9, 3), date(2026, 9, 3)),
            tmp_path,
        )
    )
    with pytest.raises(RuntimeError, match="DFLS unavailable"):
        strategy.prepare_data()
    assert not (tmp_path / "preparations").exists()
    with pytest.raises(RuntimeContractError, match="call prepare_data"):
        strategy.inspect_signals()
