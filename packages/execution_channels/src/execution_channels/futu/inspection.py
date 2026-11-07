"""Explicit isolated-ledger admission; no strategy loader or runtime dependency."""
from dataclasses import dataclass
from pathlib import Path
import re

class InspectionAccountError(ValueError):
    """An isolated account admission does not cover the requested operation."""

def _hash(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("expected lowercase SHA-256")

def _identifier(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None:
        raise ValueError("invalid inspection identifier")

def _safe_path(path: Path) -> Path:
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise InspectionAccountError("inspection path contains a link")
    return path.resolve()

@dataclass(frozen=True, slots=True)
class InspectionAccountPermit:
    """Explicit technical admission; never a formal deployment or qualification."""
    run_id: str
    release_id: str
    release_sha256: str
    package_sha256: str
    protocol_sha256: str
    isolated_repository: Path
    workspace: Path

    def __post_init__(self):
        _identifier(self.run_id)
        if type(self.release_id) is not str or re.fullmatch(r"S[0-9]{3}-v[1-9][0-9]*", self.release_id) is None:
            raise ValueError("invalid inspection release id")
        for value in (self.release_sha256, self.package_sha256, self.protocol_sha256):
            _hash(value)
        workspace = _safe_path(self.workspace)
        repository = _safe_path(self.isolated_repository)
        ancestors = (workspace, *workspace.parents)
        if not any(p.name == self.run_id and p.parent.name == "strategy-inspection" and p.parent.parent.name == ".tmp" for p in ancestors):
            raise InspectionAccountError("inspection workspace is outside its managed run")
        if not repository.is_relative_to(workspace) or repository == workspace:
            raise InspectionAccountError("isolated repository is outside inspection workspace")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "isolated_repository", repository)

    def validate_path(self, path: Path) -> Path:
        result = _safe_path(path)
        if not result.is_relative_to(self.workspace):
            raise InspectionAccountError("inspection path escapes its permit")
        return result

    def validate_release(self, release_id: str, release_sha256: str) -> None:
        if release_id != self.release_id or release_sha256 != self.release_sha256:
            raise InspectionAccountError("inspection release differs from permit")
