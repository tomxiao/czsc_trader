"""Called technical inspection and freeze operations; research owns all scheduling."""

from dataclasses import dataclass, replace, fields, is_dataclass
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path

import pandas as pd
from research_experiment import ExperimentContext, EvaluationRecord, EvaluationAttemptStatus
from research_experiment import load_experiment_input
from strategy_evaluator import (
    audit_replay,
    AuditStatus,
    compare_ledgers,
    LedgerComparisonRequest,
    LedgerComparisonMode,
    LedgerComparisonStatus,
    ReplayEvidence,
    AssessmentEvidence,
)
from strategy_manager import StrategyRegistry, CandidateEvidence, CandidateKey, canonical_sha256
from strategy_manager import freeze_contracts as f
from strategy_manager.freeze_store import FreezeVersionRequest, _durable
from strategy_manager.write_lock import RegistryWriteLock
from .research_evidence import (
    record_decision,
    build_version,
    read_decision,
    validate_inspection,
    validate_approval,
)
from strategy_runtime import (
    StrategyRuntime,
    StrategyRelease,
    RuntimeBindingSpec, RuntimeBinding,
)
from strategy_runtime import StrategyInit, TradableWindow, ExecutionPolicy
from strategy_runtime.errors import StrategyRuntimeError

from .context import RepositoryContext
from .candidate_service import load_candidate, _registered_root
from .runtime_acceptance import runtime_readiness, require_same_runtime_content
from .delivery_service import validate_delivery, _delivery_path, _resolve
from ..research_tools import delivery as d
from ..research_tools.evaluation import EvaluationRequest
from ..research_tools.assessment import build_assessment_evidence
from ..research_tools._evaluation_records import EvaluationExecutionError
from ..backtesting.audit_adapter import build_replay_evidence
from ..backtesting.metrics import calculate_metrics
from ..backtesting.models import StrategyIdentity, StrategySnapshot
from ..backtesting.result import BacktestResult
from ..backtesting.signal_replay import SignalReplay
from trading_execution_engine import HistoricalExecutor
from ..temp_workspace import create_temporary_directory


