from dataclasses import replace
from hashlib import sha256
import json
import shutil
from pathlib import Path
from dataflows import DataSpace

import pytest
from research_experiment import load_experiment, ExperimentResources, ExperimentWorkspace
from strategy_manager import (
    CandidateEvidence,
    CandidateKey,
    StrategyRegistry,
    StrategyVersion,
)
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyRelease
from czsc_trader.application import (
    assemble_delivery,
    CandidateInspectionRequest,
    InspectionReplay,
    EvaluationEvidenceReference,
    inspect_candidate,
    record_research_decision,
    freeze_candidate,
    get_freeze_result,
    RepositoryContext,
)
from czsc_trader.research_tools import create_formal_experiment_context
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_assessment_delivery import completed as completed, prepare
from test_research_delivery import Deliverable


def file_ref(root, path):
    return CandidateEvidence(
        path.relative_to(root).as_posix(), sha256(path.read_bytes()).hexdigest()
    )


@pytest.fixture
def inspection(completed):
    context, old_execution, request, result, experiment = completed
    registration = StrategyRegistry(context.research_registry_root).get_candidate(
        CandidateKey("S900", "C0001"), experiments_root=context.experiments_root
    )
    definition, content = prepare(completed)
    assemble_delivery(context, Deliverable(definition, content))
    delivery_path = (
        context.experiments_root / "S900/20261001_S900_EX01/deliveries/ASSESSMENT/1/receipt.json"
    )
    source = context.root / ".tmp/user-confirmation.json"
    source.write_text('{"message":"synthetic user approval"}')
    selection = record_research_decision(
        context,
        f.ResearchDecision(
            "select1",
            "S900",
            f.DecisionAction.APPROVE,
            f.CandidateSelectionSubject(
                file_ref(context.root, delivery_path), registration.key, registration.content_sha256
            ),
            file_ref(context.root, source),
            "选择合成候选",
        ),
    )
    execution = create_formal_experiment_context(
        old_execution.definition,
        data_space=DataSpace(Path("data/research")),
        repository_root=context.root,
        resources=ExperimentResources(1, 1),
        workspace=ExperimentWorkspace(context.root / ".tmp/inspection", context.root),
    )
    result_artifact = old_execution.trace.evaluations[0].result_artifact
    inspection_request = CandidateInspectionRequest(
        registration.key,
        selection,
        f.InspectionProtocol((f.InspectionCoordinate("full", "standard"),), 1e-7),
        execution,
        (
            InspectionReplay(
                EvaluationEvidenceReference(
                    experiment,
                    result.attempt_id,
                    tuple(x.identity.evaluation_id for x in result.runs),
                    CandidateEvidence(result_artifact.path, result_artifact.sha256),
                ),
                request,
            ),
        ),
        "v1",
        None,
        "合成冻结验证",
        request.data_cutoff.isoformat(),
        "2026-09-22",
        (),
        ("合成结果不代表收益证据",),
    )
    return context, inspection_request, source


@pytest.fixture
def inspected_candidate(request, tmp_path, frozen_seed_root):
    """Copy real, hash-valid inspection evidence for freeze persistence tests.

    Inspection scenarios still use ``inspection`` and run the full protocol.
    Each consumer owns its copied files; approvals and freeze journals start empty.
    """
    seed = frozen_seed_root / "inspection"
    report_path = frozen_seed_root / "inspection-report.json"
    if not seed.exists():
        context, inspection_request, _ = request.getfixturevalue("inspection")
        report = inspect_candidate(context, inspection_request)
        assert report.status is f.InspectionStatus.PASS
        shutil.copytree(context.root, seed)
        report_path.write_text(json.dumps(report.to_dict()), encoding="utf-8")
    root = tmp_path / "inspected-repo"
    shutil.copytree(seed, root)
    report = f.CandidateInspectionReport.from_dict(
        json.loads(report_path.read_text(encoding="utf-8"))
    )
    return RepositoryContext.discover(root), report, root / ".tmp/user-confirmation.json"


