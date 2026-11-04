"""Project current session-owned V4 account facts into SE assessment inputs."""
from __future__ import annotations

from strategy_evaluator import AssessmentEvidence

from .account_preparation import PreparedAccountEvaluation
from .equity_evaluation import EquityEvaluationResult, validate_equity_result


def build_assessment_evidence(
    request: PreparedAccountEvaluation,
    result: EquityEvaluationResult,
    *, execution=None,
) -> tuple[AssessmentEvidence, ...]:
    if type(request) is not PreparedAccountEvaluation or type(result) is not EquityEvaluationResult:
        raise TypeError('assessment requires a session-owned V4 handle and result')
    if execution is None:
        raise TypeError('V4 assessment requires its explicit execution session')
    validate_equity_result(execution.context.evaluation, request, result, execution=execution)
    from .equity_replay import build_equity_assessment
    return build_equity_assessment(result)
