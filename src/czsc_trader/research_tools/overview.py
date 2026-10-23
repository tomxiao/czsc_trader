"""Immutable facts from one retained batch, without research interpretation."""

from dataclasses import dataclass
from enum import StrEnum

from strategy_manager import CandidateKey, ResearchState

from ._records import _Record, _digest, _hash, _path, _text, _unique
from .context import ExperimentRef, ResearchBatchRef
from .delivery import (
    ComponentEntry, DeliveryReference, DeliveryStatus, SearchSummary, PrototypePanel,
)
from .evidence import EvidenceRef, ExperimentOutcome


class ResearchSourceKind(StrEnum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


@dataclass(frozen=True, slots=True)
class ResearchSourceRef(_Record):
    repository_path: str
    sha256: str
    kind: ResearchSourceKind
    present: bool = True

    def _validate(self):
        _path(self.repository_path)
        _hash(self.sha256)


class CountBasis(StrEnum):
    VERIFIED = "VERIFIED"
    DECLARED = "DECLARED"
    UNKNOWN = "UNKNOWN"


class ResearchCountKind(StrEnum):
    REGISTERED_CANDIDATES = "REGISTERED_CANDIDATES"
    PUBLISHED_ACCOUNT_EVALUATIONS = "PUBLISHED_ACCOUNT_EVALUATIONS"
    SEARCH_EVALUATIONS = "SEARCH_EVALUATIONS"
    DISTINCT_CONFIGURATIONS = "DISTINCT_CONFIGURATIONS"
    ECONOMIC_PATH_GROUPS = "ECONOMIC_PATH_GROUPS"


@dataclass(frozen=True, slots=True)
class ResearchCount(_Record):
    kind: ResearchCountKind
    value: int | None
    basis: CountBasis
    sources: tuple[ResearchSourceRef, ...]
    reason: str | None = None

    def _validate(self):
        _unique(self.sources, "count source")
        if self.basis is CountBasis.UNKNOWN:
            if self.value is not None or not self.reason:
                raise ValueError("unknown count requires null value and reason")
        elif self.value is None or self.value < 0 or not self.sources:
            raise ValueError("known count requires a nonnegative value and sources")
        if self.reason is not None:
            _text(self.reason, "count reason")


class ExperimentReportState(StrEnum):
    MISSING = "MISSING"
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED_CHANGES = "UNPUBLISHED_CHANGES"


@dataclass(frozen=True, slots=True)
class ExperimentOverview(_Record):
    experiment: ExperimentRef
    report_state: ExperimentReportState
    report: EvidenceRef | None
    outcome: ExperimentOutcome | None
    source: ResearchSourceRef


@dataclass(frozen=True, slots=True)
class DeliveryOverview(_Record):
    reference: DeliveryReference
    status: DeliveryStatus
    predecessors: tuple[DeliveryReference, ...]
    source: ResearchSourceRef


@dataclass(frozen=True, slots=True)
class ComponentPanelOverview(_Record):
    delivery: DeliveryReference
    components: tuple[ComponentEntry, ...]


@dataclass(frozen=True, slots=True)
class PrototypePanelOverview(_Record):
    delivery: DeliveryReference
    panel: PrototypePanel


@dataclass(frozen=True, slots=True)
class CandidateOverview(_Record):
    key: CandidateKey
    content_sha256: str
    record_sha256: str
    experiment_id: str
    source: ResearchSourceRef

    def _validate(self):
        _hash(self.content_sha256)
        _hash(self.record_sha256)
        _text(self.experiment_id, "candidate experiment")


@dataclass(frozen=True, slots=True)
class CandidateHandoffOverview(_Record):
    delivery: DeliveryReference
    candidates: tuple[CandidateKey, ...]


@dataclass(frozen=True, slots=True)
class SearchOverview(_Record):
    summary: SearchSummary
    deliveries: tuple[DeliveryReference, ...]


@dataclass(frozen=True, slots=True)
class OverviewLimitation(_Record):
    code: str
    repository_path: str
    message: str

    def _validate(self):
        _text(self.code, "limitation code")
        _path(self.repository_path)
        _text(self.message, "limitation message")


@dataclass(frozen=True, slots=True)
class ResearchSnapshot(_Record):
    content_sha256: str
    observed_at: str
    sources: tuple[ResearchSourceRef, ...]

    def _validate(self):
        _hash(self.content_sha256)
        _text(self.observed_at, "observation time")
        _unique((item.repository_path for item in self.sources), "snapshot source")
        if _digest(self.sources) != self.content_sha256:
            raise ValueError("snapshot identity differs from sources")


@dataclass(frozen=True, slots=True)
class ResearchOverview(_Record):
    batch: ResearchBatchRef
    snapshot: ResearchSnapshot
    registered_state: ResearchState
    deliveries: tuple[DeliveryOverview, ...]
    experiments: tuple[ExperimentOverview, ...]
    component_tests: tuple[ComponentPanelOverview, ...]
    prototype_panels: tuple[PrototypePanelOverview, ...]
    candidates: tuple[CandidateOverview, ...]
    handoffs: tuple[CandidateHandoffOverview, ...]
    searches: tuple[SearchOverview, ...]
    counts: tuple[ResearchCount, ...]
    limitations: tuple[OverviewLimitation, ...]


class ResearchOverviewError(ValueError):
    """Retained inputs are invalid or changed during the read."""

    def __init__(self, code: str, repository_path: str, message: str):
        self.code = code
        self.repository_path = repository_path
        super().__init__(f"{code}: {repository_path}: {message}")
