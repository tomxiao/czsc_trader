"""Explicit experiment material ownership and independent report contracts."""
from dataclasses import dataclass
from enum import StrEnum

from ._records import _Record, _hash, _path, _text
from .context import ExperimentRef
from .delivery import ValidationStatus
from .evidence import EvidenceRef, ExperimentOutcome


class ExperimentValidationScope(StrEnum):
    STRUCTURE = "STRUCTURE"
    REPORT_PUBLICATION = "REPORT_PUBLICATION"


@dataclass(frozen=True, slots=True)
class ExperimentArtifactRef(_Record):
    owner: ExperimentRef
    path: str
    sha256: str

    def _validate(self):
        _path(self.path)
        _hash(self.sha256)


@dataclass(frozen=True, slots=True)
class ExperimentValidationRequest(_Record):
    experiment: ExperimentRef
    scope: ExperimentValidationScope
    artifacts: tuple[ExperimentArtifactRef, ...] = ()

    def _validate(self):
        if any(item.owner.strategy_id != self.experiment.strategy_id for item in self.artifacts):
            raise ValueError("shared material must belong to the same research batch")
        if len({(item.owner, item.path) for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate experiment material")


@dataclass(frozen=True, slots=True)
class ExperimentIssue(_Record):
    code: str
    message: str

    def _validate(self):
        _text(self.code, "issue code")
        _text(self.message, "issue message")


@dataclass(frozen=True, slots=True)
class ExperimentValidation(_Record):
    status: ValidationStatus
    scope: ExperimentValidationScope
    issues: tuple[ExperimentIssue, ...]
    report: EvidenceRef | None = None

    def _validate(self):
        if (self.status is ValidationStatus.PASS) != (not self.issues):
            raise ValueError("validation status must agree with issues")


@dataclass(frozen=True, slots=True)
class ExperimentReportSnapshot(_Record):
    schema_version: int
    experiment: ExperimentRef
    report: str
    report_sha256: str
    outcome: ExperimentOutcome
    evidence: tuple[EvidenceRef, ...]
    previous: EvidenceRef | None

    def _validate(self):
        from hashlib import sha256
        if self.schema_version != 1:
            raise ValueError("unsupported experiment report schema")
        _text(self.report, "report")
        _hash(self.report_sha256)
        if sha256(self.report.encode("utf-8")).hexdigest() != self.report_sha256:
            raise ValueError("report bytes differ from declared digest")
        from .evidence import ExperimentReportWrite
        ExperimentReportWrite(self.experiment, self.report_sha256, self.outcome, self.evidence, self.previous)


class ReportPublicationError(RuntimeError):
    """A report may have an installed snapshot without a committed pointer."""
    def __init__(self, phase: str, message: str, reference: EvidenceRef | None = None,
                 pointer_committed: bool | None = False):
        self.phase = phase
        self.reference = reference
        self.pointer_committed = pointer_committed
        super().__init__(f"{phase}: {message}")