def approve(context, report, source, decision_id="freeze1", request_id="request1"):
    approval = record_research_decision(
        context,
        f.ResearchDecision(
            decision_id,
            "S900",
            f.DecisionAction.APPROVE,
            f.FreezeSubject(
                report.plan.origin.candidate,
                report.plan.origin.content_sha256,
                report.reference,
                report.plan.sha256,
                report.plan.version,
            ),
            file_ref(context.root, source),
            "批准该精确内容冻结",
        ),
    )
    return f.FreezeCandidateRequest(
        f.FreezeRequestId("S900", request_id), report.reference, approval
    )


def test_managed_inspection_freeze_and_idempotent_query(inspection):
    context, request, source = inspection
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.PASS, "\n".join(
        x.detail for x in report.checks if x.status is not f.InspectionStatus.PASS
    )
    assert len(request.execution.trace.evaluations) == 1
    report.reference.resolve(context.root)
    assert f.CandidateInspectionReport.from_dict(report.to_dict()) == report
    operation = approve(context, report, source)
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED, receipt
    assert (
        freeze_candidate(context, operation)
        == receipt
        == get_freeze_result(context, operation.request_id)
    )
    registry = StrategyRegistry(context.strategy_root)
    version = registry.get_version("S900", "v1")
    assert version.schema_version == 5
    assert not hasattr(version, "origin")
    assert StrategyVersion.from_dict(version.to_dict()) == version
    assert StrategyRelease.from_mapping(version.to_dict()).release_hash == version.release_hash
    assert not hasattr(registry, "validate_version_governance")
    assert registry.validate_all()["versions"] == 1
    assert not (context.strategy_root / "deployments").exists()
    with pytest.raises(ValueError, match="different content"):
        freeze_candidate(context, replace(operation, inspection=report.plan.payload))


def test_missing_coverage_never_passes_or_freezes(inspection):
    context, request, source = inspection
    report = inspect_candidate(context, replace(request, replays=()))
    assert report.status is f.InspectionStatus.INCOMPLETE
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="complete passing"):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND


def test_strong_contracts_reject_untyped_approval_and_bad_receipt():
    with pytest.raises(TypeError):
        f.ResearchDecision("d1", "S900", "APPROVE", None, None, "reason")
    with pytest.raises(ValueError):
        f.FreezeReceipt(f.FreezeRequestId("S900", "r1"), f.FreezeStatus.COMMITTED, "a" * 64)
    from strategy_manager import ValidationError

    with pytest.raises(ValidationError):
        f.FreezeFile("../outside.py", CandidateEvidence("source.py", "a" * 64))


@pytest.mark.parametrize("after_commit", [False, True])
def test_process_interruption_obeys_commit_visibility(inspected_candidate, monkeypatch, after_commit):
    from strategy_manager import freeze_store

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    original = freeze_store._durable

    class Interrupted(BaseException):
        pass

    def interrupt(path, value, **kwargs):
        if path.name == "v1.json":
            assert (
                get_freeze_result(context, operation.request_id).status
                is f.FreezeStatus.IN_PROGRESS
            )
            registry = StrategyRegistry(context.strategy_root)
            assert registry.versions("S900") == ()
            if after_commit:
                original(path, value, **kwargs)
            raise Interrupted()
        return original(path, value, **kwargs)

    monkeypatch.setattr(freeze_store, "_durable", interrupt)
    with pytest.raises(Interrupted):
        freeze_candidate(context, operation)
    receipt = get_freeze_result(context, operation.request_id)
    expected = f.FreezeStatus.COMMITTED if after_commit else f.FreezeStatus.UNKNOWN
    assert receipt.status is expected
    assert freeze_candidate(context, operation) == receipt
    assert bool(StrategyRegistry(context.strategy_root).versions("S900")) is after_commit
    if not after_commit:
        from strategy_manager import RegistryError

        with pytest.raises(RegistryError, match="unresolved"):
            freeze_candidate(
                context, replace(operation, request_id=f.FreezeRequestId("S900", "new_request"))
            )


