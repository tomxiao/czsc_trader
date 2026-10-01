"""Public platform tools for strategy research."""

from .evaluation import (
    METRIC_SEMANTICS_VERSION,
    BuyHoldReplay,
    CandidateEvaluationContext,
    EvaluationBenchmark,
    EvaluationCost,
    EvaluationRequest,
    EvaluationIdentity,
    EvaluationLineage,
    EvaluationResult,
    EvaluationRun,
    EvaluationWindow,
    evaluate_strategy,
)
from ._evaluation_records import EvaluationExecutionError
from .experiment import (
    create_experiment_context,
    create_formal_experiment_context,
    execute_experiment,
    preflight_experiment,
)
from .audit_evidence import build_champion_audit_request

__all__ = [
    "build_champion_audit_request",
    "METRIC_SEMANTICS_VERSION",
    "BuyHoldReplay",
    "CandidateEvaluationContext",
    "EvaluationBenchmark",
    "EvaluationCost",
    "EvaluationRequest",
    "EvaluationIdentity",
    "EvaluationLineage",
    "EvaluationExecutionError",
    "EvaluationResult",
    "EvaluationRun",
    "EvaluationWindow",
    "create_experiment_context",
    "create_formal_experiment_context",
    "execute_experiment",
    "preflight_experiment",
    "evaluate_strategy",
]
