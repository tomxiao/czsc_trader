"""Factory for immutable strategy instances."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from dataflows import Dataflows

from .binding import RuntimeBinding
from .contracts import StrategyIdentity, TradableWindow
from .loader import StrategyLoader
from .models import ExecutionPolicy, RuntimeDefinition, StrategyCandidate, StrategyRelease
from .identity import CandidateContentIdentity, ImplementationDependency, content_identity
from .strategy import StrategyInstance
from .pricing import ExecutionPricing


@dataclass(frozen=True, slots=True)
class StrategyInit:
    source: StrategyRelease | StrategyCandidate
    tradable_window: TradableWindow
    data_dir: Path
    symbol: str | None = None
    execution_policy: ExecutionPolicy | None = None
    source_root: Path | None = None
    runtime_binding: RuntimeBinding | None = None
    pricing: ExecutionPricing = field(default_factory=ExecutionPricing)

    def __post_init__(self) -> None:
        if not isinstance(self.pricing, ExecutionPricing):
            raise TypeError("pricing requires ExecutionPricing")
        if self.runtime_binding is not None and not isinstance(self.runtime_binding, RuntimeBinding):
            raise TypeError("runtime_binding requires RuntimeBinding")
        object.__setattr__(self, "data_dir", Path(self.data_dir).resolve())
        if self.source_root is not None:
            object.__setattr__(self, "source_root", Path(self.source_root).resolve())


class StrategyRuntime:
    """Create strategy instances; all running behavior belongs to the instance."""

    def __init__(
        self,
        strategy_root: Path | None = None,
        *,
        dataflows: Dataflows | None = None,
    ) -> None:
        self._loader = StrategyLoader(strategy_root)
        self._dataflows = dataflows

    def _load(
        self,
        source: StrategyRelease | StrategyCandidate,
        symbol: str | None,
        source_root: Path | None = None,
        runtime_binding: RuntimeBinding | None = None,
    ):
        if isinstance(source, StrategyRelease):
            return (
                self._loader.load_for_symbol(
                    source,
                    symbol,
                    source_root=source_root,
                    runtime_binding=runtime_binding,
                )
                if symbol is not None
                else self._loader.load(
                    source,
                    source_root=source_root,
                    runtime_binding=runtime_binding,
                )
            )
        if source_root is not None or runtime_binding is not None:
            raise ValueError("candidate does not accept release source or binding overrides")
        if symbol is not None:
            raise ValueError("candidate strategy does not support symbol rebinding")
        return self._loader.load_candidate(source)

    def describe(
        self,
        source: StrategyRelease | StrategyCandidate,
        *,
        symbol: str | None = None,
        source_root: Path | None = None,
        runtime_binding: RuntimeBinding | None = None,
    ) -> RuntimeDefinition:
        """Return the validated frozen definition without creating an instance."""

        return self._load(source, symbol, source_root, runtime_binding).definition

    def identify(
        self,
        candidate: StrategyCandidate,
        *,
        dependencies: tuple[ImplementationDependency, ...],
    ) -> CandidateContentIdentity:
        """Validate the implementation and return its effective content identity."""
        if not isinstance(candidate, StrategyCandidate):
            raise TypeError("identify requires a StrategyCandidate")
        if candidate.source_root is None:
            raise ValueError("candidate identity requires a source root")
        for name in candidate.payload["runtime"]["source_files"]:
            if not (candidate.source_root / name).resolve().is_relative_to(candidate.source_root):
                raise ValueError("candidate source escapes source root")
        definition = self.describe(candidate)
        return content_identity(
            definition,
            tuple(candidate.payload["runtime"]["source_files"]),
            dependencies,
            {
                key: value
                for key, value in candidate.payload.items()
                if key not in {"runtime", "parameters"}
            },
        )

    def create(self, request: StrategyInit) -> StrategyInstance:
        algorithm = self._load(
            request.source,
            request.symbol,
            request.source_root,
            request.runtime_binding,
        )
        definition = algorithm.definition
        if (
            request.execution_policy is not None
            and request.execution_policy.policy_type != definition.execution.policy_type
        ):
            raise ValueError("execution policy override must preserve the strategy policy type")
        symbol = definition.tradable_symbol
        identity = StrategyIdentity(
            strategy_id=definition.strategy_family_id,
            reference_id=definition.release_id,
            release_hash=definition.release_hash,
            runtime_sha256=definition.runtime_sha256,
            symbol=symbol,
        )
        return StrategyInstance(
            algorithm=algorithm,
            identity=identity,
            tradable_window=request.tradable_window,
            data_dir=request.data_dir,
            execution_policy=request.execution_policy or definition.execution,
            dataflows=self._dataflows,
            pricing=request.pricing,
        )
