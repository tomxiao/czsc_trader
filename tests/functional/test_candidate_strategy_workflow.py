from __future__ import annotations

from pathlib import Path
import shutil

import pytest
from strategy_manager import StrategyRegistry

from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.errors import ValidationError
from czsc_trader.application.runtime_acceptance import prospective_release
from czsc_trader.application.strategy_runtime_service import (
    deploy_strategy,
    list_installed_strategies,
    strategy_info,
    validate_release_package,
)


ROOT = Path(__file__).resolve().parents[2]


def _release_package(repo: Path, reference: str) -> None:
    strategy_id, version = reference.rsplit("-", 1)
    destination = repo / "strategies" / strategy_id / "releases" / version
    source = ROOT / "strategies" / strategy_id / "releases" / version
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def test_strategy_commands_cover_only_installed_srt_versions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "czsc_trader").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='0.1'\n", encoding="utf-8"
    )
    shutil.copytree(ROOT / "strategies", repo / "strategies")
    shutil.rmtree(repo / "strategies" / "deployments")
    _release_package(repo, "S007-v1")
    context = RepositoryContext.discover(repo)

    assert list_installed_strategies(context).result["strategies"] == []
    untracked = repo / "strategies" / "S007" / "releases" / "v1" / "untracked.py"
    untracked.write_text("raise RuntimeError('must not be deployed')\n", encoding="utf-8")
    expected_release = prospective_release(
        StrategyRegistry(context.strategy_root).get_version("S007", "v1")
    )
    with pytest.raises(ValueError, match="untracked or missing files"):
        validate_release_package(
            context,
            "S007-v1",
            expected_release=expected_release,
        )
    with pytest.raises(ValidationError, match="untracked or missing files"):
        deploy_strategy(context, "S007-v1")
    untracked.unlink()
    deployed = deploy_strategy(context, "S007-v1")
    listed = list_installed_strategies(context, "S007")
    info = strategy_info(context, "S007-v1")

    assert deployed.result["deployment_state"] == "SRT_DEPLOYED"
    assert [item["strategy_version_id"] for item in listed.result["strategies"]] == ["S007-v1"]
    assert info.result["strategy_version_id"] == "S007-v1"
    assert info.result["chart_contract"] is True
    assert not list((repo / "strategies" / "S007" / "releases" / "v1").rglob("__pycache__"))
