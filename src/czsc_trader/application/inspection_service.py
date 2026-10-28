"""Two-goal inspection and publication of the exact inspected package."""
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import shutil
import time
from uuid import uuid4

from strategy_manager import StrategyRegistry, StrategyVersion, canonical_sha256
from strategy_manager import freeze_contracts as f
from strategy_manager.freeze_store import FreezeVersionRequest
from strategy_manager.write_lock import RegistryWriteLock
from strategy_runtime import StrategyRuntime, RuntimeBinding, RuntimeBindingSpec
from strategy_runtime.contracts import StrategyIdentity
from strategy_runtime.deployment import validate_release_package
from strategy_runtime.inspection import (InspectionControl, InspectionStage,
                                         InspectionEnvironment, collect_inspection_environment)
from paper_trading_engine.inspection import PteReleaseInspectionRequest, inspect_release
from .context import RepositoryContext
from .candidate_service import load_candidate, _registered_root
from .research_evidence import (record_decision, read_decision, validate_inspection, validate_approval,
    build_version_from_plan, validate_migration_selection, validate_migration_target, validate_migration_files)
from .inspection_contracts import CandidateInspectionRequest, InspectionPublicationError, InspectionInputError
from .inspection_inputs import replay_identity, authenticate_execution, copy_pte_inputs, portable_value
from .inspection_execution import Controller, Interrupted, equivalence_jobs, compare_baseline, goal
from .delivery_service import validate_delivery, _delivery_path, _public_delivery_path, _resolve
from ..research_tools import delivery as d
from ..temp_workspace import create_temporary_directory


