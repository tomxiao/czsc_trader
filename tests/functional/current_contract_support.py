"""Shared synthetic candidate source for current-contract integration tests."""
from pathlib import Path
import shutil
import importlib
import sys

import pytest
import strategy_runtime
import strategy_runtime.charts
from strategy_runtime import implementation_identity


@pytest.fixture
def candidate_payload(tmp_path, monkeypatch):
    package_path = list(strategy_runtime.__path__)
    chart_path = list(strategy_runtime.charts.__path__)
    package = tmp_path / "runtime" / "strategy_runtime"
    strategies = package / "strategies"
    strategies.mkdir(parents=True)
    source = Path(__file__).parents[1] / "fixtures" / "candidate_runtime.py"
    shutil.copyfile(source, strategies / "candidate_fixture.py")
    module_name = "strategy_runtime.strategies.candidate_fixture"
    importlib.invalidate_caches()
    payload = {
        "runtime": {
            "module": module_name,
            "qualname": "CandidateFixture",
            "contract_version": 1,
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
    strategy_runtime.charts.__path__[:] = chart_path
