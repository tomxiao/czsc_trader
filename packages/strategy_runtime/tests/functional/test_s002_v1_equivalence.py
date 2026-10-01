from __future__ import annotations

from strategy_runtime import ExecutionOutcomeStatus

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataflows, Dataset

from strategy_runtime import (
    ExecutionCapabilities,
    ExecutionOutcome,
    ExecutionState,
    OrderType,
    PortfolioSnapshot,
    RuntimeContractError,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    TradableWindow,
    TradingPoint,
)


ROOT = Path(__file__).resolve().parents[4]
BASELINE_PATH = ROOT / "packages/strategy_runtime/tests/fixtures/s002_v1_equivalence.json"
ZONE = ZoneInfo("Asia/Shanghai")
WINDOW = TradableWindow(date(2025, 3, 4), date(2025, 3, 12))


def _baseline() -> dict[str, object]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _release() -> StrategyRelease:
    raw = json.loads(
        (ROOT / "strategies/S002/versions/v1.json").read_text(encoding="utf-8")
    )
    return StrategyRelease.from_mapping(raw)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _synthetic_bars() -> pd.DataFrame:
    sessions = pd.bdate_range("2024-01-02", periods=330)
    closes = pd.Series(
        [10.0 + offset * 0.001 for offset in range(len(sessions))],
        index=sessions,
    )
    closes.iloc[300:303] = [9.8, 9.5, 9.1]
    opens = closes + 0.05
    return pd.DataFrame(
        {
            "Date": sessions,
            "Open": opens.to_numpy(),
            "High": (opens + 0.1).to_numpy(),
            "Low": (closes - 0.1).to_numpy(),
            "Close": closes.to_numpy(),
            "Volume": 1000.0,
            "Amount": (closes * 1000).to_numpy(),
        }
    )


def _flows(requests: list[object]) -> Dataflows:
    bars = _synthetic_bars()

    def market(request):
        requests.append(request)
        dates = pd.to_datetime(bars["Date"])
        frame = bars.loc[dates.between(request.start, request.end)].copy()
        return frame, {
            "vendor": "s002-equivalence",
            "adjustment": "none" if "unadjusted" in request.dataset else "hfq",
            "primary_key": ["Date"],
        }

    def calendar(request):
        requests.append(request)
        days = pd.date_range(request.start, request.end)
        return pd.DataFrame(
            {"Date": days, "IsOpen": (days.dayofweek < 5).astype(int)}
        ), {"vendor": "s002-equivalence", "primary_key": ["Date"]}

    return Dataflows(
        {
            Dataset.ETF_OHLCV.value: market,
            Dataset.ETF_UNADJUSTED_DAILY.value: market,
            Dataset.TRADING_CALENDAR.value: calendar,
        }
    )


def _prepared_instance(tmp_path, monkeypatch):
    requests: list[object] = []
    flows = _flows(requests)
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: flows)
    instance = StrategyRuntime(ROOT / "strategies").create(
        StrategyInit(_release(), WINDOW, tmp_path)
    )
    instance.prepare_data()
    return instance, requests


def _input_contract(definition) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "dataset": item.dataset,
            "subject": item.subject,
            "frequency": item.frequency,
            "lookback_sessions": item.lookback_sessions,
            "cutoff_rule": item.cutoff_rule.value,
            "maximum_staleness_days": item.maximum_staleness_days,
        }
        for item in definition.inputs.requirements
    ]


def _decision_contract(definition) -> dict[str, object]:
    return asdict(definition.decision)


def _plan_projection(plan) -> dict[str, object]:
    return {
        "signal_date": plan.signal_date.isoformat(),
        "trading_date": plan.trading_date.isoformat(),
        "target_position": plan.target_position,
        "action": plan.action,
        "actual_quantity": plan.actual_quantity,
        "target_quantity": plan.target_quantity,
        "cycle_target_quantity": plan.cycle_target_quantity,
        "plan_mode": plan.plan_mode,
        "orders": [
            {
                "side": order.side.value,
                "quantity": order.quantity,
                "order_type": order.order_type.value,
                "limit_price": None
                if order.limit_price is None
                else str(order.limit_price),
            }
            for order in plan.orders
        ],
        "evidence": dict(plan.evidence),
    }


