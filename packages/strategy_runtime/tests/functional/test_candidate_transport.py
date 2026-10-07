from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import pickle

import pytest
from strategy_runtime import StrategyCandidate


def _worker(candidate):
    with pytest.raises(TypeError):
        candidate.payload["parameters"]["nested"]["threshold"] = 5
    return candidate.reference_id, candidate.runtime_identity_sha256


def test_candidate_roundtrip_revalidates_and_preserves_immutable_identity(tmp_path, monkeypatch):
    # A real spawn proves serialization and child-process immutability. Avoid
    # recompiling every imported dependency into a new cache for this one child.
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    candidate = StrategyCandidate(
        "S900",
        "C0001",
        {
            "runtime": {"module": "example"},
            "parameters": {"nested": {"threshold": 0.5}},
        },
        tmp_path,
    )
    restored = pickle.loads(pickle.dumps(candidate))
    assert restored == candidate
    assert restored.source_root == tmp_path.resolve()
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        result = pool.submit(_worker, candidate).result(timeout=30)
    assert result == (candidate.reference_id, candidate.runtime_identity_sha256)
