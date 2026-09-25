"""Convention-based loading of immutable strategy runtime implementations."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from .deployment import load_strategy_deployment
from .errors import RuntimeCompatibilityError
from .implementation_identity import implementation_sha256, strategy_source_root
from .isolated_import import load_closure_module
from .models import ImplementationRef, StrategyCandidate, StrategyRelease, canonical_sha256
from .algorithm import StrategyImplementation


class StrategyLoader:
    """Load one strategy without a central release switch or registry patch."""

    def __init__(self, strategy_root: Path | None = None) -> None:
        self.strategy_root = None if strategy_root is None else Path(strategy_root).resolve()

    def _release_source(
        self,
        release: StrategyRelease,
        source_root: Path | None,
        runtime_binding: Mapping[str, object] | None,
    ) -> tuple[Path, Mapping[str, object]]:
        if source_root is None and runtime_binding is None:
            if self.strategy_root is None:
                raise RuntimeCompatibilityError(
                    f"strategy deployment root is required for {release.release_id}"
                )
            deployment = load_strategy_deployment(self.strategy_root, release.release_id)
            source_root = deployment.source_root
            runtime_binding = deployment.binding
        elif (
            source_root is not None
            and runtime_binding is None
            and isinstance(release.payload.get("runtime"), Mapping)
        ):
            descriptor = release.payload["runtime"]
            runtime_binding = {
                "release_id": release.release_id,
                "release_hash": release.release_hash,
                "source_files": descriptor.get("source_files"),
                "implementation_sha256": descriptor.get("source_sha256"),
            }
        elif source_root is None or runtime_binding is None:
            raise RuntimeCompatibilityError(
                "release loading requires both source root and runtime binding"
            )
        root = Path(source_root).resolve()
        if root.name != "strategy_runtime" or not (root / "strategies").is_dir():
            raise RuntimeCompatibilityError("release source root is not an SRT package")
        if (
            runtime_binding.get("release_id") != release.release_id
            or runtime_binding.get("release_hash") != release.release_hash
        ):
            raise RuntimeCompatibilityError("runtime binding differs from frozen release")
        return root, runtime_binding

    def _load_factory(
        self,
        release: StrategyRelease,
        source_root: Path | None = None,
        runtime_binding: Mapping[str, object] | None = None,
    ):
        if not isinstance(release, StrategyRelease):
            raise RuntimeCompatibilityError("frozen loading requires a validated StrategyRelease")
        root, binding = self._release_source(release, source_root, runtime_binding)
        if "runtime" in release.payload:
            module_name, class_name, factory = self._declared_factory(
                release.payload, source_root=root,
            )
            return module_name, class_name, factory, root, binding
        module_name = (
            f"strategy_runtime.strategies."
            f"{release.strategy_family_id.lower()}_{release.version.lower()}"
        )
        class_name = f"{release.strategy_family_id}{release.version.upper()}"
        actual = implementation_sha256(tuple(binding["source_files"]), source_root=root)
        if actual != binding["implementation_sha256"]:
            raise RuntimeCompatibilityError(
                f"frozen implementation differs from runtime binding: {release.release_id}"
            )
        try:
            with strategy_source_root(root):
                module = load_closure_module(
                    module_name,
                    source_root=root,
                    source_files=tuple(binding["source_files"]),
                    source_sha256=actual,
                    marker="srt_source",
                )
                factory = getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            raise RuntimeCompatibilityError(
                f"strategy implementation is unavailable: {module_name}.{class_name}"
            ) from exc
        factory.__module__ = module_name
        if implementation_sha256(tuple(binding["source_files"]), source_root=root) != actual:
            raise RuntimeCompatibilityError("implementation source changed while loading")
        return module_name, class_name, factory, root, binding

    @staticmethod
    def _declared_factory(
        payload: Mapping, *, source_root: Path | None = None,
    ):
        """Load the declared closure, with no convention fallback on invalid metadata."""
        descriptor = payload.get("runtime")
        expected = {"module", "qualname", "contract_version", "source_sha256", "source_files"}
        if not isinstance(descriptor, Mapping) or set(descriptor) != expected:
            raise RuntimeCompatibilityError("runtime implementation descriptor is incomplete")
        ref = ImplementationRef(**{key: descriptor[key] for key in expected - {"source_files"}})
        if ref.contract_version != 1:
            raise RuntimeCompatibilityError("unsupported implementation contract version")
        if not ref.module.startswith("strategy_runtime.strategies."):
            raise RuntimeCompatibilityError(
                "declared strategy must reside in the SRT strategies package"
            )
        if (
            not all(part.isidentifier() for part in ref.module.split("."))
            or not ref.qualname.isidentifier()
        ):
            raise RuntimeCompatibilityError("invalid declared Python implementation identity")
        source_files = descriptor["source_files"]
        if (
            not isinstance(source_files, (list, tuple))
            or not source_files
            or not all(isinstance(name, str) for name in source_files)
            or len(source_files) != len(set(source_files))
        ):
            raise RuntimeCompatibilityError(
                "runtime source closure must contain unique source paths"
            )
        for name in source_files:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name or ":" in name:
                raise RuntimeCompatibilityError("runtime source closure contains an unsafe path")
        implementation_file = ref.module.removeprefix("strategy_runtime.").replace(".", "/") + ".py"
        if implementation_file not in source_files:
            raise RuntimeCompatibilityError(
                "runtime source closure omits the implementation module"
            )
        root = None if source_root is None else Path(source_root).resolve()
        if root is not None:
            if root.name != "strategy_runtime" or not (root / "strategies").is_dir():
                raise RuntimeCompatibilityError(
                    "candidate source root must be a strategy_runtime package directory"
                )
        actual = implementation_sha256(tuple(source_files), source_root=root)
        if actual != ref.source_sha256:
            raise RuntimeCompatibilityError(
                "declared implementation source hash differs from local code"
            )
        try:
            with strategy_source_root(root):
                module = load_closure_module(
                    ref.module,
                    source_root=root,
                    source_files=tuple(source_files),
                    source_sha256=actual,
                    marker="srt_source",
                )
                factory = getattr(module, ref.qualname)
        except (ImportError, AttributeError) as exc:
            raise RuntimeCompatibilityError(
                f"declared strategy is unavailable: {ref.module}.{ref.qualname}"
            ) from exc
        factory.__module__ = ref.module
        if factory.__module__ != ref.module or factory.__qualname__ != ref.qualname:
            raise RuntimeCompatibilityError(
                "declared factory is an alias for another implementation"
            )
        if implementation_sha256(tuple(source_files), source_root=root) != actual:
            raise RuntimeCompatibilityError("implementation source changed while loading")
        return ref.module, ref.qualname, factory

    @staticmethod
    def _validate_declared_content(
        payload: Mapping, strategy: StrategyImplementation
    ) -> None:
        descriptor = payload["runtime"]
        definition = strategy.definition
        if definition.schema_version != 2:
            raise RuntimeCompatibilityError("declared implementations must use runtime schema 2")
        actual = definition.implementation
        for key in ("module", "qualname", "contract_version", "source_sha256"):
            if getattr(actual, key) != descriptor[key]:
                raise RuntimeCompatibilityError(
                    "runtime definition differs from declared implementation"
                )
        parameters = payload.get("parameters")
        if not isinstance(parameters, Mapping) or definition.parameters.sha256 != canonical_sha256(
            parameters
        ):
            raise RuntimeCompatibilityError(
                "runtime parameters differ from the supplied parameter set"
            )

    def load_candidate(self, candidate: StrategyCandidate) -> StrategyImplementation:
        """Run a parameterized candidate before submission without creating a frozen version."""
        if not isinstance(candidate, StrategyCandidate):
            raise RuntimeCompatibilityError("candidate loading requires a StrategyCandidate")
        module_name, class_name, factory = self._declared_factory(
            candidate.payload, source_root=candidate.source_root,
        )
        create = getattr(factory, "from_candidate", None)
        if not callable(create):
            raise RuntimeCompatibilityError(
                f"candidate implementation has no from_candidate factory: {class_name}"
            )
        with strategy_source_root(candidate.source_root):
            strategy = create(candidate)
        if not isinstance(strategy, StrategyImplementation):
            raise RuntimeCompatibilityError(
                "candidate does not inherit StrategyImplementation"
            )
        definition = strategy.definition
        if (
            definition.identity_kind != "CANDIDATE"
            or definition.version is not None
            or definition.strategy_family_id != candidate.strategy_family_id
            or definition.candidate_id != candidate.candidate_id
            or definition.release_id != candidate.reference_id
            or definition.release_hash != candidate.runtime_identity_sha256
        ):
            raise RuntimeCompatibilityError("loaded runtime differs from candidate identity")
        self._validate_declared_content(candidate.payload, strategy)
        return strategy

    def _validate(
        self,
        release: StrategyRelease,
        strategy: StrategyImplementation,
        module_name: str,
        class_name: str,
        *,
        source_root: Path,
        binding: Mapping[str, object],
    ) -> StrategyImplementation:
        if not isinstance(strategy, StrategyImplementation):
            raise RuntimeCompatibilityError(
                f"loaded object does not inherit StrategyImplementation: {class_name}"
            )
        definition = strategy.definition
        if (
            definition.strategy_family_id != release.strategy_family_id
            or definition.identity_kind != "RELEASE"
            or definition.version != release.version
            or definition.release_id != release.release_id
            or definition.release_hash != release.release_hash
        ):
            raise RuntimeCompatibilityError("loaded strategy identity differs from release")
        if (
            definition.implementation.module != module_name
            or definition.implementation.qualname != class_name
        ):
            raise RuntimeCompatibilityError(
                "loaded implementation identity differs from convention"
            )
        if "runtime" in release.payload:
            self._validate_declared_content(release.payload, strategy)
            return strategy
        if binding.get("release_hash") != release.release_hash:
            raise RuntimeCompatibilityError("runtime binding release hash differs from release")
        source_files = tuple(binding["source_files"])
        actual_sha256 = implementation_sha256(source_files, source_root=source_root)
        if actual_sha256 != binding["implementation_sha256"]:
            raise RuntimeCompatibilityError(
                f"frozen implementation differs from runtime binding: {release.release_id}"
            )
        if definition.implementation.source_sha256 != actual_sha256:
            raise RuntimeCompatibilityError(
                "runtime definition implementation hash differs from its source closure"
            )
        return strategy

    def load(
        self,
        release: StrategyRelease,
        *,
        source_root: Path | None = None,
        runtime_binding: Mapping[str, object] | None = None,
    ) -> StrategyImplementation:
        module_name, class_name, factory, root, binding = self._load_factory(
            release, source_root, runtime_binding,
        )
        from_release = getattr(factory, "from_release", None)
        if not callable(from_release):
            raise RuntimeCompatibilityError(
                f"strategy implementation has no from_release factory: {class_name}"
            )
        with strategy_source_root(root):
            strategy = from_release(release)
        return self._validate(
            release, strategy, module_name, class_name,
            source_root=root, binding=binding,
        )

    def load_for_symbol(
        self,
        release: StrategyRelease,
        symbol: str,
        *,
        source_root: Path | None = None,
        runtime_binding: Mapping[str, object] | None = None,
    ) -> StrategyImplementation:
        """Bind a formula-compatible release to one explicit deployment symbol.

        A strategy must opt in by implementing ``from_release_for_symbol``.
        Symbol-specific mechanisms therefore fail closed instead of silently
        replaying their frozen source instrument against another price series.
        """

        module_name, class_name, factory, root, binding = self._load_factory(
            release, source_root, runtime_binding,
        )
        binder = getattr(factory, "from_release_for_symbol", None)
        if not callable(binder):
            strategy = self.load(
                release, source_root=root, runtime_binding=binding,
            )
            if strategy.definition.tradable_symbol == symbol.upper():
                return strategy
            raise RuntimeCompatibilityError(
                f"{release.release_id} does not support deployment symbol rebinding"
            )
        with strategy_source_root(root):
            strategy = binder(release, symbol.upper())
        return self._validate(
            release, strategy, module_name, class_name,
            source_root=root, binding=binding,
        )
