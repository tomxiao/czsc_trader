"""Host-independent technical inspection identity, control and isolated admission."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Callable
import hashlib
import importlib.metadata
import importlib.util
import math
import platform
import re
import subprocess

from .errors import RuntimeCompatibilityError
from .identity import ImplementationDependency
from .models import canonical_sha256


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
            raise RuntimeCompatibilityError("inspection path contains a link")
    return path.resolve()


class InspectionStage(StrEnum):
    PREPARE = "PREPARE"
    EQUIVALENCE = "EQUIVALENCE"
    PTE = "PTE"
    PERSIST = "PERSIST"
    FINALIZE = "FINALIZE"


@dataclass(frozen=True, slots=True)
class InspectionProgress:
    run_id: str
    stage: InspectionStage
    completed: int
    total: int | None
    elapsed_seconds: float
    message: str

    def __post_init__(self):
        _identifier(self.run_id)
        if type(self.stage) is not InspectionStage or type(self.completed) is not int or self.completed < 0:
            raise ValueError("invalid inspection progress")
        if self.total is not None and (type(self.total) is not int or self.total < self.completed):
            raise ValueError("invalid inspection total")
        if type(self.elapsed_seconds) not in (int, float) or not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("invalid elapsed seconds")
        if type(self.message) is not str:
            raise TypeError("message must be a string")


@dataclass(frozen=True, slots=True)
class InspectionControl:
    timeout_seconds: float | None = None
    max_workers: int = 1
    cancelled: Callable[[], bool] | None = None
    on_progress: Callable[[InspectionProgress], None] | None = None

    def __post_init__(self):
        if self.timeout_seconds is not None and (type(self.timeout_seconds) not in (float, int)
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be positive and finite")
        if type(self.max_workers) is not int or self.max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        for callback in (self.cancelled, self.on_progress):
            if callback is not None and not callable(callback):
                raise TypeError("inspection callbacks must be callable")


@dataclass(frozen=True, slots=True)
class ImplementationFileIdentity:
    path: str
    sha256: str

    def __post_init__(self):
        _hash(self.sha256)
        if type(self.path) is not str:
            raise TypeError("implementation path must be a string")
        path = PurePosixPath(self.path)
        if not self.path or path.is_absolute() or str(path) != self.path or ".." in path.parts or "\\" in self.path or ":" in self.path:
            raise ValueError("implementation path must be normalized and relative")


@dataclass(frozen=True, slots=True)
class InspectionEnvironment:
    platform_build_sha256: str
    platform_files: tuple[ImplementationFileIdentity, ...]
    git_revision: str | None
    python_version: str
    dependencies: tuple[ImplementationDependency, ...]
    pte_contract_version: str
    srt_contract_version: str
    effective_config_sha256: str

    def __post_init__(self):
        _hash(self.platform_build_sha256)
        _hash(self.effective_config_sha256)
        if type(self.platform_files) is not tuple or not self.platform_files or any(type(x) is not ImplementationFileIdentity for x in self.platform_files):
            raise TypeError("platform_files requires immutable file identities")
        if len({x.path.casefold() for x in self.platform_files}) != len(self.platform_files):
            raise ValueError("duplicate platform file")
        if type(self.dependencies) is not tuple or any(type(x) is not ImplementationDependency for x in self.dependencies):
            raise TypeError("dependencies require ImplementationDependency tuple")
        if len({x.name for x in self.dependencies}) != len(self.dependencies):
            raise ValueError("duplicate dependency")
        for value in (self.python_version, self.pte_contract_version, self.srt_contract_version):
            if type(value) is not str or not value.strip():
                raise ValueError("environment version must be nonempty")
        if self.git_revision is not None and (type(self.git_revision) is not str or re.fullmatch(r"[a-f0-9]{40,64}", self.git_revision) is None):
            raise ValueError("invalid git revision")
        if self.platform_build_sha256 != canonical_sha256([asdict(x) for x in self.platform_files]):
            raise ValueError("platform build differs from its file inventory")

    def to_dict(self):
        return asdict(self)


def collect_inspection_environment(repository_root: Path) -> InspectionEnvironment:
    """Read actual platform execution files; Git identity alone is insufficient."""
    # Data/research roots do not identify the executing installation. Inspect the
    # import resolver's actual module locations without importing host packages.
    modules = ("czsc_trader", "dataflows", "strategy_manager", "strategy_runtime",
               "strategy_evaluator", "trading_execution_engine", "paper_trading_engine",
               "factor_signal_catalog", "strategy_template_catalog")
    identities = []
    for name in modules:
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeCompatibilityError(f"inspection execution package unavailable: {name}")
        if len(spec.submodule_search_locations) != 1:
            raise RuntimeCompatibilityError(f"inspection package has ambiguous roots: {name}")
        package = _safe_path(next(iter(spec.submodule_search_locations)))
        for path in sorted(package.rglob("*.py")):
            identities.append(ImplementationFileIdentity(
                f"{name}/{path.relative_to(package).as_posix()}",
                hashlib.sha256(_safe_path(path).read_bytes()).hexdigest()))
    files = tuple(sorted(identities, key=lambda item: item.path))
    root = next((p for p in Path(__file__).resolve().parents if (p / ".git").exists()), None)
    dependencies = tuple(sorted((ImplementationDependency(d.metadata["Name"], d.version)
                                 for d in importlib.metadata.distributions() if d.metadata["Name"]), key=lambda x: x.name))
    # Multiple sys.path entries may identify the same installed distribution.
    unique = {x.name: x for x in dependencies}
    if any(unique[x.name].version != x.version for x in dependencies):
        raise RuntimeCompatibilityError("conflicting installed dependency versions")
    dependencies = tuple(unique[name] for name in sorted(unique))
    revision = None
    if root is not None:
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
        revision = git.stdout.strip() if git.returncode == 0 else None
    config = {"inspection_protocol": "candidate-inspection-v2", "channel_model": "RECORDED_FILLS_V1", "admission": "ISOLATED_INSPECTION_V1"}
    return InspectionEnvironment(canonical_sha256([asdict(x) for x in files]), files, revision,
                                 platform.python_version(), dependencies, "pte-inspection-v1", "srt-inspection-v1", canonical_sha256(config))


@dataclass(frozen=True, slots=True)
class InspectionRuntimePermit:
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
            raise RuntimeCompatibilityError("inspection workspace is outside its managed run")
        if not repository.is_relative_to(workspace) or repository == workspace:
            raise RuntimeCompatibilityError("isolated repository is outside inspection workspace")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "isolated_repository", repository)

    def validate_path(self, path: Path) -> Path:
        result = _safe_path(path)
        if not result.is_relative_to(self.workspace):
            raise RuntimeCompatibilityError("inspection path escapes its permit")
        return result

    def validate_release(self, release_id: str, release_sha256: str) -> None:
        if release_id != self.release_id or release_sha256 != self.release_sha256:
            raise RuntimeCompatibilityError("inspection release differs from permit")