def _bytes(value):
    return json.dumps(
        value,
        default=dict,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class _EvidenceStore:
    context: RepositoryContext
    owner: f.ResearchEvidenceOwner

    def put(self, data):
        digest = sha256(data).hexdigest()
        prefix = "objects/inspection" if self.owner.experiment_id else "decisions/objects"
        ref = f.ResearchEvidenceRef(self.owner, f"{prefix}/{digest}", digest)
        target = _resolve(self.context.root, ref.repository_path)
        lock = RegistryWriteLock(self.context.root / ".tmp/research-locks" / self.owner.strategy_id)
        with lock.hold():
            if self.owner.experiment_id and (
                self.context.root / self.owner.repository_path / "experiment_manifest.json"
            ).exists():
                raise ValueError("inspection cannot write into a sealed experiment")
            if target.exists():
                ref.resolve(self.context.root)
            else:
                stage = create_temporary_directory(self.context.root, "inspection-object") / "object"
                with stage.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                target.parent.mkdir(parents=True, exist_ok=True)
                stage.replace(target)
        return ref

    def put_json(self, value):
        return self.put(_bytes(value))


def _delivery(context, ref):
    path = ref.resolve(context.root)
    receipt = d.DeliveryReceipt.from_dict(_read(path))
    if path != (_delivery_path(context, receipt.reference) / "receipt.json").resolve():
        raise ValueError("decision delivery must reference its published receipt")
    checked = validate_delivery(context, receipt.reference, scope=d.DeliveryValidationScope.INTEGRITY)
    if checked.status is not d.ValidationStatus.PASS:
        raise ValueError(f"decision delivery is invalid: {checked.issues}")
    document = _read(path.parent / "delivery.json")
    return receipt.reference, d.DeliveryContent.from_dict(document["content"])


def record_research_decision(
    context: RepositoryContext, decision: f.ResearchDecision
) -> f.DecisionReference:
    if type(decision) is not f.ResearchDecision:
        raise TypeError("record_research_decision requires ResearchDecision")
    StrategyRegistry(context.research_registry_root).get_family(decision.strategy_id)
    subject = decision.subject
    if isinstance(subject, (f.StageAdvanceSubject, f.CandidateSelectionSubject)):
        reference, content = _delivery(context, subject.delivery)
        if reference.strategy_id != decision.strategy_id:
            raise ValueError("decision delivery family differs")
        if isinstance(subject, f.CandidateSelectionSubject):
            if reference.stage is not d.DeliveryStage.ASSESSMENT:
                raise ValueError("candidate selection requires assessment delivery")
            candidates = content.payload.assessment_request.centers
            if not any(
                x.candidate_id
                == f"{subject.candidate.strategy_id}-{subject.candidate.candidate_id}"
                and x.content_sha256 == subject.content_sha256
                for x in candidates
            ):
                raise ValueError("selected candidate is absent from assessment")
    else:
        report = validate_inspection(context.root, subject.inspection)
        plan = report.plan
        if subject != f.FreezeSubject(
            plan.origin.candidate,
            plan.origin.content_sha256,
            subject.inspection,
            plan.sha256,
            plan.version,
        ):
            raise ValueError("freeze decision does not match inspected plan")
    store = _EvidenceStore(context, f.ResearchEvidenceOwner(decision.strategy_id))
    source = store.put(decision.confirmation_source.resolve(context.root).read_bytes())
    return record_decision(context, replace(decision, confirmation_source=source))


@dataclass(frozen=True, slots=True)
class EvaluationEvidenceReference(d._Record):
    experiment: d.ExperimentEvidenceRef
    attempt_id: str
    evaluation_ids: tuple[str, ...]
    result: CandidateEvidence

    def _validate(self):
        d.EvaluationEvidenceRef(self.experiment.experiment_id, self.attempt_id, self.evaluation_ids)
        if not self.evaluation_ids or len(set(self.evaluation_ids)) != len(self.evaluation_ids):
            raise ValueError("reference requires unique evaluation IDs")


@dataclass(frozen=True, slots=True)
class InspectionReplay:
    reference: EvaluationEvidenceReference
    reproduction_request: EvaluationRequest

    def __post_init__(self):
        if (
            type(self.reference) is not EvaluationEvidenceReference
            or type(self.reproduction_request) is not EvaluationRequest
        ):
            raise TypeError("inspection replay requires typed evaluation inputs/results")


@dataclass(frozen=True, slots=True)
class CandidateInspectionRequest:
    candidate: CandidateKey
    selection: f.DecisionReference
    protocol: f.InspectionProtocol
    execution: ExperimentContext
    replays: tuple[InspectionReplay, ...]
    version: str
    parent_version: str | None
    change_summary: str
    selection_data_cutoff: str
    forward_start: str
    additional_files: tuple[f.FreezeFile, ...] = ()
    remaining_risks: tuple[str, ...] = ()

    def __post_init__(self):
        for name, kind in (
            ("candidate", CandidateKey),
            ("selection", f.DecisionReference),
            ("protocol", f.InspectionProtocol),
        ):
            if not isinstance(getattr(self, name), kind):
                raise TypeError(f"inspection {name} requires {kind}")
        from ..research_tools.experiment import _PlatformExperimentContext

        if type(self.execution) is not _PlatformExperimentContext:
            raise TypeError("inspection execution requires platform ExperimentContext")
        for name, kind in (
            ("replays", InspectionReplay),
            ("additional_files", f.FreezeFile),
            ("remaining_risks", str),
        ):
            value = getattr(self, name)
            if type(value) is not tuple or not all(type(x) is kind for x in value):
                raise TypeError(f"inspection {name} requires typed tuple")
        f._version(self.version)
        if self.parent_version is not None:
            f._version(self.parent_version)


def _copy_plan(context, request, registration, store):
    evidence_root = _registered_root(context, registration)

    def copy(ref, root):
        return store.put(ref.resolve(root).read_bytes())

    prefix = f"objects/source/{registration.source_sha256}/strategy_runtime/"
    files = tuple(
        f.FreezeFile(ref.path.removeprefix(prefix), copy(ref, evidence_root))
        for ref in registration.source_files
    )
    files += tuple(
        f.FreezeFile(item.path, copy(item.source, context.root))
        for item in request.additional_files
    )
    definition = StrategyRuntime().describe(load_candidate(context, registration.key))
    binding = RuntimeBindingSpec(
        tuple(registration_file.path.removeprefix(prefix) for registration_file in registration.source_files),
        definition.implementation.source_sha256,
        tuple(item.path for item in files), definition.observation.sha256,
    )
    return f.FreezePlan(
        f.CandidateOrigin(
            registration.key,
            registration.content_sha256,
            store.put_json(registration.to_dict()),
        ),
        request.version,
        request.parent_version,
        request.change_summary,
        registration.origin.experiment_id,
        request.selection_data_cutoff,
        request.forward_start,
        copy(registration.payload, evidence_root),
        files,
        store.put_json(binding.to_dict()),
        tuple(
            copy(ref, evidence_root)
            for ref in (
                registration.origin.preflight,
                *((registration.derivation.evidence,) if registration.derivation else ()),
            )
        ),
    )


def _materialize(context, plan):
    stage = create_temporary_directory(context.root, "freeze-package")
    for file in plan.source_files:
        target = stage / "src/strategy_runtime" / file.path
        if not target.resolve().is_relative_to(stage.resolve()):
            raise ValueError("freeze file escapes staging")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file.source.resolve(context.root).read_bytes())
    return stage


