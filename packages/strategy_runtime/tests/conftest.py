from __future__ import annotations

from pathlib import Path


import shutil
import pytest
from strategy_runtime import StrategyCandidate, implementation_sha256


ROOT = Path(__file__).resolve().parents[3]

@pytest.fixture
def runtime_candidate(tmp_path):
    source = tmp_path / "source/strategy_runtime"
    (source / "strategies").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "tests/fixtures/candidate_runtime.py",
        source / "strategies/current_fixture.py",
    )
    files = ("strategies/current_fixture.py",)
    return StrategyCandidate("S900", "C001", {
        "runtime": {
            "module": "strategy_runtime.strategies.current_fixture",
            "qualname": "CandidateFixture", "contract_version": 1,
            "source_files": list(files),
            "source_sha256": implementation_sha256(files, source_root=source),
        },
        "parameters": {"threshold": 0.5},
    }, source)