def test_failed_commit_stays_invisible_and_is_not_retried(inspected_candidate, monkeypatch):
    from strategy_manager import freeze_store

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    original = freeze_store._durable

    def fail(path, value, **kwargs):
        if path.name == "committed.json":
            raise OSError("simulated disk failure")
        return original(path, value, **kwargs)

    monkeypatch.setattr(freeze_store, "_durable", fail)
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.FAILED
    assert "disk failure" in receipt.reason
    assert freeze_candidate(context, operation) == receipt
    assert StrategyRegistry(context.strategy_root).versions("S900") == ()


def test_approval_identity_and_version_conflicts(inspected_candidate):
    from strategy_manager import RegistryError

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="matching approval"):
        freeze_candidate(context, replace(operation, approval=report.selection))
    assert freeze_candidate(context, operation).status is f.FreezeStatus.COMMITTED
    with pytest.raises(RegistryError, match="target version"):
        freeze_candidate(context, replace(operation, request_id=f.FreezeRequestId("S900", "other")))
    with pytest.raises(ValueError, match="does not match"):
        record_research_decision(
            context,
            f.ResearchDecision(
                "wrong",
                "S900",
                f.DecisionAction.APPROVE,
                f.FreezeSubject(
                    report.plan.origin.candidate,
                    "f" * 64,
                    report.reference,
                    report.plan.sha256,
                    "v1",
                ),
                file_ref(context.root, source),
                "mismatched candidate content",
            ),
        )


def test_changed_inspected_file_is_rejected(inspected_candidate):
    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    file = report.plan.source_files[0].source.resolve(context.root)
    file.write_bytes(file.read_bytes() + b"\n# altered\n")
    from strategy_manager import ValidationError

    with pytest.raises(ValidationError, match="hash differs"):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND


def test_stage_five_delivery_captures_report_and_decision_closure(inspected_candidate, monkeypatch):
    from czsc_trader.research_tools import delivery as d
    from czsc_trader.application import validate_delivery
    from czsc_trader.application.delivery_service import _walk
    from czsc_trader.application.research_evidence import read_decision
    from test_research_delivery import content

    context, report, source = inspected_candidate
    from czsc_trader.application import delivery_service

    def forbidden(_):
        pytest.fail("stage five publication must not recompute predecessor assessment")

    monkeypatch.setattr(delivery_service, "assess_candidates", forbidden)
    monkeypatch.setattr(delivery_service, "compare_candidates", forbidden)
    selection = read_decision(context.root, report.selection)
    assessment = d.DeliveryReceipt.from_dict(
        json.loads(selection.subject.delivery.resolve(context.root).read_text())
    ).reference
    refs = [report.reference, report.selection.evidence, selection.confirmation_source]
    refs.extend(x for x in _walk(report) if isinstance(x, f.ResearchEvidenceRef))
    attachments = {}
    for ref in refs:
        path = ref.resolve(context.root)
        attachments[ref.sha256] = d.EvidenceFile(
            path.relative_to(context.root).as_posix(),
            d.EvidenceRef(f"attachments/{ref.sha256}", ref.sha256, "application/octet-stream"),
        )
    payload = d.CandidateInspectionDelivery(
        assessment,
        report,
        attachments[report.reference.sha256].reference,
        (),
        None,
        ("是否批准该计划冻结",),
    )
    definition = d.DeliveryDefinition(
        d.ExperimentOwner("S900", "20261001_S900_EX01"),
        d.DeliveryStage.INSPECTION,
        1,
        predecessors=(assessment,),
    )
    value = content(payload, attachments=tuple(attachments.values()))
    receipt = assemble_delivery(context, Deliverable(definition, value))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, Deliverable(definition, value)) == receipt
    published = (
        context.experiments_root / "S900/20261001_S900_EX01/deliveries/INSPECTION/1/report.md"
    )
    assert "技术检验：PASS" in published.read_text(encoding="utf-8")
    assert "尚未请求" in published.read_text(encoding="utf-8")
    assert "选择合成候选" in published.read_text(encoding="utf-8")
    assert "确认来源" in published.read_text(encoding="utf-8")
    from czsc_trader.application.delivery_service import _report

    for status in (f.FreezeStatus.FAILED, f.FreezeStatus.UNKNOWN):
        failed = f.FreezeReceipt(
            f.FreezeRequestId("S900", "render-only"), status, "a" * 64, reason="具体冻结失败原因"
        )
        rendered = _report(
            definition, replace(value, payload=replace(payload, freeze=failed)), published.parent
        ).decode()
        assert status.value in rendered and "具体冻结失败原因" in rendered
        assert "已冻结版本" not in rendered
    before = published.read_bytes()
    operation = approve(context, report, source)
    frozen = freeze_candidate(context, operation)
    approved = read_decision(context.root, operation.approval)
    for ref in (operation.approval.evidence, approved.confirmation_source):
        path = ref.resolve(context.root)
        attachments[ref.sha256] = d.EvidenceFile(
            path.relative_to(context.root).as_posix(),
            d.EvidenceRef(f"attachments/{ref.sha256}", ref.sha256, "application/octet-stream"),
        )
    final_payload = replace(
        payload, decisions=(operation.approval,), freeze=frozen, pending_decisions=()
    )
    final_definition = replace(definition, revision=2, predecessors=(assessment, receipt.reference))
    final = assemble_delivery(
        context,
        Deliverable(
            final_definition, content(final_payload, attachments=tuple(attachments.values()))
        ),
    )
    assert validate_delivery(context, final.reference).status is d.ValidationStatus.PASS
    assert published.read_bytes() == before


