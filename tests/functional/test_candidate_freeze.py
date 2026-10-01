from dataclasses import replace
from hashlib import sha256
import json

import pytest
from research_experiment import load_experiment, ExperimentResources, ExperimentWorkspace
from strategy_manager import (
    CandidateEvidence,
    CandidateRegistrationOrigin,
    ResearchState,
    StrategyFamily,
    StrategyRegistry,
    StrategyVersion,
)
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyRelease, implementation_sha256
from czsc_trader.application import (
    assemble_delivery,
    CandidateRegistrationRequest,
    register_candidate,
    CandidateInspectionRequest,
    InspectionReplay,
    inspect_candidate,
    record_research_decision,
    freeze_candidate,
    get_freeze_result,
)
from czsc_trader.research_tools import preflight_experiment, create_formal_experiment_context
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_assessment_delivery import completed as completed, prepare
from test_research_delivery import Deliverable


def file_ref(root, path):
    return CandidateEvidence(
        path.relative_to(root).as_posix(), sha256(path.read_bytes()).hexdigest()
    )


@pytest.fixture
def inspection(completed):
    context, old_execution, request, result, _ = completed
    family = StrategyFamily(
        2,
        "S900",
        "Freeze fixture",
        "ETF",
        {"hypothesis": "synthetic"},
        ResearchState.RESEARCHING,
        "2026-10-01T00:00:00+00:00",
        "test",
        "2026-10-01T00:00:00+00:00",
    )
    StrategyRegistry(context.research_registry_root).create_family(
        family, actor="test", reason="fixture"
    )
    path = context.experiments_root / "S900" / request.experiment_id
    loaded = load_experiment(path)
    preflight = preflight_experiment(loaded, resources=ExperimentResources(1, 1))
    preflight.require_pass()
    preflight_path = path / "preflight.json"
    preflight_path.write_text(json.dumps(preflight.to_dict()))
    registration = register_candidate(
        context,
        CandidateRegistrationRequest(
            request.strategy,
            CandidateRegistrationOrigin(
                request.experiment_id,
                loaded.definition.sha256,
                sha256((path / "experiment_binding.json").read_bytes()).hexdigest(),
                file_ref(context.root, preflight_path),
            ),
            (),
        ),
    )
    definition, content = prepare(completed)
    assemble_delivery(context, Deliverable(definition, content))
    delivery_path = context.research_root / "S900/deliveries/ASSESSMENT/1/receipt.json"
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
    chart = context.root / ".tmp/chart.py"
    chart.write_text(
        "class Charts:\n    def render_backtest(self, context):\n        return '<html>fixture</html>'\n"
    )
    chart_root = context.root / ".tmp/chart-source"
    (chart_root / "charts").mkdir(parents=True)
    (chart_root / "charts/freeze_fixture.py").write_bytes(chart.read_bytes())
    binding = context.root / ".tmp/binding.json"
    binding.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_files": list(request.strategy.payload["runtime"]["source_files"]),
                "implementation_sha256": request.strategy.payload["runtime"]["source_sha256"],
                "install_files": [
                    *request.strategy.payload["runtime"]["source_files"],
                    "charts/freeze_fixture.py",
                ],
                "charts": {
                    "module": "strategy_runtime.charts.freeze_fixture",
                    "qualname": "Charts",
                    "contract_version": 1,
                    "source_files": ["charts/freeze_fixture.py"],
                    "source_sha256": implementation_sha256(
                        ("charts/freeze_fixture.py",), source_root=chart_root
                    ),
                },
                "observation": {
                    "contract_version": "strategy_observation.v1",
                    "series": [
                        {
                            "key": "target",
                            "label": "目标",
                            "value_field": "target_position",
                            "guides": [],
                        }
                    ],
                },
            }
        )
    )
    execution = create_formal_experiment_context(
        old_execution.definition,
        repository_root=context.root,
        resources=ExperimentResources(1, 1),
        workspace=ExperimentWorkspace(context.root / ".tmp/inspection", context.root),
    )
    inspection_request = CandidateInspectionRequest(
        registration.key,
        selection,
        f.InspectionProtocol((f.InspectionCoordinate("full", "standard"),), 1e-7),
        execution,
        (InspectionReplay(request, result, old_execution.workspace.root, request),),
        "v1",
        None,
        "合成冻结验证",
        request.data_cutoff.isoformat(),
        "2026-09-22",
        file_ref(context.root, binding),
        (f.FreezeFile("charts/freeze_fixture.py", file_ref(context.root, chart)),),
        ("合成结果不代表收益证据",),
    )
    return context, inspection_request, source


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
    report.reference.resolve(context.strategy_root)
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
    assert version.schema_version == 4
    assert version.origin == report.plan.origin
    assert StrategyVersion.from_dict(version.to_dict()) == version
    assert StrategyRelease.from_mapping(version.to_dict()).release_hash == version.release_hash
    assert registry.validate_version_governance("S900", "v1") == "RESEARCH_FREEZE_VALIDATED"
    assert registry.validate_all()["versions"] == 1
    assert not (context.strategy_root / "deployments").exists()
    with pytest.raises(ValueError, match="different content"):
        freeze_candidate(context, replace(operation, inspection=request.runtime_binding))


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
def test_process_interruption_obeys_commit_visibility(inspection, monkeypatch, after_commit):
    from strategy_manager import freeze_store

    context, request, source = inspection
    report = inspect_candidate(context, request)
    operation = approve(context, report, source)
    original = freeze_store._durable

    class Interrupted(BaseException):
        pass

    def interrupt(path, value, **kwargs):
        if path.name == "committed.json":
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


