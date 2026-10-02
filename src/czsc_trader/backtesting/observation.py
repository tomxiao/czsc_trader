"""Record observation facts while forwarding real plans to the executor."""

from strategy_runtime import (
    materialize_observation,
    RuntimeDefinition,
    WindowExecutor,
    StrategyObservation,
    ExecutionCapabilities,
    TradingPoint,
    PortfolioSnapshot,
    ExecutionState,
    ExecutionPlan,
    ExecutionOutcome,
)


class ObservationExecutor:
    def __init__(self, definition: RuntimeDefinition, executor: WindowExecutor) -> None:
        self.definition = definition
        self.executor = executor
        self.observations: list[StrategyObservation] = []

    @property
    def capabilities(self) -> ExecutionCapabilities:
        return self.executor.capabilities

    def snapshot(self, point: TradingPoint) -> tuple[PortfolioSnapshot, ExecutionState]:
        return self.executor.snapshot(point)

    def execute(self, plan: ExecutionPlan) -> ExecutionOutcome:
        observation = materialize_observation(self.definition, plan)
        result = self.executor.execute(plan)
        self.observations.append(observation)
        return result

    def finish(self) -> object:
        return self.executor.finish()
