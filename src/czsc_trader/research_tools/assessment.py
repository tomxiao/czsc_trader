"""Convert authenticated evaluation facts into SE-owned research input contracts."""

import pandas as pd
from strategy_evaluator import (
    AccountPoint,
    AssessmentCandidate,
    AssessmentEvidence,
    EvaluationScenarioContext,
    AssessmentFill,
    ClosedCycle,
    FillSide,
    LedgerComparisonMode,
    LedgerComparisonRequest,
    LedgerComparisonStatus,
    compare_ledgers,
    AssessmentDerivationKind,
)
from strategy_runtime import canonical_sha256

from .evaluation import (
    EvaluationRequest,
    EvaluationResult,
    METRIC_SEMANTICS_VERSION,
    _evaluation_result_hash,
    _request_identity_payload,
)
from ..backtesting.audit_adapter import build_replay_evidence
from ..backtesting.metrics import calculate_metrics


def build_assessment_evidence(
    request: EvaluationRequest,
    result: EvaluationResult,
) -> tuple[AssessmentEvidence, ...]:
    if type(request) is not EvaluationRequest or type(result) is not EvaluationResult:
        raise TypeError("assessment adaptation requires EvaluationRequest and EvaluationResult")
    if not result.runs or any(x.identity is None for x in result.runs) or result.attempt_id is None:
        raise ValueError("assessment requires identified, managed evaluation attempts")
    content = result.runs[0].identity.content_sha256
    binding = canonical_sha256(request.runtime_binding)
    expected = canonical_sha256(_request_identity_payload(request, content, binding))
    if (
        expected != result.request_hash
        or binding != result.runtime_binding_hash
        or (request.strategy.runtime_identity_sha256 != result.strategy_identity)
        or _evaluation_result_hash(expected, result.runs) != result.result_hash
    ):
        raise ValueError("assessment request/result identity differs")
    expected_coordinates = {
        (w.window_id, c.scenario_id) for w in request.windows for c in request.costs
    }
    if {(x.window_id, x.scenario_id) for x in result.runs} != expected_coordinates or len(
        result.runs
    ) != len(expected_coordinates):
        raise ValueError("evaluation coordinates differ")
    candidate = AssessmentCandidate(request.strategy.reference_id, content)
    lineage = request.lineage.derivation if request.lineage else None
    if lineage is not None and (
        lineage.child.strategy_id,
        lineage.child.candidate_id,
        lineage.child_content_sha256,
    ) != (request.strategy.strategy_family_id, request.strategy.candidate_id, content):
        raise ValueError("lineage does not describe actual evaluated candidate")
    parent = (
        None
        if lineage is None
        else AssessmentCandidate(
            f"{lineage.parent.strategy_id}-{lineage.parent.candidate_id}",
            lineage.parent_content_sha256,
        )
    )
    records = []
    for run in result.runs:
        identity = run.identity
        if (
            identity.candidate.strategy_id,
            identity.candidate.candidate_id,
            identity.content_sha256,
        ) != (request.strategy.strategy_family_id, request.strategy.candidate_id, content):
            raise ValueError("run candidate identity differs")
        account = tuple(
            AccountPoint(
                pd.Timestamp(row.date).date().isoformat(),
                float(row.cash),
                int(row.quantity),
                float(row.close),
                float(row.equity),
            )
            for row in run.execution.account_daily.itertuples()
        )
        fills = tuple(
            AssessmentFill(
                str(row.cycle_id),
                pd.Timestamp(row.fill_time).date().isoformat(),
                FillSide(row.side),
                int(row.quantity),
                float(row.price),
                float(row.fees),
            )
            for row in run.execution.fills.itertuples()
        )
        closed = tuple(
            ClosedCycle(str(row.cycle_id), pd.Timestamp(row.exit_date).date().isoformat())
            for row in run.execution.trades.itertuples()
            if row.status == "CLOSED"
        )
        benchmark = ()
        if run.buyhold is not None:
            frame = run.buyhold.account_daily
            if tuple(pd.to_datetime(frame["date"]).dt.date.astype(str)) != tuple(
                x.session for x in account
            ):
                raise ValueError("benchmark calendar differs")
            benchmark = tuple(float(x) for x in frame["equity"])
        replay = build_replay_evidence(
            run.signals,
            request.execution_data,
            run.execution,
            request.initial_cash,
            calculate_metrics(run.execution, request.initial_cash),
        )
        comparison = compare_ledgers(
            LedgerComparisonRequest(replay, replay, LedgerComparisonMode.ECONOMIC, 0.0)
        )
        if comparison.status is not LedgerComparisonStatus.EQUIVALENT:
            raise ValueError("assessment ledger identity is invalid")
        common_context = canonical_sha256(
            {
                "data": request.execution_data.fingerprint,
                "symbol": request.symbol,
                "sessions": [x.session for x in account],
                "initial_cash": request.initial_cash,
                "benchmark": request.benchmark.benchmark_id,
                "execution_mode": request.execution_mode,
                "frequency_window_days": request.frequency_window_days,
                "metric_version": METRIC_SEMANTICS_VERSION,
            }
        )
        opening = run.execution.account_daily.iloc[0]
        cost = next(x for x in request.costs if x.scenario_id == run.scenario_id)
        records.append(
            AssessmentEvidence(
                candidate,
                request.experiment_id,
                result.attempt_id,
                identity.evaluation_id,
                result.request_hash,
                result.result_hash,
                common_context,
                run.window_id,
                run.scenario_id,
                METRIC_SEMANTICS_VERSION,
                EvaluationScenarioContext(
                    float(cost.one_way_cost),
                    cost.measurement_tier,
                    request.benchmark.benchmark_id,
                    request.benchmark.kind,
                ),
                float(request.initial_cash),
                float(opening["cash_before"]),
                int(opening["quantity_before"]),
                request.frequency_window_days,
                account,
                fills,
                closed,
                benchmark,
                parent,
                None if lineage is None else canonical_sha256(lineage.to_dict()),
                comparison.economic_sha256,
                None if lineage is None else AssessmentDerivationKind(lineage.kind.value),
            )
        )
    return tuple(records)
