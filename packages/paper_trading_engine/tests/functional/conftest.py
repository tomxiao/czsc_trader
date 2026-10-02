from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

# Reuse the actual inspect -> approve -> freeze -> deploy fixture; no repository releases.
sys.path.insert(0, str(PACKAGE_ROOT.parents[1] / "tests/functional"))
from current_contract_support import candidate_payload as candidate_payload  # noqa: E402
from test_current_contracts import (  # noqa: E402
    current_frozen as current_frozen,
    inspection as inspection,
    completed as completed,
    managed_evaluation as managed_evaluation,
)
from strategy_manager import Qualification, StrategyRegistry  # noqa: E402


@pytest.fixture
def pte_frozen(current_frozen):
    context, version = current_frozen
    StrategyRegistry(context.strategy_root)._transition(
        "S900", "v1", Qualification.PAPER_READY, "PAPER_APPROVED", "test",
        "synthetic paper approval", [],
    )
    return context, version