def _binding(context, plan):
    template = _read(plan.runtime_binding.resolve(context.root))
    RuntimeBindingSpec.from_dict(template)
    payload = _read(plan.payload.resolve(context.root))
    runtime = payload["runtime"]
    if (
        template["source_files"] != runtime["source_files"]
        or template["implementation_sha256"] != runtime["source_sha256"]
    ):
        raise ValueError("binding differs from candidate runtime")
    installed = template["install_files"]
    if (
        type(installed) is not list
        or len(set(installed)) != len(installed)
        or set(installed) != {x.path for x in plan.source_files}
    ):
        raise ValueError("binding install files differ from plan")
    candidate = load_candidate(context, plan.origin.candidate)
    definition = StrategyRuntime().describe(candidate)
    if template['observation_sha256'] != definition.observation.sha256:
        raise ValueError('binding observation differs from candidate')
    return template


def _authenticate(context, request, result, workspace, store):
    projection = build_assessment_evidence(request, result)
    root = workspace.resolve()
    if not root.is_relative_to(context.root.resolve()) or result.record is None:
        raise ValueError("inspection requires local managed evaluation evidence")
    path = CandidateEvidence(result.record.path, result.record.sha256).resolve(root)
    record = EvaluationRecord.from_dict(_read(path))
    if (
        record.status is not EvaluationAttemptStatus.SUCCEEDED
        or record.attempt_id != result.attempt_id
        or record.result_hash != result.result_hash
        or record.request_hash != result.request_hash
    ):
        raise ValueError("inspection evaluation record differs")
    artifact = record.result_artifact
    value = _read(CandidateEvidence(artifact.path, artifact.sha256).resolve(root))
    if value.get("schema_version") != 4 or value["assessment_evidence"] != [
        x.to_dict() for x in projection
    ]:
        raise ValueError("inspection evaluation artifact differs")
    return projection, store.put_json({"record": record.to_dict(), "result": value})


def _load_reference(context, reference, store):
    root = _resolve(context.root, reference.experiment.workspace_path)
    _resolve(root, "execution_receipt.json")
    envelope = _read(_resolve(root, "execution_envelope.json"))
    for path in envelope["receipt"]["artifact_sha256"]:
        _resolve(root, path)
    loaded = load_experiment_input(
        root, expected_receipt_sha256=reference.experiment.receipt_sha256
    )
    if loaded.experiment_id != reference.experiment.experiment_id:
        raise ValueError("reference experiment identity differs")
    records = tuple(
        EvaluationRecord.from_dict(x) for x in envelope["receipt"]["trace"]["evaluations"]
    )
    record = next((x for x in records if x.attempt_id == reference.attempt_id), None)
    if (
        record is None
        or record.status is not EvaluationAttemptStatus.SUCCEEDED
        or tuple(record.evaluation_ids) != reference.evaluation_ids
        or record.result_artifact is None
        or (record.result_artifact.path, record.result_artifact.sha256)
        != (reference.result.path, reference.result.sha256)
    ):
        raise ValueError("reference differs from receipted evaluation")
    value = _read(reference.result.resolve(root))
    if value.get("schema_version") != 4:
        raise ValueError("inspection requires evaluation evidence schema 4")
    if (
        value["request_hash"] != record.request_hash
        or value["result_hash"] != record.result_hash
        or canonical_sha256(value["request_identity"]) != record.request_hash
    ):
        raise ValueError("reference request/result identity differs")
    projection = tuple(AssessmentEvidence.from_dict(x) for x in value["assessment_evidence"])
    if tuple(x.evaluation_id for x in projection) != reference.evaluation_ids or any(
        x.attempt_id != record.attempt_id
        or x.request_sha256 != record.request_hash
        or x.result_sha256 != record.result_hash
        or x.candidate.candidate_id != record.candidate_id
        or x.candidate.content_sha256 != record.content_sha256
        for x in projection
    ):
        raise ValueError("reference assessment identity differs")
    return value, projection, store.put_json({"record": record.to_dict(), "result": value})


