# Risk ownership: TDR-06
"""Benchmark identity and frozen limit execution, without retired research entrypoints."""
from dataclasses import replace
import pytest
from dataflows import BarFrequency, MarketId
from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark, LimitBuyHold
from czsc_trader.research_tools import ResearchExecutionSession
from account_parity_support import setup_account
from equity_test_support import setup_auxiliary, current_account_request




def test_TDR_06_C02_missing_lot_size_rejected():
    with pytest.raises(TypeError, match='lot_size'):
        LimitBuyHold(premium=.003, price_tick=.001, price_limit_ratio=.1, maximum_order_quantity=1000000)


@pytest.mark.parametrize('market', [MarketId.CN])
def test_TDR_06_C01_benchmark_identity_binds_economics_not_candidate_label(tmp_path, market):
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY)
    assert EvaluationBenchmark.from_dict(request.benchmark.to_dict()) == request.benchmark
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        baseline = context.evaluation.prepare(request, execution=execution)
        renamed = context.evaluation.prepare(replace(request,
            candidate=replace(request.candidate, candidate_id="C0002")), execution=execution)
        assert baseline.benchmark_identity == renamed.benchmark_identity
        changed = context.evaluation.prepare(replace(request, fee_rate=.002), execution=execution)
        assert changed.benchmark_identity != baseline.benchmark_identity


def test_TDR_06_C03_auxiliary_observations_do_not_change_benchmark_inputs(tmp_path):
    context, legacy, _, _ = setup_auxiliary(tmp_path)
    request = current_account_request(context, legacy)
    without_auxiliary = replace(request, candidate=replace(request.candidate,
        definition=replace(request.candidate.definition, step_data_inputs=(), session_context=False)),
        step_data_windows=())
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        observed = context.evaluation.prepare(request, execution=execution)
        primary_only = context.evaluation.prepare(without_auxiliary, execution=execution)
        assert observed.request.prepared.manifest_sha256 != primary_only.request.prepared.manifest_sha256
        assert observed.snapshot.primary_sha256 == primary_only.snapshot.primary_sha256
        assert observed.benchmark_identity == primary_only.benchmark_identity
        baseline = observed.benchmark_identity.to_dict()
        assert baseline["input_snapshot_sha256"] == observed.snapshot.primary_sha256
        assert not baseline["definition"].get("auxiliary_inputs")
        assert execution.equity_statistics.candidate_runs == 0
        assert execution.equity_statistics.benchmark_runs == 0
