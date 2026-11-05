"""Explicit saved-account inputs and compact selection-stability evidence."""
from dataclasses import dataclass
from enum import StrEnum

from strategy_evaluator.research_models import AssessmentCandidate, ResearchTargets
from strategy_evaluator.selection_models import (
    AccountWindowFacts, SelectionCandidateSource, SelectionNoFilter, SelectionRule,
    SelectionStabilityRequest, SelectionStabilityResult, SelectionWindowPlan,
)

from ._records import _Record, _unique
from .evidence import EvidenceRef


@dataclass(frozen=True)
class SelectionWindowSource(_Record):
    candidate: AssessmentCandidate
    evaluation: EvidenceRef


@dataclass(frozen=True)
class SelectionProjectionBudget(_Record):
    max_window_facts: int
    max_source_bytes: int
    max_shared_bytes: int

    def _validate(self):
        if min(self.max_window_facts, self.max_source_bytes, self.max_shared_bytes) <= 0:
            raise ValueError("selection projection budgets must be positive")


@dataclass(frozen=True)
class SelectionWindowFactsRequest(_Record):
    sources: tuple[SelectionWindowSource, ...]
    plan: SelectionWindowPlan
    frequency_window_days: int
    minimum_closed_cycles: int
    budget: SelectionProjectionBudget

    def _validate(self):
        if not self.sources or min(self.frequency_window_days, self.minimum_closed_cycles) <= 0:
            raise ValueError("sources and positive frequency definition required")
        _unique((s.candidate.candidate_id for s in self.sources), "selection candidate")
        _unique((s.evaluation.sha256 for s in self.sources), "evaluation source")


class SelectionProjectionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    SOURCE_FAILED = "SOURCE_FAILED"


@dataclass(frozen=True)
class SelectionSourceFailure(_Record):
    source: SelectionWindowSource
    reason: str


@dataclass(frozen=True)
class SelectionProjectionStats(_Record):
    source_bytes: int
    shared_bytes: int
    read_count: int
    decode_count: int
    read_seconds: float
    decode_seconds: float
    projection_seconds: float
    total_seconds: float
    projected_accounts: int
    projected_windows: int
    observation_points: int
    window_point_visits: int
    frequency_subwindows: int


@dataclass(frozen=True)
class SelectionWindowFactsResult(_Record):
    request: SelectionWindowFactsRequest
    status: SelectionProjectionStatus
    sources: tuple[SelectionCandidateSource, ...]
    facts: tuple[AccountWindowFacts, ...]
    failures: tuple[SelectionSourceFailure, ...]
    stats: SelectionProjectionStats
    version: str = "selection-window-facts-v1"

    def _validate(self):
        if self.version != "selection-window-facts-v1":
            raise ValueError("unsupported selection window facts version")
        if (self.status is SelectionProjectionStatus.SOURCE_FAILED) != bool(self.failures):
            raise ValueError("selection source failure status differs")

    def analysis_request(self, rule: SelectionRule, *,
                         observation_targets: ResearchTargets | SelectionNoFilter | None = None
                         ) -> SelectionStabilityRequest:
        """Never silently analyze a smaller universe after a corrupt source."""
        if self.failures:
            raise ValueError("SOURCE_FAILED: repair declared sources before selection analysis")
        if (rule.frequency_window_days, rule.minimum_closed_cycles) != (
                self.request.frequency_window_days, self.request.minimum_closed_cycles):
            raise ValueError("selection rule and projected frequency contract differ")
        return SelectionStabilityRequest(self.request.plan, rule, self.sources, self.facts,
                                         observation_targets)


@dataclass(frozen=True)
class SelectionStabilityEvidence(_Record):
    projection: SelectionWindowFactsResult
    analysis: SelectionStabilityRequest
    result: SelectionStabilityResult
    limitations: tuple[str, ...]
    version: str = "selection-stability-evidence-v1"

    def _validate(self):
        if self.version != "selection-stability-evidence-v1":
            raise ValueError("unsupported selection evidence version")
        if self.projection.analysis_request(self.analysis.rule,
                observation_targets=self.analysis.observation_targets) != self.analysis:
            raise ValueError("analysis differs from declared projection")
        from strategy_runtime import canonical_sha256
        if self.result.request_sha256 != canonical_sha256(self.analysis.to_dict()):
            raise ValueError("selection result belongs to another request")
