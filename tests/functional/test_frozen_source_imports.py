"""Frozen source dependencies must resolve without loader-injected aliases."""

import ast
import importlib
from pathlib import Path

import pytest

from czsc_trader.application import RepositoryContext, validate_release_package
from strategy_manager import StrategyRegistry
from strategy_runtime import StrategyRelease, StrategyRuntime, load_strategy_deployment


ROOT = Path(__file__).resolve().parents[2]
RELEASES = (("S001", "v1"), ("S001", "v2"), ("S002", "v1"), ("S003", "v1"), ("S007", "v1"))


def test_frozen_relative_imports_resolve_inside_the_package():
    for path in (ROOT / "strategies").rglob("*.py"):
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


@pytest.mark.parametrize(("strategy_id", "version"), RELEASES)
def test_frozen_source_imports_without_closure_aliases(strategy_id, version, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.setattr("sys.dont_write_bytecode", True)
    prefix = f"strategies.{strategy_id}.releases.{version}.runtime.strategy_runtime"
    source = ROOT / "strategies" / strategy_id / "releases" / version / "runtime/strategy_runtime"
    for path in sorted(source.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        suffix = ".".join(path.relative_to(source).with_suffix("").parts)
        module = importlib.import_module(f"{prefix}.{suffix}")
        assert Path(module.__file__).resolve() == path.resolve()


@pytest.mark.parametrize(("strategy_id", "version"), RELEASES)
def test_frozen_source_keeps_authenticated_runtime_loading(strategy_id, version):
    context = RepositoryContext.discover(ROOT)
    stored = StrategyRegistry(context.strategy_root).get_version(strategy_id, version)
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
