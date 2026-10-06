"""Called technical inspection and freeze operations; research owns all scheduling."""

from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
from importlib import metadata
import json
from pathlib import Path

import pandas as pd
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
from strategy_manager import StrategyRegistry, CandidateKey, canonical_sha256
from strategy_manager import freeze_contracts as f
from strategy_manager.freeze_store import FreezeVersionRequest
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
    StrategyInputBinding,
)
from strategy_runtime import StrategyInit, TradableWindow, ExecutionPolicy

from .context import RepositoryContext
from .candidate_service import load_candidate, _registered_root
from .runtime_acceptance import runtime_readiness, require_same_runtime_content
from .delivery_service import validate_delivery, _delivery_path, _resolve
from ..research_tools import delivery as d
from ..research_tools.evaluation import (
    EvaluationRequest, serialize_evaluation_evidence, validate_evaluation_evidence,
)
from ..research_tools.context import ResearchContext, ExperimentRef
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
        prefix = "evidence/inspection" if self.owner.experiment_id else "decisions/objects"
        ref = f.ResearchEvidenceRef(self.owner, f"{prefix}/{digest}", digest)
        target = _resolve(self.context.root, ref.repository_path)
        from .evidence_service import _publish_bytes
        _publish_bytes(self.context.root, target, data)
        ref.resolve(self.context.root)
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
        if plan is None:
            raise ValueError("freeze decision requires an inspected plan")
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
class InspectionReplay:
    reference: d.EvaluationEvidenceRef
    reproduction_request: EvaluationRequest

    def __post_init__(self):
        if (
            type(self.reference) is not d.EvaluationEvidenceRef
            or type(self.reproduction_request) is not EvaluationRequest
        ):
            raise TypeError("inspection replay requires typed evaluation inputs/results")


@dataclass(frozen=True, slots=True)
class CandidateInspectionRequest:
    candidate: CandidateKey
    selection: f.DecisionReference
    protocol: f.InspectionProtocol
    research: ResearchContext
    experiment: ExperimentRef
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
        if type(self.research) is not ResearchContext or type(self.experiment) is not ExperimentRef:
            raise TypeError("inspection requires ResearchContext and ExperimentRef")
        if self.research.batch.strategy_id != self.candidate.strategy_id or self.experiment.strategy_id != self.candidate.strategy_id:
            raise ValueError("inspection research family differs")
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
            if int(self.parent_version[1:]) >= int(self.version[1:]):
                raise ValueError("parent must precede target version")
        if not self.change_summary.strip():
            raise ValueError("inspection change summary is required")
        if date.fromisoformat(self.forward_start) <= date.fromisoformat(self.selection_data_cutoff):
            raise ValueError("forward_start must follow selection cutoff")


def _copy_plan(context, request, registration, store, origin):
    evidence_root = _registered_root(context, registration)

    def copy(ref, root):
        return store.put(ref.resolve(root).read_bytes())

    prefix = f"{registration.source_root}/"
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
        origin,
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
                *registration.origin.evidence,
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


def _authenticate(context, request, result, store):
    value = serialize_evaluation_evidence(request, result)
    projection = tuple(AssessmentEvidence.from_dict(x) for x in value["assessment_evidence"])
    return projection, store.put_json(value)


class _InvalidInspectionReference(ValueError):
    """A declared reference does not identify the requested evaluation."""


