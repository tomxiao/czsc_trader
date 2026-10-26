"""One real serial/parallel inspection sequence, followed by exact-package freeze."""
from dataclasses import replace
import json

import pytest
from strategy_manager import StrategyRegistry, StrategyVersion
from strategy_manager import freeze_contracts as f
from strategy_runtime import InspectionControl, StrategyRelease
from czsc_trader.application import inspect_candidate, freeze_candidate, get_freeze_result
from test_candidate_freeze import (
    _details, _build_inspection, _assert_not_freezable, approve, fresh_inspection as fresh_inspection,
    fresh_completed as fresh_completed, managed_evaluation as managed_evaluation,
)


def test_serial_parallel_inspections_preserve_reports_and_freeze_idempotently(fresh_inspection, monkeypatch):
    from czsc_trader.application import inspection_service
    context, request, source = fresh_inspection
    actual_inspect = inspection_service.inspect_release
    observed = []
    def checked_pte(request, *, control):
        result = actual_inspect(request, control=control)
        summary = json.loads((request.workspace / "pte-summary.json").read_text())
        assert 1 <= summary["effective_workers"] <= control.max_workers
        observed.append(control.max_workers)
        return result
    monkeypatch.setattr(inspection_service, "inspect_release", checked_pte)
    # A real repeat on the same repository covers both scheduling modes and
    # immutable run identities without two additional standalone inspections.
    first = inspect_candidate(context, request, control=InspectionControl(max_workers=1))
    assert first.status is f.InspectionStatus.PASS, _details(first)
    retained = first.reference.resolve(context.root).read_bytes()
    report = inspect_candidate(context, request, control=InspectionControl(max_workers=2))
    assert observed == [1, 2]
    assert first.run_id != report.run_id and first.reference != report.reference
    assert first.reference.resolve(context.root).read_bytes() == retained
    assert first.release.package_sha256 == report.release.package_sha256
    assert report.status is f.InspectionStatus.PASS, _details(report)
    assert report.behavior_equivalence.status is report.pte_runtime.status is f.InspectionStatus.PASS
    assert not context.strategy_root.exists()
    assert report.reference.resolve(context.root).is_file()
    assert f.CandidateInspectionReport.from_dict(report.to_dict()) == report
    operation = approve(context, report, source)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED, receipt
    assert freeze_candidate(context, operation) == receipt == get_freeze_result(context, operation.request_id)
    version = StrategyRegistry(context.strategy_root).get_version("S900", "v1")
    assert version.schema_version == 5
    assert StrategyVersion.from_dict(version.to_dict()) == version
    assert StrategyRelease.from_mapping(version.to_dict()).release_hash == report.release.release_sha256
    package = context.strategy_root / "S900/releases/v1"
    assert (package / "release_manifest.json").read_bytes() == report.release.manifest.resolve(context.root).read_bytes()
    for item in report.release.files:
        assert (package / item.path).read_bytes() == item.source.resolve(context.root).read_bytes()
    assert receipt.version.package_hash == report.release.package_sha256
    assert not (context.strategy_root / "deployments").exists()
    assert not (context.strategy_root / "freeze_requests").exists()
    with pytest.raises(ValueError, match="different content"):
        freeze_candidate(context, replace(operation, inspection=report.plan.payload))


def test_release_signal_divergence_is_detected(candidate_payload, tmp_path, monkeypatch):
    from strategy_runtime import implementation_sha256
    from test_research_contract_upgrade import _evaluation_fixture

    payload, package = candidate_payload
    source = package / payload["runtime"]["source_files"][0]
    original = source.read_text(encoding="utf-8")
    # The actual registered implementation branches on its installed location.
    # Both subprocesses receive these same bytes; no process-local monkeypatch
    # pretends to inject a fault across the worker boundary.
    target = '        return pd.DataFrame({"target_position": target'
    assert target in original
    source.write_text(original.replace(target,
        '        if "releases" in __import__("pathlib").Path(__file__).parts:\n            target = 1.0 - target\n' + target),
        encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        payload["runtime"]["source_files"], source_root=package)
    research, evaluation = _evaluation_fixture(candidate_payload, tmp_path, monkeypatch, prepared=True)
    completed_value = fresh_completed.__wrapped__((research, evaluation))
    context, request, _ = _build_inspection(completed_value)
    # Keep the actual behavior replay; generic PTE fault injection is exercised
    # by the successful serial/parallel roundtrip above.
    request = replace(request, protocol=replace(request.protocol, pte=replace(request.protocol.pte, failures=())))
    report = inspect_candidate(context, request)
    assert report.behavior_equivalence.status is f.InspectionStatus.FAIL
    assert any(case.reason_code is f.InspectionReason.BEHAVIOR_DIFFERENCE
               for case in report.behavior_equivalence.cases), _details(report)
    _assert_not_freezable(context, report)
