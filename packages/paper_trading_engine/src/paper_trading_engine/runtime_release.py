"""Immutable PTE release discovery, verification, and activation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable


MANIFEST_NAME = "release-manifest.json"
ACTIVE_RELEASE_NAME = "active-release.json"
RELEASE_ID_PATTERN = re.compile(r"v[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?")
PTE_SERVICE_HOST_FORBIDDEN_PATTERNS = (
    "vectorbt*", "czsc_trader*", "strategy_runtime*", "dataflows*",
    "pandas*", "numpy*", "plotly*", "futu*",
)


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def editable_installations(site_packages: Path) -> list[str]:
    editable = [path.name for path in site_packages.rglob("__editable__*.pth")]
    for path in site_packages.rglob("*.dist-info/direct_url.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid installed distribution identity: {path}") from exc
        if payload.get("dir_info", {}).get("editable") is True:
            editable.append(path.parent.name)
    return sorted(set(editable))


def service_host_runtime_dependencies(site_packages: Path) -> list[str]:
    return sorted({
        path.name
        for pattern in PTE_SERVICE_HOST_FORBIDDEN_PATTERNS
        for path in site_packages.glob(pattern)
    })


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read PTE release metadata: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"PTE release metadata must be an object: {path}")
    return value


def _safe_release_id(value: object) -> str:
    release_id = str(value or "")
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise RuntimeError(f"invalid PTE release id: {release_id}")
    return release_id


@dataclass(frozen=True)
class RuntimeRelease:
    runtime_root: Path
    release_id: str
    release_root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    manifest_sha256: str

    @property
    def scripts_dir(self) -> Path:
        return self.release_root / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")

    @property
    def pte_executable(self) -> Path:
        return self.scripts_dir / ("pte.exe" if sys.platform == "win32" else "pte")

    @property
    def trader_executable(self) -> Path:
        return self.scripts_dir / (
            "czsc-trader.exe" if sys.platform == "win32" else "czsc-trader"
        )

    def identity(self) -> dict[str, object]:
        return {
            "mode": "PTE",
            "release_id": self.release_id,
            "git_commit": self.manifest["git_commit"],
            "manifest_sha256": self.manifest_sha256,
            "release_root": str(self.release_root),
            "python_version": self.manifest.get("python_version"),
        }


def load_release(runtime_root: Path, release_id: str) -> RuntimeRelease:
    from strategy_runtime import deployment_inventory

    return _load_release(runtime_root, release_id, deployment_inventory)


def _load_release(
    runtime_root: Path, release_id: str,
    inventory_reader: Callable[[Path], dict[str, str]],
) -> RuntimeRelease:
    runtime_root = Path(runtime_root).resolve()
    release_id = _safe_release_id(release_id)
    releases_root = (runtime_root / "releases").resolve()
    release_root = (releases_root / release_id).resolve()
    try:
        release_root.relative_to(releases_root)
    except ValueError as exc:
        raise RuntimeError("PTE release path escapes releases root") from exc
    manifest_path = release_root / MANIFEST_NAME
    manifest = _read_object(manifest_path)
    if manifest.get("schema_version") != 1:
        raise RuntimeError("unsupported PTE release manifest schema")
    if manifest.get("release_id") != release_id:
        raise RuntimeError("PTE release directory and manifest identity differ")
    commit = manifest.get("git_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("PTE release manifest has no valid git commit")
    database_schema = manifest.get("database_schema")
    if (
        not isinstance(database_schema, dict)
        or not isinstance(database_schema.get("current"), int)
        or not isinstance(database_schema.get("compatible"), list)
        or not database_schema["compatible"]
        or not all(isinstance(value, int) for value in database_schema["compatible"])
    ):
        raise RuntimeError("PTE release manifest has no valid database schema contract")
    expected_strategy_hash = manifest.get("strategy_snapshot_sha256")
    strategies = release_root / "strategies"
    if not strategies.is_dir() or tree_sha256(strategies) != expected_strategy_hash:
        raise RuntimeError("PTE release strategy snapshot differs from manifest")
    expected_strategy_releases = manifest.get("strategy_releases")
    if (
        expected_strategy_releases is not None
        and inventory_reader(strategies) != expected_strategy_releases
    ):
        raise RuntimeError("PTE release strategy inventory differs from manifest")
    runtime_files = manifest.get("runtime_files")
    if not isinstance(runtime_files, dict):
        raise RuntimeError("PTE release manifest has no runtime file inventory")
    for name, expected_hash in runtime_files.items():
        if not isinstance(name, str) or not isinstance(expected_hash, str):
            raise RuntimeError("PTE release runtime file inventory is invalid")
        path = (release_root / name).resolve()
        try:
            path.relative_to(release_root)
        except ValueError as exc:
            raise RuntimeError("PTE release runtime file escapes release root") from exc
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise RuntimeError(f"PTE release runtime file differs from manifest: {name}")
    site_packages = release_root / ".venv" / "Lib" / "site-packages"
    if not site_packages.is_dir():
        candidates = sorted(
            (release_root / ".venv" / "lib").glob("python*/site-packages")
        )
        if len(candidates) != 1:
            raise RuntimeError("PTE release environment has no site-packages")
        site_packages = candidates[0]
    editable = editable_installations(site_packages)
    if editable:
        raise RuntimeError(
            f"PTE runtime release contains editable installations: {editable}"
        )
    release = RuntimeRelease(
        runtime_root=runtime_root,
        release_id=release_id,
        release_root=release_root,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_sha256=file_sha256(manifest_path),
    )
    if not release.pte_executable.is_file() or not release.trader_executable.is_file():
        raise RuntimeError("PTE release executables are incomplete")
    return release


def active_release_path(runtime_root: Path) -> Path:
    return Path(runtime_root).resolve() / "shared" / "config" / ACTIVE_RELEASE_NAME


def resolve_active_release(runtime_root: Path) -> RuntimeRelease:
    return _resolve_active_release(runtime_root, load_release)


def _installed_strategy_inventory(strategies: Path) -> dict[str, str]:
    """Run SRT validation inside the selected runtime, outside the lean host."""
    release_root = strategies.parent
    scripts = release_root / '.venv' / ('Scripts' if sys.platform == 'win32' else 'bin')
    python = scripts / ('python.exe' if sys.platform == 'win32' else 'python')
    completed = subprocess.run(
        [str(python), '-I', '-B', '-c',
         'import json,sys; from pathlib import Path; '
         'from strategy_runtime import deployment_inventory; '
         'print(json.dumps(deployment_inventory(Path(sys.argv[1]))))', str(strategies)],
        cwd=release_root, capture_output=True, text=True, timeout=60, check=True,
    )
    result = json.loads(completed.stdout)
    if not isinstance(result, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in result.items()
    ):
        raise RuntimeError('installed runtime returned invalid strategy inventory')
    return result


def _resolve_active_release_for_host(runtime_root: Path) -> RuntimeRelease:
    return _resolve_active_release(runtime_root, lambda root, release_id: _load_release(
        root, release_id, _installed_strategy_inventory,
    ))


def _resolve_active_release(
    runtime_root: Path, loader: Callable[[Path, str], RuntimeRelease],
) -> RuntimeRelease:
    active_path = active_release_path(runtime_root)
    active = _read_object(active_path)
    if active.get("schema_version") != 1:
        raise RuntimeError("unsupported active PTE release schema")
    release = loader(runtime_root, _safe_release_id(active.get("release_id")))
    if active.get("manifest_sha256") != release.manifest_sha256:
        raise RuntimeError("active PTE release manifest identity differs")
    return release


def activate_release(runtime_root: Path, release_id: str) -> dict[str, object]:
    runtime_root = Path(runtime_root).resolve()
    release = load_release(runtime_root, release_id)
    env_file = runtime_root / "shared" / "config" / ".env"
    if not env_file.is_file():
        raise RuntimeError(f"PTE runtime configuration is missing: {env_file}")
    path = active_release_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    if path.is_file():
        current = _read_object(path)
        previous = current.get("release_id")
        if previous == release.release_id:
            if current.get("manifest_sha256") != release.manifest_sha256:
                raise RuntimeError(
                    "active PTE release ID matches but manifest identity differs"
                )
            return current
    payload = {
        "schema_version": 1,
        "release_id": release.release_id,
        "manifest_sha256": release.manifest_sha256,
        "previous_release_id": previous,
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    from uuid import uuid4

    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)
    return payload


def rollback_release(runtime_root: Path) -> dict[str, object]:
    path = active_release_path(runtime_root)
    active = _read_object(path)
    previous = active.get("previous_release_id")
    if not isinstance(previous, str) or not previous:
        raise RuntimeError("active PTE release has no rollback target")
    return activate_release(runtime_root, previous)


def load_manifest_identity(manifest_path: Path) -> dict[str, object]:
    manifest_path = Path(manifest_path).resolve()
    if manifest_path.name != MANIFEST_NAME:
        raise RuntimeError("PTE runtime manifest has an unexpected filename")
    release_root = manifest_path.parent
    runtime_root = release_root.parent.parent
    release = load_release(runtime_root, release_root.name)
    if release.manifest_path != manifest_path:
        raise RuntimeError("PTE runtime manifest path differs from release layout")
    return release.identity()
