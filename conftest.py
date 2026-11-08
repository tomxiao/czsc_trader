"""Repository-wide pytest temporary-directory bootstrap."""

from collections.abc import Iterator
import json
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parent
_EXPECTED_VENV = (_REPOSITORY_ROOT / ".venv").resolve()
_RUN_ID = os.environ.get("CZSC_PYTEST_RUN_ID") or uuid4().hex
_PYTEST_RUN = _REPOSITORY_ROOT / ".tmp" / "pytest" / f"run-{_RUN_ID}"
_SHARED_CACHE = os.environ.get("CZSC_TEST_BYTECODE_ROOT")
_PYTHON_CACHE_ROOT = (Path(_SHARED_CACHE).resolve() if _SHARED_CACHE else
                      _REPOSITORY_ROOT / ".tmp" / "pycache" / f"run-{_RUN_ID}")
if not _PYTHON_CACHE_ROOT.is_relative_to(_REPOSITORY_ROOT / '.tmp/pycache'):
    raise pytest.UsageError('test bytecode must stay under the repository .tmp/pycache')

if Path(sys.prefix).resolve() != _EXPECTED_VENV:
    raise pytest.UsageError(
        "CZSC Trader tests must use the repository virtual environment. "
        f"Current interpreter: {sys.executable}. "
        r"Run .\.venv\Scripts\python.exe -m pytest -c pyproject.toml ..."
    )

# The root conftest itself is compiled before this assignment. All modules loaded
# afterwards are redirected. Standalone runs own their cache; the regression
# runner removes its shared cache after every child process has completed.
sys.pycache_prefix = str(_PYTHON_CACHE_ROOT)


def pytest_addoption(parser):
    parser.addoption("--release-acceptance", action="store_true",
                     help="Include checks against the repository's registered frozen packages")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--release-acceptance"):
        selected, deferred = [], []
        for item in items:
            (deferred if item.get_closest_marker("release_acceptance") else selected).append(item)
        items[:] = selected
        config.hook.pytest_deselected(items=deferred)
    if destination := os.environ.get("CZSC_PYTEST_COLLECTION"):
        identities = []
        for item in items:
            address, bracket, parameters = item.nodeid.partition("[")
            parts = address.split("::")
            parts[-1] += bracket + parameters
            classname = ".".join([parts[0][:-3].replace("/", "."), *parts[1:-1]])
            identities.append((classname, parts[-1]))
        Path(destination).write_text(json.dumps(identities), encoding="utf-8")


@pytest.fixture(scope="session", params=[
    path for path in sorted((_REPOSITORY_ROOT / "strategies").glob("S*/versions/v*.json"))
    if not (_REPOSITORY_ROOT / "strategies/deployments/history" /
            f"{path.parent.parent.name}-{path.stem}.json").exists()
], ids=lambda path: f"{path.parent.parent.name}-{path.stem}")
def registered_release(request):
    from strategy_manager import StrategyRegistry

    path = request.param
    return StrategyRegistry(_REPOSITORY_ROOT / "strategies").get_version(
        path.parent.parent.name, path.stem,
    )


@pytest.fixture(scope="session")
def loaded_release(registered_release, frozen_seed_root):
    """Check current frozen packages without manufacturing deployment approval."""
    from strategy_runtime import (
        InspectionRuntimePermit, StrategyRelease, StrategyRuntime, canonical_sha256,
        load_inspection_deployment, load_strategy_deployment, validate_release_package,
    )

    root = _REPOSITORY_ROOT / "strategies"
    release_id = registered_release.release_id
    if (root / "deployments" / f"{release_id}.json").exists():
        deployment = load_strategy_deployment(root, release_id)
        runtime = StrategyRuntime(strategy_root=root)
    else:
        # Freeze and deployment are separate states. Inspect an authenticated,
        # byte-identical copy of an undeployed package using technical admission.
        verified = validate_release_package(root, release_id)
        family, version = release_id.rsplit("-", 1)
        workspace = frozen_seed_root / ".tmp/strategy-inspection" / release_id
        repository = workspace / "repository"
        isolated = repository / "strategies"
        package = Path(family) / "releases" / version
        shutil.copytree(root / package, isolated / package)
        versions = isolated / family / "versions"
        versions.mkdir(parents=True)
        shutil.copyfile(root / family / "versions" / f"{version}.json", versions / f"{version}.json")
        permit = InspectionRuntimePermit(
            release_id, release_id, registered_release.release_hash, verified.package_sha256,
            canonical_sha256({"test": "frozen_package_acceptance", "release": release_id}),
            repository, workspace,
        )
        deployment = load_inspection_deployment(isolated, release_id, permit)
        runtime = StrategyRuntime(strategy_root=isolated, inspection_permit=permit)
        assert not (isolated / "deployments").exists()
    release = StrategyRelease.from_mapping(registered_release.to_dict())
    if release.payload['runtime'].get('kind') == 'ACCOUNT_REPLAY':
        from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityStrategyDefinition
        actual = EquityStrategyCandidate(registered_release.strategy_id, deployment.runtime_candidate_id,
            EquityStrategyDefinition.from_dict(dict(release.payload['equity_definition'])), deployment.source_root)
    else:
        actual = runtime.describe(release)
    return registered_release, deployment, actual, runtime



def _create_directory(path: Path) -> None:
    """Create a private directory while retaining inherited ACLs on Windows."""

    mode = 0o777 if os.name == "nt" else 0o700
    path.mkdir(mode=mode, parents=True, exist_ok=False)


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Return an isolated repository-local path without pytest's Windows ACL rewrite."""

    _PYTEST_RUN.parent.mkdir(parents=True, exist_ok=True)
    _PYTEST_RUN.mkdir(exist_ok=True)
    path = _PYTEST_RUN / f"case-{uuid4().hex}"
    _create_directory(path)
    yield path


@pytest.fixture(scope="session")
def frozen_seed_root() -> Path:
    """Keep the immutable runtime seed inside this process's managed workspace."""
    path = _PYTEST_RUN / "frozen-seed"
    _create_directory(path)
    return path


def pytest_sessionfinish() -> None:
    """Remove the process workspace and pytest's root bootstrap bytecode."""

    shutil.rmtree(_PYTEST_RUN, ignore_errors=True)
    if not _SHARED_CACHE:
        shutil.rmtree(_PYTHON_CACHE_ROOT, ignore_errors=True)
    shutil.rmtree(_REPOSITORY_ROOT / "__pycache__", ignore_errors=True)
