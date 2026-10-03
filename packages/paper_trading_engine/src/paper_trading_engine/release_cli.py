"""Build and select immutable PTE runtime releases."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from strategy_runtime import (
    StrategyRelease,
    StrategyRuntime,
    deployment_inventory,
)

from .runtime_release import (
    MANIFEST_NAME,
    RELEASE_ID_PATTERN,
    activate_release,
    active_release_path,
    editable_installations,
    file_sha256,
    load_release,
    resolve_active_release,
    service_host_runtime_dependencies,
    tree_sha256,
)
from .store import (
    RUNTIME_DATABASE_COMPATIBLE_VERSIONS,
    RUNTIME_DATABASE_SCHEMA_VERSION,
)


PTE_LOCAL_PROJECTS = (
    "packages/dataflows",
    "packages/strategy_manager",
    "packages/strategy_runtime",
    ".",
    "packages/paper_trading_engine",
)
PTE_RESOLUTION_DISTRIBUTIONS = (
    "paper-trading-engine",
    "czsc-strategy-runtime",
    "czsc-dataflows",
    "czsc-strategy-manager",
)
PTE_SOURCE_DISTRIBUTIONS = ("futu-api",)


Runner = Callable[..., subprocess.CompletedProcess[str]]
SourceDistributionFetcher = Callable[[str, str, Path], Path]
BUILD_MANIFEST_NAME = "build-manifest.json"


def _replace_directory(staging: Path, destination: Path) -> None:
    """Atomically publish a directory despite short-lived Windows file locks."""

    attempts = 6 if os.name == "nt" else 1
    for attempt in range(attempts):
        try:
            staging.replace(destination)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(0.05 * (2**attempt))


def _run(
    command: Sequence[str], *, cwd: Path, runner: Runner = subprocess.run,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = runner(
        list(command), cwd=cwd, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        **({"env": dict(env)} if env is not None else {}),
    )
    if completed.returncode:
        detail = "\n".join(
            part for part in (completed.stdout.strip(), completed.stderr.strip()) if part
        )
        raise RuntimeError(f"release command failed: {' '.join(command)}: {detail}")
    return completed


def _git_tag_identity(repo_root: Path, release_id: str, runner: Runner) -> str:
    status = _run(["git", "status", "--porcelain"], cwd=repo_root, runner=runner)
    if status.stdout.strip():
        raise RuntimeError("PTE build requires a clean Git worktree")
    tag_type = _run(
        ["git", "cat-file", "-t", release_id], cwd=repo_root, runner=runner,
    ).stdout.strip()
    if tag_type != "tag":
        raise RuntimeError(f"PTE build tag must be annotated: {release_id}")
    commit = _run(
        ["git", "rev-list", "-n", "1", release_id], cwd=repo_root, runner=runner,
    ).stdout.strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise RuntimeError(f"PTE build tag has no valid commit: {release_id}")
    return commit


def _export_tag_source(
    repo_root: Path, release_id: str, destination: Path, runner: Runner,
) -> None:
    archive = destination.with_name(f"{destination.name}.tar")
    _run(
        [
            "git", "archive", "--format=tar", "--output", str(archive),
            release_id,
        ],
        cwd=repo_root,
        runner=runner,
    )
    destination.mkdir()
    try:
        with tarfile.open(archive, "r") as source:
            source.extractall(destination, filter="data")
    finally:
        archive.unlink(missing_ok=True)


def _python_in(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _create_environment(
    *,
    uv_executable: Path,
    source_python: Path,
    venv: Path,
    artifacts: Path,
    cache_dir: Path,
    repo_root: Path,
    runner: Runner,
    packages: Sequence[str] = (),
    no_dependencies: Sequence[str] = (),
) -> None:
    _run(
        [
            str(uv_executable), "venv", str(venv),
            "--python", str(source_python),
            "--no-python-downloads", "--no-project",
            "--cache-dir", str(cache_dir),
        ],
        cwd=repo_root,
        runner=runner,
    )
    python = _python_in(venv)
    for dependencies, selected in ((True, packages), (False, no_dependencies)):
        if not selected:
            continue
        command = [
            str(uv_executable), "pip", "install",
            "--python", str(python),
            "--no-python-downloads", "--no-index",
            "--find-links", str(artifacts), "--cache-dir", str(cache_dir),
            "--refresh",
        ]
        if not dependencies:
            command.append("--no-deps")
        _run([*command, *selected], cwd=repo_root, runner=runner)


def _wheel_path(artifacts: Path, distribution: str) -> Path:
    normalized = distribution.lower().replace("-", "_")
    matches = sorted(artifacts.glob(f"{normalized}-*.whl"))
    if len(matches) != 1:
        raise RuntimeError(
            f"PTE release requires exactly one {distribution} wheel; found {len(matches)}"
        )
    return matches[0]


def _verify_strategy_runtime_wheel_boundary(artifacts: Path) -> None:
    wheel = _wheel_path(artifacts, "czsc-strategy-runtime")
    try:
        with ZipFile(wheel) as archive:
            members = set(archive.namelist())
            forbidden = sorted(
                name
                for name in members
                if name.startswith(
                    (
                        "strategy_runtime/strategies/",
                        "strategy_runtime/bindings/",
                        "strategy_runtime/resources/",
                        "strategy_runtime/charts/",
                    )
                )
            )
    except (BadZipFile, OSError) as exc:
        raise RuntimeError(f"cannot inspect strategy runtime wheel: {wheel.name}") from exc
    if forbidden:
        raise RuntimeError(
            f"strategy runtime wheel contains governed strategy assets: {forbidden}"
        )


def _verify_strategy_snapshot(strategy_root: Path) -> dict[str, str]:
    inventory = deployment_inventory(strategy_root)
    runtime = StrategyRuntime(strategy_root)
    for reference in inventory:
        family, version = reference.split("-", 1)
        path = strategy_root / family / "versions" / f"{version}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read deployed strategy version: {reference}") from exc
        release = StrategyRelease.from_mapping(payload)
        runtime.describe(release)
    return inventory


def _constraint_pin(constraints: Path, distribution: str) -> str:
    normalized = distribution.lower().replace("_", "-").replace(".", "-")
    for raw_line in constraints.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        if name.lower().replace("_", "-").replace(".", "-") == normalized:
            if version and all(
                char.isalnum() or char in ".+_-" for char in version
            ):
                return version
            break
    raise RuntimeError(f"PTE build requires an exact {distribution} constraint")


def _download_pypi_sdist(
    distribution: str, version: str, destination: Path,
) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    api_url = f"https://pypi.org/pypi/{distribution}/{version}/json"
    with urlopen(api_url, timeout=30) as response:
        metadata = json.load(response)
    candidates = [
        item for item in metadata.get("urls", [])
        if isinstance(item, dict) and item.get("packagetype") == "sdist"
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"PyPI returned {len(candidates)} source archives for {distribution}=={version}"
        )
    candidate = candidates[0]
    filename = candidate.get("filename")
    download_url = candidate.get("url")
    expected_hash = (candidate.get("digests") or {}).get("sha256")
    if (
        not isinstance(filename, str) or Path(filename).name != filename
        or not isinstance(download_url, str) or not download_url.startswith("https://")
        or not isinstance(expected_hash, str) or len(expected_hash) != 64
    ):
        raise RuntimeError(f"PyPI source metadata is invalid for {distribution}=={version}")
    target = destination / filename
    with urlopen(download_url, timeout=60) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)
    if file_sha256(target) != expected_hash:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"PyPI source hash differs for {distribution}=={version}")
    return target


def _build_pte_wheelhouse(
    *,
    source_python: Path,
    artifacts: Path,
    constraints: Path,
    cache_dir: Path,
    repo_root: Path,
    runner: Runner,
    env: Mapping[str, str] | None = None,
) -> None:
    wheels = artifacts.parent / ".dependency-wheels"
    wheels.mkdir()
    try:
        roots = [
            str(_wheel_path(artifacts, distribution))
            for distribution in PTE_RESOLUTION_DISTRIBUTIONS
        ]
        _run(
            [
                str(source_python), "-m", "pip", "wheel",
                "--cache-dir", str(cache_dir),
                "--wheel-dir", str(wheels), "--constraint", str(constraints),
                "--only-binary", ":all:", "--find-links", str(artifacts),
                *roots,
            ],
            cwd=repo_root, env=env,
            runner=runner,
        )
        for source in sorted(wheels.iterdir()):
            target = artifacts / source.name
            if target.exists():
                if file_sha256(source) != file_sha256(target):
                    raise RuntimeError(f"PTE dependency wheel identity differs: {source.name}")
                continue
            source.replace(target)
    finally:
        shutil.rmtree(wheels)


@dataclass(frozen=True)
class BuiltRelease:
    build_root: Path
    release_id: str
    release_root: Path
    manifest_path: Path
    manifest: dict[str, Any]


def _build_release_root(build_root: Path, release_id: str) -> Path:
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise RuntimeError(f"invalid PTE release id: {release_id}")
    releases = (Path(build_root).resolve() / "releases").resolve()
    release = (releases / release_id).resolve()
    try:
        release.relative_to(releases)
    except ValueError as exc:
        raise RuntimeError("PTE build path escapes releases root") from exc
    return release


def _write_build_manifest(
    *, release_root: Path, release_id: str, git_commit: str,
) -> dict[str, Any]:
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "git_commit": git_commit,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "artifacts": {
            path.name: file_sha256(path)
            for path in sorted((release_root / "artifacts").glob("*.whl"))
        },
        "strategy_snapshot_sha256": tree_sha256(release_root / "strategies"),
        "strategy_releases": _verify_strategy_snapshot(release_root / "strategies"),
        "files": {
            "build-constraints.txt": file_sha256(
                release_root / "build-constraints.txt"
            ),
        },
    }
    (release_root / BUILD_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    return manifest


def load_built_release(build_root: Path, release_id: str) -> BuiltRelease:
    build_root = Path(build_root).resolve()
    release_root = _build_release_root(build_root, release_id)
    manifest_path = release_root / BUILD_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read PTE build manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise RuntimeError("unsupported PTE build manifest schema")
    if manifest.get("release_id") != release_id:
        raise RuntimeError("PTE build directory and manifest identity differ")
    commit = manifest.get("git_commit")
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(char not in "0123456789abcdef" for char in commit)
    ):
        raise RuntimeError("PTE build manifest has no valid git commit")
    expected_artifacts = manifest.get("artifacts")
    if not isinstance(expected_artifacts, dict) or not expected_artifacts:
        raise RuntimeError("PTE build manifest has no artifacts")
    artifacts = release_root / "artifacts"
    actual_names = {path.name for path in artifacts.glob("*.whl")}
    if actual_names != set(expected_artifacts):
        raise RuntimeError("PTE build artifact inventory differs from manifest")
    for name, expected_hash in expected_artifacts.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(expected_hash, str)
        ):
            raise RuntimeError("PTE build artifact inventory is invalid")
        if file_sha256(artifacts / name) != expected_hash:
            raise RuntimeError(f"PTE build artifact differs from manifest: {name}")
    strategies = release_root / "strategies"
    if (
        not strategies.is_dir()
        or tree_sha256(strategies) != manifest.get("strategy_snapshot_sha256")
    ):
        raise RuntimeError("PTE build strategy snapshot differs from manifest")
    if _verify_strategy_snapshot(strategies) != manifest.get("strategy_releases"):
        raise RuntimeError("PTE build strategy release inventory differs from manifest")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("PTE build manifest has no file inventory")
    for name, expected_hash in files.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(expected_hash, str)
        ):
            raise RuntimeError("PTE build file inventory is invalid")
        path = release_root / name
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise RuntimeError(f"PTE build file differs from manifest: {name}")
    return BuiltRelease(build_root, release_id, release_root, manifest_path, manifest)


def _verify_installed_environment(
    release_root: Path, *, repo_root: Path, runner: Runner,
) -> None:
    script = (
        "import importlib.metadata as m,json,sys\n"
        "from pathlib import Path\n"
        "import paper_trading_engine.cli\n"
        "from strategy_runtime import StrategyRelease,StrategyRuntime,deployment_inventory\n"
        "expected=('paper-trading-engine','czsc-trader-research','czsc-strategy-runtime',"
        "'czsc-strategy-manager','czsc-dataflows')\n"
        "forbidden=('vectorbt','optuna','tsfresh','czsc-strategy-evaluator',"
        "'czsc-factor-signal-catalog','czsc-strategy-template-catalog',"
        "'czsc-trading-execution-engine')\n"
        "editable=[]\n"
        "for name in expected:\n"
        "    direct=m.distribution(name).read_text('direct_url.json')\n"
        "    if json.loads(direct or '{}').get('dir_info',{}).get('editable'):\n"
        "        editable.append(name)\n"
        "present=[]\n"
        "for name in forbidden:\n"
        "    try: m.distribution(name)\n"
        "    except m.PackageNotFoundError: continue\n"
        "    present.append(name)\n"
        "assert not editable, f'editable PTE packages: {editable}'\n"
        "assert not present, f'RSCH-only packages installed in PTE: {present}'\n"
        "root=Path(sys.argv[1]); strategies=root/'strategies'\n"
        "inventory=deployment_inventory(strategies)\n"
        "runtime=StrategyRuntime(strategies)\n"
        "for reference in inventory:\n"
        "    family,version=reference.split('-',1)\n"
        "    payload=json.loads((strategies/family/'versions'/f'{version}.json').read_text(encoding='utf-8'))\n"
        "    runtime.describe(StrategyRelease.from_mapping(payload))\n"
    )
    _run(
        [str(_python_in(release_root / ".venv")), "-c", script, str(release_root)],
        cwd=repo_root,
        runner=runner,
    )


def _write_manifest(
    *,
    release_root: Path,
    release_id: str,
    git_commit: str,
    runtime_files: dict[str, str],
) -> dict[str, Any]:
    artifacts = {
        path.name: file_sha256(path)
        for path in sorted((release_root / "artifacts").glob("*.whl"))
    }
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "git_commit": git_commit,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "database_schema": {
            "current": RUNTIME_DATABASE_SCHEMA_VERSION,
            "compatible": list(RUNTIME_DATABASE_COMPATIBLE_VERSIONS),
        },
        "artifacts": artifacts,
        "strategy_snapshot_sha256": tree_sha256(release_root / "strategies"),
        "strategy_releases": _verify_strategy_snapshot(release_root / "strategies"),
        "runtime_files": dict(sorted(runtime_files.items())),
    }
    (release_root / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def _write_runtime_root(release_root: Path) -> dict[str, str]:
    marker = release_root / "runtime-root.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "czsc-trader-runtime",
                "strategy_root": "strategies",
            },
            indent=2,
        ) + "\n",
        encoding="utf-8", newline="\n",
    )
    return {marker.name: file_sha256(marker)}


def _initialize_service_host(
    runtime_root: Path,
    release_id: str,
    artifacts: Path,
    cache_dir: Path,
    uv_executable: Path,
    source_python: Path,
    repo_root: Path,
    runner: Runner,
) -> None:
    host = runtime_root / "host" / "releases" / release_id
    if host.exists():
        raise RuntimeError(f"PTE service host already exists: {host}")
    host.parent.mkdir(parents=True, exist_ok=True)
    host.mkdir()
    try:
        _create_environment(
            uv_executable=uv_executable,
            source_python=source_python,
            venv=host / ".venv",
            artifacts=artifacts,
            cache_dir=cache_dir,
            repo_root=repo_root,
            runner=runner,
            packages=(("pywin32>=308",) if os.name == "nt" else ()),
            no_dependencies=("paper-trading-engine==0.1.0",),
        )
        _verify_service_host(host)
        _run(
            [str(_python_in(host / '.venv')), '-I', '-B', '-c',
             'import paper_trading_engine.service_config; '
             'import paper_trading_engine.watchdog'
             + ('; import paper_trading_engine.windows_service' if os.name == 'nt' else '')],
            cwd=host, runner=runner,
        )
    except Exception:
        shutil.rmtree(host)
        raise


def _verify_service_host(host: Path) -> None:
    scripts = host / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    watchdog = scripts / ("pte-watchdog.exe" if os.name == "nt" else "pte-watchdog")
    if not watchdog.is_file():
        raise RuntimeError(f"PTE service host is incomplete: {watchdog}")
    site_packages = host / ".venv" / "Lib" / "site-packages"
    if not site_packages.is_dir():
        candidates = sorted((host / ".venv" / "lib").glob("python*/site-packages"))
        if len(candidates) != 1:
            raise RuntimeError(f"PTE service host has no site-packages: {host}")
        site_packages = candidates[0]
    editable = editable_installations(site_packages)
    if editable:
        raise RuntimeError(f"PTE service host contains editable installations: {editable}")
    heavyweight = service_host_runtime_dependencies(site_packages)
    if heavyweight:
        raise RuntimeError(f"PTE service host contains runtime dependencies: {heavyweight}")


def build_release(
    *,
    repo_root: Path,
    build_root: Path,
    release_id: str,
    source_python: Path = Path(sys.executable),
    uv_executable: Path | None = None,
    source_distribution_fetcher: SourceDistributionFetcher = _download_pypi_sdist,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Build a portable release bundle without writing to the PTE runtime."""
    repo_root = repo_root.resolve()
    build_root = build_root.resolve()
    cache_root = repo_root / ".tmp" / "pte-release"
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise RuntimeError(f"invalid PTE release id: {release_id}")
    git_commit = _git_tag_identity(repo_root, release_id, runner)
    destination = _build_release_root(build_root, release_id)
    if destination.exists():
        raise RuntimeError(f"PTE build already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{release_id}-{uuid4().hex}"
    staging.mkdir()
    try:
        source_root = staging / ".source"
        _export_tag_source(repo_root, release_id, source_root, runner)
        artifacts = staging / "artifacts"
        artifacts.mkdir()
        if uv_executable is None:
            discovered_uv = shutil.which("uv")
            if discovered_uv is None:
                raise RuntimeError("PTE build requires uv on PATH")
            uv_executable = Path(discovered_uv)
        uv_version = _run(
            [str(uv_executable), "--version"], cwd=source_root, runner=runner,
        ).stdout.strip()
        if not uv_version.startswith("uv "):
            raise RuntimeError(f"PTE build found an invalid uv executable: {uv_version}")
        build_env = os.environ.copy()
        if os.name == "nt":
            temp_root = cache_root / "temp"
            temp_root.mkdir(parents=True, exist_ok=True)
            build_support = (
                source_root / "packages" / "paper_trading_engine" / "src"
                / "paper_trading_engine" / "build_support"
            )
            if not (build_support / "sitecustomize.py").is_file():
                raise RuntimeError("PTE release source has no Windows sandbox build support")
            build_env.update({
                "PTE_INHERITED_TEMP_ACL": "1",
                "TEMP": str(temp_root),
                "TMP": str(temp_root),
                "PYTHONPATH": os.pathsep.join(
                    part for part in (
                        str(build_support), build_env.get("PYTHONPATH", ""),
                    ) if part
                ),
            })
        frozen = _run(
            [
                str(source_python), "-m", "pip", "freeze", "--exclude-editable",
                *[
                    option
                    for distribution in (*PTE_RESOLUTION_DISTRIBUTIONS, "czsc-trader-research")
                    for option in ("--exclude", distribution)
                ],
            ],
            cwd=repo_root,
            runner=runner,
        ).stdout
        constraints = staging / "build-constraints.txt"
        constraints.write_text(frozen, encoding="utf-8", newline="\n")
        pip_cache = cache_root / "pip"
        uv_cache = cache_root / "uv-build"
        for project in PTE_LOCAL_PROJECTS:
            _run(
                [
                    str(uv_executable), "build", "--wheel",
                    "--out-dir", str(artifacts), "--cache-dir", str(uv_cache),
                    "--python", str(source_python), "--no-python-downloads",
                    "--no-create-gitignore", str(source_root / project),
                ],
                cwd=source_root, env=build_env,
                runner=runner,
            )
        _verify_strategy_runtime_wheel_boundary(artifacts)
        source_archives = staging / ".source-archives"
        for distribution in PTE_SOURCE_DISTRIBUTIONS:
            version = _constraint_pin(constraints, distribution)
            source_archive = source_distribution_fetcher(
                distribution, version, source_archives,
            )
            _run(
                [
                    str(uv_executable), "build", "--wheel",
                    "--out-dir", str(artifacts), "--cache-dir", str(uv_cache),
                    "--python", str(source_python), "--no-python-downloads",
                    "--no-create-gitignore", str(source_archive),
                ],
                cwd=source_root, env=build_env, runner=runner,
            )
        _build_pte_wheelhouse(
            source_python=source_python,
            artifacts=artifacts,
            constraints=constraints,
            cache_dir=pip_cache,
            repo_root=source_root,
            env=build_env,
            runner=runner,
        )
        shutil.rmtree(source_archives)
        shutil.copytree(
            source_root / "strategies",
            staging / "strategies",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.lock"),
        )
        shutil.rmtree(source_root)
        manifest = _write_build_manifest(
            release_root=staging,
            release_id=release_id,
            git_commit=git_commit,
        )
        _replace_directory(staging, destination)
        built = load_built_release(build_root, release_id)
        return {
            "build": {
                "release_id": built.release_id,
                "git_commit": built.manifest["git_commit"],
                "build_root": str(built.release_root),
                "manifest_sha256": file_sha256(built.manifest_path),
            },
            "artifact_count": len(manifest["artifacts"]),
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def publish_release(
    *,
    build_root: Path,
    runtime_root: Path,
    release_id: str,
    source_python: Path = Path(sys.executable),
    uv_executable: Path | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Install one validated build bundle into the immutable PTE runtime."""
    build_root = build_root.resolve()
    runtime_root = runtime_root.resolve()
    built = load_built_release(build_root, release_id)
    uv_cache = build_root.parent.parent / ".tmp" / "pte-release" / "uv"
    if uv_executable is None:
        discovered_uv = shutil.which("uv")
        if discovered_uv is None:
            raise RuntimeError("PTE publication requires uv on PATH")
        uv_executable = Path(discovered_uv)
    uv_version = _run(
        [str(uv_executable), "--version"], cwd=built.release_root, runner=runner,
    ).stdout.strip()
    if not uv_version.startswith("uv "):
        raise RuntimeError(f"PTE publication found an invalid uv executable: {uv_version}")

    destination = runtime_root / "releases" / release_id
    if destination.exists():
        raise RuntimeError(f"PTE release already exists: {destination}")
    host = runtime_root / "host" / "releases" / release_id
    if host.exists():
        raise RuntimeError(f"PTE service host already exists: {host}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{release_id}-{uuid4().hex}"
    staging.mkdir()
    try:
        shutil.copytree(built.release_root / "artifacts", staging / "artifacts")
        shutil.copytree(built.release_root / "strategies", staging / "strategies")
        for name in ("build-constraints.txt", BUILD_MANIFEST_NAME):
            shutil.copy2(built.release_root / name, staging / name)
        runtime_files = {
            "build-constraints.txt": file_sha256(staging / "build-constraints.txt"),
            BUILD_MANIFEST_NAME: file_sha256(staging / BUILD_MANIFEST_NAME),
            **_write_runtime_root(staging),
        }
        _replace_directory(staging, destination)
        try:
            _create_environment(
                uv_executable=uv_executable,
                source_python=source_python,
                venv=destination / ".venv",
                artifacts=destination / "artifacts",
                cache_dir=uv_cache,
                repo_root=built.release_root,
                runner=runner,
                packages=(
                    "paper-trading-engine==0.1.0", "czsc-strategy-manager==0.1.0",
                ),
                no_dependencies=("czsc-trader-research==0.1.0",),
            )
            environment_lock = destination / "environment.lock"
            environment_lock.write_text(
                _run(
                    [
                        str(uv_executable), "pip", "freeze",
                        "--python", str(_python_in(destination / ".venv")),
                        "--no-python-downloads",
                        "--cache-dir", str(uv_cache),
                    ],
                    cwd=built.release_root,
                    runner=runner,
                ).stdout,
                encoding="utf-8", newline="\n",
            )
            runtime_files[environment_lock.name] = file_sha256(environment_lock)
            manifest = _write_manifest(
                release_root=destination,
                release_id=release_id,
                git_commit=str(built.manifest["git_commit"]),
                runtime_files=runtime_files,
            )
            _verify_installed_environment(
                destination, repo_root=built.release_root, runner=runner,
            )
            release = load_release(runtime_root, release_id)
        except Exception:
            shutil.rmtree(destination)
            raise
        try:
            for directory in ("config", "data", "logs", "state"):
                (runtime_root / "shared" / directory).mkdir(parents=True, exist_ok=True)
            _initialize_service_host(
                runtime_root,
                release_id,
                release.release_root / "artifacts",
                uv_cache,
                uv_executable,
                source_python,
                built.release_root,
                runner,
            )
        except Exception:
            shutil.rmtree(destination)
            raise
        return {
            "release": release.identity(),
            "artifact_count": len(manifest["artifacts"]),
            "builder": uv_version,
            "active": False,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _write(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")


def _restart_command(
    runtime_root: Path, release_id: str, wait: float, host: str, port: int,
) -> list[str]:
    release = load_release(runtime_root, release_id)
    shared = runtime_root / "shared"
    return [
        str(release.pte_executable),
        "control", "restart",
        "--repo-root", str(release.release_root),
        "--database", str(shared / "state" / "runtime.db"),
        "--data-dir", str(shared / "data"),
        "--config-root", str(shared / "config"),
        "--release-manifest", str(release.manifest_path),
        "--host", host,
        "--port", str(port),
        "--wait", str(wait),
    ]


def _running_release(host: str, port: int, timeout: float = 5.0) -> str | None:
    with urlopen(f"http://{host}:{port}/api/health", timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    release = payload.get("release")
    if not isinstance(release, dict):
        return None
    value = release.get("release_id")
    return str(value) if value else None


def _database_schema_version(database: Path) -> int:
    if not database.is_file():
        return RUNTIME_DATABASE_SCHEMA_VERSION
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT value FROM settings WHERE key='runtime_database_schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        connection.close()
    if row is None:
        return RUNTIME_DATABASE_SCHEMA_VERSION
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"PTE runtime database has an invalid schema version: {row[0]!r}"
        ) from exc


def _require_database_compatibility(release, database: Path) -> int:
    database_schema = _database_schema_version(database)
    compatible = release.manifest["database_schema"]["compatible"]
    if database_schema not in compatible:
        raise RuntimeError(
            f"PTE release {release.release_id} does not support database schema "
            f"{database_schema}; compatible={compatible}"
        )
    return database_schema


def verify_release_configuration(
    runtime_root: Path,
    release_id: str,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Read-only validation of runtime configuration and account strategy bindings."""
    release = load_release(runtime_root, release_id)
    shared = release.runtime_root / "shared"
    data_dir = shared / "data"
    database = shared / "state" / "runtime.db"
    config_dir = shared / "config"
    _require_database_compatibility(release, database)
    script = (
        "import json,sqlite3,sys\n"
        "from pathlib import Path\n"
        "from dotenv import dotenv_values\n"
        "from paper_trading_engine.srt_advice_client import SrtAdviceClient\n"
        "root=Path(sys.argv[1]); data=Path(sys.argv[2]); database=Path(sys.argv[3]); config=Path(sys.argv[4])\n"
        "def require(condition,message):\n"
        "    if not condition: raise RuntimeError(message)\n"
        "require(database.is_file(),'PTE release verification found no runtime database')\n"
        "require(data.is_dir(),'PTE release verification found no shared data directory')\n"
        "env_file=config/'.env'\n"
        "require(env_file.is_file(),'PTE release verification found no runtime configuration')\n"
        "require(str(dotenv_values(env_file).get('TUSHARE_TOKEN') or '').strip(),'PTE release verification found no TUSHARE_TOKEN')\n"
        "connection=sqlite3.connect(f'file:{database.resolve().as_posix()}?mode=ro',uri=True)\n"
        "try:\n"
        "    rows=connection.execute(\"SELECT account_id,strategy_id,strategy_version,release_hash,symbol,asset_type,selection_data_cutoff FROM virtual_accounts WHERE account_type='STRATEGY' AND status<>'RETIRED'\").fetchall()\n"
        "finally:\n"
        "    connection.close()\n"
        "client=SrtAdviceClient(repo_root=root,data_dir=data)\n"
        "validated=[]\n"
        "for account_id,strategy_id,version,release_hash,symbol,asset,cutoff in rows:\n"
        "    identity=client.validate_account_binding(strategy_id=strategy_id,strategy_version=version,symbol=symbol,asset=asset)\n"
        "    require(identity.release_hash==release_hash,f'{account_id}: account release hash differs from frozen strategy')\n"
        "    require(identity.selection_data_cutoff.isoformat()==cutoff,f'{account_id}: selection cutoff differs from frozen strategy')\n"
        "    validated.append(identity.release_id)\n"
        "print(json.dumps({'accounts':len(rows),'releases':sorted(set(validated))}))\n"
    )
    completed = _run(
        [
            str(_python_in(release.release_root / ".venv")), "-c", script,
            str(release.release_root), str(data_dir), str(database), str(config_dir),
        ],
        cwd=release.release_root,
        runner=runner,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PTE release verification returned invalid output") from exc
    if (
        not isinstance(result, dict) or type(result.get("accounts")) is not int
        or result["accounts"] < 0 or not isinstance(result.get("releases"), list)
        or (result["accounts"] > 0 and not result["releases"])
        or (result["accounts"] == 0 and result["releases"])
    ):
        raise RuntimeError("PTE release verification returned invalid account bindings")
    return result


def deploy_release(
    runtime_root: Path,
    release_id: str,
    *,
    wait: float = 60.0,
    host: str = "127.0.0.1",
    port: int = 8080,
    runner: Runner = subprocess.run,
    running_release: Callable[[str, int], str | None] = _running_release,
) -> dict[str, object]:
    if host != "127.0.0.1":
        raise RuntimeError("PTE deployment host must be localhost")
    runtime_root = runtime_root.resolve()
    previous = resolve_active_release(runtime_root)
    target = load_release(runtime_root, release_id)
    if previous.release_id == release_id:
        raise RuntimeError(f"PTE release is already active: {release_id}")
    database = runtime_root / "shared" / "state" / "runtime.db"
    _require_database_compatibility(target, database)
    verify_release_configuration(runtime_root, release_id, runner=runner)
    activate_release(runtime_root, release_id)
    try:
        _run(
            _restart_command(runtime_root, previous.release_id, wait, host, port),
            cwd=runtime_root,
            runner=runner,
        )
        observed = running_release(host, port)
        if observed != release_id:
            raise RuntimeError(
                f"PTE health reported release {observed!r}, expected {release_id!r}"
            )
    except Exception as deployment_error:
        try:
            _require_database_compatibility(previous, database)
            verify_release_configuration(runtime_root, previous.release_id, runner=runner)
        except Exception as compatibility_error:
            raise RuntimeError(
                f"PTE deployment failed ({deployment_error}); rollback blocked by "
                f"release/account compatibility ({compatibility_error}); "
                "active release was not switched back"
            ) from compatibility_error
        activate_release(runtime_root, previous.release_id)
        try:
            _run(
                _restart_command(runtime_root, previous.release_id, wait, host, port),
                cwd=runtime_root,
                runner=runner,
            )
            observed = running_release(host, port)
            if observed != previous.release_id:
                raise RuntimeError(
                    f"rollback health reported release {observed!r}, "
                    f"expected {previous.release_id!r}"
                )
        except Exception as rollback_error:
            raise RuntimeError(
                f"PTE deployment failed ({deployment_error}); rollback failed ({rollback_error})"
            ) from rollback_error
        raise RuntimeError(
            f"PTE deployment failed and was rolled back: {deployment_error}"
        ) from deployment_error
    return {
        "status": "READY",
        "release_id": release_id,
        "previous_release_id": previous.release_id,
    }


def deploy_previous_release(
    runtime_root: Path,
    *,
    wait: float = 60.0,
    host: str = "127.0.0.1",
    port: int = 8080,
    runner: Runner = subprocess.run,
    running_release: Callable[[str, int], str | None] = _running_release,
) -> dict[str, object]:
    selection = json.loads(active_release_path(runtime_root).read_text(encoding="utf-8"))
    previous = selection.get("previous_release_id")
    if not isinstance(previous, str) or not previous:
        raise RuntimeError("active PTE release has no rollback target")
    return deploy_release(
        runtime_root,
        previous,
        wait=wait,
        host=host,
        port=port,
        runner=runner,
        running_release=running_release,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pte-release")
    actions = parser.add_subparsers(dest="action", required=True)
    build = actions.add_parser("build")
    build.add_argument("--repo-root", required=True, type=Path)
    build.add_argument("--build-root", required=True, type=Path)
    build.add_argument("--release", required=True)
    build.add_argument("--python", type=Path, default=Path(sys.executable))
    build.add_argument("--uv", type=Path)
    publish = actions.add_parser("publish")
    publish.add_argument("--build-root", required=True, type=Path)
    publish.add_argument("--runtime-root", required=True, type=Path)
    publish.add_argument("--release", required=True)
    publish.add_argument("--python", type=Path, default=Path(sys.executable))
    publish.add_argument("--uv", type=Path)
    for action in ("activate", "verify", "deploy", "rollback", "status"):
        leaf = actions.add_parser(action)
        leaf.add_argument("--runtime-root", required=True, type=Path)
        if action in {"activate", "verify", "deploy"}:
            leaf.add_argument("--release", required=True)
        if action in {"deploy", "rollback"}:
            leaf.add_argument("--wait", type=float, default=60.0)
            leaf.add_argument("--host", default="127.0.0.1")
            leaf.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.action == "build":
            result = build_release(
                repo_root=args.repo_root,
                build_root=args.build_root,
                release_id=args.release,
                source_python=args.python,
                uv_executable=args.uv,
            )
        elif args.action == "publish":
            result = publish_release(
                build_root=args.build_root,
                runtime_root=args.runtime_root,
                release_id=args.release,
                source_python=args.python,
                uv_executable=args.uv,
            )
        elif args.action == "activate":
            release = load_release(args.runtime_root, args.release)
            _require_database_compatibility(
                release, args.runtime_root / "shared" / "state" / "runtime.db"
            )
            result = activate_release(args.runtime_root, args.release)
        elif args.action == "verify":
            result = verify_release_configuration(args.runtime_root, args.release)
        elif args.action == "deploy":
            result = deploy_release(
                args.runtime_root,
                args.release,
                wait=args.wait,
                host=args.host,
                port=args.port,
            )
        elif args.action == "rollback":
            result = deploy_previous_release(
                args.runtime_root,
                wait=args.wait,
                host=args.host,
                port=args.port,
            )
        else:
            active = resolve_active_release(args.runtime_root)
            result = {
                "active": active.identity(),
                "selection": json.loads(
                    active_release_path(args.runtime_root).read_text(encoding="utf-8")
                ),
            }
        _write({"status": "PASS", "command": f"pte.release.{args.action}", "result": result})
        return 0
    except Exception as exc:
        _write({
            "status": "FAIL",
            "command": f"pte.release.{args.action}",
            "error": {"code": "release_error", "message": str(exc)},
        })
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
