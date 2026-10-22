"""Package authentication and technical admission share bytes, never approval."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from strategy_runtime import (
    InspectionControl, InspectionRuntimePermit, RuntimeBinding, RuntimeBindingSpec,
    RuntimeCompatibilityError, StrategyCandidate, StrategyRuntime, canonical_sha256,
    collect_inspection_environment, implementation_sha256, load_inspection_deployment,
    load_strategy_deployment, validate_release_package,
)


@pytest.fixture
def package(tmp_path):
    workspace = tmp_path / ".tmp/strategy-inspection/run1"
    repository = workspace / "repository"
    root = repository / "strategies"
    release_root = root / "S900/releases/v1"
    source_root = release_root / "src/strategy_runtime"
    source = source_root / "strategies/candidate_fixture.py"
    source.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[4] / "tests/fixtures/candidate_runtime.py", source)
    files = ("strategies/candidate_fixture.py",)
    source_hash = implementation_sha256(files, source_root=source_root)
    payload = {"runtime": {"module": "strategy_runtime.strategies.candidate_fixture",
                           "qualname": "CandidateFixture", "contract_version": 1,
                           "source_files": list(files), "source_sha256": source_hash},
               "parameters": {"threshold": 0.5}}
    definition = StrategyRuntime().describe(StrategyCandidate("S900", "C0001", payload, source_root))
    version = {"schema_version": 5, "strategy_id": "S900", "version": "v1",
               "release_id": "S900-v1", "parent_version": None, "change_summary": "fixture",
               "source_experiment": "20261001_S900_EX01", "source_candidate": "C0001",
               "selection_data_cutoff": "2026-09-21", "forward_start": "2026-09-22",
               "strategy_payload": payload}
    version["release_hash"] = canonical_sha256(version)
    version_file = root / "S900/versions/v1.json"
    version_file.parent.mkdir(parents=True)
    version_file.write_text(json.dumps(version), encoding="utf-8")
    binding = RuntimeBinding("S900-v1", version["release_hash"], RuntimeBindingSpec(
        files, source_hash, files, definition.observation.sha256))
    (release_root / "runtime_binding.json").write_text(json.dumps(binding.to_dict()), encoding="utf-8")
    manifest = {"schema_version": 1, "strategy_version_id": "S900-v1",
                "strategy_version_hash": version["release_hash"], "source_candidate_id": "S900-C0001",
                "candidate_package_hash": "a" * 64, "runtime_root": "src/strategy_runtime",
                "runtime_binding": "runtime_binding.json", "files": {
                    p.relative_to(release_root).as_posix(): sha256(p.read_bytes()).hexdigest()
                    for p in release_root.rglob("*") if p.is_file()}}
    manifest["package_hash"] = canonical_sha256(manifest)
    (release_root / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    permit = InspectionRuntimePermit("run1", "S900-v1", version["release_hash"], manifest["package_hash"],
                                     "b" * 64, repository, workspace)
    return root, permit, source


def test_package_loads_without_deployment_but_formal_loader_rejects(package):
    root, permit, _ = package
    verified = validate_release_package(root, "S900-v1")
    with pytest.raises(RuntimeCompatibilityError, match="cannot read"):
        load_strategy_deployment(root, "S900-v1")
    deployed = load_inspection_deployment(root, "S900-v1", permit)
    assert deployed.package_hash == verified.package_sha256
    actual = StrategyRuntime(root, inspection_permit=permit).describe(verified.release)
    assert actual.release_hash == permit.release_sha256
    # Technical envelope copied to formal location is not a deployment receipt.
    (root / "deployments").mkdir()
    (root / "deployments/S900-v1.json").write_text(json.dumps({"run_id": "run1"}), encoding="utf-8")
    with pytest.raises(RuntimeCompatibilityError, match="fields"):
        load_strategy_deployment(root, "S900-v1")


def test_every_runtime_load_reauthenticates_permitted_package(package):
    root, permit, source = package
    verified = validate_release_package(root, "S900-v1")
    runtime = StrategyRuntime(root, inspection_permit=permit)
    runtime.describe(verified.release)
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    with pytest.raises(RuntimeCompatibilityError, match="file differs"):
        runtime.describe(verified.release, source_root=verified.source_root, runtime_binding=verified.runtime_binding)


def test_manifest_one_allows_hash_authenticated_absent_plan_provenance(package):
    root, _, _ = package
    path = root / "S900/releases/v1/release_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.pop("package_hash")
    manifest["candidate_package_hash"] = None
    manifest["package_hash"] = canonical_sha256(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_release_package(root, "S900-v1").package_sha256 == manifest["package_hash"]
    manifest.pop("package_hash")
    manifest["candidate_package_hash"] = "invalid-plan-hash"
    manifest["package_hash"] = canonical_sha256(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeCompatibilityError, match="plan identity"):
        validate_release_package(root, "S900-v1")


def test_permit_cannot_escape_or_admit_another_package(package, tmp_path):
    root, permit, _ = package
    with pytest.raises(RuntimeCompatibilityError, match="managed run"):
        replace(permit, workspace=tmp_path)
    with pytest.raises(RuntimeCompatibilityError, match="escapes"):
        permit.validate_path(tmp_path / "prod/runtime.db")
    with pytest.raises(RuntimeCompatibilityError, match="package differs"):
        load_inspection_deployment(root, "S900-v1", replace(permit, package_sha256="0" * 64))
    with pytest.raises(RuntimeCompatibilityError, match="release differs"):
        load_inspection_deployment(root, "S900-v1", replace(permit, release_sha256="0" * 64))


@pytest.mark.parametrize("kwargs", [{"timeout_seconds": float("nan")}, {"timeout_seconds": 0},
                                    {"max_workers": True}, {"cancelled": 1}])
def test_control_rejects_invalid_budget_and_callbacks(kwargs):
    with pytest.raises((TypeError, ValueError)):
        InspectionControl(**kwargs)


def test_environment_identifies_executing_code_not_test_repository(tmp_path):
    first = collect_inspection_environment(tmp_path)
    second = collect_inspection_environment(tmp_path / "isolated")
    assert first == second
    assert any(x.path == "strategy_runtime/inspection.py" for x in first.platform_files)
    assert first.platform_build_sha256
