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

__all__ = [
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
