"""Record observation facts while forwarding real plans to the executor."""

from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite
import re

from strategy_runtime import (
    observe_execution_plan,
    ObservationUnavailable,
    StrategyIdentity,
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


@dataclass(frozen=True)
class UnavailablePlanObservation:
    """Attach failed display computation to its successfully validated plan."""

    strategy: StrategyIdentity
    definition_sha256: str
    signal_identity: str
    plan_identity: str
    signal_date: date
    valid_session: date
    action: str
    target_position: float
    unavailable: ObservationUnavailable

    def __post_init__(self):
        if not isinstance(self.strategy, StrategyIdentity) or not isinstance(self.unavailable, ObservationUnavailable):
            raise TypeError("unavailable plan observation requires typed identity and failure")
        if any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
               for value in (self.definition_sha256, self.signal_identity, self.plan_identity)):
            raise ValueError("unavailable plan observation requires SHA-256 identities")
        if (type(self.signal_date) is not date or type(self.valid_session) is not date
                or self.signal_date >= self.valid_session):
            raise ValueError("unavailable plan observation requires ordered session dates")
        if type(self.action) is not str or not self.action.strip():
            raise ValueError("unavailable plan observation requires an action")
        if (type(self.target_position) not in (int, float) or not isfinite(self.target_position)
                or not 0 <= self.target_position <= 1):
            raise ValueError("unavailable plan observation requires a finite target in [0, 1]")

    def to_dict(self):
        return {"contract_version": "tdr_plan_observation.v1",
                "observation": self.unavailable.to_dict(), "strategy": asdict(self.strategy),
                "definition_sha256": self.definition_sha256,
                "signal_identity": self.signal_identity, "plan_identity": self.plan_identity,
                "signal_date": self.signal_date.isoformat(), "valid_session": self.valid_session.isoformat(),
                "action": self.action, "target_position": self.target_position}

    @classmethod
    def from_dict(cls, value):
        fields = {"contract_version", "observation", "strategy", "definition_sha256",
                  "signal_identity", "plan_identity", "signal_date", "valid_session", "action", "target_position"}
        if (type(value) is not dict or set(value) != fields
                or value["contract_version"] != "tdr_plan_observation.v1"):
            raise ValueError("invalid unavailable plan observation envelope")
        identity = value["strategy"]
        if type(identity) is not dict or set(identity) != {
                "strategy_id", "reference_id", "release_hash", "runtime_sha256", "symbol"}:
            raise ValueError("invalid unavailable plan observation strategy identity")
        return cls(StrategyIdentity(**identity), value["definition_sha256"], value["signal_identity"],
                   value["plan_identity"], date.fromisoformat(value["signal_date"]),
                   date.fromisoformat(value["valid_session"]), value["action"], value["target_position"],
                   ObservationUnavailable.from_dict(value["observation"]))


class ObservationExecutor:
    def __init__(self, definition: RuntimeDefinition, executor: WindowExecutor) -> None:
        self.definition = definition
        self.executor = executor
        self.observations: list[StrategyObservation | UnavailablePlanObservation] = []

    @property
    def capabilities(self) -> ExecutionCapabilities:
        return self.executor.capabilities

    def snapshot(self, point: TradingPoint) -> tuple[PortfolioSnapshot, ExecutionState]:
        return self.executor.snapshot(point)

    def execute(self, plan: ExecutionPlan) -> ExecutionOutcome:
        observation = observe_execution_plan(self.definition, plan)
        if isinstance(observation, ObservationUnavailable):
            observation = UnavailablePlanObservation(
                plan.strategy, self.definition.observation.sha256, plan.signal_identity,
                plan.plan_identity, plan.signal_date, plan.trading_date, plan.action,
                plan.target_position, observation,
            )
        result = self.executor.execute(plan)
        self.observations.append(observation)
        return result

    def finish(self) -> object:
        return self.executor.finish()
