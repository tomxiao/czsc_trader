# Risk ownership: TDR-27
"""Frozen source dependencies must resolve without loader-injected aliases."""

import importlib
from pathlib import Path

import pytest
from frozen_contract_support import current_frozen as current_frozen

from strategy_runtime import validate_release_package as authenticate_package


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.release_acceptance


def test_frozen_source_imports_without_closure_aliases(loaded_release, monkeypatch):
    registered_release, _, _, _ = loaded_release
    from frozen_contract_support import assert_installed_release_identity
    assert_installed_release_identity(loaded_release)
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.setattr("sys.dont_write_bytecode", True)
    source = authenticate_package(ROOT / "strategies", registered_release.release_id).source_root
    prefix = ".".join(source.relative_to(ROOT).parts)
    for path in sorted(source.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        suffix = ".".join(path.relative_to(source).with_suffix("").parts)
        module = importlib.import_module(f"{prefix}.{suffix}")
        assert Path(module.__file__).resolve() == path.resolve()


def test_TDR_27_C07_undeployed_frozen_package_loads_only_from_isolated_copy(current_frozen):
    import shutil
    from strategy_runtime import (InspectionRuntimePermit, StrategyRelease, StrategyRuntime,
        canonical_sha256, load_inspection_deployment)
    context, version = current_frozen
    (context.strategy_root / 'deployments/S900-v1.json').unlink()
    before = {path.relative_to(context.strategy_root): path.read_bytes()
              for path in context.strategy_root.rglob('*') if path.is_file()}
    verified = authenticate_package(context.strategy_root, version.release_id)
    workspace = context.root / '.tmp/strategy-inspection/undeployed'
    repository = workspace / 'repository'
    isolated = repository / 'strategies'
    package = Path('S900/releases/v1')
    shutil.copytree(context.strategy_root / package, isolated / package)
    versions = isolated / 'S900/versions'
    versions.mkdir(parents=True)
    shutil.copyfile(context.strategy_root / 'S900/versions/v1.json', versions / 'v1.json')
    permit = InspectionRuntimePermit(workspace.name, version.release_id,
        version.release_hash, verified.package_sha256, canonical_sha256({'case':'TDR-27-C07'}),
        repository, workspace)
    deployment = load_inspection_deployment(isolated, version.release_id, permit)
    runtime = StrategyRuntime(strategy_root=isolated, inspection_permit=permit)
    definition = runtime.describe(StrategyRelease.from_mapping(version.to_dict()))
    assert definition.release_id == version.release_id
    assert deployment.source_root.is_relative_to(isolated)
    assert not (isolated / 'deployments').exists()
    assert {path.relative_to(context.strategy_root): path.read_bytes()
            for path in context.strategy_root.rglob('*') if path.is_file()} == before
