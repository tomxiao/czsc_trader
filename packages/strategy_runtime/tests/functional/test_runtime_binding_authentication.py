"""Frozen input authentication at the public SRT boundary, without TDR execution."""

from dataclasses import replace
from pathlib import Path
import shutil

import pytest
from strategy_runtime import (
    RuntimeBinding, RuntimeBindingSpec, RuntimeCompatibilityError, RuntimeContractError,
    StrategyCandidate, StrategyRelease, StrategyRuntime, canonical_sha256,
    implementation_sha256,
)


@pytest.fixture
def release_binding(tmp_path):
    package = tmp_path / "src" / "strategy_runtime"
    source = package / "strategies" / "candidate_fixture.py"
    source.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[4] / "tests/fixtures/candidate_runtime.py", source)
    files = ("strategies/candidate_fixture.py",)
    source_hash = implementation_sha256(files, source_root=package)
    payload = {
        "runtime": {"module": "strategy_runtime.strategies.candidate_fixture",
                    "qualname": "CandidateFixture", "contract_version": 1,
                    "source_files": list(files), "source_sha256": source_hash},
        "parameters": {"threshold": 0.5},
    }
    definition = StrategyRuntime().describe(StrategyCandidate("S900", "C0001", payload, package))
    raw = {
        "schema_version": 5, "strategy_id": "S900", "version": "v1",
        "release_id": "S900-v1", "parent_version": None,
        "change_summary": "SRT public binding input", "source_experiment": "20261001_S900_EX01",
        "source_candidate": "C0001", "selection_data_cutoff": "2026-09-21",
        "forward_start": "2026-09-22", "strategy_payload": payload,
    }
    release = StrategyRelease.from_mapping({**raw, "release_hash": canonical_sha256(raw)})
    binding = RuntimeBinding(release.release_id, release.release_hash,
                             RuntimeBindingSpec(files, source_hash, files, definition.observation.sha256))
    actual = StrategyRuntime().describe(release, source_root=package, runtime_binding=binding)
    assert actual.release_hash == release.release_hash
    return release, binding, package, raw


@pytest.mark.parametrize("field,value", [("change_summary", "changed"),
                                         ("strategy_payload", {"changed": True})])
def test_release_authenticates_complete_record(release_binding, field, value):
    release, _, _, raw = release_binding
    with pytest.raises(RuntimeContractError, match="complete frozen record"):
        StrategyRelease.from_mapping({**raw, "release_hash": release.release_hash, field: value})


def test_describe_rejects_binding_for_foreign_release(release_binding):
    release, binding, source, _ = release_binding
    with pytest.raises(RuntimeCompatibilityError, match="differs from frozen release"):
        StrategyRuntime().describe(release, source_root=source,
                                   runtime_binding=replace(binding, release_hash="0" * 64))


@pytest.mark.parametrize("corruption", ["observation_hash", "untyped_binding", "missing_binding"])
def test_describe_requires_authenticated_observation_binding(release_binding, corruption):
    release, binding, source, _ = release_binding
    if corruption == "observation_hash":
        binding = replace(binding, spec=replace(binding.spec, observation_sha256="0" * 64))
        message = "observation"
    elif corruption == "untyped_binding":
        binding = binding.to_dict()
        message = "requires RuntimeBinding"
    else:
        binding = None
        message = "both source root and runtime binding"
    with pytest.raises(RuntimeCompatibilityError, match=message):
        StrategyRuntime().describe(release, source_root=source, runtime_binding=binding)
