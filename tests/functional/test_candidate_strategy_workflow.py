from __future__ import annotations

import json
from test_current_contracts import current_frozen as current_frozen, inspection as inspection, completed as completed, managed_evaluation as managed_evaluation

import pytest

from czsc_trader.application import (
    ValidationError,
    deploy_strategy,
    list_installed_strategies,
    strategy_info,
    validate_release_package,
)


def test_strategy_commands_cover_only_installed_srt_versions(current_frozen):
    context, version = current_frozen
    repo = context.root
    (context.strategy_root / "deployments/S900-v1.json").unlink()

    assert list_installed_strategies(context).result["strategies"] == []
    untracked = repo / "strategies" / "S900" / "releases" / "v1" / "untracked.py"
    untracked.write_text("raise RuntimeError('must not be deployed')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="untracked or missing files"):
        validate_release_package(context, "S900-v1")
    with pytest.raises(ValidationError, match="untracked or missing files"):
        deploy_strategy(context, "S900-v1")
    assert not (context.strategy_root / "deployments/S900-v1.json").exists()
    untracked.unlink()
    deployed = deploy_strategy(context, "S900-v1")
    listed = list_installed_strategies(context, "S900")
    info = strategy_info(context, "S900-v1")

    assert deployed.result["deployment_state"] == "SRT_DEPLOYED"
    assert [item["strategy_version_id"] for item in listed.result["strategies"]] == ["S900-v1"]
    assert info.result["strategy_version_id"] == "S900-v1"
    assert len(info.result["observation_sha256"]) == 64
    assert info.result["strategy_version_hash"] == version.release_hash
    assert deploy_strategy(context, "S900-v1").result == deployed.result
    assert info.result["receipt_hash"] == deployed.result["receipt_hash"]
    manifest, binding, _ = validate_release_package(context, "S900-v1")
    assert not any(name.startswith("charts/") for name in binding["install_files"])
    assert manifest["strategy_version_hash"] == version.release_hash
    assert not list((repo / "strategies" / "S900" / "releases" / "v1").rglob("__pycache__"))

    receipt_path = context.strategy_root / "deployments/S900-v1.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["receipt_hash"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    corrupt_bytes = receipt_path.read_bytes()
    for query, code in ((lambda: strategy_info(context, "S900-v1"), "strategy_info_failed"),
                        (lambda: list_installed_strategies(context), "strategy_list_failed")):
        with pytest.raises(ValidationError) as error:
            query()
        assert error.value.code == code
    assert receipt_path.read_bytes() == corrupt_bytes