def test_runtime_deployment_is_independent_of_research_commit_marker(inspected_candidate):
    from czsc_trader.application import deploy_strategy, validate_release_package
    from strategy_runtime import load_strategy_deployment
    from strategy_runtime.prepare_cli import _load_release
    from paper_trading_engine.srt_advice_client import SrtAdviceClient

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    receipt = freeze_candidate(context, operation)
    validate_release_package(context, "S900-v1")
    # This is an isolated synthetic repository, never a production deployment.
    deploy_strategy(context, "S900-v1")
    assert (
        load_strategy_deployment(context.strategy_root, "S900-v1").release_hash
        == receipt.version.release_hash
    )
    client = object.__new__(SrtAdviceClient)
    client.repo_root = context.root
    assert client._load_release("S900", "v1").release_hash == receipt.version.release_hash
    assert _load_release(context.root, "S900", "v1").release_hash == receipt.version.release_hash
    marker = context.research_root / "S900/freeze_requests/request1/committed.json"
    marker.rename(marker.with_name("simulated-lost-commit.json"))
    assert load_strategy_deployment(context.strategy_root, "S900-v1").release_hash == receipt.version.release_hash
    assert client._load_release("S900", "v1").release_hash == receipt.version.release_hash
    assert _load_release(context.root, "S900", "v1").release_hash == receipt.version.release_hash


def test_inspection_artifacts_are_sealed_in_rex_receipt(inspection, monkeypatch):
    from research_experiment import ExperimentResult, ExperimentOutcome
    from czsc_trader.research_tools import execute_experiment

    context, request, _ = inspection
    report = inspect_candidate(context, request)
    loaded = load_experiment(
        context.experiments_root / "S900" / request.execution.definition.experiment_id
    )
    monkeypatch.setattr(
        loaded.implementation,
        "execute",
        lambda execution: ExperimentResult(
            ExperimentOutcome.PASS, {"inspection": report.sha256}, {}
        ),
    )
    result = execute_experiment(loaded, request.execution)
    inspection_artifacts = [x for x in result.artifacts if x.kind == "candidate_inspection"]
    assert inspection_artifacts
    assert any(x.sha256 == report.reference.sha256 for x in inspection_artifacts)
    for artifact in inspection_artifacts:
        assert result.receipt.artifact_sha256[artifact.path] == artifact.sha256
    with pytest.raises(ValueError, match="sealed"):
        inspect_candidate(context, request)


def test_corrupt_research_commit_does_not_change_runtime_version(inspected_candidate):

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    freeze_candidate(context, operation)
    path = context.research_root / "S900/freeze_requests/request1/committed.json"
    path.write_text("{malformed")
    receipt = get_freeze_result(context, operation.request_id)
    assert receipt.status is f.FreezeStatus.UNKNOWN
    assert receipt.version is None
    assert "cannot be verified" in receipt.reason
    assert StrategyRegistry(context.strategy_root).get_version("S900", "v1").release_id == "S900-v1"