def test_failed_commit_stays_invisible_and_is_not_retried(inspection, monkeypatch):
    from strategy_manager import freeze_store

    context, request, source = inspection
    operation = approve(context, inspect_candidate(context, request), source)
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


def test_approval_identity_and_version_conflicts(inspection):
    from strategy_manager import RegistryError

    context, request, source = inspection
    report = inspect_candidate(context, request)
    operation = approve(context, report, source)
    with pytest.raises(ValueError, match="matching approval"):
        freeze_candidate(context, replace(operation, approval=request.selection))
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


def test_changed_inspected_file_is_rejected(inspection):
    context, request, source = inspection
    report = inspect_candidate(context, request)
    operation = approve(context, report, source)
    file = report.plan.source_files[0].source.resolve(context.strategy_root)
    file.write_bytes(file.read_bytes() + b"\n# altered\n")
    from strategy_manager import ValidationError

    with pytest.raises(ValidationError, match="hash differs"):
        freeze_candidate(context, operation)
    assert get_freeze_result(context, operation.request_id).status is f.FreezeStatus.NOT_FOUND


def test_stage_five_delivery_captures_report_and_decision_closure(inspection):
    from czsc_trader.research_tools import delivery as d
    from czsc_trader.application import validate_delivery
    from czsc_trader.application.delivery_service import _walk
    from strategy_manager.freeze_store import read_decision
    from test_research_delivery import content

    context, request, source = inspection
    report = inspect_candidate(context, request)
    selection = read_decision(context.strategy_root, request.selection)
    assessment = d.DeliveryReceipt.from_dict(
        json.loads(selection.subject.delivery.resolve(context.root).read_text())
    ).reference
    refs = [report.reference, request.selection.evidence, selection.confirmation_source]
    refs.extend(x for x in _walk(report) if isinstance(x, CandidateEvidence))
    attachments = {}
    for ref in refs:
        path = ref.resolve(context.strategy_root)
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
        "S900", d.DeliveryStage.INSPECTION, 1, predecessors=(assessment,)
    )
    value = content(payload, attachments=tuple(attachments.values()))
    receipt = assemble_delivery(context, Deliverable(definition, value))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, Deliverable(definition, value)) == receipt
    published = context.research_root / "S900/deliveries/INSPECTION/1/report.md"
    assert "技术检验：PASS" in published.read_text(encoding="utf-8")
    assert "尚未请求" in published.read_text(encoding="utf-8")
    before = published.read_bytes()
    operation = approve(context, report, source)
    frozen = freeze_candidate(context, operation)
    approved = read_decision(context.strategy_root, operation.approval)
    for ref in (operation.approval.evidence, approved.confirmation_source):
        path = ref.resolve(context.strategy_root)
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


