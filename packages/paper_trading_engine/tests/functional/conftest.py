from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

# Each test copies a current runtime package generated once by the real freeze pipeline.
sys.path.insert(0, str(PACKAGE_ROOT.parents[1] / "tests/functional"))
from current_contract_support import candidate_payload as candidate_payload  # noqa: E402
from test_current_contracts import (  # noqa: E402
    current_frozen as current_frozen,
    freshly_frozen as freshly_frozen,
    inspection as inspection,
    completed as completed,
    managed_evaluation as managed_evaluation,
)
from strategy_manager import PaperTradingApproval, StrategyRegistry  # noqa: E402


@pytest.fixture
def pte_frozen(current_frozen):
    context, version = current_frozen
    StrategyRegistry(context.strategy_root).approve_paper_trading(PaperTradingApproval(
        "S900", "v1", version.release_hash, "test", "synthetic paper approval",
    ))
    return context, version
