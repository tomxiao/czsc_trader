# Risk ownership: TDR-27 TDR-04
"""Current contracts and explicit rejection of retired serialized formats."""

from pathlib import Path
import shutil

import pytest
from strategy_manager import StrategyRegistry
from czsc_trader.application import RepositoryContext
from test_candidate_freeze import (
    inspection as inspection, inspected_candidate as inspected_candidate, completed as completed, fresh_completed as fresh_completed,
    fresh_inspection as fresh_inspection, managed_evaluation as managed_evaluation,
)


def assert_installed_release_identity(loaded_release):
    from czsc_trader.application import strategy_info
    from czsc_trader.application.errors import ValidationError
    from strategy_runtime.equity_definition import EquityStrategyCandidate

    registered_release, deployment, definition, _ = loaded_release
    context = RepositoryContext.discover(Path(__file__).resolve().parents[2])
    if not (context.strategy_root / "deployments" / f"{registered_release.release_id}.json").exists():
        with pytest.raises(ValidationError, match="cannot read strategy deployment file") as failed:
            strategy_info(context, registered_release.release_id)
        assert failed.value.code == "strategy_info_failed"
        assert failed.value.context["strategy_version_id"] == registered_release.release_id
        return
    result = strategy_info(context, registered_release.release_id)
    assert result.status == "PASS"
    assert result.result["strategy_version_id"] == registered_release.release_id
    assert result.result["strategy_version_hash"] == registered_release.release_hash
    if isinstance(definition, EquityStrategyCandidate):
        assert result.result["fee_rate"] is None
        assert result.result["runtime_hash"] == deployment.binding.spec.implementation_sha256
    else:
        policy = definition.execution
        expected_fee = (policy.settings["capital"]["fee_rate"]
                        if policy.policy_type == "FROZEN_RULE" else policy.settings["one_way_cost"])
        assert 0 <= expected_fee < 1
        assert result.result["fee_rate"] == expected_fee




@pytest.fixture
def current_frozen(tmp_path):
    # Consumers test loading/reporting/maintenance, not the inspection that made
    # this immutable synthetic package. Freeze tests still run the real pipeline.
    seed = Path(__file__).parents[1] / "fixtures/published/legacy"
    root = tmp_path / "frozen-repo"
    (root / "src/czsc_trader").mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(seed, root / "strategies")
    context = RepositoryContext.discover(root)
    # Fresh freeze/deploy creates this coordination file before consumers take
    # byte-for-byte publication snapshots. Recreate it through the real lock.
    from strategy_manager.write_lock import RegistryWriteLock
    with RegistryWriteLock(context.strategy_root).hold():
        pass
    return context, StrategyRegistry(context.strategy_root).get_version("S900", "v1")
