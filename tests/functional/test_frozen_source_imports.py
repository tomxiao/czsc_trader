"""Frozen source dependencies must resolve without loader-injected aliases."""

import ast
import importlib
from pathlib import Path

import pytest

from czsc_trader.application import RepositoryContext, validate_release_package
from strategy_manager import StrategyRegistry
from strategy_runtime import StrategyRelease, StrategyRuntime, load_strategy_deployment


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.release_acceptance


def test_frozen_relative_imports_resolve_inside_the_package():
    sources = [
        load_strategy_deployment(ROOT / "strategies", f"{path.parent.parent.name}-{path.stem}").source_root
        for path in sorted((ROOT / "strategies").glob("S*/versions/v*.json"))
    ]
    assert sources, "registered frozen packages must be present for release acceptance"
    for path in (path for source in sources for path in source.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            target = path.parent
            for _ in range(node.level - 1):
                target = target.parent
            target = target.joinpath(*(node.module or "").split("."))
            assert target.with_suffix(".py").is_file() or (target / "__init__.py").is_file(), (
                path, node.lineno, node.module
            )


def test_frozen_source_imports_without_closure_aliases(registered_release, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.setattr("sys.dont_write_bytecode", True)
    source = load_strategy_deployment(ROOT / "strategies", registered_release.release_id).source_root
    prefix = ".".join(source.relative_to(ROOT).parts)
    for path in sorted(source.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        suffix = ".".join(path.relative_to(source).with_suffix("").parts)
        module = importlib.import_module(f"{prefix}.{suffix}")
        assert Path(module.__file__).resolve() == path.resolve()


def test_frozen_source_keeps_authenticated_runtime_loading(registered_release):
    context = RepositoryContext.discover(ROOT)
    stored = StrategyRegistry(context.strategy_root).get_version(
        registered_release.strategy_id, registered_release.version,
    )
    manifest, binding, source = validate_release_package(context, stored.release_id)
    deployment = load_strategy_deployment(context.strategy_root, stored.release_id)
    definition = StrategyRuntime().describe(
        StrategyRelease.from_mapping(stored.to_dict()),
        source_root=deployment.source_root,
        runtime_binding=deployment.binding,
    )
    assert definition.release_hash == stored.release_hash == deployment.release_hash
    assert definition.implementation.source_sha256 == binding["implementation_sha256"]
    assert manifest["package_hash"] == deployment.package_hash
    assert source == deployment.source_root
