"""Public, offline inspection of an authenticated release in the real PTE."""
from strategy_runtime.inspection import InspectionControl
from .inspection_contracts import (
    SubmissionOutcome, InspectionOrderStatus, PteInspectionStatus,
    PteInspectionCapability, CoverageRequirement, PteFault,
    PteEnvironmentRequirement, PteDecisionInput, PteOrderKey,
    PteSubmissionResult, PteOrderUpdate, PteRepeatedOrderReport,
    PteChannelEvent, PteCheckpointExpectation, PteInspectionScenario,
    PteCoverageRequirement, PteFailureCase, PteInspectionProtocol,
    InputContentIdentity, InspectionInputCopy, PteReleaseInspectionRequest,
    PteArtifact, PteScenarioResult, PteCoverageResult, PteInspectionOutcome,
)

__all__ = [
    "SubmissionOutcome", "InspectionOrderStatus", "PteInspectionStatus",
    "PteInspectionCapability", "CoverageRequirement", "PteFault",
    "PteEnvironmentRequirement", "PteDecisionInput", "PteOrderKey",
    "PteSubmissionResult", "PteOrderUpdate", "PteRepeatedOrderReport",
    "PteChannelEvent", "PteCheckpointExpectation", "PteInspectionScenario",
    "PteCoverageRequirement", "PteFailureCase", "PteInspectionProtocol",
    "InputContentIdentity", "InspectionInputCopy", "PteReleaseInspectionRequest",
    "PteArtifact", "PteScenarioResult", "PteCoverageResult", "PteInspectionOutcome",
    "inspect_release",
]


def inspect_release(request: PteReleaseInspectionRequest, *, control: InspectionControl | None = None) -> PteInspectionOutcome:
    from .inspection_runner import inspect_release as run
    return run(request, control=control)
