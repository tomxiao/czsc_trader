"""Validated access to immutable strategy deployments outside the SRT wheel."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import RuntimeCompatibilityError
from .models import canonical_sha256
from .binding import RuntimeBinding


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeCompatibilityError(f"cannot read strategy deployment file: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeCompatibilityError(f"strategy deployment file is not an object: {path}")
    return value


def _safe_relative(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise RuntimeCompatibilityError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or "\\" in value
        or ":" in value
    ):
        raise RuntimeCompatibilityError(f"{field} contains an unsafe path")
    return path


def _file_sha256(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise RuntimeCompatibilityError(f"cannot read strategy deployment file: {path}") from exc
    return digest.hexdigest()


def _paths(values: object, field: str) -> tuple[str, ...]:
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(item, str) for item in values)
    ):
        raise RuntimeCompatibilityError(f"{field} must be a non-empty path list")
    normalized = tuple(str(_safe_relative(item, field)) for item in values)
    if len(normalized) != len(set(normalized)):
        raise RuntimeCompatibilityError(f"{field} contains duplicate paths")
    return normalized


@dataclass(frozen=True, slots=True)
class StrategyDeployment:
    """One immutable strategy release selected for an SRT/PTE snapshot."""

    strategy_root: Path
    release_id: str
    release_hash: str
    package_hash: str
    package_root: Path
    source_root: Path
    binding: RuntimeBinding
    receipt_hash: str

    @property
    def install_files(self) -> tuple[str, ...]:
        return self.binding.spec.install_files


def load_strategy_deployment(strategy_root: Path, release_id: str) -> StrategyDeployment:
    """Load and authenticate one tool-managed strategy deployment record."""

    root = Path(strategy_root).resolve()
    receipt_path = root / "deployments" / f"{release_id}.json"
    receipt = _read_object(receipt_path)
    expected_receipt = {
        "schema_version",
        "strategy_version_id",
        "strategy_version_hash",
        "release_package",
        "package_hash",
        "receipt_hash",
    }
    if set(receipt) != expected_receipt or receipt.get("schema_version") != 1:
        raise RuntimeCompatibilityError("strategy deployment receipt fields are invalid")
    receipt_identity = dict(receipt)
    receipt_hash = receipt_identity.pop("receipt_hash")
    if receipt_hash != canonical_sha256(receipt_identity):
        raise RuntimeCompatibilityError("strategy deployment receipt hash mismatch")
    if receipt.get("strategy_version_id") != release_id:
        raise RuntimeCompatibilityError("strategy deployment receipt identity differs")

    package_relative = _safe_relative(receipt.get("release_package"), "release_package")
    package_root = root.joinpath(*package_relative.parts).resolve()
    if not package_root.is_relative_to(root) or not package_root.is_dir():
        raise RuntimeCompatibilityError("strategy release package is unavailable")
    manifest = _read_object(package_root / "release_manifest.json")
    expected_manifest = {
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
    if set(manifest) != expected_manifest or manifest.get("schema_version") != 1:
        raise RuntimeCompatibilityError("strategy release package manifest is invalid")
    manifest_identity = dict(manifest)
    package_hash = manifest_identity.pop("package_hash")
    if package_hash != canonical_sha256(manifest_identity):
        raise RuntimeCompatibilityError("strategy release package hash mismatch")
    if (
        manifest.get("strategy_version_id") != release_id
        or manifest.get("strategy_version_hash") != receipt.get("strategy_version_hash")
        or package_hash != receipt.get("package_hash")
    ):
        raise RuntimeCompatibilityError("strategy deployment differs from its release package")

    family, version = release_id.rsplit("-", 1)
    version_path = root / family / "versions" / f"{version}.json"
    frozen = _read_object(version_path)
    from .models import StrategyRelease
    release = StrategyRelease.from_mapping(frozen)
    request_id = frozen["governance"]["request_id"]
    transaction = root / "freeze_requests" / family / request_id["value"]
    marker = _read_object(transaction / "committed.json")
    request = _read_object(transaction / "request.json")
    expected_version = {
        "type": "FrozenVersionReference", "strategy_id": family, "version": version,
        "release_hash": release.release_hash, "package_hash": package_hash,
    }
    if (marker.get("type") != "FreezeReceipt" or marker.get("status") != "COMMITTED" or
        marker.get("request_id") != request_id or request.get("request_id") != request_id or
        marker.get("request_sha256") != canonical_sha256(request) or
        marker.get("version") != expected_version or
        release.release_hash != receipt.get("strategy_version_hash")):
        raise RuntimeCompatibilityError("strategy version has no matching freeze commit")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeCompatibilityError("strategy release package has no file inventory")
    tracked: set[str] = set()
    for name, expected_hash in files.items():
        relative = _safe_relative(name, "files")
        path = package_root.joinpath(*relative.parts)
        if not isinstance(expected_hash, str) or not path.is_file():
            raise RuntimeCompatibilityError(f"strategy release package file is missing: {name}")
        if _file_sha256(path) != expected_hash:
            raise RuntimeCompatibilityError(f"strategy release package file differs: {name}")
        tracked.add(str(relative))
    actual = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and path.name != "release_manifest.json"
    }
    if actual != tracked:
        raise RuntimeCompatibilityError("strategy release package inventory differs")

    source_relative = _safe_relative(manifest.get("runtime_root"), "runtime_root")
    source_root = package_root.joinpath(*source_relative.parts).resolve()
    if (
        not source_root.is_relative_to(package_root)
        or source_root.name != "strategy_runtime"
        or not (source_root / "strategies").is_dir()
    ):
        raise RuntimeCompatibilityError("strategy release runtime root is invalid")
    binding_relative = _safe_relative(manifest.get("runtime_binding"), "runtime_binding")
    binding = _read_object(package_root.joinpath(*binding_relative.parts))
    RuntimeBinding.from_dict(binding)
    if (
        binding.get("release_id") != release_id
        or binding.get("release_hash") != receipt.get("strategy_version_hash")
    ):
        raise RuntimeCompatibilityError("strategy runtime binding identity differs")
    source_files = _paths(binding.get("source_files"), "source_files")
    install_files = _paths(binding.get("install_files"), "install_files")
    if not set(source_files).issubset(install_files):
        raise RuntimeCompatibilityError("strategy install files omit the source closure")
    missing = [name for name in install_files if not source_root.joinpath(*PurePosixPath(name).parts).is_file()]
    if missing:
        raise RuntimeCompatibilityError(f"strategy install files are missing: {missing}")
    return StrategyDeployment(
        root,
        release_id,
        str(receipt["strategy_version_hash"]),
        str(package_hash),
        package_root,
        source_root,
        RuntimeBinding.from_dict(binding),
        str(receipt_hash),
    )


def deployment_inventory(strategy_root: Path) -> dict[str, str]:
    """Return release-to-package identities after validating every deployment."""

    root = Path(strategy_root).resolve()
    deployments = root / "deployments"
    if not deployments.is_dir():
        raise RuntimeCompatibilityError("strategy deployment directory is unavailable")
    inventory: dict[str, str] = {}
    for path in sorted(deployments.glob("S*-v*.json")):
        deployment = load_strategy_deployment(root, path.stem)
        inventory[deployment.release_id] = deployment.package_hash
    if not inventory:
        raise RuntimeCompatibilityError("strategy deployment inventory is empty")
    return inventory