def _replay_evidence(request, run):
    return build_replay_evidence(
        run.signals,
        request.execution_data,
        run.execution,
        request.initial_cash,
        calculate_metrics(run.execution, request.initial_cash),
    )


def _reference_signals(run):
    # Construct each typed column directly: read_json inference changes object
    # nulls to NaN and datetime units, causing false reproduction differences.
    columns = [x["name"] for x in run["signals"]["schema"]["fields"]]
    return pd.DataFrame(
        {
            name: pd.Series(
                [row[name] for row in run["signals"]["data"]], dtype=run["signal_dtypes"][name]
            )
            for name in columns
        }
    )


def _inspect_release_replay(context, execution, request, run, release, source_root, tolerance, binding):
    """Exercise from_release through the managed runtime port, without deployment."""
    window = TradableWindow(run.signals.evaluation_start.date(), run.signals.evaluation_end.date())
    root = create_temporary_directory(context.root, "inspection-runtime")
    candidate = execution.runtime.create(StrategyInit(request.strategy, window, root / "candidate"))
    frozen = execution.runtime.create(
        StrategyInit(release, window, root / "release", source_root=source_root, runtime_binding=binding)
    )
    candidate_prepared = candidate.prepare_data()
    prepared = frozen.prepare_data()
    left_signals, right_signals = candidate.inspect_signals(), frozen.inspect_signals()
    signal_equal = True
    try:
        pd.testing.assert_frame_equal(
            left_signals, right_signals, check_exact=tolerance == 0, atol=tolerance, rtol=0
        )
    except AssertionError:
        signal_equal = False
    from strategy_runtime.prepared_store import load_prepared_inputs

    left_inputs = load_prepared_inputs(
        root / "candidate", strategy=candidate_prepared.strategy, tradable_window=window
    )
    right_inputs = load_prepared_inputs(
        root / "release", strategy=prepared.strategy, tradable_window=window
    )
    if (
        candidate_prepared.data_identity != run.signals.data_identity
        or left_inputs.input_identities != right_inputs.input_identities
        or left_inputs.signal_dates != right_inputs.signal_dates
        or left_inputs.calculation_dates != right_inputs.calculation_dates
        or candidate_prepared.available_through != prepared.available_through
    ):
        raise ValueError("prospective release prepared input content/coverage differs")
    policy = frozen.definition.execution
    settings = dict(policy.settings)
    fee = next(x.one_way_cost for x in request.costs if x.scenario_id == run.scenario_id)
    if policy.policy_type == "FROZEN_RULE":
        settings["capital"] = {**settings["capital"], "fee_rate": fee}
    else:
        settings["one_way_cost"] = fee
    policy = ExecutionPolicy(policy.policy_type, settings)
    frozen = execution.runtime.create(
        StrategyInit(
            release, window, root / "release", execution_policy=policy, source_root=source_root, runtime_binding=binding
        )
    )
    frozen.prepare_data()
    channel = HistoricalExecutor(
        strategy_reference=release.release_id,
        symbol=request.symbol,
        execution_daily=request.execution_data.execution_daily,
        execution_intraday=request.execution_data.execution_intraday,
        execution_five_minute=request.execution_data.execution_five_minute,
        evaluation_start=run.signals.evaluation_start,
        evaluation_end=run.signals.evaluation_end,
        initial_cash=request.initial_cash,
        execution_policy=policy,
        order_types=frozen.definition.capabilities.order_types,
        checkpoints=frozen.definition.capabilities.checkpoints,
    )
    from ..backtesting.observation import ObservationExecutor
    observed = ObservationExecutor(frozen.definition, channel)
    ledger = frozen.run_window(executor=observed)
    left_observations = tuple(run.execution.observations)
    def economic_observations(items):
        return [{k: v for k, v in item.to_dict().items() if k not in
                 ('strategy', 'signal_identity', 'plan_identity')} for item in items]
    if economic_observations(left_observations) != economic_observations(observed.observations):
        raise ValueError('candidate and frozen observation facts differ')
    identity = StrategyIdentity("REGISTERED", release.release_id, "prospective_inspection")
    result = BacktestResult(
        identity, ledger.decisions, ledger.orders, ledger.fills, ledger.account_daily, ledger.trades, tuple(observed.observations)
    )
    support = dict(run.signals.support_data)
    support.update(
        release_id=release.release_id,
        runtime_sha256=frozen.definition.runtime_sha256,
        execution_policy={"policy_type": policy.policy_type, "settings": settings},
    )
    replay = SignalReplay(
        StrategySnapshot(
            identity,
            release.release_hash,
            sha256(_bytes(release.payload)).hexdigest(),
            dict(release.payload),
            runtime_root=source_root,
        ),
        release,
        ledger.decisions,
        right_signals.index.min(),
        right_signals.index.max(),
        run.signals.evaluation_start,
        run.signals.evaluation_end,
        root / "release",
        prepared.data_identity,
        support,
    )
    evidence = build_replay_evidence(
        replay,
        request.execution_data,
        result,
        request.initial_cash,
        calculate_metrics(result, request.initial_cash),
    )
    comparison = compare_ledgers(
        LedgerComparisonRequest(
            _replay_evidence(request, run), evidence, LedgerComparisonMode.ECONOMIC, tolerance
        )
    )
    audit = audit_replay(evidence, tolerance=tolerance)
    execution._recorder.record_operation("inspection.release_replay")
    return {
        "release_id": release.release_id,
        "release_hash": release.release_hash,
        "candidate_prepared_identity": candidate_prepared.data_identity,
        "release_prepared_identity": prepared.data_identity,
        "input_identities": left_inputs.input_identities,
        "evidence": evidence.to_dict(),
        "audit": audit.to_dict(),
        "comparison": comparison.to_dict(),
        "candidate_signals": json.loads(left_signals.to_json(orient="table", date_format="iso")),
        "release_signals": json.loads(right_signals.to_json(orient="table", date_format="iso")),
        "signal_equivalence": signal_equal,
    }


