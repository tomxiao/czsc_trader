"""Published evidence identities; researchers never choose its storage path."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
import re
from typing import TYPE_CHECKING

from ._records import _Record, _hash, _path, _text
from .context import ExperimentRef
if TYPE_CHECKING:
    from .evaluation import EvaluationRequest, EvaluationResult


def managed_path(root: Path, relative: str) -> Path:
    _path(relative)
    root = Path(root).resolve()
    target = root.joinpath(*relative.split("/"))
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("managed path contains a filesystem link")
    if not target.resolve().is_relative_to(root):
        raise ValueError("managed path escapes repository")
    return target


@dataclass(frozen=True, slots=True)
class EvidenceRef(_Record):
    experiment: ExperimentRef
    evidence_id: str
    sha256: str
    media_type: str
    name: str
    schema: str | None = None
    schema_version: int | None = None

    def _validate(self):
        _name(self.name)
        if not re.fullmatch(r"[0-9a-f]{64}\.[a-z0-9]{1,12}", self.evidence_id):
            raise ValueError("evidence ID must be a content hash with a format suffix")
        _hash(self.sha256)
        if self.evidence_id.split(".", 1)[0] != self.sha256:
            raise ValueError("evidence ID differs from content hash")
        _text(self.media_type, "media_type")
        if (self.schema is None) != (self.schema_version is None):
            raise ValueError("schema and schema_version must be supplied together")
        if self.schema is not None:
            _text(self.schema, "schema")
            if self.schema_version < 1:
                raise ValueError("schema_version must be positive")

    @property
    def path(self):
        return f"evidence/{self.evidence_id}"

    @property
    def repository_path(self):
        return f"research/{self.experiment.strategy_id}/assets/evidence/{self.experiment.experiment_id}/{self.evidence_id}"

    def resolve(self, repository_root: Path) -> Path:
        return self._read_verified(repository_root)[0]

    def _read_verified(self, repository_root: Path) -> tuple[Path, bytes]:
        """Read once so internal consumers decode the bytes that were verified."""
        target = managed_path(repository_root, self.repository_path)
        if not target.is_file():
            raise FileNotFoundError(f"published evidence is missing: {self.evidence_id}")
        data = target.read_bytes()
        if sha256(data).hexdigest() != self.sha256:
            raise ValueError("published evidence content differs from its reference")
        return target, data


def _name(value: str):
    _text(value, "evidence name")
    _path(value)
    if "/" in value or len(value) > 100:
        raise ValueError("evidence name must be one short business name")


@dataclass(frozen=True, slots=True)
class MaterialEvidenceWrite(_Record):
    experiment: ExperimentRef
    name: str
    content: bytes
    media_type: str
    suffix: str

    def _validate(self):
        _name(self.name)
        _text(self.media_type, "media_type")
        if not re.fullmatch(r"[a-z0-9]{1,12}", self.suffix):
            raise ValueError("suffix must be one lowercase format extension")
        if not self.content:
            raise ValueError("evidence content must be nonempty")


@dataclass(frozen=True, slots=True)
class EvaluationEvidenceWrite:
    experiment: ExperimentRef
    name: str
    request: EvaluationRequest
    result: EvaluationResult

    def __post_init__(self):
        from .evaluation import EvaluationRequest, EvaluationResult

        _name(self.name)
        for value, expected in (
            (self.experiment, ExperimentRef), (self.request, EvaluationRequest),
            (self.result, EvaluationResult),
        ):
            if type(value) is not expected:
                raise TypeError(f"evaluation publication requires {expected.__name__}")


EvidenceWriteRequest = MaterialEvidenceWrite | EvaluationEvidenceWrite


class PublicationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PublicationError:
    code: str
    message: str

    def __post_init__(self):
        _text(self.code, "publication error code")
        _text(self.message, "publication error message")


@dataclass(frozen=True, slots=True)
class PublicationOutcome:
    index: int
    status: PublicationStatus
    reference: EvidenceRef | None = None
    error: PublicationError | None = None

    def __post_init__(self):
        if type(self.index) is not int or self.index < 0:
            raise ValueError("publication index must be a nonnegative integer")
        if type(self.status) is not PublicationStatus:
            raise TypeError("publication status requires PublicationStatus")
        if self.status is PublicationStatus.PUBLISHED:
            if type(self.reference) is not EvidenceRef or self.error is not None:
                raise ValueError("published outcome requires only an evidence reference")
        elif self.reference is not None or type(self.error) is not PublicationError:
            raise ValueError("unsuccessful publication requires only an error")
