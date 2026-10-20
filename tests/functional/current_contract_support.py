"""Shared synthetic candidate source for current-contract integration tests."""
from pathlib import Path
import importlib
import sys

import pytest
import strategy_runtime
from strategy_runtime import implementation_identity


@pytest.fixture
def candidate_payload(tmp_path, monkeypatch):
    package_path = list(strategy_runtime.__path__)
    package = tmp_path / "runtime" / "strategy_runtime"
    strategies = package / "strategies"
    strategies.mkdir(parents=True)
    source = Path(__file__).parents[1] / "fixtures" / "candidate_runtime.py"
    text = source.read_text(encoding="utf-8")
    text = text.replace("StrategyImplementation,", "StrategyImplementationV2,")
    text = text.replace("(StrategyImplementation):", "(StrategyImplementationV2):")
    text = text.replace("def calculate_history(self, inputs, sessions):",
                        "def calculate_context_history(self, inputs, context):\n        sessions = context.sessions")
    (strategies / "candidate_fixture.py").write_text(text, encoding="utf-8")
    module_name = "strategy_runtime.strategies.candidate_fixture"
    importlib.invalidate_caches()
    payload = {
        "decision_feedback": "MARKET_INTENT",
        "runtime": {
            "module": module_name,
            "qualname": "CandidateFixture",
            "contract_version": 2,
            "source_files": ["strategies/candidate_fixture.py"],
            "source_sha256": implementation_identity.implementation_sha256(
                ("strategies/candidate_fixture.py",),
                source_root=package,
            ),
        },
        "parameters": {"threshold": 0.5},
    }
    yield payload, package
    sys.modules.pop(module_name, None)
    sys.modules.pop("strategy_runtime.strategies", None)
    strategy_runtime.__path__[:] = package_path