class _DeterministicExecutor:
    def __init__(self) -> None:
        self._cash = Decimal("100000")
        self._quantity = 0
        self._revision = 0
        self._cycle_target: int | None = None
        self.plans: list[dict[str, object]] = []

    @property
    def capabilities(self) -> ExecutionCapabilities:
        return ExecutionCapabilities((OrderType.LIMIT, OrderType.MARKET))

    def snapshot(self, point: TradingPoint):
        return (
            PortfolioSnapshot(
                "s002-equivalence",
                "510500.SH",
                self._cash,
                self._cash + Decimal(self._quantity) * Decimal("10"),
                self._quantity,
                self._revision,
                point.calculation_time,
            ),
            ExecutionState(
                self._revision,
                point.calculation_time,
                self._cycle_target,
            ),
        )

    def execute(self, plan):
        self.plans.append(_plan_projection(plan))
        for order in plan.orders:
            price = order.limit_price or plan.references.execution_price
            value = Decimal(order.quantity) * price
            if order.side.value == "BUY":
                self._cash -= value
                self._quantity += order.quantity
                self._cycle_target = plan.cycle_target_quantity
            else:
                self._cash += value
                self._quantity -= order.quantity
                if self._quantity == 0:
                    self._cycle_target = None
        self._revision += 1
        portfolio, state = self.snapshot(
            TradingPoint(plan.trading_date, plan.generated_at)
        )
        return ExecutionOutcome(plan.plan_identity, portfolio, state, ExecutionOutcomeStatus.SETTLED)

    def finish(self):
        return tuple(self.plans)


def test_frozen_formal_execution_evidence_is_immutable() -> None:
    baseline = _baseline()["formal_execution_evidence"]
    root = ROOT / baseline["directory"]
    for name, expected in baseline["files"].items():
        path = root / name
        assert _file_sha256(path) == expected["sha256"]
        assert len(pd.read_csv(path)) == expected["rows"]

    summary = json.loads((root / "execution_compatibility.json").read_text(encoding="utf-8"))
    counts = baseline["semantic_counts"]
    for name, expected in counts.items():
        if name == "closed_trades":
            actual = summary["formal_execution_metrics"][name]
        else:
            actual = summary[name]
        assert actual == expected
    assert summary["target_positions_identical"] is True
    assert summary["se_replay_audit"]["status"] == "PASS"

    decisions = pd.read_csv(root / "decisions.csv")
    changes = decisions["target_position"].diff()
    assert int(changes.eq(1).sum()) == counts["entry_signals"]
    assert int(changes.eq(-1).sum()) == counts["exit_signals"]
    orders = pd.read_csv(root / "orders.csv")
    buys = orders.loc[orders["side"].eq("BUY")]
    sells = orders.loc[orders["side"].eq("SELL")]
    assert len(buys) == counts["buy_orders"]
    assert int(buys["status"].eq("FILLED").sum()) == counts["buy_orders_filled"]
    assert int(buys["status"].eq("UNFILLED").sum()) == counts["buy_orders_unfilled"]
    assert len(sells) == counts["sell_orders"]
    assert int(sells["status"].eq("FILLED").sum()) == counts["sell_orders_filled"]


def test_runtime_definition_preserves_frozen_calculation_contract() -> None:
    baseline = _baseline()
    definition = StrategyRuntime(ROOT / "strategies").describe(_release())

    assert definition.release_id == baseline["strategy_reference"]
    assert definition.release_hash == baseline["release_hash"]
    assert definition.runtime_sha256 == baseline["resigned_runtime_sha256"]
    assert (
        definition.implementation.source_sha256
        == baseline["resigned_implementation_sha256"]
    )
    assert _input_contract(definition) == baseline["calculation_contract"]["inputs"]
    assert _decision_contract(definition) == baseline["calculation_contract"]["decision"]


def test_preparation_derives_the_frozen_s002_scope(tmp_path, monkeypatch) -> None:
    instance, requests = _prepared_instance(tmp_path, monkeypatch)
    by_dataset = {request.dataset: request for request in requests}

    adjusted = by_dataset[Dataset.ETF_OHLCV.value]
    execution = by_dataset[Dataset.ETF_UNADJUSTED_DAILY.value]
    calendar = by_dataset[Dataset.TRADING_CALENDAR.value]
    assert (
        adjusted.symbol,
        adjusted.start,
        adjusted.end,
        adjusted.required_cutoff,
    ) == ("510500.SH", "2024-01-09", "2025-03-11", "2025-03-11")
    assert (
        execution.symbol,
        execution.start,
        execution.end,
        execution.required_cutoff,
    ) == ("510500.SH", "2025-03-03", "2025-03-11", "2025-03-11")
    assert (
        calendar.symbol,
        calendar.start,
        calendar.end,
        calendar.required_cutoff,
    ) == ("SSE", "2023-07-13", "2025-04-01", "2025-04-01")
    assert instance.inspect_signals().index.max() == pd.Timestamp("2025-03-11")


