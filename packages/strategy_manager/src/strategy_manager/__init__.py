"""Strategy identity, lifecycle, and performance evidence domain package."""

from .errors import (
    EvidenceRequiredError,
    ImmutableVersionError,
    InvalidTransitionError,
    RegistryError,
    StrategyManagerError,
    ValidationError,
)
from .models import (
    EvidencePhase,
    GovernanceResult,
    GovernanceStage,
    LifecycleEvent,
    PerformanceEvidence,
    Qualification,
    PaperTradingApproval,
    ResearchState,
    StrategyFamily,
    StrategyGovernanceCredential,
    StrategyGovernanceSeal,
    StrategyVersion,
    canonical_sha256,
)
from .registry import StrategyRegistry
from .candidates import (
    CandidateKey, CandidateEvidence, CandidateRegistrationOrigin, CandidateRegistration,
    CandidateDerivation, CandidateDerivationKind, CandidateIdentityConflict,
)
from .freeze_contracts import (
    ResearchEvidenceOwner, ResearchEvidenceRef, ResearchEvidenceLocation,
    CandidateOrigin, CandidateInspectionReport, CandidateSelectionSubject,
    DecisionAction, DecisionReference, FreezeCandidateRequest, FreezeFile,
    FreezePlan, FreezeReceipt, FreezeRequestId, FreezeStatus,
    FreezeSubject, FrozenVersionReference, InspectionCheck, InspectionCheckResult,
    InspectionCoordinate, InspectionProtocol, InspectionStatus, ResearchDecision,
    StageAdvanceSubject,
)
from .freeze_store import FreezeVersionRequest

__all__ = [
    "PaperTradingApproval",
    "ResearchEvidenceOwner", "ResearchEvidenceRef", "ResearchEvidenceLocation",
    "CandidateOrigin", "CandidateInspectionReport", "CandidateSelectionSubject",
    "DecisionAction", "DecisionReference", "FreezeCandidateRequest", "FreezeFile",
    "FreezePlan", "FreezeReceipt", "FreezeRequestId", "FreezeStatus",
    "FreezeSubject", "FrozenVersionReference", "InspectionCheck", "InspectionCheckResult",
    "InspectionCoordinate", "InspectionProtocol", "InspectionStatus", "ResearchDecision",
    "StageAdvanceSubject", "FreezeVersionRequest",
    "CandidateKey", "CandidateEvidence", "CandidateRegistrationOrigin", "CandidateRegistration",
    "CandidateDerivation", "CandidateDerivationKind", "CandidateIdentityConflict",
    "EvidencePhase",
    "EvidenceRequiredError",
    "GovernanceResult",
    "GovernanceStage",
    "ImmutableVersionError",
    "InvalidTransitionError",
    "LifecycleEvent",
    "PerformanceEvidence",
    "Qualification",
    "ResearchState",
    "RegistryError",
    "StrategyFamily",
    "StrategyGovernanceCredential",
    "StrategyGovernanceSeal",
    "StrategyRegistry",
    "StrategyManagerError",
    "StrategyVersion",
    "ValidationError",
    "canonical_sha256",
]
