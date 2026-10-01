from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

from czsc_trader.backtesting.benchmarks import replay_buyhold
from czsc_trader.research_tools import EvaluationBenchmark, LimitBuyHold, NextOpenBuyHold
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_assessment_delivery import completed as completed, prepare, Deliverable
from czsc_trader.application import assemble_delivery
from czsc_trader.research_tools import delivery as d


def test_limit_reservation_differs_from_next_open_and_keeps_account_evidence():
    sessions = pd.date_range("2025-02-05", periods=3)
    daily = pd.DataFrame({"dt": sessions, "open": [1.062] * 3, "close": [1.062, 1.062, 1.555]})
    data = SimpleNamespace(
        symbol="159326.SZ",
        fingerprint="a" * 64,
        execution_daily=daily,
        adjusted_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
    )
    signals = SimpleNamespace(
        evaluation_start=sessions[1],
        evaluation_end=sessions[-1],
        support_data={
            "mode": "srt_input_contract",
            "execution_policy": {
                "policy_type": "FROZEN_RULE",
                "settings": {"capital": {"fee_rate": 0.001}},
            },
        },
    )
    benchmark = EvaluationBenchmark(LimitBuyHold(100, 0.003, 0.001, 0.1, 1000000))
    result = replay_buyhold(signals, data, 1e6, benchmark=benchmark)
    assert result.execution.fills.iloc[0].quantity == 938000
    assert result.execution.orders.iloc[0].limit_price == 1.065
    assert result.account_daily.iloc[-1].cash == pytest.approx(2847.844)
    assert result.account_daily.iloc[-1].equity == pytest.approx(1461437.844)
    assert len(result.execution.fills) == 1  # residual cash is not reinvested
    assert result.execution.decisions.action.tolist() == ["BUY", "HOLD"]
    assert (result.execution.decisions.reason == "BUY_AND_HOLD").all()
    next_open = replay_buyhold(
        signals, data, 1e6, benchmark=EvaluationBenchmark(NextOpenBuyHold(100))
    )
    assert next_open.account_daily.iloc[-1].quantity == 940600


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lot_size": True},
        {"lot_size": 0},
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
def test_limit_orders_can_remain_unfilled_and_are_split_by_policy(open_price, expected_fills):
    sessions = pd.date_range("2026-01-01", periods=2)
    daily = pd.DataFrame({"dt": sessions, "open": [1.0, open_price], "close": [1.0, open_price]})
    data = SimpleNamespace(
        symbol="159326.SZ",
        fingerprint="a" * 64,
        execution_daily=daily,
        adjusted_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
    )
    signals = SimpleNamespace(
        evaluation_start=sessions[-1],
        evaluation_end=sessions[-1],
        support_data={
            "mode": "srt_input_contract",
            "execution_policy": {
                "policy_type": "FROZEN_RULE",
                "settings": {"capital": {"fee_rate": 0.001}},
            },
        },
    )
    benchmark = EvaluationBenchmark(LimitBuyHold(100, 0.003, 0.001, 0.1, 100))
    result = replay_buyhold(signals, data, 250.0, benchmark=benchmark)
    assert len(result.execution.orders) == 2
    assert len(result.execution.fills) == expected_fills
    assert (result.execution.orders.quantity == 100).all()
    if not expected_fills:
        assert result.account_daily.iloc[-1].cash == 250.0
        assert (result.execution.orders.status == "UNFILLED").all()


def test_managed_limit_execution_is_bound_to_result_and_projection(managed_evaluation):
    from czsc_trader.research_tools import build_assessment_evidence
    import json

    context, request = managed_evaluation
    request = replace(
        request, benchmark=EvaluationBenchmark(LimitBuyHold(100, 0.003, 0.001, 0.1, 1000000))
    )
    result = context.evaluation.evaluate(request)
    projection = build_assessment_evidence(request, result)
    assert projection[0].scenario_context.benchmark_contract_sha256 == request.benchmark.fingerprint
    saved = json.loads(
        context.workspace.path(context.trace.evaluations[-1].result_artifact.path).read_text()
    )
    assert saved["runs"][0]["buyhold"]["execution"]["fills"]["data"]
    result.runs[0].buyhold.execution.fills.loc[0, "fees"] += 1
    with pytest.raises(ValueError, match="identity differs"):
        build_assessment_evidence(request, result)


def test_stage_four_rejects_confirmed_benchmark_mismatch(completed):
    context = completed[0]
    defined, value = prepare(completed)
    request = value.payload.assessment_request
    changed = tuple(
        replace(e, scenario_context=replace(e.scenario_context, benchmark_contract_sha256="f" * 64))
        for e in request.evidence
    )
    payload = replace(value.payload, assessment_request=replace(request, evidence=changed))
    with pytest.raises(d.DeliveryValidationError) as exc:
        assemble_delivery(context, Deliverable(defined, replace(value, payload=payload)))
    assert any(x.code == "BENCHMARK_BINDING" for x in exc.value.issues)