def test_release_signal_divergence_blocks_freeze(inspection, monkeypatch):
    from strategy_runtime import StrategyInstance

    context, request, source = inspection
    original = StrategyInstance.inspect_signals

    def divergent(instance):
        frame = original(instance)
        if instance.definition.identity_kind == "RELEASE":
            frame = frame.copy()
            frame["target_position"] = 1.0 - frame["target_position"]
        return frame

    monkeypatch.setattr(StrategyInstance, "inspect_signals", divergent)
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.FAIL
    assert (
        next(x for x in report.checks if x.check is f.InspectionCheck.SIGNAL_EQUIVALENCE).status
        is f.InspectionStatus.FAIL
    )
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="complete passing"):
        freeze_candidate(context, operation)


def test_invalid_package_reports_failure_and_decisions_are_immutable(inspection):
    from strategy_manager import ValidationError
    from czsc_trader.application.research_evidence import read_decision

    context, request, source = inspection
    report = inspect_candidate(context, request)
    operation = approve(context, report, source)
    binding_path = report.plan.runtime_binding.resolve(context.root)
    binding_path.write_bytes(binding_path.read_bytes() + b" ")
    with pytest.raises(ValidationError, match="hash"):
        freeze_candidate(context, operation)
    selection = read_decision(context.root, request.selection)
    repeated = replace(selection, confirmation_source=file_ref(context.root, source))
    assert record_research_decision(context, repeated) == request.selection
    with pytest.raises(ValidationError, match="hash differs"):
        record_research_decision(context, replace(repeated, reason="changed decision content"))


@pytest.mark.parametrize("field", ["attempt", "evaluation", "artifact"])
def test_inspection_rejects_reference_identity_mismatch(inspection, field):
    context, request, _ = inspection
    replay = request.replays[0]
    ref = replay.reference
    if field == "attempt":
        ref = replace(ref, attempt_id="f" * 32)
    elif field == "evaluation":
        ref = replace(ref, evaluation_ids=("f" * 64,))
    else:
        ref = replace(ref, result=replace(ref.result, sha256="f" * 64))
    with pytest.raises(ValueError, match="receipted evaluation"):
        inspect_candidate(context, replace(request, replays=(replace(replay, reference=ref),)))
    assert request.execution.trace.evaluations == ()


def test_inspection_rejects_tampered_archive(inspection):
    context, request, _ = inspection
    ref = request.replays[0].reference
    artifact = context.root / ref.experiment.workspace_path / ref.result.path
    artifact.write_bytes(artifact.read_bytes() + b" ")
    with pytest.raises(ValueError):
        inspect_candidate(context, request)
    assert request.execution.trace.evaluations == ()


def test_inspection_rejects_wrong_receipt_and_untyped_reference(inspection):
    context, request, _ = inspection
    replay = request.replays[0]
    ref = replay.reference
    with pytest.raises(TypeError):
        InspectionReplay(ref.to_dict(), replay.reproduction_request)
    with pytest.raises(ValueError):
        replace(ref, evaluation_ids=())
    wrong = replace(ref, experiment=replace(ref.experiment, receipt_sha256="f" * 64))
    with pytest.raises(ValueError, match="expected identity"):
        inspect_candidate(context, replace(request, replays=(replace(replay, reference=wrong),)))
    assert request.execution.trace.evaluations == ()


def test_inspection_in_fresh_process_uses_archived_reference(inspection):
    import pickle
    import subprocess
    import sys
    from pathlib import Path
    from dataclasses import fields

    context, request, _ = inspection
    replay = request.replays[0]
    ref = replay.reference
    original = context.root / ref.experiment.workspace_path
    original.rename(original.with_name("original-evaluation-removed"))
    archived = replace(
        ref,
        experiment=replace(
            ref.experiment,
            workspace_path=f"experiments/S900/20261001_S900_EX01/deliveries/ASSESSMENT/1/experiments/{ref.experiment.experiment_id}",
        ),
    )
    # Transfer only fresh reproduction inputs and public references. No old
    # EvaluationRequest/EvaluationResult, execution context, or baseline frames.
    payload = {
        "inspection": {
            x.name: getattr(request, x.name)
            for x in fields(request)
            if x.name not in {"execution", "replays"}
        },
        "reference": archived.to_dict(),
        "reproduction": {
            x.name: getattr(replay.reproduction_request, x.name)
            for x in fields(replay.reproduction_request)
            if x.name != "strategy"
        },
    }
    path = context.root / ".tmp/fresh-inspection-input.pkl"
    path.write_bytes(pickle.dumps(payload))
    script = "import sys; sys.path.insert(0, sys.argv[1]); from test_candidate_freeze import _cold_start_inspection; _cold_start_inspection(sys.argv[2])"
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(Path(__file__).parent), str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COLD_START_PASS" in result.stdout


