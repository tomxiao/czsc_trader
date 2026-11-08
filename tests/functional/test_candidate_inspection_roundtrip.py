"""One real serial/parallel inspection sequence, followed by exact-package freeze."""
from dataclasses import replace
import json
import shutil

import pytest
from strategy_manager import StrategyRegistry, StrategyVersion
from strategy_manager import freeze_contracts as f
from strategy_runtime import InspectionControl, StrategyRelease
from czsc_trader.application import inspect_candidate, freeze_candidate, get_freeze_result, validate_delivery
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.research_tools import delivery as d
from test_candidate_freeze import (
    _details, _delivery, _build_inspection, _restore_inspection_request, approve,
    inspected_candidate as inspected_candidate, inspection as inspection,
    fresh_inspection as fresh_inspection,
    fresh_completed as fresh_completed, managed_evaluation as managed_evaluation,
)


def test_serial_parallel_inspections_preserve_reports_and_freeze_idempotently(
    inspected_candidate, frozen_seed_root, monkeypatch,
):
    from czsc_trader.application import inspection_service
    context, first, source = inspected_candidate
    request = _restore_inspection_request(context.root, frozen_seed_root, full_protocol=True)
    coverage_case = next(case for case in first.pte_runtime.cases if case.case_id == 'pte-coverage')
    coverage = json.loads(coverage_case.evidence[0].resolve(context.root).read_bytes())
    summary_ref = next(item['reference'] for item in coverage['artifacts'] if item['artifact_id'] == 'pte-summary')
    summary = json.loads(f.ResearchEvidenceRef.from_dict(summary_ref).resolve(context.root).read_bytes())
    assert summary['effective_workers'] == 1
    actual_inspect = inspection_service.inspect_release
    observed = []
    def checked_pte(request, *, control):
        result = actual_inspect(request, control=control)
        summary = json.loads((request.workspace / "pte-summary.json").read_text())
        assert 1 <= summary["effective_workers"] <= control.max_workers
        observed.append(control.max_workers)
        return result
    monkeypatch.setattr(inspection_service, "inspect_release", checked_pte)
    # Reuse the real serial run that also supplies publication/admission tests;
    # the second run below still executes the complete parallel fault matrix.
    assert first.status is f.InspectionStatus.PASS, _details(first)
    first_facts = json.loads(first.behavior_equivalence.cases[0].evidence[-1].resolve(context.root).read_text())
    assert first_facts['baseline']['status'] == 'PASS'
    retained = first.reference.resolve(context.root).read_bytes()
    # The second real run also proves that archived evaluations, original
    # research sources and previous deliveries are not publication prerequisites.
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
    for evidence in registration.origin.evidence:
        evidence.resolve(context.research_root / 'S900').unlink()
    original_source = context.research_root / 'S900/experiments' / registration.origin.experiment_id / 'src'
    if original_source.exists():
        shutil.rmtree(original_source)
    for relative in ('assets/deliveries', 'deliveries'):
        folder = context.research_root / 'S900' / relative
        if folder.exists():
            shutil.rmtree(folder)
    assert validate_inspection(context.root, first.reference) == first
    parallel_request = replace(request, replays=tuple(replace(x, baseline=None) for x in request.replays))
    report = inspect_candidate(context, parallel_request, control=InspectionControl(max_workers=2))
    assert observed == [2]
    assert first.run_id != report.run_id and first.reference != report.reference
    assert first.reference.resolve(context.root).read_bytes() == retained
    assert first.release.package_sha256 == report.release.package_sha256
    assert report.status is f.InspectionStatus.PASS, _details(report)
    report_facts = json.loads(report.behavior_equivalence.cases[0].evidence[-1].resolve(context.root).read_text())
    assert report_facts['baseline']['status'] == 'NOT_REQUESTED'
    fault_cases = {'damaged_package', 'missing_input', 'future_input'}
    assert fault_cases & {case.case_id for case in first.pte_runtime.cases} == {'damaged_package'}
    assert fault_cases <= {case.case_id for case in report.pte_runtime.cases}
    assert report.behavior_equivalence.status is report.pte_runtime.status is f.InspectionStatus.PASS
    assert not context.strategy_root.exists()
    assert report.reference.resolve(context.root).is_file()
    assert f.CandidateInspectionReport.from_dict(report.to_dict()) == report
    assert not hasattr(report.plan, 'registration_evidence')
    delivery = _delivery(context, report)
    assert delivery.schema_version == 9
    assert validate_delivery(context, delivery.reference).status is d.ValidationStatus.PASS
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
    from inspection_replay_support import candidate_release_replay
    from strategy_runtime import implementation_sha256
    from test_research_contract_upgrade import _evaluation_fixture

    payload, package = candidate_payload
    source = package / payload["runtime"]["source_files"][0]
    original = source.read_text(encoding="utf-8")
    # The actual registered implementation branches on its installed location.
    # Both runtime instances receive these same bytes; only the installed
    # source location changes, without replacing strategy or comparison logic.
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
    facts = candidate_release_replay(context, request)
    assert facts["passed"] is False
    assert facts["signal_error"]
    assert facts["candidate_signals"] != facts["release_signals"]
    assert not context.strategy_root.exists()