def _load_reference(context, reference, store):
    value = _read(reference.evidence.resolve(context.root))
    if reference.evidence.schema != "account_evaluation" or value.get("schema_version") != 5:
        raise ValueError("inspection requires platform account evaluation evidence")
    validate_evaluation_evidence(value)
    if value["request_identity"]["experiment_id"] != reference.evidence.experiment.experiment_id:
        raise _InvalidInspectionReference("reference evaluation origin differs")
    projection = tuple(AssessmentEvidence.from_dict(x) for x in value["assessment_evidence"])
    selected = set(reference.evaluation_ids)
    if selected and not selected.issubset({x.evaluation_id for x in projection}):
        raise _InvalidInspectionReference("reference assessment identity differs")
    source = store.put_json(value)
    if selected:
        projection = tuple(x for x in projection if x.evaluation_id in selected)
        value = {**value, "runs": [x for x in value["runs"]
            if canonical_sha256(x["identity"]) in selected]}
    return value, projection, source


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
    candidate_binding = StrategyInputBinding.from_mapping(run.signals.support_data["input_binding"])
    candidate_prepared = candidate.prepare_data(binding=candidate_binding)
    # The prospective release must reproduce the same admitted inputs. SRT
    # independently re-derives and authenticates this plan for the release.
    frozen_plan = replace(candidate_binding.plan, strategy=frozen.identity)
    frozen_binding = StrategyInputBinding(frozen_plan, candidate_binding.prepared)
    prepared = frozen.prepare_data(binding=frozen_binding)
    left_signals, right_signals = candidate.inspect_signals(), frozen.inspect_signals()
    signal_equal = True
    try:
        pd.testing.assert_frame_equal(
            left_signals, right_signals, check_exact=tolerance == 0, atol=tolerance, rtol=0
        )
    except AssertionError:
        signal_equal = False
    def identities(bound):
        result = {}
        for name, request in bound.plan.requests.items():
            if name == bound.plan.calendar_name:
                result[name] = bound.plan.calendar_sha256
                continue
            data = execution.data.fetch(request, prepared=bound.prepared)
            if not data.ready:
                raise ValueError("inspection input reference cannot be read")
            result[name] = data.identity.content_sha256
        return result
    if (
        candidate_prepared.data_identity != run.signals.data_identity
        or identities(candidate_binding) != identities(frozen_binding)
        or candidate_binding.plan.signal_dates != frozen_plan.signal_dates
        or candidate_binding.plan.calculation_dates != frozen_plan.calculation_dates
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
    frozen.prepare_data(binding=frozen_binding)
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
        input_binding=frozen_binding.to_dict(),
        prepared_data_identity=prepared.data_identity,
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
    return {
        "release_id": release.release_id,
        "release_hash": release.release_hash,
        "candidate_prepared_identity": candidate_prepared.data_identity,
        "release_prepared_identity": prepared.data_identity,
        "input_identities": identities(candidate_binding),
        "candidate_input_binding": candidate_binding.to_dict(),
        "release_input_binding": frozen_binding.to_dict(),
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
    if type(request.research) is not ResearchContext or request.research.repository.root.resolve() != context.root.resolve():
        raise TypeError("inspection requires the local ResearchContext")
    owner = f.ResearchEvidenceOwner(request.candidate.strategy_id, request.experiment.experiment_id)
    experiment_root = context.research_root / owner.strategy_id / "experiments" / owner.experiment_id
    if not experiment_root.is_dir():
        raise ValueError("inspection experiment does not exist")
    store = _EvidenceStore(context, owner)
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
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
    origin = f.CandidateOrigin(registration.key, registration.content_sha256,
                              store.put_json(registration.to_dict()))
    plan = None
    completed_checks = {}

    def failed_preparation(kind, exc):
        error_detail = f"{type(exc).__name__}: {exc}"
        detail = store.put_json({"check": kind.value, "error_type": type(exc).__name__,
                                 "error": str(exc), "candidate": request.candidate.to_dict(),
                                 "registration_sha256": registration.record_sha256,
                                 "requested_plan": {"version": request.version,
                                     "parent_version": request.parent_version,
                                     "change_summary": request.change_summary,
                                     "selection_data_cutoff": request.selection_data_cutoff,
                                     "forward_start": request.forward_start,
                                     "additional_files": [item.to_dict() for item in request.additional_files]}})
        checks = tuple(completed_checks[item] if item in completed_checks and item is not kind
            else f.InspectionCheckResult(
                item, f.InspectionStatus.FAIL if item is kind else f.InspectionStatus.INCOMPLETE,
                (origin.registration, detail), error_detail if item is kind else
                "not started because inspection preparation failed") for item in f.InspectionCheck)
        report = f.CandidateInspectionReport(
            origin, plan, request.selection, request.protocol,
            canonical_sha256({"origin": origin.sha256, "selection": request.selection.sha256,
                              "protocol": request.protocol.sha256, "failure": detail.sha256,
                              "risks": request.remaining_risks}), checks, request.remaining_risks, owner)
        store.put_json(report.to_dict())
        return report

    try:
        for name, version in registration.dependencies:
            if metadata.version(name) != version:
                raise ValueError(f"installed dependency version differs: {name}")
        candidate = load_candidate(context, request.candidate)
    except Exception as exc:
        return failed_preparation(f.InspectionCheck.CONTENT, exc)
    completed_checks[f.InspectionCheck.CONTENT] = f.InspectionCheckResult(
        f.InspectionCheck.CONTENT, f.InspectionStatus.PASS, (origin.registration,),
        "registered candidate source, payload and installed dependencies verified")
    try:
        plan = _copy_plan(context, request, registration, store, origin)
    except Exception as exc:
        return failed_preparation(f.InspectionCheck.PACKAGE, exc)
    evidence = store.put_json(plan.to_dict())
    checks = list(completed_checks.values())

    def check(kind, status, detail, refs=(evidence,)):
        checks.append(f.InspectionCheckResult(kind, status, refs, detail))

    try:
        stage = _materialize(context, plan)
    except Exception as exc:
        return failed_preparation(f.InspectionCheck.PACKAGE, exc)
    try:
        _binding(context, plan)
        check(
            f.InspectionCheck.PACKAGE,
            f.InspectionStatus.PASS,
            "source, observation and install closure verified",
        )
    except Exception as exc:
        check(f.InspectionCheck.PACKAGE, f.InspectionStatus.FAIL, f"{type(exc).__name__}: {exc}")
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
        runtime = request.research.runtime
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
    except Exception as exc:
        check(f.InspectionCheck.RUNTIME, f.InspectionStatus.FAIL, f"{type(exc).__name__}: {exc}")
    covered = []
    comparisons, audits, signals, sources, release_replays = [], [], [], [], []
    errors = []
    unavailable_references = []
    signal_errors = []
    static_ready = all(x.status is f.InspectionStatus.PASS for x in checks)
    for replay in request.replays if static_ready else ():
        new_request = replay.reproduction_request
        if (new_request.strategy.strategy_family_id, new_request.strategy.candidate_id) != (
            request.candidate.strategy_id,
            request.candidate.candidate_id,
        ) or Path(new_request.repository_root).resolve() != context.root.resolve():
            raise ValueError("inspection replay candidate/repository differs")
        try:
            baseline, projection, ref = _load_reference(context, replay.reference, store)
        except _InvalidInspectionReference:
            raise
        except Exception as exc:
            errors.append(f"reference {replay.reference.evidence.path}: {type(exc).__name__}: {exc}")
            unavailable_references.append(replay.reference.to_dict())
            continue
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
            current_request = request.research.evaluation.prepare(current_request)
            current = request.research.evaluation.evaluate(current_request)
            _, current_ref = _authenticate(
                context, current_request, current, store
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
                    request.research,
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
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    detail = store.put_json(
        {
            "coverage": [x.to_dict() for x in covered],
            "audits": audits,
            "comparisons": comparisons,
            "signal_equivalence": signals,
            "signal_errors": signal_errors,
            "errors": errors,
            "unavailable_references": unavailable_references,
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
        origin,
        plan,
        request.selection,
        request.protocol,
        request_hash,
        tuple(checks),
        request.remaining_risks,
        owner,
    )
    store.put_json(report.to_dict())
    return report


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
        report.plan.origin.candidate, evidence_root=context.research_root / report.plan.origin.candidate.strategy_id
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
    prefix = f"{registration.source_root}/"
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
            _write_request(context, operation_path, request.to_dict())
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


def _write_request(context, path, value):
    from .evidence_service import _publish_bytes
    _publish_bytes(context.root, path, _bytes(value))