def _cold_start_inspection(path):
    import pickle
    from pathlib import Path
    import pandas as pd
    from czsc_trader.application import RepositoryContext, load_candidate
    from czsc_trader.research_tools import EvaluationRequest
    from test_candidate_runtime_execution import _install_candidate_dataflows
    from czsc_trader.research_tools import evaluation

    payload = pickle.loads(Path(path).read_bytes())
    values = payload["reproduction"]
    context = RepositoryContext.discover(values["repository_root"])
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    flow = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0.0, 0.0]})
    with pytest.MonkeyPatch.context() as patch:
        _install_candidate_dataflows(patch, flow, daily, base_dir=context.root,
                                    space=DataSpace(Path("data/research")))
        patch.setattr("czsc_trader.research_tools.experiment.Dataflows", evaluation.Dataflows)
        definition = load_experiment(
            context.experiments_root / "S900" / values["experiment_id"]
        ).definition
        execution = create_formal_experiment_context(
            definition,
            data_space=DataSpace(Path("data/research")),
            repository_root=context.root,
            resources=ExperimentResources(1, 1),
            workspace=ExperimentWorkspace(context.root / ".tmp/fresh-inspection", context.root),
        )
        fresh = EvaluationRequest(
            strategy=load_candidate(context, payload["inspection"]["candidate"]), **values
        )
        reference = EvaluationEvidenceReference.from_dict(payload["reference"])
        request = CandidateInspectionRequest(
            **payload["inspection"],
            execution=execution,
            replays=(InspectionReplay(reference, fresh),),
        )
        report = inspect_candidate(context, request)
        assert report.status is f.InspectionStatus.PASS, report.checks
        print("COLD_START_PASS")


def test_archived_signal_restoration_preserves_precision_units_and_nulls():
    import pandas as pd
    from czsc_trader.application.inspection_service import _reference_signals
    from czsc_trader.research_tools._evaluation_records import _signal_table

    signals = pd.DataFrame(
        {
            "signal_date": pd.Series(["2026-10-01T00:00:00.123456"], dtype="datetime64[us]"),
            "target": [0.12345678901234567],
            "regime": pd.Series([None], dtype=object),
        }
    )
    persisted = json.loads(
        json.dumps(
            {
                "signals": _signal_table(signals),
                "signal_dtypes": {name: str(dtype) for name, dtype in signals.dtypes.items()},
            }
        )
    )
    pd.testing.assert_frame_equal(signals, _reference_signals(persisted), check_exact=True)


def test_selection_inspection_and_pending_freeze_do_not_write_runtime_registry(inspection, monkeypatch):
    from czsc_trader.application import delivery_service

    context, request, source = inspection
    assert not context.strategy_root.exists()

    def forbidden(_):
        pytest.fail("stage five must not recompute stage four statistics")

    monkeypatch.setattr(delivery_service, "assess_candidates", forbidden)
    monkeypatch.setattr(delivery_service, "compare_candidates", forbidden)
    report = inspect_candidate(context, request)
    assert report.status is f.InspectionStatus.PASS
    assert not context.strategy_root.exists()
    assert report.reference.resolve(context.root).is_relative_to(
        context.experiments_root / "S900" / request.execution.definition.experiment_id
    )
    operation = approve(context, report, source)
    assert operation.approval.evidence.resolve(context.root).is_relative_to(
        context.research_root / "S900/decisions"
    )
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND
    assert not context.strategy_root.exists()
    assert freeze_candidate(context, operation).status is f.FreezeStatus.COMMITTED
    assert not (context.strategy_root / "research_objects").exists()
    assert not (context.strategy_root / "research_decisions").exists()
    assert not (context.strategy_root / "freeze_requests").exists()
    assert not hasattr(StrategyRegistry(context.strategy_root), "record_research_decision")


