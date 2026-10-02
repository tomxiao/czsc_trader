"""Disk-backed verification for completed REX experiment evidence."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .contracts import (
    ExperimentArtifact,
    ExperimentCapability,
    ExperimentInput,
    ExperimentOutcome,
    ExperimentReceipt,
    ExperimentTrace,
    ExperimentDataScope,
    EvaluationRecord,
    EvaluationAttemptStatus,
    _canonical_sha256,
    _freeze_json,
    _safe_relative_path,
    _thaw_json,
)


_SHA256 = re.compile(r"[0-9a-f]{64}")
_ENVELOPE_FILE = "execution_envelope.json"
_RECEIPT_FILE = "execution_receipt.json"


def _exact_mapping(value: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} fields differ from schema")
    return value


def _read_document(path: Path, name: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {name}: {path}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _trace_from_mapping(value: Any, *, schema_version: int) -> ExperimentTrace:
    if type(schema_version) is not int or schema_version != 2:
        raise ValueError("experiment receipt schema_version must be 2")
    payload = _exact_mapping(
        value,
        {"capabilities", "operations", "data_requests", "evaluations", "data_scope"},
        "experiment trace",
    )
    capabilities = payload["capabilities"]
    operations = payload["operations"]
    data_requests = payload["data_requests"]
    evaluations = payload["evaluations"]
    if not isinstance(capabilities, list):
        raise ValueError("experiment trace capabilities must be a list")
    if not isinstance(operations, list):
        raise ValueError("experiment trace operations must be a list")
    if not isinstance(data_requests, list):
        raise ValueError("experiment trace data_requests must be a list")
    if not isinstance(evaluations, list):
        raise ValueError("experiment trace evaluations must be a list")
    try:
        parsed_capabilities = tuple(ExperimentCapability(item) for item in capabilities)
    except (TypeError, ValueError) as exc:
        raise ValueError("experiment trace contains an invalid capability") from exc
    return ExperimentTrace(
        capabilities=parsed_capabilities,
        operations=tuple(operations),
        data_requests=tuple(data_requests),
        evaluations=tuple(EvaluationRecord.from_dict(item) for item in evaluations),
        data_scope=ExperimentDataScope(payload["data_scope"]),
    )


def _receipt_from_mapping(value: Any) -> ExperimentReceipt:
    payload = _exact_mapping(
        value,
        {
            "schema_version",
            "experiment_id",
            "definition_sha256",
            "source_sha256",
            "resources_sha256",
            "predecessor_receipts",
            "result_sha256",
            "artifact_sha256",
            "trace",
        },
        "experiment receipt",
    )
    predecessors = payload["predecessor_receipts"]
    artifacts = payload["artifact_sha256"]
    if not isinstance(predecessors, Mapping):
        raise ValueError("receipt predecessor_receipts must be an object")
    if not isinstance(artifacts, Mapping):
        raise ValueError("receipt artifact_sha256 must be an object")
    return ExperimentReceipt._from_execution(
        schema_version=payload["schema_version"],
        experiment_id=payload["experiment_id"],
        definition_sha256=payload["definition_sha256"],
        source_sha256=payload["source_sha256"],
        resources_sha256=payload["resources_sha256"],
        predecessor_receipts=predecessors,
        result_sha256=payload["result_sha256"],
        artifact_sha256=artifacts,
        trace=_trace_from_mapping(payload["trace"], schema_version=payload["schema_version"]),
    )


def _result_from_mapping(
    value: Any,
) -> tuple[ExperimentOutcome, Mapping[str, Any], tuple[ExperimentArtifact, ...], dict[str, object]]:
    payload = _exact_mapping(
        value,
        {"outcome", "facts", "diagnostics", "artifacts", "candidate"},
        "experiment result",
    )
    try:
        outcome = ExperimentOutcome(payload["outcome"])
    except (TypeError, ValueError) as exc:
        raise ValueError("experiment result outcome is invalid") from exc
    facts = _freeze_json(payload["facts"], "result facts")
    diagnostics = _freeze_json(payload["diagnostics"], "result diagnostics")
    artifact_values = payload["artifacts"]
    if not isinstance(artifact_values, list):
        raise ValueError("experiment result artifacts must be a list")
    artifacts: list[ExperimentArtifact] = []
    for item in artifact_values:
        artifact = _exact_mapping(
            item, {"path", "kind", "sha256"}, "experiment result artifact"
        )
        artifacts.append(
            ExperimentArtifact(
                path=artifact["path"],
                kind=artifact["kind"],
                sha256=artifact["sha256"],
            )
        )
    paths = tuple(item.path for item in artifacts)
    if len(paths) != len(set(paths)):
        raise ValueError("experiment result artifact paths must be unique")
    candidate = payload["candidate"]
    normalized_candidate: dict[str, str] | None
    if candidate is None:
        normalized_candidate = None
    else:
        candidate_payload = _exact_mapping(
            candidate,
            {"reference_id", "runtime_identity_sha256"},
            "experiment result candidate",
        )
        reference_id = candidate_payload["reference_id"]
        identity = candidate_payload["runtime_identity_sha256"]
        if not isinstance(reference_id, str) or not reference_id.strip():
            raise ValueError("experiment result candidate reference_id is invalid")
        if not isinstance(identity, str) or _SHA256.fullmatch(identity) is None:
            raise ValueError("experiment result candidate identity is invalid")
        normalized_candidate = {
            "reference_id": reference_id.strip(),
            "runtime_identity_sha256": identity,
        }
    normalized = {
        "outcome": outcome.value,
        "facts": _thaw_json(facts),
        "diagnostics": _thaw_json(diagnostics),
        "artifacts": [
            {"path": item.path, "kind": item.kind, "sha256": item.sha256}
            for item in artifacts
        ],
        "candidate": normalized_candidate,
    }
    return outcome, facts, tuple(artifacts), normalized


def _validate_artifact(root: Path, artifact: ExperimentArtifact) -> None:
    relative = _safe_relative_path(artifact.path)
    target = root.joinpath(*PurePosixPath(relative).parts).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("experiment artifact escapes the execution workspace") from exc
    if not target.is_file():
        raise FileNotFoundError(f"experiment artifact does not exist: {target}")
    if sha256(target.read_bytes()).hexdigest() != artifact.sha256:
        raise ValueError(f"experiment artifact hash differs: {artifact.path}")


def load_experiment_input(
    workspace_root: Path,
    *,
    expected_receipt_sha256: str,
) -> ExperimentInput:
    """Load predecessor evidence matching an independently retained receipt identity."""

    root = Path(workspace_root).resolve()
    envelope = _exact_mapping(
        _read_document(root / _ENVELOPE_FILE, "experiment execution envelope"),
        {"schema_version", "receipt", "receipt_sha256", "result"},
        "experiment execution envelope",
    )
    if envelope["schema_version"] != 1:
        raise ValueError("experiment execution envelope schema_version must be 1")
    receipt = _receipt_from_mapping(envelope["receipt"])
    recorded_receipt_hash = envelope["receipt_sha256"]
    if not isinstance(recorded_receipt_hash, str) or _SHA256.fullmatch(recorded_receipt_hash) is None:
        raise ValueError("experiment execution envelope receipt_sha256 is invalid")
    if receipt.sha256 != recorded_receipt_hash:
        raise ValueError("experiment execution receipt hash differs")
    if not isinstance(expected_receipt_sha256, str) or _SHA256.fullmatch(
        expected_receipt_sha256
    ) is None:
        raise ValueError("expected receipt SHA-256 must be lowercase SHA-256")
    if receipt.sha256 != expected_receipt_sha256:
        raise ValueError("experiment execution receipt differs from expected identity")

    outcome, facts, artifacts, result_payload = _result_from_mapping(envelope["result"])
    if _canonical_sha256(result_payload) != receipt.result_sha256:
        raise ValueError("experiment execution result hash differs")
    artifact_hashes = {item.path: item.sha256 for item in artifacts}
    if artifact_hashes != dict(receipt.artifact_sha256):
        raise ValueError("experiment execution artifacts differ from receipt")
    attempts = set()
    candidates = {}
    for record in receipt.trace.evaluations:
        if record.experiment_id != receipt.experiment_id or record.attempt_id in attempts:
            raise ValueError("evaluation attempt identity differs or is duplicated")
        attempts.add(record.attempt_id)
        previous = candidates.setdefault(record.candidate_id, record.content_sha256)
        if previous != record.content_sha256:
            raise ValueError("candidate ID has conflicting content in execution evidence")
        if record.status is EvaluationAttemptStatus.STARTED:
            raise ValueError("completed execution contains an unfinished evaluation")
        if record.status is EvaluationAttemptStatus.SUCCEEDED and artifact_hashes.get(record.result_artifact.path) != record.result_artifact.sha256:
            raise ValueError("successful evaluation artifact is missing from execution evidence")
    for artifact in artifacts:
        _validate_artifact(root, artifact)

    receipt_path = root / _RECEIPT_FILE
    if not receipt_path.is_file():
        raise ValueError("execution receipt publication is incomplete")
    if receipt_path.exists():
        receipt_document = _exact_mapping(
            _read_document(receipt_path, "experiment execution receipt"),
            set(receipt.to_dict()) | {"receipt_sha256"},
            "experiment execution receipt",
        )
        if receipt_document != {**receipt.to_dict(), "receipt_sha256": receipt.sha256}:
            raise ValueError("experiment execution receipt differs from envelope")

    return ExperimentInput._from_receipt(
        experiment_id=receipt.experiment_id,
        receipt_sha256=receipt.sha256,
        outcome=outcome,
        facts=facts,
        artifacts=artifacts,
    )


__all__ = ["load_experiment_input"]
