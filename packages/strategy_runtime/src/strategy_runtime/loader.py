"""Load the explicitly declared source closure of strategy implementations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
import inspect
from pathlib import Path, PurePosixPath

from .deployment import load_strategy_deployment
from .binding import RuntimeBinding
from .errors import RuntimeCompatibilityError
from .implementation_identity import implementation_sha256, strategy_source_root
from .isolated_import import load_closure_module
from .models import (
    ImplementationRef,
    StrategyCandidate,
    StrategyRelease,
    ParameterSet,
    StrategyDefinition,
    RuntimeDefinition,
)
from .algorithm import StrategyImplementation


@dataclass(frozen=True)
class _BoundStrategy:
    implementation: StrategyImplementation
    definition: RuntimeDefinition

    def calendar_request(self, window):
        return self.implementation.calendar_request(window)

    def derive_calculation_scope(self, window, calendar_dates):
        return self.implementation.derive_calculation_scope(window, calendar_dates)

    def calculate_history(self, inputs, sessions):
        return self.implementation.calculate_history(inputs, sessions)

    def calculate_window_history(self, inputs, sessions):
        return self.implementation.calculate_window_history(inputs, sessions)


class StrategyLoader:
    """Load one strategy without a central release switch or registry patch."""

    def __init__(self, strategy_root: Path | None = None) -> None:
        self.strategy_root = None if strategy_root is None else Path(strategy_root).resolve()

    def _release_source(
        self,
        release: StrategyRelease,
        source_root: Path | None,
        runtime_binding: RuntimeBinding | None,
    ) -> tuple[Path, RuntimeBinding]:
        if source_root is None and runtime_binding is None:
            if self.strategy_root is None:
                raise RuntimeCompatibilityError(
                    f"strategy deployment root is required for {release.release_id}"
                )
            deployment = load_strategy_deployment(self.strategy_root, release.release_id)
            source_root = deployment.source_root
            runtime_binding = deployment.binding
        elif source_root is None or runtime_binding is None:
            raise RuntimeCompatibilityError(
                "release loading requires both source root and runtime binding"
            )
        if not isinstance(runtime_binding, RuntimeBinding):
            raise RuntimeCompatibilityError("runtime_binding requires RuntimeBinding")
        root = Path(source_root).resolve()
        if root.name != "strategy_runtime" or not (root / "strategies").is_dir():
            raise RuntimeCompatibilityError("release source root is not an SRT package")
        if (
            runtime_binding.release_id != release.release_id
            or runtime_binding.release_hash != release.release_hash
        ):
            raise RuntimeCompatibilityError("runtime binding differs from frozen release")
        return root, runtime_binding

    def _load_factory(
        self,
        release: StrategyRelease,
        source_root: Path | None = None,
        runtime_binding: RuntimeBinding | None = None,
    ):
        if not isinstance(release, StrategyRelease):
            raise RuntimeCompatibilityError("frozen loading requires a validated StrategyRelease")
        root, binding = self._release_source(release, source_root, runtime_binding)
        descriptor = release.payload.get("runtime")
        if (
            not isinstance(descriptor, Mapping)
            or tuple(descriptor.get("source_files", ())) != binding.spec.source_files
            or descriptor.get("source_sha256") != binding.spec.implementation_sha256
        ):
            raise RuntimeCompatibilityError("runtime binding differs from declared source closure")
        module_name, class_name, factory = self._declared_factory(
            release.payload,
            source_root=root,
        )
        return module_name, class_name, factory, root, binding

    @staticmethod
    def _declared_factory(
        payload: Mapping,
        *,
        source_root: Path | None = None,
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
            if (
                path.is_absolute()
                or ".." in path.parts
                or str(path) != name
                or "\\" in name
                or ":" in name
            ):
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
        if not isinstance(factory, type) or not issubclass(factory, StrategyImplementation):
            raise RuntimeCompatibilityError("declared class must inherit StrategyImplementation")
        if inspect.isabstract(factory):
            raise RuntimeCompatibilityError(
                "incomplete strategy implementation: "
                + ", ".join(sorted(factory.__abstractmethods__))
            )
        factory.__module__ = ref.module
        if factory.__module__ != ref.module or factory.__qualname__ != ref.qualname:
            raise RuntimeCompatibilityError(
                "declared factory is an alias for another implementation"
            )
        if implementation_sha256(tuple(source_files), source_root=root) != actual:
            raise RuntimeCompatibilityError("implementation source changed while loading")
        return ref.module, ref.qualname, factory

    @staticmethod
    def _construct(identity, factory, root, *, symbol=None):
        parameters = ParameterSet(identity.payload["parameters"])
        with strategy_source_root(root):
            strategy = factory.from_parameters(parameters)
            if not isinstance(strategy, StrategyImplementation):
                raise RuntimeCompatibilityError("factory must return StrategyImplementation")
            if type(strategy.definition) is not StrategyDefinition:
                raise RuntimeCompatibilityError("implementation must declare StrategyDefinition")
            if symbol is not None and strategy.definition.tradable_symbol != symbol.upper():
                strategy = factory.from_parameters_for_symbol(parameters, symbol.upper())
        if not isinstance(strategy, StrategyImplementation):
            raise RuntimeCompatibilityError("factory must return StrategyImplementation")
        definition = strategy.definition
        if type(definition) is not StrategyDefinition:
            raise RuntimeCompatibilityError("implementation must declare StrategyDefinition")
        if definition.parameters.sha256 != parameters.sha256:
            raise RuntimeCompatibilityError(
                "runtime parameters differ from the supplied parameter set"
            )
        if symbol is not None and definition.tradable_symbol != symbol.upper():
            raise RuntimeCompatibilityError("runtime tradable symbol differs from deployment")
        candidate = isinstance(identity, StrategyCandidate)
        descriptor = identity.payload["runtime"]
        runtime = RuntimeDefinition(
            schema_version=3,
            strategy_family_id=identity.strategy_family_id,
            version=None if candidate else identity.version,
            release_id=identity.reference_id if candidate else identity.release_id,
            release_hash=identity.runtime_identity_sha256 if candidate else identity.release_hash,
            implementation=ImplementationRef(
                **{
                    k: descriptor[k]
                    for k in ("module", "qualname", "contract_version", "source_sha256")
                }
            ),
            identity_kind="CANDIDATE" if candidate else "RELEASE",
            candidate_id=identity.candidate_id if candidate else None,
            **{f.name: getattr(definition, f.name) for f in fields(StrategyDefinition)},
        )
        return _BoundStrategy(strategy, runtime)

    def load_candidate(self, candidate: StrategyCandidate) -> _BoundStrategy:
        if not isinstance(candidate, StrategyCandidate):
            raise RuntimeCompatibilityError("candidate loading requires a StrategyCandidate")
        _, _, factory = self._declared_factory(candidate.payload, source_root=candidate.source_root)
        return self._construct(candidate, factory, candidate.source_root)

    def load(
        self, release: StrategyRelease, *, source_root=None, runtime_binding=None
    ) -> _BoundStrategy:
        return self._load_release(release, source_root, runtime_binding)

    def load_for_symbol(
        self, release: StrategyRelease, symbol: str, *, source_root=None, runtime_binding=None
    ) -> _BoundStrategy:
        return self._load_release(release, source_root, runtime_binding, symbol=symbol)

    def _load_release(self, release, source_root, runtime_binding, *, symbol=None):
        _, _, factory, root, binding = self._load_factory(release, source_root, runtime_binding)
        strategy = self._construct(release, factory, root, symbol=symbol)
        if strategy.definition.observation.sha256 != binding.spec.observation_sha256:
            raise RuntimeCompatibilityError("observation definition differs from binding")
        return strategy
