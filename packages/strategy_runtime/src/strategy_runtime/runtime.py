"""Factory for immutable strategy instances."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path

from .contracts import StrategyIdentity, TradableWindow
from .loader import StrategyLoader
from .models import ExecutionPolicy, StrategyCandidate, StrategyRelease
from .strategy import StrategyInstance


@dataclass(frozen=True, slots=True)
class StrategyInit:
    source: StrategyRelease | StrategyCandidate
    tradable_window: TradableWindow
    data_dir: Path
    symbol: str | None = None
    execution_policy: ExecutionPolicy | None = None
    source_root: Path | None = None
    runtime_binding: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir).resolve())
        if self.source_root is not None:
            object.__setattr__(self, "source_root", Path(self.source_root).resolve())


class StrategyRuntime:
    """Create strategy instances; all running behavior belongs to the instance."""

    def __init__(self, strategy_root: Path | None = None) -> None:
        self._loader = StrategyLoader(strategy_root)

    def _load(
        self,
        source: StrategyRelease | StrategyCandidate,
        symbol: str | None,
        source_root: Path | None = None,
        runtime_binding: Mapping[str, object] | None = None,
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
        if symbol is not None:
            raise ValueError("candidate strategy does not support symbol rebinding")
        return self._loader.load_candidate(source)

    def describe(
        self,
        source: StrategyRelease | StrategyCandidate,
        *,
        symbol: str | None = None,
        source_root: Path | None = None,
        runtime_binding: Mapping[str, object] | None = None,
    ):
        """Return the validated frozen definition without creating an instance."""

        return self._load(source, symbol, source_root, runtime_binding).definition

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
        )
