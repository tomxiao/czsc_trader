"""Content identity belongs to the public SRT runtime."""

from copy import deepcopy
from dataclasses import replace
import shutil
import pytest
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency


def test_content_identity_is_id_and_path_independent(runtime_candidate, tmp_path):
    payload = {
        "runtime": dict(runtime_candidate.payload["runtime"]),
        "parameters": dict(runtime_candidate.payload["parameters"]),
    }
    root = runtime_candidate.source_root
    candidate = StrategyCandidate("S900", "C0001", payload, root)
    runtime = StrategyRuntime()
    identity = runtime.identify(candidate, dependencies=())
    moved = tmp_path / "copy" / "strategy_runtime"
    shutil.copytree(root, moved)
    assert (
        runtime.identify(
            replace(candidate, candidate_id="C0002", source_root=moved), dependencies=()
        )
        == identity
    )
    changed = deepcopy(payload)
    changed["parameters"]["threshold"] = 0.8
    assert (
        runtime.identify(replace(candidate, payload=changed), dependencies=()).content_sha256
        != identity.content_sha256
    )
    assert (
        runtime.identify(
            candidate, dependencies=(ImplementationDependency("some_pkg", "1.0"),)
        ).content_sha256
        != identity.content_sha256
    )
    with pytest.raises(ValueError):
        runtime.identify(
            candidate,
            dependencies=(
                ImplementationDependency("some_pkg", "1.0"),
                ImplementationDependency("some-pkg", "1.1"),
            ),
        )
