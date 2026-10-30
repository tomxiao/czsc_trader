"""Validated access to immutable strategy deployments outside the SRT wheel."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import RuntimeCompatibilityError
from .models import canonical_sha256, StrategyRelease
from .inspection import InspectionRuntimePermit, _safe_path
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


@dataclass(frozen=True, slots=True)
class VerifiedReleasePackage:
    """A complete version/package/binding authenticated without deployment approval."""
    release: StrategyRelease
    package_sha256: str
    runtime_binding: RuntimeBinding
    source_root: Path


def validate_release_package(strategy_root: Path, release_id: str) -> VerifiedReleasePackage:
    """Authenticate the same immutable bytes for deployment and technical inspection."""
    if type(release_id) is not str or re.fullmatch(r"S[0-9]{3}-v[1-9][0-9]*", release_id) is None:
        raise RuntimeCompatibilityError("invalid release identity")
    root = _safe_path(strategy_root)
    family, version = release_id.rsplit("-", 1)
    package_root = _safe_path(root / family / "releases" / version)
    if not package_root.is_dir():
        raise RuntimeCompatibilityError("strategy release package is unavailable")
    version_path = _safe_path(root / family / "versions" / f"{version}.json")
    frozen = _read_object(version_path)
    release = StrategyRelease.from_mapping(frozen)
    manifest = _read_object(_safe_path(package_root / "release_manifest.json"))
    expected_manifest = {
        "schema_version", "strategy_version_id", "strategy_version_hash",
        "source_candidate_id", "candidate_package_hash", "runtime_root",
        "runtime_binding", "files", "package_hash",
    }
    if set(manifest) != expected_manifest or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise RuntimeCompatibilityError("strategy release package manifest is invalid")
    manifest_identity = dict(manifest)
    package_hash = manifest_identity.pop("package_hash")
    if package_hash != canonical_sha256(manifest_identity):
        raise RuntimeCompatibilityError("strategy release package hash mismatch")
    if (release.release_id != release_id or manifest["strategy_version_id"] != release_id
            or manifest["strategy_version_hash"] != release.release_hash):
        raise RuntimeCompatibilityError("strategy release package differs from frozen version")
    if type(manifest["source_candidate_id"]) is not str or not manifest["source_candidate_id"]:
        raise RuntimeCompatibilityError("strategy release source candidate is invalid")
    # Manifest schema 1 predates freeze plans: imported releases explicitly use
    # null for this optional provenance field. Its exact value remains covered
    # by package_hash; a newly inspected package always supplies its plan hash.
    plan_hash = manifest["candidate_package_hash"]
    if plan_hash is not None and (type(plan_hash) is not str or re.fullmatch(r"[a-f0-9]{64}", plan_hash) is None):
        raise RuntimeCompatibilityError("strategy release plan identity is invalid")
    files = manifest["files"]
    if type(files) is not dict or not files:
        raise RuntimeCompatibilityError("strategy release package has no file inventory")
    tracked: set[str] = set()
    for name, expected_hash in files.items():
        relative = _safe_relative(name, "files")
        path = _safe_path(package_root.joinpath(*relative.parts))
        if (type(expected_hash) is not str or re.fullmatch(r"[a-f0-9]{64}", expected_hash) is None
                or not path.is_file() or not path.is_relative_to(package_root)):
            raise RuntimeCompatibilityError(f"strategy release package file is missing or invalid: {name}")
        if _file_sha256(path) != expected_hash:
            raise RuntimeCompatibilityError(f"strategy release package file differs: {name}")
        if str(relative).casefold() in {x.casefold() for x in tracked}:
            raise RuntimeCompatibilityError("strategy release package repeats file path")
        tracked.add(str(relative))
    actual = set()
    for path in package_root.rglob("*"):
        _safe_path(path)
        if path.is_file() and path != package_root / "release_manifest.json":
            actual.add(path.relative_to(package_root).as_posix())
    if actual != tracked:
        raise RuntimeCompatibilityError("strategy release package inventory differs")
    source_root = _safe_path(package_root.joinpath(*_safe_relative(manifest["runtime_root"], "runtime_root").parts))
    binding_path = _safe_path(package_root.joinpath(*_safe_relative(manifest["runtime_binding"], "runtime_binding").parts))
    if (not source_root.is_relative_to(package_root) or source_root.name != "strategy_runtime"
            or not binding_path.is_relative_to(package_root)):
        raise RuntimeCompatibilityError("strategy release package layout differs")
    binding = RuntimeBinding.from_dict(_read_object(binding_path))
    if binding.release_id != release_id or binding.release_hash != release.release_hash:
        raise RuntimeCompatibilityError("strategy runtime binding identity differs")
    equity = release.payload.get("runtime", {}).get("kind") == "US_EQUITY"
    if not equity and not (source_root / "strategies").is_dir():
        raise RuntimeCompatibilityError("strategy release runtime root is invalid")
    descriptor = release.payload["runtime"]
    if (tuple(descriptor["source_files"]) != binding.spec.source_files
            or descriptor["source_sha256"] != binding.spec.implementation_sha256):
        raise RuntimeCompatibilityError("runtime binding differs from frozen source identity")
    if not set(binding.spec.source_files).issubset(binding.spec.install_files):
        raise RuntimeCompatibilityError("strategy install files omit the source closure")
    if any(not source_root.joinpath(*_safe_relative(name, "install_files").parts).is_file() for name in binding.spec.install_files):
        raise RuntimeCompatibilityError("strategy install files are missing")
    from .implementation_identity import implementation_sha256
    if equity:
        from .equity_definition import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash
        definition = EquityStrategyDefinition.from_dict(dict(release.payload["equity_definition"]))
        if definition.contract_version != 2:
            raise RuntimeCompatibilityError('equity V3 is historical research only; production state migration is not supported')
        candidate = EquityStrategyCandidate(family, str(frozen["source_candidate"]), definition, source_root)
        candidate.verify()
        digest = equity_source_hash(source_root, binding.spec.source_files)
        if canonical_sha256({"contract": "equity-decision-v2", "definition": definition.to_dict()}) != binding.spec.observation_sha256:
            raise RuntimeCompatibilityError("equity runtime binding differs from decision definition")
    else:
        digest = implementation_sha256(binding.spec.source_files, source_root=source_root)
    if digest != binding.spec.implementation_sha256:
        raise RuntimeCompatibilityError("strategy source closure hash differs")
    return VerifiedReleasePackage(release, str(package_hash), binding, source_root)


def load_strategy_deployment(strategy_root: Path, release_id: str) -> StrategyDeployment:
    """Authenticate a formal deployment receipt and its exact release package."""
    root = _safe_path(strategy_root)
    if type(release_id) is not str or re.fullmatch(r"S[0-9]{3}-v[1-9][0-9]*", release_id) is None:
        raise RuntimeCompatibilityError("invalid release identity")
    receipt = _read_object(_safe_path(root / "deployments" / f"{release_id}.json"))
    expected = {"schema_version", "strategy_version_id", "strategy_version_hash", "release_package", "package_hash", "receipt_hash"}
    if set(receipt) != expected or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1:
        raise RuntimeCompatibilityError("strategy deployment receipt fields are invalid")
    identity = dict(receipt)
    receipt_hash = identity.pop("receipt_hash")
    if receipt_hash != canonical_sha256(identity):
        raise RuntimeCompatibilityError("strategy deployment receipt hash mismatch")
    package = validate_release_package(root, release_id)
    family, version = release_id.rsplit("-", 1)
    package_root = root / family / "releases" / version
    if (receipt["strategy_version_id"] != release_id
            or receipt["strategy_version_hash"] != package.release.release_hash
            or receipt["package_hash"] != package.package_sha256
            or receipt["release_package"] != f"{family}/releases/{version}"):
        raise RuntimeCompatibilityError("strategy deployment differs from its release package")
    return StrategyDeployment(root, release_id, package.release.release_hash, package.package_sha256,
                              package_root, package.source_root, package.runtime_binding, receipt_hash)


def load_inspection_deployment(strategy_root: Path, release_id: str, permit: InspectionRuntimePermit) -> StrategyDeployment:
    """Load only through an explicit isolated permit; never manufacture a receipt."""
    if type(permit) is not InspectionRuntimePermit:
        raise RuntimeCompatibilityError("inspection requires a typed runtime permit")
    root = permit.validate_path(strategy_root)
    if root != permit.isolated_repository / "strategies":
        raise RuntimeCompatibilityError("inspection strategy root differs from permit")
    package = validate_release_package(root, release_id)
    permit.validate_release(release_id, package.release.release_hash)
    if package.package_sha256 != permit.package_sha256:
        raise RuntimeCompatibilityError("inspection package differs from permit")
    family, version = release_id.rsplit("-", 1)
    return StrategyDeployment(root, release_id, package.release.release_hash, package.package_sha256,
                              root / family / "releases" / version, package.source_root,
                              package.runtime_binding, canonical_sha256({"inspection_run": permit.run_id,
                              "package": permit.package_sha256, "protocol": permit.protocol_sha256}))


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
