"""Strategy Runtime (SRT) public contracts."""

from .input_binding import StrategyInputPlan, StrategyInputBinding
from .pricing import ExecutionPriceBasis, ExecutionPricing
from .algorithm import StrategyImplementation, StrategyImplementationV2
from .identity import CandidateContentIdentity, ImplementationDependency
from .alignment import AlignmentRule, AlignedInput, InputAlignment, align_input_history
from .calculation import (
    CalculationScope,
    HistoryCalculationContext,
)
from .binding import RuntimeBinding, RuntimeBindingSpec
from .observation import (
    OBSERVATION_CONTRACT_VERSION,
    materialize_observation,
    unavailable_observation,
    ObservationUnavailable, ObservationDefinition, ObservationSeries, ObservationFact, ConstantGuide, EvidenceGuide,
    ObservationValueType, ObservationFormat, StrategyObservation, ObservedSeries, ObservedFact,
)
from .contracts import (
    DataPreparationResult,
    ExecutionCapabilities,
    ExecutionOutcome,
    ExecutionOutcomeStatus,
    ExecutionPlan,
    ExecutionState,
    OrderSide,
    OrderType,
    PlanLeg,
    PlannedOrder,
    PortfolioSnapshot,
    PriceReference,
    StrategyIdentity,
    SignalHistoryMode,
    TradableWindow,
    TradingPoint,
    WindowExecutor,
)
from .errors import (
    RuntimeCompatibilityError,
    RuntimeContractError,
    RuntimeExecutionError,
    StrategyRuntimeError,
)
from .deployment import (StrategyDeployment, VerifiedReleasePackage, deployment_inventory,
                         load_strategy_deployment, load_inspection_deployment, validate_release_package)
from .inspection import (InspectionControl, InspectionProgress, InspectionStage, InspectionEnvironment,
                         ImplementationFileIdentity, InspectionRuntimePermit, collect_inspection_environment)
from .models import (
    CutoffRule,
    DecisionContract,
    DecisionFeedback,
    ExecutionPolicy,
    HistoryPolicy,
    ImplementationRef,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    RuntimeDefinition,
    StrategyDefinition,
    StrategyCandidate,
    StrategyRelease,
    canonical_sha256,
)
from .implementation_identity import implementation_sha256
from .runtime import StrategyInit, StrategyRuntime
from .strategy import StrategyInstance

__version__ = "0.1.0"

__all__ = [
    "VerifiedReleasePackage", "load_inspection_deployment", "validate_release_package",
    "InspectionControl", "InspectionProgress", "InspectionStage", "InspectionEnvironment",
    "ImplementationFileIdentity", "InspectionRuntimePermit", "collect_inspection_environment",
    "ExecutionPriceBasis", "ExecutionPricing",
    "StrategyInputPlan", "StrategyInputBinding",
    "RuntimeBinding", "RuntimeBindingSpec",
    "ObservationUnavailable", "ObservationDefinition", "ObservationSeries", "ObservationFact", "ConstantGuide", "EvidenceGuide",
    "ObservationValueType", "ObservationFormat", "StrategyObservation", "ObservedSeries", "ObservedFact",
    "CandidateContentIdentity",
    "ImplementationDependency",
    "ExecutionOutcomeStatus",
    "SignalHistoryMode",
    "AlignedInput",
    "AlignmentRule",
    "DataPreparationResult",
    "CalculationScope",
    "HistoryCalculationContext",
    "CutoffRule",
    "ExecutionCapabilities",
    "DecisionContract",
    "DecisionFeedback",
    "ExecutionOutcome",
    "ExecutionPlan",
    "ExecutionPolicy",
    "ExecutionState",
    "HistoryPolicy",
    "ImplementationRef",
    "InputContract",
    "InputAlignment",
    "InputRequirement",
    "MonitoringPolicy",
    "OrderSide",
    "OrderType",
    "OBSERVATION_CONTRACT_VERSION",
    "PlanLeg",
    "PlannedOrder",
    "PortfolioSnapshot",
    "PriceReference",
    "ParameterSet",
    "RequiredCapabilities",
    "RuntimeCompatibilityError",
    "RuntimeContractError",
    "RuntimeDefinition",
    "StrategyDefinition",
    "RuntimeExecutionError",
    "StrategyCandidate",
    "StrategyDeployment",
    "StrategyIdentity",
    "StrategyInit",
    "StrategyImplementation",
    "StrategyImplementationV2",
    "StrategyInstance",
    "StrategyRelease",
    "StrategyRuntime",
    "StrategyRuntimeError",
    "TradableWindow",
    "TradingPoint",
    "WindowExecutor",
    "canonical_sha256",
    "align_input_history",
    "deployment_inventory",
    "load_strategy_deployment",
    "materialize_observation",
    "implementation_sha256",
    "unavailable_observation",
]
