"""Current contracts and explicit rejection of retired serialized formats."""

from pathlib import Path
import shutil

import pytest
from strategy_manager import StrategyRegistry
from strategy_runtime import StrategyRelease
from czsc_trader.application import RepositoryContext, freeze_candidate, deploy_strategy
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools import ResearchBatchRef
from test_candidate_freeze import (
    inspection as inspection, inspected_candidate as inspected_candidate, approve,
    completed as completed, fresh_completed as fresh_completed,
    fresh_inspection as fresh_inspection, managed_evaluation as managed_evaluation,
)


@pytest.mark.release_acceptance
def test_real_installed_versions_report_execution_contract_fees(registered_release):
    from czsc_trader.application import strategy_info
    from strategy_runtime import StrategyRuntime

    context = RepositoryContext.discover(Path(__file__).resolve().parents[2])
    result = strategy_info(context, registered_release.release_id)
    assert result.status == "PASS"
    policy = StrategyRuntime(strategy_root=context.strategy_root).describe(
        StrategyRelease.from_mapping(registered_release.to_dict()),
    ).execution
    expected_fee = (policy.settings["capital"]["fee_rate"]
                    if policy.policy_type == "FROZEN_RULE" else policy.settings["one_way_cost"])
    assert result.result["strategy_version_id"] == registered_release.release_id
    assert result.result["fee_rate"] == expected_fee


@pytest.fixture
def freshly_frozen(inspected_candidate):
    # Exercise real freeze/deployment once from the same verified inspection seed
    # used by persistence tests; consumers still receive private repository copies.
    context, report, source = inspected_candidate
    receipt = freeze_candidate(context, approve(context, report, source))
    assert receipt.status.value == "COMMITTED", receipt
    deploy_strategy(context, "S900-v1")
    return context, StrategyRegistry(context.strategy_root).get_version("S900", "v1")


@pytest.fixture
def current_frozen(request, tmp_path, frozen_seed_root):
    seed = frozen_seed_root / "strategies"
    if not seed.exists():
        context, _ = request.getfixturevalue("freshly_frozen")
        shutil.copytree(context.strategy_root, seed)
    root = tmp_path / "frozen-repo"
    (root / "src/czsc_trader").mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(seed, root / "strategies")
    context = RepositoryContext.discover(root)
    return context, StrategyRegistry(context.strategy_root).get_version("S900", "v1")




@pytest.mark.parametrize("schema", [1, True, "4"])
def test_delivery_receipt_rejects_old_schema(schema):
    reference = d.DeliveryReference(ResearchBatchRef("S900"), d.DeliveryStage.MANDATE, 1, "a" * 64)
    raw = d.DeliveryReceipt(reference, (d.PublicationFile("report.md", "b" * 64),)).to_dict()
    raw["schema_version"] = schema
    with pytest.raises((TypeError, ValueError)):
        d.DeliveryReceipt.from_dict(raw)
