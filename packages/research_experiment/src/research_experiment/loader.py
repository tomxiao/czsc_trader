"""Hash-verified isolated loader for research experiment implementations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import importlib
import importlib.machinery
from importlib.metadata import PackageNotFoundError, version as distribution_version
import json
from pathlib import Path, PurePosixPath
import re
import sys
from threading import RLock
from types import ModuleType
from typing import Any

from .contracts import (
    ExperimentDefinition,
    ExperimentDependency,
    ResearchExperiment,
    _safe_relative_path,
)


_STRATEGY_ID = re.compile(r"S\d{3}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LOAD_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class ExperimentBinding:
    """Identity of an isolated experiment implementation closure."""

    schema_version: int
    module: str
    qualname: str
    source_files: tuple[str, ...]
    source_sha256: str
    dependencies: tuple[ExperimentDependency, ...]

    def __post_init__(self) -> None:
        if self.schema_version not in {2, 3}:
            raise ValueError("experiment binding schema_version must be 2 or 3")
        module = _nonempty_text(self.module, "binding module")
        qualname = _nonempty_text(self.qualname, "binding qualname")
        if not all(part.isidentifier() for part in module.split(".")):
            raise ValueError("binding module must be a dotted Python identifier")
        if not all(part.isidentifier() for part in qualname.split(".")):
            raise ValueError("binding qualname must be a dotted Python identifier")
        source_files = tuple(_safe_relative_path(item).as_posix() for item in self.source_files)
        if not source_files or len(source_files) != len(set(source_files)):
            raise ValueError("binding source_files must be non-empty and unique")
        expected_module = f"{module.replace('.', '/')}.py"
        package_module = f"{module.replace('.', '/')}/__init__.py"
        if expected_module not in source_files and package_module not in source_files:
            raise ValueError("binding source_files do not contain the implementation module")
        if not _SHA256.fullmatch(self.source_sha256):
            raise ValueError("binding source_sha256 must be lowercase SHA-256")
        dependencies = tuple(self.dependencies)
        if not all(isinstance(item, ExperimentDependency) for item in dependencies):
            raise ValueError("binding dependencies must contain ExperimentDependency values")
        names = tuple(item.name for item in dependencies)
        if len(names) != len(set(names)):
            raise ValueError("binding dependency names must be unique")
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "qualname", qualname)
        object.__setattr__(self, "source_files", source_files)
        object.__setattr__(self, "dependencies", dependencies)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ExperimentBinding:
        expected = {
            "schema_version",
            "module",
            "qualname",
            "source_files",
            "source_sha256",
            "dependencies",
        }
        if set(payload) != expected:
            raise ValueError("experiment binding fields differ from schema")
        source_files = payload["source_files"]
        if not isinstance(source_files, list):
            raise ValueError("binding source_files must be a list")
        dependencies = payload["dependencies"]
        if not isinstance(dependencies, list) or any(
            not isinstance(item, Mapping) or set(item) != {"name", "version"}
            for item in dependencies
        ):
            raise ValueError("binding dependencies must be a list of exact versions")
        return cls(
            schema_version=payload["schema_version"],
            module=payload["module"],
            qualname=payload["qualname"],
            source_files=tuple(source_files),
            source_sha256=payload["source_sha256"],
            dependencies=tuple(
                ExperimentDependency(name=item["name"], version=item["version"])
                for item in dependencies
            ),
        )


@dataclass(frozen=True, slots=True, init=False)
class LoadedExperiment:
    """A source-bound experiment handle created only by :func:`load_experiment`."""

    root: Path
    binding: ExperimentBinding
    implementation: ResearchExperiment
    definition: ExperimentDefinition

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("LoadedExperiment can only be created by load_experiment")

    @classmethod
    def _from_verified(
        cls,
        *,
        root: Path,
        binding: ExperimentBinding,
        implementation: ResearchExperiment,
        definition: ExperimentDefinition,
    ) -> LoadedExperiment:
        loaded = object.__new__(cls)
        object.__setattr__(loaded, "root", root)
        object.__setattr__(loaded, "binding", binding)
        object.__setattr__(loaded, "implementation", implementation)
        object.__setattr__(loaded, "definition", definition)
        return loaded


def _nonempty_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def experiment_source_sha256(root: Path, source_files: tuple[str, ...]) -> str:
    """Return a deterministic identity for the complete declared source closure."""

    root = Path(root).resolve()
    digest = sha256()
    normalized = tuple(_safe_relative_path(item).as_posix() for item in source_files)
    if len(normalized) != len(set(normalized)):
        raise ValueError("source_files must be unique")
    for name in sorted(normalized):
        target = root.joinpath(*PurePosixPath(name).parts).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("experiment source escapes its root") from exc
        if not target.is_file():
            raise FileNotFoundError(f"experiment source does not exist: {name}")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(target.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_dependencies(dependencies: tuple[ExperimentDependency, ...]) -> None:
    for dependency in dependencies:
        try:
            installed = distribution_version(dependency.name)
        except PackageNotFoundError as exc:
            raise ValueError(f"experiment dependency is not installed: {dependency.name}") from exc
        if installed != dependency.version:
            raise ValueError(
                "experiment dependency version differs: "
                f"{dependency.name} requires {dependency.version}, installed {installed}"
            )


def load_experiment(root: Path) -> LoadedExperiment:
    """Return a source-bound experiment without adding its path to ``sys.path``."""

    root = Path(root).resolve()
    binding_path = root / "experiment_binding.json"
    try:
        raw = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read experiment binding: {binding_path}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("experiment binding must be a JSON object")
    binding = ExperimentBinding.from_mapping(raw)
    actual_hash = experiment_source_sha256(root, binding.source_files)
    if actual_hash != binding.source_sha256:
        raise ValueError("experiment source SHA-256 differs from binding")
    _validate_dependencies(binding.dependencies)

    root_identity = sha256(str(root).encode("utf-8")).hexdigest()[:12]
    namespace = f"_czsc_research_experiment_{root_identity}_{actual_hash[:12]}"
    full_module = f"{namespace}.{binding.module}"
    with _LOAD_LOCK:
        for name in tuple(sys.modules):
            if name == namespace or name.startswith(f"{namespace}."):
                sys.modules.pop(name, None)
        package = ModuleType(namespace)
        package.__path__ = [str(root)]
        package.__package__ = namespace
        package.__spec__ = importlib.machinery.ModuleSpec(namespace, loader=None, is_package=True)
        sys.modules[namespace] = package
        try:
            module = importlib.import_module(full_module)
            declared = set(binding.source_files)
            loaded_sources: set[str] = set()
            for name, loaded in tuple(sys.modules.items()):
                if name != namespace and not name.startswith(f"{namespace}."):
                    continue
                file_name = getattr(loaded, "__file__", None)
                if file_name is None:
                    continue
                loaded_path = Path(file_name).resolve()
                try:
                    relative = loaded_path.relative_to(root).as_posix()
                except ValueError as exc:
                    raise ValueError("experiment imported source outside its root") from exc
                loaded_sources.add(relative)
            undeclared = loaded_sources - declared
            if undeclared:
                raise ValueError(
                    "experiment loaded undeclared source files: " + ", ".join(sorted(undeclared))
                )
            implementation: Any = module
            for part in binding.qualname.split("."):
                implementation = getattr(implementation, part)
            experiment = implementation()
        finally:
            for name in tuple(sys.modules):
                if name == namespace or name.startswith(f"{namespace}."):
                    sys.modules.pop(name, None)
    if not isinstance(experiment, ResearchExperiment):
        raise TypeError("bound implementation must instantiate ResearchExperiment")
    definition = experiment.definition
    if not isinstance(definition, ExperimentDefinition):
        raise TypeError("bound experiment definition must be ExperimentDefinition")
    if definition.experiment_id != root.name:
        raise ValueError("experiment definition id differs from its directory")
    if _STRATEGY_ID.fullmatch(root.parent.name) and (definition.strategy_id != root.parent.name):
        raise ValueError("experiment definition strategy differs from its directory")
    if definition.dependencies != binding.dependencies:
        raise ValueError("experiment definition dependencies differ from binding")
    return LoadedExperiment._from_verified(
        root=root,
        binding=binding,
        implementation=experiment,
        definition=definition,
    )


__all__ = [
    "ExperimentBinding",
    "LoadedExperiment",
    "experiment_source_sha256",
    "load_experiment",
]