def inspect_candidate(
    context: RepositoryContext, request: CandidateInspectionRequest
) -> f.CandidateInspectionReport:
    if type(request) is not CandidateInspectionRequest:
        raise TypeError("inspect_candidate requires CandidateInspectionRequest")
    # Require the platform-created formal adapter, not a caller-supplied evaluator.
    from ..research_tools.experiment import _ExperimentEvaluationAccess

    if (
        type(request.execution.evaluation) is not _ExperimentEvaluationAccess
        or request.execution.definition.mode.value != "FORMAL"
        or not request.execution._formal
    ):
        raise TypeError("inspection requires a TDR formal REX context")
    if any(
        request.execution.workspace.path(name).exists()
        for name in ("execution_receipt.json", "execution_envelope.json", "execution_failure.json")
    ):
        raise ValueError("inspection cannot append to a sealed experiment workspace")
    owner = f.ResearchEvidenceOwner(request.candidate.strategy_id, request.execution.definition.experiment_id)
    if request.execution.definition.strategy_id != owner.strategy_id:
        raise ValueError("inspection experiment family differs")
    from .delivery_service import _load_scoped_experiment
    loaded = _load_scoped_experiment(context, owner.strategy_id, owner.experiment_id)
    if loaded.definition != request.execution.definition:
        raise ValueError("inspection execution differs from bound experiment")
    store = _EvidenceStore(context, owner)
    registration = StrategyRegistry(context.research_registry_root).get_candidate(
        request.candidate, experiments_root=context.experiments_root
    )
    candidate = load_candidate(context, request.candidate)
    selection = read_decision(context.root, request.selection)
    if (
        selection.action is not f.DecisionAction.APPROVE
        or type(selection.subject) is not f.CandidateSelectionSubject
        or selection.subject.candidate != request.candidate
        or selection.subject.content_sha256 != registration.content_sha256
    ):
        raise ValueError("inspection requires matching candidate selection")
    _, assessment = _delivery(context, selection.subject.delivery)
    selected_evidence = assessment.payload.assessment_request.evidence
    plan = _copy_plan(context, request, registration, store)
    evidence = store.put_json(plan.to_dict())
    checks = []

    def check(kind, status, detail, refs=(evidence,)):
        checks.append(f.InspectionCheckResult(kind, status, refs, detail))

    try:
        for name, version in registration.dependencies:
            if metadata.version(name) != version:
                raise ValueError(f"installed dependency version differs: {name}")
        check(
            f.InspectionCheck.CONTENT,
            f.InspectionStatus.PASS,
            "registered candidate source, payload and installed dependencies verified",
        )
    except (metadata.PackageNotFoundError, ValueError) as exc:
        check(f.InspectionCheck.CONTENT, f.InspectionStatus.FAIL, str(exc))
    stage = _materialize(context, plan)
    try:
        _binding(context, plan)
        check(
            f.InspectionCheck.PACKAGE,
            f.InspectionStatus.PASS,
            "source, observation and install closure verified",
        )
    except (ValueError, TypeError, OSError, StrategyRuntimeError) as exc:
        check(f.InspectionCheck.PACKAGE, f.InspectionStatus.FAIL, str(exc))
    release = None
    binding = None
    try:
        release = StrategyRelease._from_runtime_identity(
            strategy_family_id=request.candidate.strategy_id,
            version=plan.version,
            release_id=f"{request.candidate.strategy_id}-{plan.version}",
            release_hash=plan.sha256,
            payload=_read(plan.payload.resolve(context.root)),
        )
        binding = RuntimeBinding(release.release_id, release.release_hash, RuntimeBindingSpec.from_dict(_binding(context, plan)))
        runtime = request.execution.runtime
        left = runtime_readiness(runtime.describe(candidate))
        right = runtime_readiness(
            runtime.describe(release, source_root=stage / "src/strategy_runtime", runtime_binding=binding)
        )
        require_same_runtime_content(left, right)
        check(
            f.InspectionCheck.RUNTIME,
            f.InspectionStatus.PASS,
            "candidate and prospective release runtime contracts match",
        )
    except (ValueError, TypeError, OSError, StrategyRuntimeError) as exc:
        check(f.InspectionCheck.RUNTIME, f.InspectionStatus.FAIL, str(exc))
    covered = []
    comparisons, audits, signals, sources, release_replays = [], [], [], [], []
    errors = []
    signal_errors = []
    static_ready = all(x.status is f.InspectionStatus.PASS for x in checks)
    for replay in request.replays if static_ready else ():
        new_request = replay.reproduction_request
        if (new_request.strategy.strategy_family_id, new_request.strategy.candidate_id) != (
            request.candidate.strategy_id,
            request.candidate.candidate_id,
        ) or Path(new_request.repository_root).resolve() != context.root.resolve():
            raise ValueError("inspection replay candidate/repository differs")
        baseline, projection, ref = _load_reference(context, replay.reference, store)
        if (
            baseline["request_identity"]["data_cutoff"] > plan.selection_data_cutoff
            or new_request.data_cutoff.isoformat() > plan.selection_data_cutoff
        ):
            raise ValueError("reproduction cutoff exceeds frozen selection cutoff")
        if not all(
            p in selected_evidence
            and p.candidate.candidate_id
            == f"{request.candidate.strategy_id}-{request.candidate.candidate_id}"
            and p.candidate.content_sha256 == registration.content_sha256
            for p in projection
        ):
            raise ValueError("reference evaluation is absent from selected assessment")
        sources.append(ref)
        try:
            current_request = replace(new_request, strategy=candidate)
            current = request.execution.evaluation.evaluate(current_request)
            _, current_ref = _authenticate(
                context, current_request, current, request.execution.workspace.root, store
            )
            sources.append(current_ref)
            old = {(x["window_id"], x["scenario_id"]): x for x in baseline["runs"]}
            if len(old) != len(baseline["runs"]):
                raise ValueError("duplicate reference coordinates")
            if set(old) != {(x.window_id, x.scenario_id) for x in current.runs}:
                raise ValueError("reproduction coordinates differ from reference")
            for run in current.runs:
                previous = old[(run.window_id, run.scenario_id)]
                if (
                    run.identity.content_sha256,
                    run.identity.input_sha256,
                    run.identity.protocol_sha256,
                ) != (
                    previous["identity"]["content_sha256"],
                    previous["identity"]["input_sha256"],
                    previous["identity"]["protocol_sha256"],
                ):
                    raise ValueError("reproduction content/input/protocol identity differs")
                a, b = (
                    ReplayEvidence.from_dict(previous["replay_evidence"]),
                    _replay_evidence(current_request, run),
                )
                audit = audit_replay(b, tolerance=request.protocol.tolerance)
                audits.append(audit.to_dict())
                compared = compare_ledgers(
                    LedgerComparisonRequest(
                        a, b, LedgerComparisonMode.ECONOMIC, request.protocol.tolerance
                    )
                )
                comparisons.append(compared.to_dict())
                try:
                    pd.testing.assert_frame_equal(
                        _reference_signals(previous),
                        run.signals.decisions,
                        check_exact=request.protocol.tolerance == 0,
                        atol=request.protocol.tolerance,
                        rtol=0,
                    )
                    signals.append(True)
                except AssertionError as exc:
                    signals.append(False)
                    signal_errors.append(str(exc))
                if release is None:
                    raise ValueError("prospective release runtime unavailable")
                release_replay = _inspect_release_replay(
                    context,
                    request.execution,
                    current_request,
                    run,
                    release,
                    stage / "src/strategy_runtime",
                    request.protocol.tolerance,
                    binding,
                )
                release_replays.append(release_replay)
                comparisons.append(release_replay["comparison"])
                audits.append(release_replay["audit"])
                signals.append(release_replay["signal_equivalence"])
                covered.append(f.InspectionCoordinate(run.window_id, run.scenario_id))
        except (
            EvaluationExecutionError,
            ValueError,
            TypeError,
            OSError,
            StrategyRuntimeError,
        ) as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    detail = store.put_json(
        {
            "coverage": [x.to_dict() for x in covered],
            "audits": audits,
            "comparisons": comparisons,
            "signal_equivalence": signals,
            "signal_errors": signal_errors,
            "errors": errors,
            "release_replays": release_replays,
            "sources": [x.to_dict() for x in sources],
        },
    )
    refs = (detail, *sources)
    complete = set(covered) == set(request.protocol.coordinates) and len(covered) == len(
        request.protocol.coordinates
    )
    check(
        f.InspectionCheck.COVERAGE,
        f.InspectionStatus.PASS if complete else f.InspectionStatus.INCOMPLETE,
        "actual reproduction coverage compared with explicit protocol",
        refs,
    )
    check(
        f.InspectionCheck.REPRODUCTION,
        f.InspectionStatus.FAIL
        if errors
        else (f.InspectionStatus.PASS if complete else f.InspectionStatus.INCOMPLETE),
        "; ".join(errors) or (
            "fresh managed evaluations persisted" if static_ready
            else "reproduction not started because static inspection failed"
        ),
        refs,
    )
    for kind, values in (
        (f.InspectionCheck.LEDGER_AUDIT, [x["status"] == AuditStatus.PASS.value for x in audits]),
        (
            f.InspectionCheck.LEDGER_EQUIVALENCE,
            [x["status"] == LedgerComparisonStatus.EQUIVALENT.value for x in comparisons],
        ),
        (f.InspectionCheck.SIGNAL_EQUIVALENCE, signals),
    ):
        status = (
            f.InspectionStatus.FAIL
            if any(not x for x in values)
            else (f.InspectionStatus.PASS if complete and values else f.InspectionStatus.INCOMPLETE)
        )
        detail = f"{sum(values)}/{len(values)} reproduction coordinates passed"
        if kind is f.InspectionCheck.SIGNAL_EQUIVALENCE and signal_errors:
            detail += "; " + "; ".join(signal_errors)
        check(kind, status, detail, refs)
    request_hash = canonical_sha256(
        {
            "plan": plan.sha256,
            "selection": request.selection.sha256,
            "protocol": request.protocol.sha256,
            "sources": [x.to_dict() for x in sources],
            "risks": request.remaining_risks,
        }
    )
    report = f.CandidateInspectionReport(
        plan,
        request.selection,
        request.protocol,
        request_hash,
        tuple(checks),
        request.remaining_risks,
        owner,
    )
    store.put_json(report.to_dict())
    _archive_inspection(context, request.execution, report)
    return report