def _bytes(value):
    return json.dumps(value, default=dict, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class _EvidenceStore:
    context: RepositoryContext
    owner: f.ResearchEvidenceOwner

    def __post_init__(self):
        self.references = []

    def put(self, data):
        digest = sha256(data).hexdigest()
        prefix = "inspection" if self.owner.experiment_id else "decisions/objects"
        ref = f.ResearchEvidenceRef(self.owner, f"{prefix}/{digest}", digest)
        from .evidence_service import _publish_bytes
        try:
            _publish_bytes(self.context.root, _resolve(self.context.root, ref.repository_path), data)
            ref.resolve(self.context.root)
        except Exception as exc:
            raise InspectionPublicationError("PERSIST", self.references, None, str(exc)) from exc
        self.references.append(ref)
        return ref

    def put_json(self, value):
        return self.put(_bytes(value))


def _delivery(context, ref):
    path = ref.resolve(context.root)
    receipt = d.DeliveryReceipt.from_dict(_read(path))
    if path != (_public_delivery_path(context, receipt.reference) / "receipt.json").resolve():
        raise ValueError("decision delivery must reference its published receipt")
    checked = validate_delivery(context, receipt.reference, scope=d.DeliveryValidationScope.INTEGRITY)
    if checked.status is not d.ValidationStatus.PASS:
        raise ValueError(f"decision delivery is invalid: {checked.issues}")
    document = _read(_delivery_path(context, receipt.reference) / "delivery.json")
    return receipt.reference, d.DeliveryContent.from_dict(document["content"])


def record_research_decision(context: RepositoryContext, decision: f.ResearchDecision) -> f.DecisionReference:
    if type(decision) is not f.ResearchDecision:
        raise TypeError("record_research_decision requires ResearchDecision")
    registry = StrategyRegistry(context.research_registry_root)
    registry.get_family(decision.strategy_id)
    subject = decision.subject
    if type(subject) is f.CandidateSelectionSubject:
        registered = registry.get_candidate_registration(subject.candidate)
        if (subject.content_sha256, subject.registration_sha256) != (registered.content_sha256, registered.record_sha256):
            raise ValueError("selection differs from candidate registration identity")
    elif type(subject) in (f.FrozenMigrationSelectionSubject, f.FrozenObservationUpgradeSelectionSubject):
        validate_migration_selection(context, subject)
    elif type(subject) is f.StageAdvanceSubject:
        reference, _ = _delivery(context, subject.delivery)
        if reference.strategy_id != decision.strategy_id:
            raise ValueError("decision delivery family differs")
    else:
        report = validate_inspection(context.root, subject.inspection)
        plan = report.plan
        if plan is None or subject != f.FreezeSubject(plan.origin.candidate, plan.origin.content_sha256,
                                                      subject.inspection, plan.sha256, plan.version):
            raise ValueError("freeze decision does not match inspected plan")
    store = _EvidenceStore(context, f.ResearchEvidenceOwner(decision.strategy_id))
    source = store.put(decision.confirmation_source.resolve(context.root).read_bytes())
    return record_decision(context, replace(decision, confirmation_source=source))


def describe_inspection_environment(repository: RepositoryContext) -> InspectionEnvironment:
    if type(repository) is not RepositoryContext:
        raise TypeError("environment requires RepositoryContext")
    return collect_inspection_environment(repository.root)


def _copy_plan(context, request, registration, store, origin):
    evidence_root = _registered_root(context, registration)
    prefix = registration.source_root + "/"
    files = tuple(f.FreezeFile(ref.path.removeprefix(prefix), store.put(ref.resolve(evidence_root).read_bytes()))
                  for ref in registration.source_files)
    files += tuple(f.FreezeFile(item.path, store.put(item.source.resolve(context.root).read_bytes()))
                   for item in request.additional_files)
    definition = StrategyRuntime().describe(load_candidate(context, registration.key))
    from strategy_runtime.equity_definition import EquityStrategyDefinition
    if type(definition) is EquityStrategyDefinition:
        binding = RuntimeBindingSpec(tuple(x.path.removeprefix(prefix) for x in registration.source_files),
            definition.source_sha256, tuple(x.path for x in files),
            canonical_sha256({"contract": "equity-decision-v2", "definition": definition.to_dict()}))
    else:
        binding = RuntimeBindingSpec(tuple(x.path.removeprefix(prefix) for x in registration.source_files),
            definition.implementation.source_sha256, tuple(x.path for x in files), definition.observation.sha256)
    target = request.target
    return f.FreezePlan(origin, target.version, target.parent_version, target.change_summary,
        registration.origin.experiment_id, target.selection_data_cutoff, target.forward_start,
        store.put(registration.payload.resolve(evidence_root).read_bytes()), files, store.put_json(binding.to_dict()))


def _package(context, plan, store, repository, selection_subject=None):
    version = build_version_from_plan(context.root, plan, selection_subject)
    root = repository / "strategies" / version.strategy_id
    package = root / "releases" / version.version
    package.mkdir(parents=True)
    for file in plan.source_files:
        target = package / "src/strategy_runtime" / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file.source.resolve(context.root).read_bytes())
    binding = RuntimeBinding(version.release_id, version.release_hash,
                              RuntimeBindingSpec.from_dict(_read(plan.runtime_binding.resolve(context.root))))
    (package / "runtime_binding.json").write_bytes(_bytes(binding.to_dict()))
    files = tuple(f.FreezeFile(p.relative_to(package).as_posix(), store.put(p.read_bytes()))
                  for p in sorted(package.rglob("*")) if p.is_file())
    manifest = {"schema_version": 1, "strategy_version_id": version.release_id,
        "strategy_version_hash": version.release_hash,
        "source_candidate_id": f"{version.strategy_id}-{version.source_candidate}",
        "candidate_package_hash": plan.sha256, "runtime_root": "src/strategy_runtime",
        "runtime_binding": "runtime_binding.json", "files": {x.path: x.source.sha256 for x in files}}
    manifest["package_hash"] = canonical_sha256(manifest)
    (package / "release_manifest.json").write_bytes(_bytes(manifest))
    (root / "versions").mkdir()
    (root / "versions" / f"{version.version}.json").write_bytes(_bytes(version.to_dict()))
    family = StrategyRegistry(context.research_registry_root).get_family(version.strategy_id)
    (root / "family.json").write_bytes(_bytes(family.to_dict()))
    verified = validate_release_package(repository / "strategies", version.release_id)
    return f.InspectedRelease(store.put_json(version.to_dict()), store.put_json(manifest), files,
                              version.release_hash, manifest["package_hash"]), verified


