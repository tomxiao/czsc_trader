"""Publish prepared runtime packages with a separately located transaction journal."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil

from . import freeze_contracts as f
from .candidates import CandidateEvidence
from .errors import RegistryError, ValidationError
from .models import StrategyFamily, StrategyVersion, canonical_sha256

_ACTIVE: set[Path] = set()


def _bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _durable(path, value, *, temporary_root):
    """Same-volume staged write; the caller owns the registry lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    from uuid import uuid4

    temporary = temporary_root / f"{uuid4().hex}.json"
    try:
        with temporary.open("xb") as stream:
            stream.write(_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class FreezeVersionRequest:
    request_id: f.FreezeRequestId
    request_sha256: str
    version: StrategyVersion
    family: StrategyFamily
    staged_package: Path
    package_sha256: str
    journal_root: Path

    def __post_init__(self):
        if (
            type(self.request_id) is not f.FreezeRequestId
            or type(self.version) is not StrategyVersion
            or type(self.family) is not StrategyFamily
            or not isinstance(self.staged_package, Path)
            or not isinstance(self.journal_root, Path)
        ):
            raise TypeError("freeze_version requires typed publication and paths")
        f._hash(self.request_sha256)
        f._hash(self.package_sha256)
        StrategyVersion.from_dict(self.version.to_dict())
        StrategyFamily.from_dict(self.family.to_dict())
        if (
            self.request_id.strategy_id != self.version.strategy_id
            or self.family.strategy_id != self.version.strategy_id
        ):
            raise ValueError("freeze publication family differs")

    def journal_record(self):
        return {
            "request_id": self.request_id.to_dict(),
            "request_sha256": self.request_sha256,
            "version": self.version.to_dict(),
            "package_sha256": self.package_sha256,
        }


def _transaction_root(registry, request_id, journal_root):
    if type(request_id) is not f.FreezeRequestId or not isinstance(journal_root, Path):
        raise TypeError("freeze query requires FreezeRequestId and journal_root Path")
    root = journal_root.resolve()
    if root.is_relative_to(registry.root.resolve()) or registry.root.resolve().is_relative_to(root):
        raise ValueError("freeze journal must be separate from runtime registry")
    return root / request_id.value


def _request(path):
    value = _read(path)
    if set(value) != {"request_id", "request_sha256", "version", "package_sha256"}:
        raise ValueError("freeze journal request fields differ")
    request_id = f.FreezeRequestId.from_dict(value["request_id"])
    version = StrategyVersion.from_dict(value["version"])
    if version.strategy_id != request_id.strategy_id:
        raise ValueError("freeze journal version family differs")
    f._hash(value["request_sha256"])
    f._hash(value["package_sha256"])
    return value


def _package(root, expected_version, expected_hash):
    manifest = _read(root / "release_manifest.json")
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
    if (
        set(manifest) != expected_fields
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
    ):
        raise ValueError("freeze package manifest fields differ")
    if (
        manifest["source_candidate_id"]
        != f"{expected_version.strategy_id}-{expected_version.source_candidate}"
    ):
        raise ValueError("freeze package candidate differs")
    f._hash(manifest["candidate_package_hash"])
    identity = dict(manifest)
    package_hash = identity.pop("package_hash")
    if (
        package_hash != expected_hash
        or package_hash != canonical_sha256(identity)
        or manifest["strategy_version_hash"] != expected_version.release_hash
        or manifest["strategy_version_id"] != expected_version.release_id
    ):
        raise ValueError("freeze package identity differs")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if any(p.is_symlink() or p.is_junction() for p in root.rglob("*")):
        raise ValueError("freeze package contains links")
    if actual != set(manifest["files"]) | {"release_manifest.json"}:
        raise ValueError("freeze package file inventory differs")
    for name, digest in manifest["files"].items():
        CandidateEvidence(name, digest).resolve(root)
    if (
        manifest["runtime_root"] != "src/strategy_runtime"
        or manifest["runtime_binding"] != "runtime_binding.json"
    ):
        raise ValueError("freeze package layout differs")
    binding = _read(root / "runtime_binding.json")
    if (
        binding["release_id"] != expected_version.release_id
        or binding["release_hash"] != expected_version.release_hash
    ):
        raise ValueError("runtime binding differs from version")
    return package_hash


def query(registry, request_id, *, journal_root):
    root = _transaction_root(registry, request_id, journal_root)
    try:
        return _query(registry, request_id, journal_root=journal_root)
    except (OSError, ValueError, TypeError, KeyError, ValidationError) as exc:
        request_hash = None
        try:
            request_hash = _request(root / "request.json")["request_sha256"]
        except (OSError, ValueError, TypeError, KeyError, ValidationError):
            pass
        return f.FreezeReceipt(
            request_id,
            f.FreezeStatus.UNKNOWN,
            request_hash,
            reason=f"freeze evidence cannot be verified: {type(exc).__name__}: {exc}",
        )


def _query(registry, request_id, *, journal_root):
    root = _transaction_root(registry, request_id, journal_root)
    if not (root / "request.json").exists():
        if (root / "committed.json").exists() or (root / "failed.json").exists():
            raise ValueError("terminal freeze record has no request")
        return f.FreezeReceipt(request_id, f.FreezeStatus.NOT_FOUND)
    request = _request(root / "request.json")
    if f.FreezeRequestId.from_dict(request["request_id"]) != request_id:
        raise ValueError("stored freeze request identity differs")
    if (root / "committed.json").exists():
        receipt = f.FreezeReceipt.from_dict(_read(root / "committed.json"))
        if (
            receipt.status is not f.FreezeStatus.COMMITTED
            or receipt.request_sha256 != request["request_sha256"]
            or receipt.request_id != request_id
        ):
            raise ValueError("freeze commit marker differs")
        version_path = registry._version_path(request_id.strategy_id, receipt.version.version)
        if not version_path.exists() and root.resolve() in _ACTIVE:
            return f.FreezeReceipt(
                request_id, f.FreezeStatus.IN_PROGRESS, request["request_sha256"]
            )
        version = StrategyVersion.from_dict(_read(version_path))
        expected = StrategyVersion.from_dict(request["version"])
        if (
            version.to_dict() != expected.to_dict()
            or receipt.version.release_hash != version.release_hash
        ):
            raise ValueError("committed version differs")
        package_hash = _package(
            registry.root / request_id.strategy_id / "releases" / version.version,
            version,
            request["package_sha256"],
        )
        if receipt.version.package_hash != package_hash:
            raise ValueError("committed package differs")
        return receipt
    if (root / "failed.json").exists():
        receipt = f.FreezeReceipt.from_dict(_read(root / "failed.json"))
        if (
            receipt.status is not f.FreezeStatus.FAILED
            or receipt.request_id != request_id
            or receipt.request_sha256 != request["request_sha256"]
        ):
            raise ValueError("failed freeze receipt differs")
        return receipt
    if root.resolve() in _ACTIVE:
        return f.FreezeReceipt(request_id, f.FreezeStatus.IN_PROGRESS, request["request_sha256"])
    # A durable STARTED record cannot prove that its former owner is alive.
    return f.FreezeReceipt(
        request_id,
        f.FreezeStatus.UNKNOWN,
        request["request_sha256"],
        reason="freeze has no terminal commit record; explicit investigation required",
    )


def freeze(registry, request):
    if type(request) is not FreezeVersionRequest:
        raise TypeError("freeze_version requires FreezeVersionRequest")
    request_id = request.request_id
    journal_root = request.journal_root
    existing = query(registry, request_id, journal_root=journal_root)
    if existing.status is not f.FreezeStatus.NOT_FOUND:
        if existing.request_sha256 is not None and existing.request_sha256 != request.request_sha256:
            raise ValueError("freeze request ID already binds different content")
        if existing.status is f.FreezeStatus.UNKNOWN:
            return existing
        saved = _request(_transaction_root(registry, request_id, journal_root) / "request.json")
        if saved != request.journal_record():
            raise ValueError("freeze publication differs from registered request")
        return existing
    version, family = request.version, request.family
    for path in journal_root.glob("*/request.json"):
        prior = _request(path)
        if prior["version"]["version"] == version.version and query(
            registry, f.FreezeRequestId.from_dict(prior["request_id"]), journal_root=journal_root
        ).status in {f.FreezeStatus.UNKNOWN, f.FreezeStatus.IN_PROGRESS}:
            raise RegistryError("target version is reserved by an unresolved freeze request")
    package_hash = _package(request.staged_package, version, request.package_sha256)
    version_path = registry._version_path(version.strategy_id, version.version)
    package_path = registry.root / version.strategy_id / "releases" / version.version
    if version_path.exists() or package_path.exists():
        raise RegistryError("target version already exists; explicit version required")
    if version.parent_version is not None:
        registry.get_version(version.strategy_id, version.parent_version)
    registered = {x.strategy_id for x in registry.list_families()}
    if family.strategy_id in registered:
        if registry.get_family(family.strategy_id).name != family.name:
            raise ValueError("research and release family identity differ")
    root = _transaction_root(registry, request_id, journal_root)
    _durable(
        root / "request.json",
        request.journal_record(),
        temporary_root=registry.root.parent / ".tmp/freeze",
    )
    _ACTIVE.add(root.resolve())
    try:
        if family.strategy_id not in registered:
            registry.create_family(family, actor="TDR.freeze", reason="首次冻结登记策略族")
        package_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(request.staged_package, package_path)
        for path in package_path.rglob("*"):
            if path.is_file():
                with path.open("r+b") as stream:
                    os.fsync(stream.fileno())
        _package(package_path, version, request.package_sha256)
        receipt = f.FreezeReceipt(
            request_id,
            f.FreezeStatus.COMMITTED,
            request.request_sha256,
            f.FrozenVersionReference(
                version.strategy_id, version.version, version.release_hash, package_hash
            ),
        )
        _durable(
            root / "committed.json",
            receipt.to_dict(),
            temporary_root=registry.root.parent / ".tmp/freeze",
        )
        # Version is the runtime visibility boundary; runtime readers need no journal.
        _durable(
            version_path, version.to_dict(), temporary_root=registry.root.parent / ".tmp/freeze"
        )
        return receipt
    except Exception as exc:
        if (root / "committed.json").exists():
            _ACTIVE.discard(root.resolve())
            return query(registry, request_id, journal_root=journal_root)
        failure = f.FreezeReceipt(
            request_id,
            f.FreezeStatus.FAILED,
            request.request_sha256,
            reason=f"{type(exc).__name__}: {exc}",
        )
        _durable(
            root / "failed.json",
            failure.to_dict(),
            temporary_root=registry.root.parent / ".tmp/freeze",
        )
        return failure
    finally:
        _ACTIVE.discard(root.resolve())
