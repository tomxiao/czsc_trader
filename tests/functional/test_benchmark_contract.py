"""Benchmark identity and frozen limit execution, without retired research entrypoints."""
from copy import deepcopy
from dataclasses import replace
import pandas as pd
import pytest
from dataflows import BarFrequency, MarketId, canonical_frame_sha256
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark, LimitBuyHold, NextOpenBuyHold
from czsc_trader.backtesting.benchmarks import BenchmarkWindow, replay_buyhold
from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.research_tools import ResearchExecutionSession
from account_parity_support import setup_account


def benchmark_inputs(root, daily, start_index=1):
    prices = daily.copy()
    prices["high"] = prices[["open", "close"]].max(axis=1)
    prices["low"] = prices[["open", "close"]].min(axis=1)
    data = BacktestExecutionData(root=root, symbol="588080.SH", asset_type="etf",
        adjusted_daily=prices.copy(), execution_daily=prices,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        fingerprint="a" * 64, cutoff=prices.dt.iloc[-1].date(),
        evaluation_sessions=pd.DatetimeIndex(prices.dt.iloc[start_index:]))
    return BenchmarkWindow(prices.dt.iloc[start_index], prices.dt.iloc[-1], .001), data


def test_limit_reservation_differs_from_next_open_and_preserves_inputs(tmp_path):
    sessions = pd.bdate_range("2025-02-05", periods=3)
    daily = pd.DataFrame({"dt": sessions, "open": [1.062] * 3, "close": [1.062, 1.062, 1.555]})
    window, data = benchmark_inputs(tmp_path, daily)
    contract = EvaluationBenchmark(LimitBuyHold(100, .003, .001, .1, 1000000))
    inputs = (data.adjusted_daily, data.execution_daily)
    originals = [(deepcopy(frame.attrs), canonical_frame_sha256(frame)) for frame in inputs]
    result = replay_buyhold(window, data, 1e6, benchmark=contract)
    assert result.execution.fills.iloc[0].quantity == 938000
    assert result.execution.orders.iloc[0].limit_price == 1.065
    assert result.account_daily.iloc[-1].cash == pytest.approx(2847.844)
    assert result.account_daily.iloc[-1].equity == pytest.approx(1461437.844)
    assert len(result.execution.fills) == 1
    assert result.execution.decisions.action.tolist() == ["BUY", "HOLD"]
    repeated = replay_buyhold(window, data, 1e6, benchmark=contract)
    assert repeated.metrics == result.metrics
    for name in ("decisions", "orders", "fills", "account_daily", "trades"):
        pd.testing.assert_frame_equal(getattr(result.execution, name), getattr(repeated.execution, name))
    for frame, (attrs, digest) in zip(inputs, originals, strict=True):
        assert frame.attrs == attrs and canonical_frame_sha256(frame) == digest
    next_open = replay_buyhold(window, data, 1e6, benchmark=EvaluationBenchmark(NextOpenBuyHold(100)))
    assert next_open.account_daily.iloc[-1].quantity == 940600


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lot_size": True},
        {"lot_size": 0},
        {"lot_size": 1},
        {"premium": float("nan")},
        {"premium": 0.1},
        {"price_tick": 0.0},
        {"maximum_order_quantity": 150},
    ],
)
def test_invalid_limit_contract_is_rejected_before_execution(kwargs):
    values = dict(
        lot_size=100,
        premium=0.003,
        price_tick=0.001,
        price_limit_ratio=0.1,
        maximum_order_quantity=1000000,
    )
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        LimitBuyHold(**values)


def test_contract_fingerprints_roundtrip_and_reject_implicit_defaults():
    next_open = EvaluationBenchmark(NextOpenBuyHold(lot_size=1))
    assert EvaluationBenchmark.from_dict(next_open.to_dict()) == next_open
    contract = EvaluationBenchmark(LimitBuyHold(100, 0.003, 0.001, 0.1, 1000000))
    assert EvaluationBenchmark.from_dict(contract.to_dict()) == contract
    for field, value in (
        ("premium", 0.004),
        ("lot_size", 200),
        ("maximum_order_quantity", 1000),
        ("price_tick", 0.01),
        ("price_limit_ratio", 0.2),
    ):
        assert (
            replace(contract, execution=replace(contract.execution, **{field: value})).fingerprint
            != contract.fingerprint
        )
    with pytest.raises(TypeError):
        EvaluationBenchmark()
    raw = contract.to_dict()
    raw["execution_version"] = "unknown"
    with pytest.raises(ValueError):
        EvaluationBenchmark.from_dict(raw)


@pytest.mark.parametrize("open_price, expected_fills", [(2.0, 0), (1.0, 2)])
def test_frozen_limit_orders_remain_unfilled_or_split_by_policy(tmp_path, open_price, expected_fills):
    sessions = pd.bdate_range("2026-01-05", periods=2)
    window, data = benchmark_inputs(tmp_path, pd.DataFrame({"dt": sessions,
        "open": [1., open_price], "close": [1., open_price]}))
    result = replay_buyhold(window, data, 250.,
        benchmark=EvaluationBenchmark(LimitBuyHold(100, .003, .001, .1, 100)))
    assert len(result.execution.orders) == 2
    assert len(result.execution.fills) == expected_fills
    assert (result.execution.orders.quantity == 100).all()
    if not expected_fills:
        assert result.account_daily.iloc[-1].cash == 250.
        assert (result.execution.orders.status == "UNFILLED").all()


@pytest.mark.parametrize("market", [MarketId.CN, MarketId.US])
def test_v4_benchmark_identity_binds_economics_not_candidate_label(tmp_path, market):
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY)
    assert EvaluationBenchmark.from_dict(request.benchmark.to_dict()) == request.benchmark
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        baseline = context.evaluation.prepare(request, execution=execution)
        renamed = context.evaluation.prepare(replace(request,
            candidate=replace(request.candidate, candidate_id="C0002")), execution=execution)
        assert baseline.benchmark_identity == renamed.benchmark_identity
        for changed in (replace(request, fee_rate=.002), replace(request, initial_cash=50000.)):
            other = context.evaluation.prepare(changed, execution=execution)
            assert other.benchmark_identity != baseline.benchmark_identity
