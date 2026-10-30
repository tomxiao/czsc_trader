"""Strategy Runtime (SRT) public contracts."""
from .replay_contracts import (
    ReplayPoint, AccountSnapshot, ReplayOrder, ReplayLeg, CycleBudget,
    AccountExecutionPlan, AccountPlanExecutor, StrategyComputation, ExecutionPrecision,
)
from .replay_kernel import ReplayDriver, run_account_replay
from .equity import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, UsEquitySpec,
                     ResearchExecutionSpec, ExecutionModel, DecisionPoint, EquityPortfolio,
                     EquityClosedCycle, EquityClosedCycleFeedback,
                     EquityCandidate, EquityPlan, EquityStrategyInstance, equity_implementation_hash)

from .input_binding import StrategyInputPlan, StrategyInputBinding
from .entry_cycle import CycleTarget, EntryCycleState, EntryCyclePhase, EntryCyclePlanStatus
from .pricing import ExecutionPriceBasis, ExecutionPricing
from .resources import ExecutionResources, default_worker_count
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
    OBSERVATION_PANEL_CONTRACT_VERSION,
    OBSERVATION_EXPLANATION_CONTRACT_VERSION,
    materialize_observation,
    observe_execution_plan,
    unavailable_observation,
    ObservationUnavailable, ObservationDefinition, ObservationSeries, ObservationFact, ConstantGuide, EvidenceGuide,
    ObservationValueType, ObservationFormat, StrategyObservation, ObservedSeries, ObservedFact,
)
from .signal_explanation import (
    SeriesValueRef, GuideValueRef, StateValueRef, SignalText, SignalBasisDefinition,
    SignalExplanationCase, SignalExplanationDefinition, SignalBasisSnapshot, SignalExplanationSnapshot,
)
from .signal_panel import (
    SignalAvailability, SignalRender, SignalGroup, SignalSeriesDefinition,
    SignalStateOption, SignalStateDefinition, SignalPanelDefinition,
    ObservedSignalSeries, ObservedSignalState, SignalPanelSnapshot,
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
    validate_entry_cycle_plan_facts,
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

from .account_strategy import (AccountDecision, AccountStepResult, AccountStepContext,
    PositionCycle, PositionFeedback, BatchObservation, BatchAccountContext, SellRemainderPolicy,
    AccountStrategyState, RecognizedAccountEvent, RecognizedEventKind)
from .account_replay import plan_account_decision
from .equity_definition import ExecutionInput, ExecutionInputBinding

__all__ = [
    "AccountPolicy", "CashAvailabilityPolicy", "CnEquitySpec", "UsEquitySpec",
    "ResearchExecutionSpec", "ExecutionModel", "DecisionPoint", "EquityPortfolio",
    "EquityClosedCycle", "EquityClosedCycleFeedback",
    "EquityCandidate", "EquityPlan", "EquityStrategyInstance", "equity_implementation_hash",
    "CycleTarget", "EntryCycleState", "EntryCyclePhase", "EntryCyclePlanStatus",
    "validate_entry_cycle_plan_facts",
    "ExecutionResources", "default_worker_count",
    "VerifiedReleasePackage", "load_inspection_deployment", "validate_release_package",
    "InspectionControl", "InspectionProgress", "InspectionStage", "InspectionEnvironment",
    "ImplementationFileIdentity", "InspectionRuntimePermit", "collect_inspection_environment",
    "ExecutionPriceBasis", "ExecutionPricing",
    "StrategyInputPlan", "StrategyInputBinding",
    "RuntimeBinding", "RuntimeBindingSpec",
    "observe_execution_plan",
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
    "OBSERVATION_PANEL_CONTRACT_VERSION",
    "SignalAvailability",
    "SignalRender",
    "SignalGroup",
    "SignalSeriesDefinition",
    "SignalStateOption",
    "SignalStateDefinition",
    "SignalPanelDefinition",
    "OBSERVATION_EXPLANATION_CONTRACT_VERSION",
    "SeriesValueRef", "GuideValueRef", "StateValueRef", "SignalText", "SignalBasisDefinition",
    "SignalExplanationCase", "SignalExplanationDefinition", "SignalBasisSnapshot", "SignalExplanationSnapshot",
    "ObservedSignalSeries",
    "ObservedSignalState",
    "SignalPanelSnapshot",
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

from .equity_definition import (
    EquityStrategyCandidate, EquityStrategyDefinition, EquityDecision, EquityDecisionContext,
    EquityInputBinding, EquityAuxiliaryInput, EquityAuxiliaryBinding, equity_source_hash, execution_spec_from_dict,
)
from .equity_context import build_equity_decision_context
from .equity_features import (BarField, RawField, Lag, TrueRange, Mean, SameLocalSlotMedian,
    FeatureGraph, ReadyValue, NotReady, FeatureView, HistoryView)
from .equity_replay import (StateValueType, StateField, StateRecord, StrategyStateSchema,
    CycleState, StrategyState, StepContext, StepResult, PreparedReplay, ReplayOutcome,
    ReplayStatistics, ReplayFailure, run_replay)

__all__ += ["EquityStrategyCandidate", "EquityStrategyDefinition", "EquityDecision", "EquityDecisionContext",
            "EquityInputBinding", "EquityAuxiliaryInput", "EquityAuxiliaryBinding", "equity_source_hash", "execution_spec_from_dict",
            "build_equity_decision_context"]
__all__ += ['BarField', 'RawField', 'Lag', 'TrueRange', 'Mean', 'SameLocalSlotMedian',
    'FeatureGraph', 'ReadyValue', 'NotReady', 'FeatureView', 'HistoryView',
    'StateValueType', 'StateField', 'StateRecord', 'StrategyStateSchema', 'CycleState',
    'StrategyState', 'StepContext', 'StepResult', 'PreparedReplay', 'ReplayOutcome',
    'ReplayStatistics', 'ReplayFailure', 'run_replay']
__all__ += ['ReplayPoint', 'AccountSnapshot', 'ReplayOrder', 'ReplayLeg', 'CycleBudget',
    'AccountExecutionPlan', 'AccountPlanExecutor', 'StrategyComputation', 'ExecutionPrecision',
    'ReplayDriver', 'run_account_replay']

__all__ += ['AccountDecision', 'AccountStepResult', 'AccountStepContext', 'PositionCycle',
    'PositionFeedback', 'BatchObservation', 'BatchAccountContext', 'SellRemainderPolicy', 'plan_account_decision',
    'AccountStrategyState', 'RecognizedAccountEvent', 'RecognizedEventKind']

__all__ += ['ExecutionInput', 'ExecutionInputBinding']
