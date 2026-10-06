"""Published evidence identities; researchers never choose its storage path."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from ._records import _Record, _hash, _path, _text
from .context import ExperimentRef
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
        return f"{self.experiment.repository_path}/{self.path}"

    def resolve(self, repository_root: Path) -> Path:
        target = managed_path(repository_root, self.repository_path)
        if not target.is_file():
            raise FileNotFoundError(f"published evidence is missing: {self.evidence_id}")
        if sha256(target.read_bytes()).hexdigest() != self.sha256:
            raise ValueError("published evidence content differs from its reference")
        return target


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
        _name(self.name)
        for value, expected in (
            (self.experiment, ExperimentRef), (self.request, EvaluationRequest),
            (self.result, EvaluationResult),
        ):
            if type(value) is not expected:
                raise TypeError(f"evaluation publication requires {expected.__name__}")


EvidenceWriteRequest = MaterialEvidenceWrite | EvaluationEvidenceWrite
