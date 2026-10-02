from __future__ import annotations

from pathlib import Path
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation

import pytest

from czsc_trader.application.errors import ValidationError
from czsc_trader.application.runtime_acceptance import prospective_release
from czsc_trader.application.strategy_runtime_service import (
    deploy_strategy,
    list_installed_strategies,
    strategy_info,
    validate_release_package,
)


ROOT = Path(__file__).resolve().parents[2]


def test_strategy_commands_cover_only_installed_srt_versions(current_frozen):
    context, version = current_frozen
    repo = context.root
    (context.strategy_root / "deployments/S900-v1.json").unlink()

    assert list_installed_strategies(context).result["strategies"] == []
    untracked = repo / "strategies" / "S900" / "releases" / "v1" / "untracked.py"
    untracked.write_text("raise RuntimeError('must not be deployed')\n", encoding="utf-8")
    expected_release = prospective_release(
        version
    )
    with pytest.raises(ValueError, match="untracked or missing files"):
        validate_release_package(
            context,
            "S900-v1",
            expected_release=expected_release,
        )
    with pytest.raises(ValidationError, match="untracked or missing files"):
        deploy_strategy(context, "S900-v1")
    untracked.unlink()
    deployed = deploy_strategy(context, "S900-v1")
    listed = list_installed_strategies(context, "S900")
    info = strategy_info(context, "S900-v1")

    assert deployed.result["deployment_state"] == "SRT_DEPLOYED"
    assert [item["strategy_version_id"] for item in listed.result["strategies"]] == ["S900-v1"]
    assert info.result["strategy_version_id"] == "S900-v1"
    assert len(info.result["observation_sha256"]) == 64
    assert not list((repo / "strategies" / "S900" / "releases" / "v1").rglob("__pycache__"))
