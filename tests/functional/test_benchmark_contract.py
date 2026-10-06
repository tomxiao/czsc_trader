from dataclasses import replace

import pandas as pd
import pytest

from public_backtest_support import request_for_prices
from czsc_trader.research_tools import evaluate_strategy
from czsc_trader.research_tools import EvaluationBenchmark, LimitBuyHold, NextOpenBuyHold
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_assessment_delivery import completed as completed, prepare, Deliverable
from czsc_trader.application import assemble_delivery
from czsc_trader.research_tools import delivery as d


def test_limit_reservation_differs_from_next_open_and_keeps_account_evidence(candidate_payload, tmp_path, monkeypatch):
    from copy import deepcopy
    from dataflows import canonical_frame_sha256

    sessions = pd.bdate_range("2025-02-05", periods=3)
    daily = pd.DataFrame({"dt": sessions, "open": [1.062] * 3, "close": [1.062, 1.062, 1.555]})
    _, request, _ = request_for_prices(
        candidate_payload, tmp_path, monkeypatch, daily, initial_cash=1e6,
        benchmark=EvaluationBenchmark(LimitBuyHold(100, 0.003, 0.001, 0.1, 1000000)),
    )
    evaluated = evaluate_strategy(request)
    result = evaluated.runs[0].buyhold
    assert result.execution.fills.iloc[0].quantity == 938000
    assert result.execution.orders.iloc[0].limit_price == 1.065
    assert result.account_daily.iloc[-1].cash == pytest.approx(2847.844)
    assert result.account_daily.iloc[-1].equity == pytest.approx(1461437.844)
    assert len(result.execution.fills) == 1
    assert result.execution.decisions.action.tolist() == ["BUY", "HOLD"]
    assert (result.execution.decisions.reason == "BUY_AND_HOLD").all()
    inputs = (evaluated.execution_data.adjusted_daily, evaluated.execution_data.execution_daily)
    originals = [(deepcopy(frame.attrs), canonical_frame_sha256(frame)) for frame in inputs]
    repeated = evaluate_strategy(replace(request, execution_data=evaluated.execution_data)).runs[0].buyhold
    assert repeated.metrics == result.metrics
    for name in ("decisions", "orders", "fills", "account_daily", "trades"):
        pd.testing.assert_frame_equal(getattr(result.execution, name), getattr(repeated.execution, name))
    for frame, (attrs, digest) in zip(inputs, originals, strict=True):
        assert frame.attrs == attrs
        assert canonical_frame_sha256(frame) == digest
    next_open = evaluate_strategy(replace(
        request, benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),
    )).runs[0].buyhold
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
def test_limit_orders_can_remain_unfilled_and_are_split_by_policy(candidate_payload, tmp_path, monkeypatch, open_price, expected_fills):
    sessions = pd.bdate_range("2026-01-05", periods=2)
    daily = pd.DataFrame({"dt": sessions, "open": [1.0, open_price], "close": [1.0, open_price]})
    _, request, _ = request_for_prices(
        candidate_payload, tmp_path, monkeypatch, daily, initial_cash=250,
        benchmark=EvaluationBenchmark(LimitBuyHold(100, 0.003, 0.001, 0.1, 100)),
    )
    result = evaluate_strategy(request).runs[0].buyhold
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