def test_static_runtime_failure_stops_account_reproduction(inspection, monkeypatch):
    from strategy_runtime import StrategyRuntime, RuntimeCompatibilityError

    context, request, source = inspection
    describe = StrategyRuntime.describe

    def incompatible(runtime, identity, **kwargs):
        if isinstance(identity, StrategyRelease):
            raise RuntimeCompatibilityError("synthetic release mismatch")
        return describe(runtime, identity, **kwargs)

    monkeypatch.setattr(StrategyRuntime, "describe", incompatible)
    report = inspect_candidate(context, request)
    checks = {x.check: x for x in report.checks}
    assert report.status is f.InspectionStatus.FAIL
    assert checks[f.InspectionCheck.RUNTIME].status is f.InspectionStatus.FAIL
    for check in (f.InspectionCheck.COVERAGE, f.InspectionCheck.REPRODUCTION,
                  f.InspectionCheck.LEDGER_AUDIT, f.InspectionCheck.SIGNAL_EQUIVALENCE,
                  f.InspectionCheck.LEDGER_EQUIVALENCE):
        assert checks[check].status is f.InspectionStatus.INCOMPLETE
    assert request.execution.trace.evaluations == ()
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="complete passing"):
        freeze_candidate(context, operation)
    assert not context.strategy_root.exists()


def test_research_evidence_requires_owner_relative_paths_and_repository_root(inspection):
    from strategy_manager import ValidationError

    context, request, _ = inspection
    reference = request.selection.evidence
    assert f.ResearchEvidenceRef.from_dict(reference.to_dict()) == reference
    with pytest.raises(ValidationError):
        reference.resolve(context.strategy_root)
    with pytest.raises(ValidationError):
        replace(reference, path="../other.json")
    with pytest.raises(ValueError, match="owner"):
        f.ResearchEvidenceOwner("S900", "20261001_S901_EX01")
    with pytest.raises(ValidationError):
        replace(reference, owner=f.ResearchEvidenceOwner("S901")).resolve(context.root)
    with pytest.raises(TypeError):
        f.DecisionReference("selection", CandidateEvidence("arbitrary.json", "a" * 64))


def test_reproduction_cutoff_conflict_starts_no_evaluation(inspection):
    from datetime import timedelta

    context, request, _ = inspection
    replay = request.replays[0]
    cutoff = replay.reproduction_request.data_cutoff - timedelta(days=1)
    replay = replace(replay, reproduction_request=replace(replay.reproduction_request, data_cutoff=cutoff))
    report = inspect_candidate(context, replace(request, replays=(replay,)))
    assert report.status is f.InspectionStatus.FAIL
    assert request.execution.trace.evaluations == ()
    assert any("data cutoff differs" in x.detail for x in report.checks)
    assert not context.strategy_root.exists()


def test_failed_version_publication_returns_unknown_not_stale_in_progress(inspected_candidate, monkeypatch):
    from strategy_manager import freeze_store

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    durable = freeze_store._durable

    def fail(path, value, **kwargs):
        if path.name == "v1.json":
            raise OSError("synthetic version publication failure")
        return durable(path, value, **kwargs)

    monkeypatch.setattr(freeze_store, "_durable", fail)
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.UNKNOWN
    assert receipt.version is None
    assert get_freeze_result(context, operation.request_id) == receipt
    assert StrategyRegistry(context.strategy_root).versions("S900") == ()


def test_corrupt_publication_request_remains_unknown_without_retry(inspected_candidate):
    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    freeze_candidate(context, operation)
    journal = context.research_root / "S900/freeze_requests/request1/request.json"
    journal.write_text("{malformed")
    receipt = get_freeze_result(context, operation.request_id)
    assert receipt.status is f.FreezeStatus.UNKNOWN
    assert receipt.request_sha256 is None
    assert freeze_candidate(context, operation) == receipt
    assert journal.read_text() == "{malformed"
