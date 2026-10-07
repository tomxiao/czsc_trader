from __future__ import annotations

from pathlib import Path
from dataclasses import replace


import shutil
import pytest
from strategy_runtime import StrategyCandidate, implementation_sha256


ROOT = Path(__file__).resolve().parents[3]

@pytest.fixture(scope="session")
def runtime_candidate_seed(frozen_seed_root):
    source = frozen_seed_root / "srt-candidate/strategy_runtime"
    (source / "strategies").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "tests/fixtures/candidate_runtime.py",
        source / "strategies/current_fixture.py",
    )
    files = ("strategies/current_fixture.py",)
    return StrategyCandidate("S900", "C0001", {
        "runtime": {
            "module": "strategy_runtime.strategies.current_fixture",
            "qualname": "CandidateFixture", "contract_version": 1,
            "source_files": list(files),
            "source_sha256": implementation_sha256(files, source_root=source),
        },
        "parameters": {"threshold": 0.5},
    }, source)


@pytest.fixture
def runtime_candidate(tmp_path, runtime_candidate_seed):
    """Each test owns writable source; the original source seed stays immutable."""
    source = tmp_path / "source/strategy_runtime"
    shutil.copytree(runtime_candidate_seed.source_root, source)
    return replace(runtime_candidate_seed, source_root=source)
