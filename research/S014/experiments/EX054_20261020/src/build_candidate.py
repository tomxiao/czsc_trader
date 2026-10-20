"""Build authenticated, unregistered C9524 stage-four coordinate values."""

from collections.abc import Mapping
from pathlib import Path

from strategy_runtime import (
    DecisionFeedback,
    StrategyCandidate,
    StrategyRuntime,
    implementation_sha256,
)


SOURCE_ROOT = Path(__file__).resolve().parent / "strategy_runtime"
CENTER_PARAMETERS = {
    "permission_profile": "AGE_PRIOR_TREND_PERMISSION",
    "support_window": 5,
    "warmup_sessions": 60,
    "holding_horizon": 10,
    "trend_window": 20,
    "trend_lag": 5,
    "atr_window": 20,
    "shock_window": 5,
    "volatility_window": 20,
    "shock_z": 2.0,
    "cost_atr": 1.0,
}


def build(parameters: Mapping | None = None, *, candidate_id: str = "C9524"):
    """Validate a complete parameter point without registration or account execution.

    Domain bounds and joint-perturbation design belong to the predeclared study
    plan. This builder enforces the implementation's exact types and legal
    indicator sizes; it does not invent or repair a caller's coordinates.
    """
    if parameters is not None and not isinstance(parameters, Mapping):
        raise ValueError("Complete parameter mapping required")
    values = dict(CENTER_PARAMETERS if parameters is None else parameters)
    source_hash = implementation_sha256(
        ("strategies/trend_permission.py",), source_root=SOURCE_ROOT
    )
    payload = {
        "parameters": values,
        "decision_feedback": DecisionFeedback.SIMULATED_FILL_FEEDBACK.value,
        "runtime": {
            "contract_version": 2,
            "module": "strategy_runtime.strategies.trend_permission",
            "qualname": "TrendPermissionStrategy",
            "source_files": ["strategies/trend_permission.py"],
            "source_sha256": source_hash,
        },
    }
    candidate = StrategyCandidate("S014", candidate_id, payload, SOURCE_ROOT)
    return candidate, StrategyRuntime().describe(candidate)