def inspect_candidate(context: RepositoryContext, request: CandidateInspectionRequest, *, control: InspectionControl | None = None) -> f.CandidateInspectionReport:
    if type(context) is not RepositoryContext:
        raise InspectionInputError("INVALID_TYPE", "repository", "inspection requires RepositoryContext")
    if type(request) is not CandidateInspectionRequest:
        raise InspectionInputError("INVALID_TYPE", "request", "inspect_candidate requires CandidateInspectionRequest")
    if request.research.repository.root.resolve() != context.root.resolve():
        raise InspectionInputError("IDENTITY_MISMATCH", "research", "inspection requires local ResearchContext")
    control = InspectionControl() if control is None else control
    if type(control) is not InspectionControl:
        raise InspectionInputError("INVALID_TYPE", "control", "inspection control requires InspectionControl")
    if not request.experiment.resolve(context.root).is_dir():
        raise InspectionInputError("NOT_FOUND", "experiment", "inspection experiment does not exist")
    try:
        registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
    except Exception as exc:
        raise InspectionInputError("INVALID_REFERENCE", "candidate", str(exc)) from exc
    try:
        selection = read_decision(context.root, request.selection)
    except Exception as exc:
        raise InspectionInputError("INVALID_REFERENCE", "selection", str(exc)) from exc
    subject = selection.subject
    if (selection.action is not f.DecisionAction.APPROVE
            or type(subject) not in (f.CandidateSelectionSubject, f.FrozenMigrationSelectionSubject, f.FrozenObservationUpgradeSelectionSubject)
            or subject.candidate != request.candidate or subject.content_sha256 != registration.content_sha256
            or (isinstance(subject, f.CandidateSelectionSubject) and subject.registration_sha256 != registration.record_sha256)):
        raise InspectionInputError("IDENTITY_MISMATCH", "selection", "inspection requires matching candidate selection")
    owner = f.ResearchEvidenceOwner(request.candidate.strategy_id, request.experiment.experiment_id)
    from .equity_inspection_contracts import EquityInspectionProtocol
    if type(request.protocol) is EquityInspectionProtocol:
        from .equity_inspection import inspect_equity_candidate
        return inspect_equity_candidate(context, request, control, registration, selection)
    store = _EvidenceStore(context, owner)
    run_id = "inspection-" + uuid4().hex
    try:
        workspace = _resolve(context.root, ".tmp/strategy-inspection/" + run_id)
    except Exception as exc:
        raise InspectionInputError("UNSAFE_PATH", "workspace", str(exc)) from exc
    workspace.mkdir(parents=True)
    controller = Controller(run_id, control, workspace)
    origin = f.CandidateOrigin(registration.key, registration.content_sha256, store.put_json(registration.to_dict()))
    protocol = store.put_json(portable_value(request.protocol.to_dict()))
    normalized = {"schema_version": 2, "candidate": request.candidate.to_dict(), "selection": request.selection.to_dict(),
        "experiment": request.experiment.to_dict(), "target": request.target.to_dict(), "protocol_sha256": protocol.sha256,
        "replays": [replay_identity(x) for x in request.replays], "additional_files": [x.to_dict() for x in request.additional_files],
        "remaining_risks": list(request.remaining_risks), "data_kind": request.data_kind.value}
    request_ref = store.put_json(normalized)
    environment_ref = plan = release = None
    behavior, pte = [], []
    quiescent = True
    failure_reason = f.InspectionReason.EXECUTION_ERROR
    try:
        controller.tick(force=True)
        environment = describe_inspection_environment(context)
        environment_ref = store.put_json(environment.to_dict())
        expected = request.protocol.pte.environment
        if (expected.platform_build_sha256 != environment.platform_build_sha256
                or expected.pte_contract_version != environment.pte_contract_version
                or expected.srt_contract_version != environment.srt_contract_version):
            raise Interrupted(f.InspectionReason.ENVIRONMENT_MISMATCH, "requested runtime environment differs")
        failure_reason = f.InspectionReason.CONTENT_MISMATCH
        candidate = load_candidate(context, request.candidate)
        definition = request.research.runtime.describe(candidate)
        identity = StrategyIdentity(definition.strategy_family_id, definition.release_id,
            definition.release_hash, definition.runtime_sha256, definition.tradable_symbol)
        failure_reason = f.InspectionReason.INPUT_MISMATCH
        for scenario in request.protocol.pte.scenarios:
            for step in scenario.decisions:
                if step.binding.plan.strategy != identity:
                    raise ValueError("PTE input binding differs from selected candidate")
                if step.binding.plan.tradable_window.end > request.target.selection_data_cutoff:
                    raise ValueError("PTE input exceeds selection cutoff")
        failure_reason = f.InspectionReason.CONTENT_MISMATCH
        if candidate.payload["runtime"].get("contract_version") != 2 or candidate.payload.get("decision_feedback", "UNDECLARED") == "UNDECLARED":
            raise Interrupted(f.InspectionReason.UNSUPPORTED_CONTRACT, "inspection requires implementation contract 2 and declared feedback")
        if type(subject) in (f.FrozenMigrationSelectionSubject, f.FrozenObservationUpgradeSelectionSubject):
            t = request.target
            validate_migration_target(context, subject, t.version, t.parent_version,
                                      t.selection_data_cutoff.isoformat(), t.forward_start.isoformat(), available=True)
            validate_migration_files(context, subject, request.additional_files)
        plan = _copy_plan(context, request, registration, store, origin)
        release, verified = _package(context, plan, store, workspace / "repository", subject)
        failure_reason = f.InspectionReason.INPUT_MISMATCH
        input_origins = []
        for replay in request.replays:
            controller.tick()
            input_origins.append(store.put_json({"data_kind": request.data_kind.value,
                "data_kind_source": "CALLER_DECLARATION", **authenticate_execution(
                    request.research.data, replay, request.target.selection_data_cutoff)}))
        controller.stage = InspectionStage.EQUIVALENCE
        failure_reason = f.InspectionReason.EXECUTION_ERROR
        controller.tick(force=True)
        jobs = equivalence_jobs(request, candidate, verified, workspace, controller)
        quiescent = jobs.interruption is None or jobs.interruption.quiescent
        for index, ok, facts in jobs.completed:
            replay = request.replays[index]
            refs = []
            reason = f.InspectionReason.OK if ok and facts["passed"] else f.InspectionReason.BEHAVIOR_DIFFERENCE if ok else f.InspectionReason.EXECUTION_ERROR
            if ok:
                try:
                    baseline, sources = compare_baseline(context, replay, facts["candidate"], registration, request.protocol.float_tolerance, store)
                    facts["baseline"] = baseline
                    refs.extend(sources)
                    if baseline["status"] == "FAIL":
                        reason = f.InspectionReason.BASELINE_DIFFERENCE
                except InspectionPublicationError:
                    raise
                except Exception as exc:
                    facts["baseline"] = {"status": "FAIL", "error": str(exc)}
                    reason = f.InspectionReason.BASELINE_DIFFERENCE
            refs.append(input_origins[index])
            refs.append(store.put_json(facts))
            behavior.append(f.InspectionCaseResult("replay-" + str(index),
                f.InspectionStatus.PASS if reason is f.InspectionReason.OK else f.InspectionStatus.FAIL,
                reason, "candidate/frozen behavior and requested baseline", tuple(refs)))
        if jobs.interruption is not None:
            raise jobs.interruption
        controller.stage = InspectionStage.PTE
        controller.tick(force=True)
        spaces, copies = copy_pte_inputs(request.research.data, request.protocol.pte, workspace, controller.tick)
        pte_request = PteReleaseInspectionRequest(run_id, workspace / "repository", workspace, verified.release.release_id,
            release.release_sha256, release.package_sha256, spaces, copies, request.protocol.pte)
        outcome = inspect_release(pte_request, control=InspectionControl(controller.remaining(), control.max_workers,
            control.cancelled, lambda progress: controller.progress(progress.completed, progress.total, progress.message, force=True)))
        controller.stage = InspectionStage.PERSIST
        artifacts = {}
        for item in outcome.artifacts:
            path = workspace / item.path
            if not path.resolve().is_relative_to(workspace.resolve()) or sha256(path.read_bytes()).hexdigest() != item.sha256:
                raise ValueError("PTE artifact identity differs")
            artifacts[item.artifact_id] = store.put(path.read_bytes())
        coverage = store.put_json({"status": outcome.status.value, "coverage": [x.to_dict() for x in outcome.coverage],
                                  "input_copies": [x.to_dict() for x in copies], "environment": outcome.environment.to_dict(),
                                  "data_kind": request.data_kind.value, "channel_kind": "SYNTHETIC",
                                  "artifacts": [{**item.to_dict(), "reference": artifacts[item.artifact_id].to_dict()}
                                                for item in outcome.artifacts]})
        for case in outcome.scenarios:
            status = f.InspectionStatus(case.status.value)
            reason = f.InspectionReason.OK if status is f.InspectionStatus.PASS else f.InspectionReason.PTE_FAILURE
            if case.code in f.InspectionReason._value2member_map_ and status is not f.InspectionStatus.PASS:
                reason = f.InspectionReason(case.code)
            pte.append(f.InspectionCaseResult(case.case_id, status, reason, case.summary,
                (coverage, *(artifacts[x] for x in case.artifact_ids))))
        status = f.InspectionStatus(outcome.status.value)
        pte.append(f.InspectionCaseResult("pte-coverage", status,
            f.InspectionReason.OK if status is f.InspectionStatus.PASS else f.InspectionReason.COVERAGE_MISSING,
            "observed PTE scenario capability coverage", (coverage, *artifacts.values())))
        controller.stage = InspectionStage.FINALIZE
        if control.timeout_seconds is not None and time.monotonic() - controller.started >= control.timeout_seconds:
            raise Interrupted(f.InspectionReason.RESOURCE_LIMIT, "inspection total deadline exceeded after evidence collection")
        load_candidate(context, request.candidate)
        if StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate) != registration:
            raise Interrupted(f.InspectionReason.CONTENT_MISMATCH, "candidate registration changed during inspection")
        final_package = validate_release_package(workspace / "repository/strategies", verified.release.release_id)
        if final_package.package_sha256 != release.package_sha256 or final_package.release.release_hash != release.release_sha256:
            raise Interrupted(f.InspectionReason.CONTENT_MISMATCH, "inspected package changed during execution")
        final_environment = describe_inspection_environment(context)
        if final_environment.to_dict() != environment.to_dict() or outcome.environment.to_dict() != environment.to_dict():
            raise Interrupted(f.InspectionReason.ENVIRONMENT_MISMATCH, "runtime environment changed during inspection")
    except InspectionPublicationError:
        raise
    except Exception as exc:
        quiescent = quiescent and getattr(exc, "quiescent", True)
        reason = exc.reason if isinstance(exc, Interrupted) else failure_reason
        if not quiescent:
            reason = f.InspectionReason.RESOURCE_LIMIT
        status = f.InspectionStatus.INCOMPLETE if reason in (f.InspectionReason.CANCELLED, f.InspectionReason.RESOURCE_LIMIT) else f.InspectionStatus.FAIL
        detail = store.put_json({"stage": controller.stage.value, "reason": reason.value, "type": type(exc).__name__, "message": str(exc)})
        target = pte if controller.stage in (InspectionStage.PTE, InspectionStage.PERSIST, InspectionStage.FINALIZE) else behavior
        target.append(f.InspectionCaseResult("execution-" + controller.stage.value.lower(), status, reason, str(exc) or type(exc).__name__, (detail,)))
    measurements = store.put_json({"run_id": run_id, "elapsed_seconds": time.monotonic() - controller.started,
                                   "max_workers": control.max_workers, "timeout_seconds": control.timeout_seconds})
    report = f.CandidateInspectionReport(run_id, owner, origin, request.selection, request_ref, protocol,
        environment_ref, plan, release, goal(behavior), goal(pte), measurements, request.remaining_risks)
    try:
        store.put_json(report.to_dict())
    except InspectionPublicationError as exc:
        # A candidate reference is not evidence of successful publication.
        raise InspectionPublicationError("REPORT", exc.partial_evidence, None, str(exc)) from exc
    if quiescent:
        try:
            shutil.rmtree(workspace)
        except OSError as exc:
            raise InspectionPublicationError("CLEANUP", store.references, report.reference, str(exc)) from exc
    return report