def _archive_inspection(context, execution, report):
    """Make platform-produced inspection evidence part of the eventual REX receipt."""

    def references(value):
        if isinstance(value, f.ResearchEvidenceRef):
            yield value
        elif is_dataclass(value):
            for field in fields(value):
                yield from references(getattr(value, field.name))
        elif isinstance(value, tuple):
            for item in value:
                yield from references(item)

    selection = read_decision(context.root, report.selection)
    refs = (report.reference, selection.confirmation_source, *references(report))
    for ref in dict.fromkeys(refs):
        relative = f"inspections/{report.sha256}/{ref.path}"
        destination = execution.workspace.path(relative)
        data = ref.resolve(context.root).read_bytes()
        if destination.exists():
            if destination.read_bytes() != data:
                raise ValueError("inspection archive conflict")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
        artifact = execution.workspace.register_artifact(relative, "candidate_inspection")
        if artifact not in execution._artifacts:
            execution._artifacts.append(artifact)


def freeze_candidate(
    context: RepositoryContext, request: f.FreezeCandidateRequest
) -> f.FreezeReceipt:
    if type(request) is not f.FreezeCandidateRequest:
        raise TypeError("freeze_candidate requires FreezeCandidateRequest")
    registry = StrategyRegistry(context.strategy_root)
    existing = get_freeze_result(context, request.request_id)
    if existing.status is not f.FreezeStatus.NOT_FOUND:
        if existing.request_sha256 is not None and existing.request_sha256 != request.sha256:
            raise ValueError("freeze request ID already binds different content")
        return existing
    report = validate_approval(context.root, request)
    # Revalidate the selected delivery and registered candidate before materialization.
    selection = read_decision(context.root, report.selection)
    _delivery(context, selection.subject.delivery)
    load_candidate(context, report.plan.origin.candidate)
    registration = StrategyRegistry(context.research_registry_root).get_candidate(
        report.plan.origin.candidate, experiments_root=context.experiments_root
    )
    plan = report.plan
    evidence_root = _registered_root(context, registration)
    if (registration.record_sha256 != plan.origin.registration_sha256
        or registration.content_sha256 != plan.origin.content_sha256):
        raise ValueError("candidate changed since inspection")
    if registration.payload.resolve(evidence_root).read_bytes() != plan.payload.resolve(context.root).read_bytes():
        raise ValueError("freeze payload differs from registered candidate")
    runtime_descriptor = _read(plan.payload.resolve(context.root))["runtime"]
    planned = {x.path: x.source.sha256 for x in plan.source_files}
    prefix = f"objects/source/{registration.source_sha256}/strategy_runtime/"
    if {x.path.removeprefix(prefix): x.sha256 for x in registration.source_files} != {
        name: planned.get(name) for name in runtime_descriptor["source_files"]
    }:
        raise ValueError("freeze source differs from registration")
    for name, expected in registration.dependencies:
        if metadata.version(name) != expected:
            raise ValueError(f"installed dependency changed since inspection: {name}")
    stage = _materialize(context, report.plan)
    template = _binding(context, report.plan)
    version = build_version(context.root, request)
    binding = {**template, "release_id": version.release_id, "release_hash": version.release_hash}
    (stage / "runtime_binding.json").write_bytes(_bytes(binding))
    runtime = StrategyRuntime()
    actual = runtime.describe(
        StrategyRelease.from_mapping(version.to_dict()),
        source_root=stage / "src/strategy_runtime",
        runtime_binding=RuntimeBinding.from_dict(binding),
    )
    candidate = runtime.describe(load_candidate(context, report.plan.origin.candidate))
    require_same_runtime_content(runtime_readiness(candidate), runtime_readiness(actual))
    manifest = {
        "schema_version": 1,
        "strategy_version_id": version.release_id,
        "strategy_version_hash": version.release_hash,
        "source_candidate_id": f"{version.strategy_id}-{version.source_candidate}",
        "candidate_package_hash": report.plan.sha256,
        "runtime_root": "src/strategy_runtime",
        "runtime_binding": "runtime_binding.json",
        "files": {
            p.relative_to(stage).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in stage.rglob("*")
            if p.is_file()
        },
    }
    manifest["package_hash"] = canonical_sha256(manifest)
    (stage / "release_manifest.json").write_bytes(_bytes(manifest))
    journal_root = _journal_root(context, request.request_id)
    operation_path = journal_root / request.request_id.value / "research_request.json"
    lock = RegistryWriteLock(context.root / ".tmp/freeze-locks" / request.request_id.strategy_id)
    with lock.hold():
        if operation_path.exists():
            if f.FreezeCandidateRequest.from_dict(_read(operation_path)) != request:
                raise ValueError("freeze request ID already binds different content")
        else:
            _durable(operation_path, request.to_dict(), temporary_root=context.root / ".tmp/freeze")
        return registry.freeze_version(FreezeVersionRequest(
            request.request_id, request.sha256, version,
            StrategyRegistry(context.research_registry_root).get_family(version.strategy_id),
            stage, manifest["package_hash"], journal_root,
        ))


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
