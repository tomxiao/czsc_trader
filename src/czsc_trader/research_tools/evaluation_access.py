"""Batch-owned account computation; persistence is an explicit evidence operation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .account_preparation import PreparedAccountEvaluation

from dataflows import Dataflows
from strategy_runtime.resources import ExecutionResources
from strategy_runtime.equity import ResearchExecutionSpec
from .equity_evaluation import EquityEvaluationRequest, EquityEvaluationResult
from .execution import ResearchExecutionSession


class EvaluationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EvaluationError:
    code: str
    message: str

    def __post_init__(self):
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("evaluation error requires a code")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("evaluation error requires a message")


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    status: EvaluationStatus
    request_hash: str
    result: EquityEvaluationResult | None = None
    error: EvaluationError | None = None

    def __post_init__(self):
        if not isinstance(self.status, EvaluationStatus):
            raise TypeError("outcome status must be EvaluationStatus")
        if not isinstance(self.request_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.request_hash) is None:
            raise ValueError("outcome requires a request identity")
        if self.status is EvaluationStatus.SUCCEEDED:
            if not isinstance(self.result, EquityEvaluationResult) or self.error is not None:
                raise ValueError("successful outcome requires only a result")
            if self.result.request_hash != self.request_hash:
                raise ValueError("outcome and result request identities differ")
        elif self.result is not None or not isinstance(self.error, EvaluationError):
            raise ValueError("unsuccessful outcome requires only an error")


class EvaluationAccess:
    """Use one injected DFLS space for preparation and all account calculations."""

    def __init__(self, *, dataflows: Dataflows, resources: ExecutionResources | None = None,
                 strategy_id: str | None = None, execution_spec: ResearchExecutionSpec | None = None):
        if not isinstance(dataflows, Dataflows):
            raise TypeError("evaluation requires Dataflows")
        self.data = dataflows
        if resources is not None and type(resources) is not ExecutionResources:
            raise TypeError("evaluation requires ExecutionResources")
        self.resources = resources
        self._context = None
        self.strategy_id = strategy_id
        if execution_spec is not None and type(execution_spec) is not ResearchExecutionSpec:
            raise TypeError("execution_spec requires ResearchExecutionSpec")
        self.execution_spec = execution_spec
        self._session_lock = Lock()
        self._active_execution = None
        self._base_dir = dataflows.binding.base_dir

    def prepare(self, request: EquityEvaluationRequest, *,
                execution: ResearchExecutionSession | None = None) -> PreparedAccountEvaluation:
        if type(request) is not EquityEvaluationRequest:
            raise TypeError("account preparation requires EquityEvaluationRequest contract V4")
        from .equity_replay import prepare_equity
        return prepare_equity(self, request, execution=execution)

    def evaluate_many(self, requests: tuple[PreparedAccountEvaluation, ...], *,
                      execution: ResearchExecutionSession | None = None) -> tuple[EvaluationOutcome, ...]:
        if type(requests) is not tuple or not requests:
            raise ValueError("evaluate_many requires a nonempty tuple")
        from .account_preparation import PreparedAccountEvaluation
        if not all(type(item) is PreparedAccountEvaluation for item in requests):
            raise TypeError("evaluate_many requires explicitly prepared session-owned account handles")
        from .equity_replay import evaluate_many_equity
        return evaluate_many_equity(self, requests, execution=execution)