def freeze_candidate(context: RepositoryContext, request: f.FreezeCandidateRequest) -> f.FreezeReceipt:
    if type(request) is not f.FreezeCandidateRequest:
        raise TypeError("freeze_candidate requires FreezeCandidateRequest")
    existing = get_freeze_result(context, request.request_id)
    if existing.status is not f.FreezeStatus.NOT_FOUND:
        if existing.request_sha256 is not None and existing.request_sha256 != request.sha256:
            raise ValueError("freeze request ID already binds different content")
        return existing
    report = validate_approval(context.root, request)
    plan, release = report.plan, report.release
    selection = read_decision(context.root, report.selection)
    if isinstance(selection.subject, f.FrozenMigrationSelectionSubject) and plan.version == selection.subject.original.version:
        raise ValueError("same-version migration requires the explicit runtime upgrade API")
    candidate = load_candidate(context, plan.origin.candidate)
    if candidate.payload["runtime"].get("contract_version") != 2:
        raise ValueError("freeze requires implementation contract version 2")
    if (candidate.payload.get("runtime", {}).get("kind") != "US_EQUITY"
            and candidate.payload.get("decision_feedback", "UNDECLARED") == "UNDECLARED"):
        raise ValueError("freeze requires explicit decision feedback semantics")
    registered = StrategyRegistry(context.research_registry_root).get_candidate_registration(plan.origin.candidate)
    if registered.record_sha256 != plan.origin.registration_sha256:
        raise ValueError("candidate changed since inspection")
    version = StrategyVersion.from_dict(_read(release.version_record.resolve(context.root)))
    stage = create_temporary_directory(context.root, "freeze-package")
    for file in release.files:
        target = stage / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file.source.resolve(context.root).read_bytes())
    (stage / "release_manifest.json").write_bytes(release.manifest.resolve(context.root).read_bytes())
    journal_root = _journal_root(context, request.request_id)
    operation_path = journal_root / request.request_id.value / "research_request.json"
    with RegistryWriteLock(context.root / ".tmp/freeze-locks" / request.request_id.strategy_id).hold():
        if operation_path.exists() and f.FreezeCandidateRequest.from_dict(_read(operation_path)) != request:
            raise ValueError("freeze request ID already binds different content")
        _write_request(context, operation_path, request.to_dict())
        return StrategyRegistry(context.strategy_root).freeze_version(FreezeVersionRequest(
            request.request_id, request.sha256, version,
            StrategyRegistry(context.research_registry_root).get_family(version.strategy_id),
            stage, release.package_sha256, journal_root))


def _journal_root(context, request_id):
    if type(request_id) is not f.FreezeRequestId:
        raise TypeError("freeze query requires FreezeRequestId")
    return _resolve(context.root, f"research/{request_id.strategy_id}/freeze_requests")


def get_freeze_result(context: RepositoryContext, request_id: f.FreezeRequestId) -> f.FreezeReceipt:
    journal_root = _journal_root(context, request_id)
    receipt = StrategyRegistry(context.strategy_root).get_freeze_result(request_id, journal_root=journal_root)
    if receipt.status is f.FreezeStatus.NOT_FOUND:
        return receipt
    try:
        request = f.FreezeCandidateRequest.from_dict(_read(journal_root / request_id.value / "research_request.json"))
        if request.request_id != request_id or request.sha256 != receipt.request_sha256:
            raise ValueError("research freeze request differs from publication")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return f.FreezeReceipt(request_id, f.FreezeStatus.UNKNOWN, receipt.request_sha256,
                               reason=f"research freeze request cannot be verified: {exc}")
    return receipt


def _write_request(context, path, value):
    from .evidence_service import _publish_bytes
    _publish_bytes(context.root, path, _bytes(value))
