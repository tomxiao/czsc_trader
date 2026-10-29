"""Immutable facts from one retained batch, without research interpretation."""

from dataclasses import dataclass
from enum import StrEnum

from strategy_manager import ResearchState

from ._records import _Record, _digest, _hash, _path, _text, _unique
from .context import ExperimentRef, ResearchBatchRef
from .delivery import DeliveryReference, DeliveryStage
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


class OverviewScope(StrEnum):
    METADATA_ONLY = "METADATA_ONLY"


class DeliveryMetadataState(StrEnum):
    READABLE = "READABLE"
    UNSUPPORTED = "UNSUPPORTED"


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
    stage: DeliveryStage
    revision: int
    reference: DeliveryReference | None
    report_path: str
    metadata_state: DeliveryMetadataState
    source: ResearchSourceRef

    def _validate(self):
        if self.revision < 1:
            raise ValueError("delivery revision must be positive")
        _path(self.report_path)
        if (self.metadata_state is DeliveryMetadataState.READABLE) != (self.reference is not None):
            raise ValueError("readable delivery metadata requires a reference")
        if self.reference is not None and (self.reference.stage, self.reference.revision) != (self.stage, self.revision):
            raise ValueError("delivery navigation identity differs")


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
    scope: OverviewScope = OverviewScope.METADATA_ONLY

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
    task_sources: tuple[ResearchSourceRef, ...]
    deliveries: tuple[DeliveryOverview, ...]
    experiments: tuple[ExperimentOverview, ...]
    limitations: tuple[OverviewLimitation, ...]
    schema_version: int = 2

    def _validate(self):
        if self.schema_version != 2:
            raise ValueError("unsupported research overview schema")
        _unique((x.stage for x in self.deliveries), "latest delivery stage")
        _unique((x.experiment for x in self.experiments), "experiment")
        _unique(self.task_sources, "task source")
        if any(x.experiment.strategy_id != self.batch.strategy_id for x in self.experiments):
            raise ValueError("overview experiment belongs to another batch")
        if any(x.reference is not None and x.reference.batch != self.batch for x in self.deliveries):
            raise ValueError("overview delivery belongs to another batch")


class ResearchOverviewError(ValueError):
    """Retained inputs are invalid or changed during the read."""

    def __init__(self, code: str, repository_path: str, message: str):
        self.code = code
        self.repository_path = repository_path
        super().__init__(f"{code}: {repository_path}: {message}")
