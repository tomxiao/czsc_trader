"""Pre-freeze acceptance for one immutable strategy runtime release."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
import json
from pathlib import Path

from strategy_manager import StrategyVersion, canonical_sha256
from strategy_runtime import StrategyRelease, StrategyRuntime


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def prospective_release(version: StrategyVersion) -> StrategyRelease:
    """Build the exact frozen release identity without mutating SM state."""

    release_hash = version.release_hash or canonical_sha256(version.release_payload())
    frozen = replace(version, release_hash=release_hash)
    return StrategyRelease.from_mapping(frozen.to_dict())


def _runtime_report(definition) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "PASS",
        "release_id": definition.release_id,
        "release_hash": definition.release_hash,
        "identity_kind": definition.identity_kind,
        "runtime_sha256": definition.runtime_sha256,
        "parameters_sha256": definition.parameters.sha256,
        "implementation": {
            "module": definition.implementation.module,
            "qualname": definition.implementation.qualname,
            "contract_version": definition.implementation.contract_version,
            "source_sha256": definition.implementation.source_sha256,
        },
        "input_contract_sha256": canonical_sha256(
            [asdict(item) for item in definition.inputs.requirements]
        ),
        "input_contract": {
            "requirements": [asdict(item) for item in definition.inputs.requirements],
        },
        "history_policy_sha256": canonical_sha256(asdict(definition.history)),
        "history_policy": asdict(definition.history),
        "decision_contract_sha256": canonical_sha256(asdict(definition.decision)),
        "decision_contract": asdict(definition.decision),
        "execution_policy_sha256": canonical_sha256(
            {
                "policy_type": definition.execution.policy_type,
                "settings": _plain(definition.execution.settings),
            }
        ),
        "execution_policy": {
            "policy_type": definition.execution.policy_type,
            "settings": _plain(definition.execution.settings),
        },
        "state_mode": definition.state_mode,
        "capabilities_sha256": canonical_sha256(asdict(definition.capabilities)),
        "monitoring_sha256": canonical_sha256(
            {
                "policy_type": definition.monitoring.policy_type,
                "rules": _plain(definition.monitoring.rules),
            }
        ),
    }


def validate_runtime_readiness(
    version: StrategyVersion,
    *,
    source_root: Path | None = None,
) -> dict[str, object]:
    """Load the exact prospective release without changing SM state."""
    binding = None
    if source_root is not None:
        binding_path = Path(source_root).resolve().parent.parent / "runtime_binding.json"
        if binding_path.is_file():
            value = json.loads(binding_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("strategy version runtime binding must be an object")
            binding = value
    return _runtime_report(
        StrategyRuntime().describe(
            prospective_release(version),
            source_root=source_root,
            runtime_binding=binding,
        )
    )


def require_same_runtime_content(candidate: dict, release: dict) -> None:
    """Only lifecycle identity may change when a reviewed candidate is frozen."""
    if candidate.get("identity_kind") != "CANDIDATE" or release.get("identity_kind") != "RELEASE":
        raise ValueError("freeze requires candidate-to-release runtime identities")
    for key in (
        "implementation",
        "parameters_sha256",
        "strategy_payload_hash",
        "input_contract_sha256",
        "decision_contract_sha256",
        "execution_policy_sha256",
        "history_policy_sha256",
        "state_mode",
        "capabilities_sha256",
        "monitoring_sha256",
    ):
        if key not in candidate or candidate[key] != release.get(key):
            raise ValueError(f"frozen runtime differs from reviewed candidate: {key}")


def require_runtime_readiness(
    version: StrategyVersion,
    validator=validate_runtime_readiness,
) -> dict[str, object]:
    """Reject false-success readiness reports before SM freezes a version."""

    report = validator(version)
    release = prospective_release(version)
    if not isinstance(report, dict) or report.get("status") != "PASS":
        raise ValueError("strategy runtime readiness did not pass")
    if report.get("release_id") != release.release_id:
        raise ValueError("strategy runtime readiness belongs to another release")
    if report.get("release_hash") != release.release_hash:
        raise ValueError("strategy runtime readiness release hash differs")
    runtime_sha256 = report.get("runtime_sha256")
    if not isinstance(runtime_sha256, str) or len(runtime_sha256) != 64:
        raise ValueError("strategy runtime readiness is missing runtime identity")
    return report
