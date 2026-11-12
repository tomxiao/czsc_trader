"""Project current session-owned V4 account facts into SE assessment inputs."""
from __future__ import annotations

from strategy_evaluator import AssessmentEvidence, AssessmentReference, ParameterPerformanceEvidence, PerformanceFacts
from strategy_evaluator.equity_assessment import equity_performance

from .account_preparation import PreparedAccountEvaluation
from .equity_evaluation import EquityEvaluationResult, validate_equity_result
from .equity_assessment import AssessmentProjection
from .evidence import EvidenceRef


def build_assessment_evidence(
    request: PreparedAccountEvaluation,
    result: EquityEvaluationResult,
    *, execution=None,
    projection: AssessmentProjection = AssessmentProjection.FULL,
) -> tuple[AssessmentEvidence, ...] | tuple[ParameterPerformanceEvidence, ...]:
    if type(projection) is not AssessmentProjection:
        raise TypeError('assessment projection requires AssessmentProjection')
    if type(request) is not PreparedAccountEvaluation or type(result) is not EquityEvaluationResult:
        raise TypeError('assessment requires a session-owned V4 handle and result')
    if execution is None:
        raise TypeError('V4 assessment requires its explicit execution session')
    validate_equity_result(execution.context.evaluation, request, result, execution=execution)
    from .equity_replay import build_equity_assessment
    return build_equity_assessment(result, projection=projection)


def build_assessment_reference(
    request: PreparedAccountEvaluation,
    result: EquityEvaluationResult,
    reference: EvidenceRef,
    *, execution,
) -> AssessmentReference:
    """Read a declared published account for same-window relative performance targets."""
    from ..application.equity_evidence_io import materialize_equity_document
    from .equity_evaluation import EQUITY_EVIDENCE_VERSIONS
    from .equity_replay import _read, build_equity_assessment

    if (type(reference) is not EvidenceRef or reference.schema != "equity_research"
            or reference.schema_version not in EQUITY_EVIDENCE_VERSIONS
            or reference.media_type != "application/json"):
        raise TypeError("assessment reference requires published equity evidence")
    base, = build_assessment_evidence(request, result, execution=execution)
    root = execution.context.repository.root
    _, raw = reference._read_verified(root)
    header = _read(raw)
    saved, current = header["request"], result.payload["request"]
    if (header["schema_version"] != reference.schema_version
            or (saved["experiment"]["strategy_id"], saved["experiment"]["experiment_id"])
            != (reference.experiment.strategy_id, reference.experiment.experiment_id)):
        raise ValueError("published reference identity differs")
    EquityEvaluationResult(header["request_hash"], raw)
    dimensions = ("instrument", "window", "initial_cash", "fee_rate", "measurement_tier",
                  "scenario_id", "drawdown_basis", "price_basis", "quantity_basis", "income_policy")
    if any(saved[key] != current[key] for key in dimensions):
        raise ValueError("reference instrument, window or measurement basis differs")
    if current["drawdown_basis"] == "BAR_CLOSE" and (
            saved["specification"]["decision_clock"] != current["specification"]["decision_clock"]):
        raise ValueError("BAR_CLOSE reference observation frequencies differ")
    view = materialize_equity_document(root, reference.repository_path, raw)
    incumbent, = build_equity_assessment(view)
    if (incumbent.candidate == base.candidate
            or tuple(x.session for x in incumbent.account) != tuple(x.session for x in base.account)):
        raise ValueError("reference account or observation sessions differ")
    annual, drawdown = equity_performance(incumbent)
    performance = PerformanceFacts(incumbent.candidate, incumbent.evaluation_id, incumbent.scenario_context,
                                   annual, drawdown, None, None)
    return AssessmentReference(base.evaluation_id, reference.sha256, performance)