def test_schema_four_deployment_requires_commit_marker(inspection):
    from czsc_trader.application import deploy_strategy, validate_release_package
    from strategy_runtime import load_strategy_deployment
    from strategy_runtime.errors import RuntimeCompatibilityError
    from strategy_runtime.prepare_cli import _load_release
    from paper_trading_engine.srt_advice_client import SrtAdviceClient

    context, request, source = inspection
    operation = approve(context, inspect_candidate(context, request), source)
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
    marker = context.strategy_root / "freeze_requests/S900/request1/committed.json"
    marker.rename(marker.with_name("simulated-lost-commit.json"))
    with pytest.raises(RuntimeCompatibilityError, match="cannot read"):
        load_strategy_deployment(context.strategy_root, "S900-v1")
    with pytest.raises(RuntimeCompatibilityError, match="cannot read"):
        client._load_release("S900", "v1")
    with pytest.raises(RuntimeCompatibilityError, match="cannot read"):
        _load_release(context.root, "S900", "v1")


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


def test_corrupt_commit_returns_unknown_and_blocks_version_read(inspection):
    from strategy_manager import RegistryError

    context, request, source = inspection
    operation = approve(context, inspect_candidate(context, request), source)
    freeze_candidate(context, operation)
    path = context.strategy_root / "freeze_requests/S900/request1/committed.json"
    path.write_text("{malformed")
    receipt = get_freeze_result(context, operation.request_id)
    assert receipt.status is f.FreezeStatus.UNKNOWN
    assert receipt.version is None
    assert "cannot be verified" in receipt.reason
    with pytest.raises(RegistryError, match="not committed"):
        StrategyRegistry(context.strategy_root).get_version("S900", "v1")


def test_legacy_release_files_and_hashes_remain_unchanged():
    from pathlib import Path
    from czsc_trader.application import RepositoryContext, validate_release_package

    root = Path(__file__).resolve().parents[2]
    context = RepositoryContext.discover(root)
    paths = tuple(sorted(context.strategy_root.glob("S*/versions/v*.json")))
    legacy = [
        p for p in paths if json.loads(p.read_text(encoding="utf-8"))["schema_version"] in (1, 2, 3)
    ]
    assert len(legacy) == 5
    before = {p: p.read_bytes() for p in legacy}
    registry = StrategyRegistry(context.strategy_root)
    for path in legacy:
        version = registry.get_version(path.parent.parent.name, path.stem)
        assert StrategyRelease.from_mapping(version.to_dict()).release_hash == version.release_hash
        registry.validate_version_governance(version.strategy_id, version.version)
        validate_release_package(context, version.release_id)
    assert before == {p: p.read_bytes() for p in legacy}


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
    from strategy_manager.freeze_store import read_decision

    context, request, source = inspection
    binding_path = request.runtime_binding.resolve(context.root)
    payload = json.loads(binding_path.read_text(encoding="utf-8"))
    payload["install_files"] = []
    binding_path.write_text(json.dumps(payload), encoding="utf-8")
    report = inspect_candidate(
        context, replace(request, runtime_binding=file_ref(context.root, binding_path), replays=())
    )
    assert (
        next(x for x in report.checks if x.check is f.InspectionCheck.PACKAGE).status
        is f.InspectionStatus.FAIL
    )
    selection = read_decision(context.strategy_root, request.selection)
    repeated = replace(selection, confirmation_source=file_ref(context.root, source))
    assert record_research_decision(context, repeated) == request.selection
    with pytest.raises(ValidationError, match="hash differs"):
        record_research_decision(context, replace(repeated, reason="changed decision content"))