def test_s002_signal_and_state_machine_match_the_legacy_behavior(
    tmp_path, monkeypatch
) -> None:
    instance, _ = _prepared_instance(tmp_path, monkeypatch)
    history = instance.inspect_signals()
    actual = history.loc[
        pd.Timestamp("2025-03-03") : pd.Timestamp("2025-03-11"),
        ["entry_transition", "held_sessions", "action", "target_position"],
    ].reset_index()
    actual["date"] = actual["date"].dt.strftime("%Y-%m-%d")

    expected = pd.DataFrame(
        [
            ["2025-03-03", True, 0, "ENTER", 1.0],
            ["2025-03-04", False, 1, "HOLD_POSITION", 1.0],
            ["2025-03-05", False, 2, "HOLD_POSITION", 1.0],
            ["2025-03-06", False, 3, "HOLD_POSITION", 1.0],
            ["2025-03-07", False, 4, "HOLD_POSITION", 1.0],
            ["2025-03-10", False, 5, "EXIT_TIME", 0.0],
            ["2025-03-11", False, 0, "HOLD_CASH", 0.0],
        ],
        columns=["date", "entry_transition", "held_sessions", "action", "target_position"],
    )
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)


def test_s002_window_starts_with_empty_position_state(tmp_path, monkeypatch) -> None:
    requests: list[object] = []
    monkeypatch.setattr(
        "strategy_runtime.preparation.Dataflows", lambda: _flows(requests)
    )
    window = TradableWindow(date(2025, 3, 5), date(2025, 3, 6))
    instance = StrategyRuntime(ROOT / "strategies").create(
        StrategyInit(_release(), window, tmp_path)
    )
    instance.prepare_data()

    window_history = instance.inspect_signals()
    frames = {
        name: result.dataframe
        for name, result in instance._prepared_data._inputs.results.items()
    }
    full_history = instance._algorithm.calculate_history(
        frames, pd.DatetimeIndex(instance._prepared_data.calculation_dates())
    )

    assert full_history.loc[pd.Timestamp("2025-03-04"), "action"] == "HOLD_POSITION"
    assert full_history.loc[pd.Timestamp("2025-03-04"), "held_sessions"] == 1
    assert window_history.loc[pd.Timestamp("2025-03-04"), "action"] == "ENTER"
    assert window_history.loc[pd.Timestamp("2025-03-04"), "held_sessions"] == 0


def test_srt_rejects_incomplete_window_history(tmp_path, monkeypatch) -> None:
    instance, _ = _prepared_instance(tmp_path, monkeypatch)
    original = instance._algorithm.calculate_window_history

    def incomplete(inputs, sessions):
        return original(inputs, sessions).iloc[:-1]

    monkeypatch.setattr(instance._algorithm, "calculate_window_history", incomplete)

    with pytest.raises(
        RuntimeContractError,
        match="history differs from requested evaluation sessions",
    ):
        instance.inspect_signals()


def test_single_window_plans_equal_continuous_window_replay(tmp_path, monkeypatch) -> None:
    instance, _ = _prepared_instance(tmp_path, monkeypatch)
    continuous = _DeterministicExecutor()
    continuous_result = instance.run_window(executor=continuous)

    stepwise = _DeterministicExecutor()
    for trading_date in pd.bdate_range(WINDOW.start, WINDOW.end).date:
        signal_date = max(
            value for value in pd.bdate_range("2024-01-02", trading_date).date
            if value < trading_date
        )
        point = TradingPoint(
            trading_date,
            datetime.combine(
                signal_date,
                datetime.min.time().replace(hour=20, minute=31),
                tzinfo=ZONE,
            ),
        )
        portfolio, state = stepwise.snapshot(point)
        plan = instance.plan_at(point=point, portfolio=portfolio, state=state)
        stepwise.execute(plan)

    assert tuple(stepwise.plans) == continuous_result
    assert [item["action"] for item in continuous_result] == [
        "BUY",
        "HOLD",
        "HOLD",
        "HOLD",
        "HOLD",
        "SELL",
        "WAIT",
    ]
    assert [item["target_position"] for item in continuous_result] == [
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.0,
        0.0,
    ]
    assert [item["actual_quantity"] for item in continuous_result] == [
        0,
        9700,
        9700,
        9700,
        9700,
        9700,
        0,
    ]
    assert [item["target_quantity"] for item in continuous_result] == [
        9700,
        9700,
        9700,
        9700,
        9700,
        0,
        0,
    ]
    assert [item["cycle_target_quantity"] for item in continuous_result] == [
        9700,
        9700,
        9700,
        9700,
        9700,
        9700,
        0,
    ]
    assert [item["orders"] for item in continuous_result] == [
        [
            {
                "side": "BUY",
                "quantity": 9700,
                "order_type": "LIMIT",
                "limit_price": "10.304",
            }
        ],
        [],
        [],
        [],
        [],
        [
            {
                "side": "SELL",
                "quantity": 9700,
                "order_type": "MARKET",
                "limit_price": "10.309",
            }
        ],
        [],
    ]
