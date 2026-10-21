"""Public account-diagnosis references; researchers supply population membership."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import Enum

from strategy_evaluator.account_diagnosis import (
    AccountDiagnosisStatus,
    AccountPnl,
    CyclePathComparison,
    DailyPathComparison,
    DecisionCoverage,
    PopulationCoverageSummary,
)

from .evidence import EvidenceRef
from .evaluation import EvaluationIdentity, EvaluationWindow


def _json(value):
    if isinstance(value, Enum):
        return value.value
    if type(value) is date:
        return value.isoformat()
    if is_dataclass(value):
        return {f.name: _json(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [_json(v) for v in value]
    return value


class _DiagnosisRecord:
    def to_dict(self):
        return _json(self)


@dataclass(frozen=True, slots=True)
class AccountRunRef(_DiagnosisRecord):
    evidence: EvidenceRef
    identity: EvaluationIdentity

    def __post_init__(self):
        if type(self.evidence) is not EvidenceRef or type(self.identity) is not EvaluationIdentity:
            raise TypeError("account run requires EvidenceRef and EvaluationIdentity")
        if self.evidence.experiment.strategy_id != self.identity.candidate.strategy_id:
            raise ValueError("account evidence and candidate belong to different batches")


@dataclass(frozen=True, slots=True)
class DecisionPopulationRef(_DiagnosisRecord):
    evidence: EvidenceRef
    population_id: str

    def __post_init__(self):
        if type(self.evidence) is not EvidenceRef:
            raise TypeError("decision population requires EvidenceRef")
        if not isinstance(self.population_id, str) or not self.population_id.strip():
            raise ValueError("population_id must be nonblank")


@dataclass(frozen=True, slots=True)
class AccountDiagnosisRequest(_DiagnosisRecord):
    baseline: AccountRunRef
    alternative: AccountRunRef | None
    window: EvaluationWindow
    populations: tuple[DecisionPopulationRef, ...] = ()

    def __post_init__(self):
        if type(self.baseline) is not AccountRunRef or (
            self.alternative is not None and type(self.alternative) is not AccountRunRef
        ):
            raise TypeError("diagnosis requires typed account run references")
        if type(self.window) is not EvaluationWindow:
            raise TypeError("diagnosis requires EvaluationWindow")
        if type(self.populations) is not tuple or any(
            type(p) is not DecisionPopulationRef for p in self.populations
        ):
            raise TypeError("populations must be a tuple of DecisionPopulationRef")
        batch = self.baseline.evidence.experiment.strategy_id
        if (
            self.alternative is not None
            and self.alternative.evidence.experiment.strategy_id != batch
        ):
            raise ValueError("diagnosis accounts must belong to the same research batch")
        if any(p.evidence.experiment.strategy_id != batch for p in self.populations):
            raise ValueError("diagnosis populations must belong to the same research batch")
        if len({(p.evidence.sha256, p.population_id) for p in self.populations}) != len(
            self.populations
        ):
            raise ValueError("duplicate population references")


@dataclass(frozen=True, slots=True)
class DiagnosisReconciliation(_DiagnosisRecord):
    evaluation_id: str
    opening_equity: float
    closing_equity: float
    equity_change: float
    decomposed_change: float
    residual: float


@dataclass(frozen=True, slots=True)
class AccountDiagnosisResult(_DiagnosisRecord):
    status: AccountDiagnosisStatus
    protocol: str
    issues: tuple[str, ...]
    sources: tuple[EvidenceRef, ...]
    pnl_breakdown: tuple[AccountPnl, ...] = ()
    decision_coverage: tuple[DecisionCoverage, ...] = ()
    path_comparison: tuple[CyclePathComparison, ...] = ()
    daily_paths: tuple[DailyPathComparison, ...] = ()
    reconciliation: tuple[DiagnosisReconciliation, ...] = ()
    coverage_summary: tuple[PopulationCoverageSummary, ...] = ()
