from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from public_backtest_support import request_for_prices
from czsc_trader.research_tools import ExecutionPriceBasis, EvaluationBenchmark, LimitBuyHold, NextOpenBuyHold
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from strategy_runtime import canonical_sha256


@pytest.mark.parametrize("benchmark", [EvaluationBenchmark(NextOpenBuyHold(100)),
    EvaluationBenchmark(LimitBuyHold(100, .003, .001, .1, 1000000))])
def test_hfq_evaluation_uses_one_price_contract_for_plans_account_benchmark_and_evidence(
    candidate_payload, tmp_path, monkeypatch, benchmark,
):
    days = pd.bdate_range("2025-12-29", periods=7)
    prices = pd.DataFrame({"dt": days, "open": [10., 10., 5., 5., 6., 6., 6.],
                           "close": [10., 10., 5., 5., 6., 6., 6.]})
    context, request, _ = request_for_prices(candidate_payload, tmp_path, monkeypatch, prices,
        benchmark=benchmark, flow=[.1, .8, .8, .1, .1, .1, .1],
        hfq_factors=pd.Series([.3, .3, .6, .6, .6, .6, .6]))
    raw_request = context.evaluation.prepare(request)
    raw_result = context.evaluation.evaluate(raw_request)
    bound = context.evaluation.prepare(replace(request, price_basis=ExecutionPriceBasis.HFQ_RESEARCH))
    result = context.evaluation.evaluate(bound)
    run = result.runs[0]
    assert bound.execution_data.pricing.anchor_date == days[0].date()
    assert bound.execution_data.execution_daily.close.tolist() == pytest.approx([10., 10., 10., 10., 12., 12., 12.])
    assert bound.execution_data.execution_intraday.close.max() == pytest.approx(12.)
    assert result.request_hash != raw_result.request_hash
    assert bound.execution_data.fingerprint != raw_request.execution_data.fingerprint
    assert run.buyhold.account_daily.iloc[-1].equity > raw_result.runs[0].buyhold.account_daily.iloc[-1].equity
    assert run.execution.fills.price.tolist() == pytest.approx([10., 12.])
    assert (run.execution.fills.quantity % 100 == 0).all()
    assert run.execution.fills.fees.tolist() == pytest.approx(
        (run.execution.fills.quantity * run.execution.fills.price * .001).tolist())
    for frame in (run.execution.account_daily, run.buyhold.account_daily):
        assert frame.equity.tolist() == pytest.approx((frame.cash + frame.quantity * frame.close).tolist())
    saved = serialize_evaluation_evidence(bound, result)
    validate_evaluation_evidence(saved)
    assert saved["request_identity"]["pricing"]["quantity_unit"] == "RESEARCH_UNIT"
    tampered = deepcopy(saved)
    tampered["request_identity"]["price_basis"] = "UNADJUSTED"
    tampered["request_hash"] = canonical_sha256(tampered["request_identity"])
    with pytest.raises(ValueError, match="pricing differs"):
        validate_evaluation_evidence(tampered)
    with pytest.raises(ValueError, match="units differ"):
        context.evaluation.prepare(replace(bound, price_basis=ExecutionPriceBasis.UNADJUSTED))
