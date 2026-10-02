"""SRT-only deployment and query commands for frozen strategy versions."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any

from strategy_manager import StrategyRegistry, canonical_sha256
from strategy_runtime import (
    StrategyRuntime,
    RuntimeBinding,
    load_strategy_deployment,
)

from .context import RepositoryContext
from .errors import ValidationError
from .results import CommandResult
from .runtime_acceptance import prospective_release


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or "\\" in value
        or ":" in value
    ):
        raise ValueError(f"{field} contains an unsafe path")
    return value


def _version_parts(reference: str) -> tuple[str, str]:
    strategy_id, separator, version = reference.rpartition("-")
    if (
        not separator
        or not strategy_id.startswith("S")
        or not strategy_id[1:].isdigit()
        or not version.startswith("v")
        or not version[1:].isdigit()
    ):
        raise ValueError(f"invalid strategy version id: {reference}")
    return strategy_id, version


def validate_release_package(
    context: RepositoryContext,
    reference: str,
    *,
    expected_release=None,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    strategy_id, version = _version_parts(reference)
    root = context.strategy_root / strategy_id / "releases" / version
    manifest = _read_object(root / "release_manifest.json")
    expected_fields = {
        "schema_version",
        "strategy_version_id",
        "strategy_version_hash",
        "source_candidate_id",
        "candidate_package_hash",
        "runtime_root",
        "runtime_binding",
        "files",
        "package_hash",
    }
    if set(manifest) != expected_fields or manifest["schema_version"] != 1:
        raise ValueError("strategy version package manifest is invalid")
    identity = dict(manifest)
    package_hash = identity.pop("package_hash")
    if package_hash != canonical_sha256(identity) or manifest["strategy_version_id"] != reference:
        raise ValueError("strategy version package identity is invalid")
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("strategy version package has no file identities")
    normalized_files: set[str] = set()
    for name, expected_hash in files.items():
        safe_name = _safe_relative(name, "files")
        relative = PurePosixPath(safe_name)
        path = root.joinpath(*relative.parts)
        if (
            not isinstance(expected_hash, str)
            or not path.is_file()
            or _file_sha256(path) != expected_hash
        ):
            raise ValueError(f"strategy version package file differs: {name}")
        normalized_files.add(safe_name)
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != root / "release_manifest.json"
    }
    if normalized_files != actual_files:
        raise ValueError("strategy version package contains untracked or missing files")
    runtime_root = root / _safe_relative(manifest["runtime_root"], "runtime_root")
    binding = _read_object(root / _safe_relative(manifest["runtime_binding"], "runtime_binding"))
    RuntimeBinding.from_dict(binding)
    if (
        binding.get("release_id") != reference
        or binding.get("release_hash") != manifest["strategy_version_hash"]
    ):
        raise ValueError("strategy version runtime binding identity differs")
    install_files = binding.get("install_files")
    if not isinstance(install_files, list) or not install_files:
        raise ValueError("strategy version runtime binding has no install files")
    normalized_install_files = tuple(
        _safe_relative(name, "install_files") for name in install_files
    )
    if len(normalized_install_files) != len(set(normalized_install_files)):
        raise ValueError("strategy version runtime binding repeats install files")
    release = expected_release
    if release is None:
        registry = StrategyRegistry(context.strategy_root)
        stored = registry.get_version(strategy_id, version)
        if stored.release_hash != manifest["strategy_version_hash"]:
            raise ValueError("strategy version package differs from frozen registry identity")
        release = prospective_release(stored)
    elif (
        release.release_id != reference or release.release_hash != manifest["strategy_version_hash"]
    ):
        raise ValueError("strategy version package differs from expected release identity")
    StrategyRuntime().describe(
        release,
        source_root=runtime_root,
        runtime_binding=RuntimeBinding.from_dict(binding),
    )
    return manifest, binding, runtime_root


def _receipt_path(root: Path, reference: str) -> Path:
    return root / "deployments" / f"{reference}.json"


def _deployment_receipt(root: Path, reference: str) -> dict[str, Any] | None:
    path = _receipt_path(root, reference)
    if not path.is_file():
        return None
    value = _read_object(path)
    receipt_hash = value.pop("receipt_hash", None)
    if receipt_hash != canonical_sha256(value):
        raise ValueError("SRT deployment receipt hash mismatch")
    value["receipt_hash"] = receipt_hash
    return value


def deploy_strategy(context: RepositoryContext, reference: str) -> CommandResult:
    created_receipt = False
    receipt_path: Path | None = None
    try:
        manifest, binding, source_root = validate_release_package(context, reference)
        registry = StrategyRegistry(context.strategy_root)
        strategy_id, version = _version_parts(reference)
        release = prospective_release(registry.get_version(strategy_id, version))
        definition = StrategyRuntime().describe(
            release,
            source_root=source_root,
            runtime_binding=RuntimeBinding.from_dict(binding),
        )
        receipt_payload = {
            "schema_version": 1,
            "strategy_version_id": reference,
            "strategy_version_hash": manifest["strategy_version_hash"],
            "release_package": source_root.parent.parent.relative_to(
                context.strategy_root
            ).as_posix(),
            "package_hash": manifest["package_hash"],
        }
        receipt = {**receipt_payload, "receipt_hash": canonical_sha256(receipt_payload)}
        receipt_path = _receipt_path(context.strategy_root, reference)
        existing_receipt = _deployment_receipt(context.strategy_root, reference)
        if existing_receipt is not None and existing_receipt != receipt:
            raise ValueError("strategy deployment receipt conflicts with strategy version")
        if existing_receipt is None:
            _write_object(receipt_path, receipt)
            created_receipt = True
        deployment = load_strategy_deployment(context.strategy_root, reference)
        StrategyRuntime(context.strategy_root).describe(release)
    except Exception as exc:
        if created_receipt and receipt_path is not None:
            receipt_path.unlink(missing_ok=True)
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(
            "strategy_deploy_failed",
            str(exc),
            context={"command": "strategy.deploy", "strategy_version_id": reference},
        ) from exc
    return CommandResult(
        "PASS",
        "strategy.deploy",
        {
            "strategy_version_id": reference,
            "deployment_state": "SRT_DEPLOYED",
            "runtime_hash": definition.runtime_sha256,
            "receipt_hash": deployment.receipt_hash,
        },
    )


def _installed_identity(context: RepositoryContext, reference: str) -> dict[str, Any]:
    deployment = load_strategy_deployment(context.strategy_root, reference)
    binding = deployment.binding
    strategy_id, version = _version_parts(reference)
    registry = StrategyRegistry(context.strategy_root)
    stored = registry.get_version(strategy_id, version)
    family = registry.get_family(strategy_id)
    release = prospective_release(stored)
    if (
        binding.release_id != reference
        or binding.release_hash != release.release_hash
    ):
        raise ValueError("SRT binding differs from frozen strategy version")
    definition = StrategyRuntime(context.strategy_root).describe(release)
    candidate = stored.source_candidate
    if candidate is not None:
        candidate = str(candidate)
    if candidate is not None and not candidate.startswith(f"{strategy_id}-"):
        candidate = f"{strategy_id}-{candidate}"
    fee_rate = (
        stored.strategy_payload.get("rule", {})
        .get("execution", {})
        .get("capital", {})
        .get("fee_rate")
    )
    return {
        "strategy_id": strategy_id,
        "name": family.name,
        "version": version,
        "strategy_version_id": reference,
        "strategy_version_hash": release.release_hash,
        "source_candidate_id": candidate,
        "qualification": registry.current_qualification(strategy_id, version).value,
        "selection_data_cutoff": stored.selection_data_cutoff,
        "fee_rate": fee_rate,
        "runtime_hash": definition.runtime_sha256,
        "implementation_hash": binding.spec.implementation_sha256,
        "observation_sha256": binding.spec.observation_sha256,
        "deployment_state": "SRT_DEPLOYED",
        "receipt_hash": deployment.receipt_hash,
        "package_hash": deployment.package_hash,
    }


def list_installed_strategies(
    context: RepositoryContext,
    strategy_id: str | None = None,
) -> CommandResult:
    try:
        if strategy_id is not None and (
            not strategy_id.startswith("S") or not strategy_id[1:].isdigit()
        ):
            raise ValueError(f"invalid strategy id: {strategy_id}")
        bindings = context.strategy_root / "deployments"
        references = sorted(
            (path.stem for path in bindings.glob("S*-v*.json")),
            key=lambda reference: tuple(int(part[1:]) for part in _version_parts(reference)),
        )
        rows = []
        for reference in references:
            family, _version = _version_parts(reference)
            if strategy_id is None or family == strategy_id:
                rows.append(_installed_identity(context, reference))
    except Exception as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(
            "strategy_list_failed", str(exc), context={"command": "strategy.list"}
        ) from exc
    return CommandResult("PASS", "strategy.list", {"strategies": rows})


def strategy_info(context: RepositoryContext, reference: str) -> CommandResult:
    try:
        result = _installed_identity(context, reference)
    except Exception as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(
            "strategy_info_failed",
            str(exc),
            context={"command": "strategy.info", "strategy_version_id": reference},
        ) from exc
    return CommandResult("PASS", "strategy.info", result)
