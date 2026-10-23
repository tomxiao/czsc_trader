"""Publish research conclusions and selected evidence without execution history."""

from dataclasses import fields, is_dataclass, replace
from contextvars import ContextVar
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
from hashlib import sha256
import json
import math
from pathlib import Path
from multiprocessing import get_context
import shutil
from time import perf_counter
from typing import Callable
from threadpoolctl import threadpool_limits
from strategy_runtime.resources import ExecutionResources

from factor_signal_catalog import FactorDefinition, SignalDefinition
from strategy_evaluator import AssessmentEvidence, AssessmentPanel, assess_candidates, compare_candidates
from strategy_evaluator.research_models import is_frequency_target
from strategy_manager.write_lock import RegistryWriteLock
from strategy_manager.errors import RegistryError, StrategyManagerError

from .context import RepositoryContext
from ..research_tools import delivery as d
from ..research_tools.evidence import EvidenceRef
from ..temp_workspace import create_temporary_directory


class _ValidationSession:
    """Only this invocation owns reuse; files are authenticated on every visit."""

    def __init__(self, resources=None, on_progress=None):
        self.resources = resources if resources is not None else ExecutionResources()
        if type(self.resources) is not ExecutionResources:
            raise TypeError("delivery validation requires ExecutionResources")
        if on_progress is not None and not callable(on_progress):
            raise TypeError("on_progress must be callable")
        self.on_progress = on_progress
        self.started = perf_counter()
        self.completed = set()
        self.nodes = {}
        self.identities = set()
        self.account_cache = {}
        self.reference_visits = self.recursive_expansions = self.semantic_reuses = 0
        self.files_hashed = self.bytes_hashed = 0
        self.authentication_seconds = self.recomputation_seconds = self.final_recheck_seconds = 0.0
        self.accounts_authenticated = self.account_reuses = 0
        self.file_read_task_seconds = self.file_hash_task_seconds = 0.0
        self.package_load_seconds = 0.0
        self.executor = None

    def progress(self, phase, completed, total):
        if self.on_progress is not None:
            self.on_progress(d.DeliveryValidationProgress(
                phase, completed, total, float(perf_counter() - self.started)))

    def close(self):
        if self.executor is not None:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.executor = None

    def stats(self):
        return d.DeliveryValidationStats(
            len(self.identities), self.reference_visits, self.recursive_expansions,
            self.semantic_reuses, self.files_hashed, self.bytes_hashed,
            float(perf_counter() - self.started),
            self.authentication_seconds, self.recomputation_seconds, self.final_recheck_seconds,
            self.accounts_authenticated, self.account_reuses,
            self.file_read_task_seconds, self.file_hash_task_seconds,
            self.package_load_seconds,
        )

    def recheck(self, context):
        started = perf_counter()
        self.progress(d.DeliveryValidationPhase.FINAL_RECHECK, 0, len(self.nodes))
        try:
            for index, (root, reference, receipt, published) in enumerate(self.nodes.values(), 1):
                if d.DeliveryReceipt.from_dict(_read_json(_resolve(root, "receipt.json"))) != receipt:
                    _fail("SOURCE_CHANGED", "receipt.json", "delivery receipt changed during validation")
                if _manifest(root) != receipt.files:
                    _fail("SOURCE_CHANGED", "receipt.files", "delivery files changed during validation")
                if published:
                    _validate_public_copy(context, reference, root)
                self.progress(d.DeliveryValidationPhase.FINAL_RECHECK, index, len(self.nodes))
        finally:
            self.final_recheck_seconds += perf_counter() - started

    def preload_accounts(self, root, references):
        missing = {ref.sha256: ref for ref in references
                   if (ref.schema, ref.schema_version) == ("account_evaluation", 7)
                   and ref.sha256 not in self.account_cache}
        workers = min(self.resources.max_workers, len(missing))
        if workers < 2:
            return
        if self.executor is None:
            self.executor = ProcessPoolExecutor(max_workers=self.resources.max_workers,
                                                mp_context=get_context("spawn"))
        iterator = iter(missing.values())
        pending = {}
        started = perf_counter()
        completed = 0
        self.progress(d.DeliveryValidationPhase.AUTHENTICATION, 0, len(missing))
        try:
            def submit():
                reference = next(iterator, None)
                if reference is not None:
                    future = self.executor.submit(_authenticate_account, root, reference,
                                                  self.resources.native_threads_per_worker)
                    pending[future] = reference
            for _ in range(workers):
                submit()
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    reference = pending.pop(future)
                    projection, size, issues, read_seconds, hash_seconds = future.result()
                    self.file_read_task_seconds += read_seconds
                    self.file_hash_task_seconds += hash_seconds
                    if issues:
                        raise d.DeliveryValidationError(issues)
                    self.account_cache[reference.sha256] = projection
                    self.files_hashed += 1
                    self.bytes_hashed += size
                    self.accounts_authenticated += 1
                    completed += 1
                    self.progress(d.DeliveryValidationPhase.AUTHENTICATION, completed, len(missing))
                    submit()
        finally:
            for future in pending:
                future.cancel()
            self.authentication_seconds += perf_counter() - started


_validation_session = ContextVar("delivery_validation_session", default=None)


@contextmanager
def _package_loading(session):
    """Exclusive envelope/manifest/decode wall time, including rejected loads."""
    started = perf_counter()
    if session is not None:
        session.progress(d.DeliveryValidationPhase.PACKAGE_LOAD, 0, 1)
    try:
        yield
        if session is not None:
            session.progress(d.DeliveryValidationPhase.PACKAGE_LOAD, 1, 1)
    finally:
        if session is not None:
            session.package_load_seconds += perf_counter() - started


def _file_hash(data):
    started = perf_counter()
    digest = sha256(data).hexdigest()
    session = _validation_session.get()
    if session is not None:
        session.files_hashed += 1
        session.bytes_hashed += len(data)
        session.file_hash_task_seconds += perf_counter() - started
    return digest


def _read_bytes(path):
    started = perf_counter()
    try:
        return path.read_bytes()
    finally:
        session = _validation_session.get()
        if session is not None:
            session.file_read_task_seconds += perf_counter() - started


def _fail(code, path, message):
    raise d.DeliveryValidationError((d.DeliveryIssue(code, path, message),))


def _resolve(root: Path, relative: str) -> Path:
    d._path(relative)
    root = root.resolve()
    target = root.joinpath(*relative.split("/"))
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink() or parent.is_junction():
            _fail("UNSAFE_PATH", relative, "evidence path contains a link")
    if not target.resolve().is_relative_to(root):
        _fail("UNSAFE_PATH", relative, "path escapes evidence root")
    return target


def _delivery_path(context: RepositoryContext, reference) -> Path:
    return _resolve(context.root,
        f"research/{reference.strategy_id}/assets/deliveries/{reference.stage.value}/{reference.revision}")


def _public_delivery_path(context: RepositoryContext, reference) -> Path:
    return _resolve(context.root,
        f"research/{reference.strategy_id}/deliveries/{reference.stage.value}/{reference.revision}")


def _read_json(path: Path):
    return _decode_json(_read_bytes(path).decode("utf-8"))


def _decode_json(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs)


def _read_evidence(root, reference):
    data = _read_bytes(_resolve(root, reference.path))
    if _file_hash(data) != reference.sha256:
        _fail("EVIDENCE_HASH", reference.path, "evidence hash differs")
    return data


def _walk(value):
    yield value
    if is_dataclass(value):
        for field in fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _walk(item)


def _references(content):
    return tuple(dict.fromkeys(x for x in _walk(content) if isinstance(x, EvidenceRef)))


def _account_evidence(root, ref, account_cache=None):
    return _account_document(root, ref, account_cache)[1]


def _certify_account(data, reference):
    from ..research_tools.evaluation import validate_evaluation_evidence

    try:
        value = _decode_json(data.decode("utf-8"))
        validate_evaluation_evidence(value)
        records = tuple(AssessmentEvidence.from_dict(item) for item in value["assessment_evidence"])
        # Retain only fields needed for later identity/plan checks. Raw JSON and
        # account ledgers are deliberately released after full certification.
        projection = {"request_hash": value["request_hash"], "request_identity": value["request_identity"],
                      "execution_policies": tuple(run["signal_support"]["execution_policy"]
                                                  for run in value["runs"])}
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError,
            StopIteration, RecursionError, StrategyManagerError) as exc:
        _fail("ACCOUNT_AUTHENTICATION", reference.path, str(exc) or type(exc).__name__)
    return projection, records


def _authenticate_account(root, reference, native_threads):
    """Return compact facts or typed issues; propagate infrastructure failures."""
    read_seconds = hash_seconds = 0.0
    try:
        with threadpool_limits(limits=native_threads):
            path = _resolve(root, reference.path)
            started = perf_counter()
            data = path.read_bytes()
            read_seconds = perf_counter() - started
            started = perf_counter()
            digest = sha256(data).hexdigest()
            hash_seconds = perf_counter() - started
            if digest != reference.sha256:
                _fail("EVIDENCE_HASH", reference.path, "evidence hash differs")
            return _certify_account(data, reference), len(data), (), read_seconds, hash_seconds
    except d.DeliveryValidationError as exc:
        return None, 0, exc.issues, read_seconds, hash_seconds


def _account_document(root, ref, account_cache=None):
    if (ref.schema, ref.schema_version) != ("account_evaluation", 7):
        _fail("EVALUATION_REFERENCE", ref.path, "published account evaluation schema 7 required")
    # Always authenticate the current file. Only immutable, identical bytes may
    # reuse account decoding/certification within this publication or validation.
    data = _read_evidence(root, ref)
    session = _validation_session.get()
    cached = None if account_cache is None else account_cache.get(ref.sha256)
    if cached is None:
        started = perf_counter()
        if session is not None:
            session.progress(d.DeliveryValidationPhase.AUTHENTICATION, 0, 1)
        try:
            with threadpool_limits(limits=1 if session is None else session.resources.native_threads_per_worker):
                value, records = _certify_account(data, ref)
        finally:
            if session is not None:
                session.authentication_seconds += perf_counter() - started
        if session is not None:
            session.accounts_authenticated += 1
            session.progress(d.DeliveryValidationPhase.AUTHENTICATION, 1, 1)
    else:
        value, records = cached
        if session is not None:
            session.account_reuses += 1
    request = value["request_identity"]
    if (request["experiment_id"] != ref.experiment.experiment_id
        or not request["strategy_reference"].startswith(ref.experiment.strategy_id + "-")):
        _fail("EVALUATION_REFERENCE", ref.path, "evaluation origin differs from its evidence owner")
    if account_cache is not None and cached is None:
        account_cache[ref.sha256] = (value, records)
    return value, records


def _check_evaluation(root, ref, candidate, account_cache=None):
    records = _account_evidence(root, ref.evidence, account_cache)
    key = candidate.key
    if any((item.candidate.candidate_id, item.candidate.content_sha256) != (
        f"{key.strategy_id}-{key.candidate_id}", candidate.content_sha256,
    ) for item in records):
        _fail("CANDIDATE_CONFLICT", key.candidate_id, "evaluation candidate identity differs")
    if not set(ref.evaluation_ids).issubset({x.evaluation_id for x in records}):
        _fail("EVALUATION_REFERENCE", ref.evidence.path, "evaluation ID absent from saved result")


def _validate_content(definition, content, root, context, scope=d.DeliveryValidationScope.FULL,
                      *, account_cache=None):
    if account_cache is None:
        account_cache = {}
    expected = {
        d.DeliveryStage.MANDATE: d.ResearchMandate,
        d.DeliveryStage.COMPONENTS: d.ComponentPanel,
        d.DeliveryStage.PROTOTYPES: d.PrototypePanel,
        d.DeliveryStage.CANDIDATES: d.CandidateSet,
        d.DeliveryStage.ASSESSMENT: d.CandidateAssessmentDelivery,
        d.DeliveryStage.INSPECTION: d.CandidateInspectionDelivery,
    }
    if type(content.payload) is not expected[definition.stage]:
        _fail("STAGE_CONTENT", "content.payload", "stage and content type differ")
    references = _references(content)
    for reference in references:
        if reference.experiment.strategy_id != definition.strategy_id:
            _fail("EVIDENCE_OWNER", reference.path, "evidence belongs to another batch")
        if reference.schema == "account_evaluation" and reference.schema_version != 7:
            _fail("EVALUATION_REFERENCE", reference.path, "published account evaluation schema 7 required")
    session = _validation_session.get()
    if session is not None:
        session.preload_accounts(root, references)
    for value in _walk(content):
        if isinstance(value, EvidenceRef):
            if value.schema == "account_evaluation":
                _account_document(root, value, account_cache)
            else:
                _read_evidence(root, value)
        elif isinstance(value, d.CatalogDefinitionRef):
            cls = FactorDefinition if value.kind is d.CatalogDefinitionKind.FACTOR else SignalDefinition
            catalog = cls.from_dict(_read_json(_resolve(root, value.evidence.path)))
            identifier = catalog.factor_id if isinstance(catalog, FactorDefinition) else catalog.signal_id
            if (identifier, catalog.version, catalog.definition_sha256) != (
                value.catalog_id, value.version, value.definition_sha256,
            ):
                _fail("COMPONENT_DEFINITION", value.catalog_id, "selected definition identity differs")
        elif isinstance(value, d.CandidateIdentityRef):
            if value.key.strategy_id != definition.strategy_id:
                _fail("CANDIDATE_FAMILY", value.key.candidate_id, "candidate family differs")
        elif isinstance(value, d.PrototypeReference):
            if value.delivery not in definition.predecessors:
                _fail("PROTOTYPE_REFERENCE", value.prototype_id,
                      "prototype source must be an exact declared predecessor")
            # Predecessors have already been authenticated by _read_delivery.
            document = _read_json(_resolve(_delivery_path(context, value.delivery), "delivery.json"))
            previous = d.DeliveryContent.from_dict(document["content"]).payload
            if not isinstance(previous, d.PrototypePanel) or value.prototype_id not in {
                item.prototype_id for item in previous.prototypes
            }:
                _fail("PROTOTYPE_REFERENCE", value.prototype_id, "prototype absent from source delivery")
    payload = content.payload
    if isinstance(payload, d.PrototypePanel):
        for prototype in payload.prototypes:
            for ref in prototype.evaluations:
                _check_evaluation(root, ref, prototype.identity, account_cache)
    elif isinstance(payload, d.CandidateSet):
        for candidate in payload.candidates:
            if not candidate.evaluations:
                _fail("CANDIDATE_EVIDENCE", candidate.identity.key.candidate_id,
                      "candidate requires a published account evaluation")
            for ref in candidate.evaluations:
                _check_evaluation(root, ref, candidate.identity, account_cache)
    elif isinstance(payload, d.CandidateAssessmentDelivery):
        _validate_assessment_delivery(definition, payload, root, context, content, scope, account_cache)
    elif isinstance(payload, d.CandidateInspectionDelivery):
        _validate_inspection_delivery(definition, content, root, context)


def _support_references(context, content):
    """Follow technical roles only; registration provenance is not a dependency."""
    if not isinstance(content.payload, d.CandidateInspectionDelivery):
        return ()
    from .research_evidence import (
        read_decision, validate_inspection, inspection_evidence_references,
    )
    payload = content.payload
    report = validate_inspection(context.root, payload.inspection)
    references = [payload.inspection, *inspection_evidence_references(context.root, report)]
    for reference in (report.selection, *payload.decisions):
        decision = read_decision(context.root, reference)
        references.extend((reference.evidence, decision.confirmation_source))
    return tuple(dict.fromkeys(references))


def _validate_inspection_delivery(definition, content, root, context):
    from strategy_manager import freeze_contracts as f
    from .research_evidence import read_decision, validate_inspection

    payload = content.payload
    if payload.inspection.owner.strategy_id != definition.strategy_id:
        _fail("INSPECTION_OWNER", "inspection", "inspection and delivery batch differ")
    report_bytes = _read_bytes(_resolve(root, f"support/{payload.inspection.sha256}"))
    if _file_hash(report_bytes) != payload.inspection.sha256:
        _fail("INSPECTION_REPORT", "inspection", "report snapshot hash differs")
    report = f.CandidateInspectionReport.from_dict(_decode_json(report_bytes.decode("utf-8")))
    if report.reference != payload.inspection or report != validate_inspection(context.root, payload.inspection):
        _fail("INSPECTION_REPORT", "inspection", "inspection differs from persisted evidence")
    for ref in payload.decisions:
        record = read_decision(context.root, ref)
        if record.strategy_id != definition.strategy_id:
            _fail("INSPECTION_DECISION", ref.decision_id, "decision family differs")
        if isinstance(record.subject, f.FreezeSubject) and record.subject.inspection != report.reference:
            _fail("INSPECTION_DECISION", ref.decision_id, "freeze decision report differs")
    for ref in _support_references(context, content):
        snapshot = _read_bytes(_resolve(root, f"support/{ref.sha256}"))
        if _file_hash(snapshot) != ref.sha256 or snapshot != _read_bytes(ref.resolve(context.root)):
            _fail("INSPECTION_EVIDENCE", ref.path, "inspection or decision snapshot differs")
    if payload.freeze is not None:
        from .inspection_service import get_freeze_result
        receipt = get_freeze_result(context, payload.freeze.request_id)
        if receipt != payload.freeze:
            _fail("FREEZE_RECEIPT", "freeze", "freeze receipt differs from actual result")
        if receipt.status is f.FreezeStatus.COMMITTED:
            path = (context.research_root / receipt.request_id.strategy_id / "freeze_requests"
                    / receipt.request_id.value / "research_request.json")
            request = f.FreezeCandidateRequest.from_dict(_read_json(path))
            if (request.sha256 != receipt.request_sha256 or request.inspection != report.reference
                or request.approval not in payload.decisions):
                _fail("FREEZE_RECEIPT", "freeze", "freeze request report/approval differs")


def _assessment_recomputation_matches(recomputed: AssessmentPanel, published: AssessmentPanel) -> bool:
    if replace(recomputed, family_diagnostics=published.family_diagnostics) != published:
        return False
    if len(recomputed.family_diagnostics) != len(published.family_diagnostics):
        return False
    for actual, expected in zip(recomputed.family_diagnostics, published.family_diagnostics):
        if actual == expected:
            continue
        if (actual.name != "DSR_EFFECTIVE" or (actual.name, actual.status, actual.reason)
            != (expected.name, expected.status, expected.reason) or actual.value is None
            or expected.value is None or not 0.0 <= actual.value <= 1.0
            or not 0.0 <= expected.value <= 1.0
            or not math.isclose(actual.value, expected.value, rel_tol=1e-12, abs_tol=0.0)):
            return False
    return True


def _validate_assessment_delivery(definition, payload, root, context, content, scope, account_cache):
    for ref in (payload.source_candidates, payload.source_mandate):
        if ref not in definition.predecessors:
            _fail("ASSESSMENT_SOURCE", "predecessors", "assessment sources must be predecessors")

    def source(ref):
        document = _read_json(_resolve(_delivery_path(context, ref), "delivery.json"))
        if document.get("schema_version") != 8:
            _fail("ASSESSMENT_SOURCE", ref.stage.value, "assessment requires schema 8 handoffs")
        return d.DeliveryContent.from_dict(document["content"]).payload

    candidates = source(payload.source_candidates)
    mandate = source(payload.source_mandate)
    expected = {f"{key.strategy_id}-{key.candidate_id}": next(
        x.identity.content_sha256 for x in candidates.candidates if x.identity.key == key)
        for key in candidates.handoff}
    actual = {x.candidate_id: x.content_sha256 for x in payload.assessment_request.centers}
    if expected != actual:
        _fail("ASSESSMENT_SCOPE", "centers", "assessment centers differ from stage-three handoff")
    declarations = {x.item_id: x for x in mandate.items}
    targets = {x.target_id: x for x in payload.comparison_request.targets.requirements}
    if {x.target_id for x in payload.target_bindings} != set(targets):
        _fail("TARGET_BINDING", "target_bindings", "each target needs a confirmed mandate binding")
    expected = {target.target_id: (item.item_id, target)
        for item in mandate.items if isinstance(item.requirement, d.PerformanceRequirement)
        and item.confirmation.status is d.ConfirmationStatus.CONFIRMED
        for target in item.requirement.targets}
    if set(expected) != set(targets):
        _fail("TARGET_BINDING", "target_bindings", "confirmed performance targets must be preserved")
    for binding in payload.target_bindings:
        if expected[binding.target_id] != (binding.mandate_item_id, targets[binding.target_id]):
            _fail("TARGET_BINDING", binding.target_id, "target differs from confirmed mandate")
    if any(is_frequency_target(x) for x in targets.values()):
        item = declarations.get(payload.frequency_window_item_id)
        days = payload.comparison_request.targets.frequency_window_days
        if (item is None or item.confirmation.status is not d.ConfirmationStatus.CONFIRMED
            or not isinstance(item.requirement, d.NumericRequirement)
            or (item.requirement.metric, item.requirement.unit, item.requirement.lower,
                item.requirement.upper) != ("frequency_window_days", "sessions", float(days), float(days))):
            _fail("TARGET_BINDING", "frequency_window", "frequency window requires confirmed exact sessions")
    item = declarations.get(payload.benchmark_mandate_item_id)
    if (item is None or item.confirmation.status is not d.ConfirmationStatus.CONFIRMED
        or not isinstance(item.requirement, d.BenchmarkRequirement)):
        _fail("BENCHMARK_BINDING", "benchmark", "benchmark requires a confirmed typed mandate")
    benchmark = item.requirement.benchmark
    for evidence in payload.assessment_request.evidence:
        if (evidence.scenario_context.benchmark_contract_sha256 != benchmark.fingerprint
            or evidence.scenario_context.benchmark_id != benchmark.benchmark_id
            or evidence.scenario_context.benchmark_kind != benchmark.kind):
            _fail("BENCHMARK_BINDING", evidence.evaluation_id, "benchmark differs from confirmed mandate")
    saved = {}
    saved_requests = {}
    saved_policies = {}
    for reference in _references(content):
        if (reference.schema, reference.schema_version) == ("account_evaluation", 7):
            account, records = _account_document(root, reference, account_cache)
            saved_requests[account["request_hash"]] = account["request_identity"]
            saved_policies[account["request_hash"]] = account["execution_policies"]
            for evidence in records:
                saved[evidence.evaluation_id] = evidence
    predecessor_root = _delivery_path(context, payload.source_candidates)
    for candidate in candidates.candidates:
        for reference in candidate.evaluations:
            account, records = _account_document(predecessor_root, reference.evidence, account_cache)
            saved_requests[account["request_hash"]] = account["request_identity"]
            saved_policies[account["request_hash"]] = account["execution_policies"]
            for evidence in records:
                previous = saved.setdefault(evidence.evaluation_id, evidence)
                if previous != evidence:
                    _fail("ASSESSMENT_EVIDENCE", evidence.evaluation_id, "conflicting saved account facts")
    for evidence in payload.assessment_request.evidence:
        if saved.get(evidence.evaluation_id) != evidence:
            _fail("ASSESSMENT_EVIDENCE", evidence.evaluation_id, "assessment differs from saved evaluation facts")
    _validate_parameter_plans(payload, root, saved_requests, saved_policies)
    if scope is d.DeliveryValidationScope.INTEGRITY:
        return
    session = _validation_session.get()
    started = perf_counter()
    if session is not None:
        session.progress(d.DeliveryValidationPhase.RECOMPUTATION, 0, 2)
    try:
        if not _assessment_recomputation_matches(assess_candidates(payload.assessment_request), payload.assessment):
            _fail("ASSESSMENT_RESULT", "assessment", "assessment differs from numeric recomputation")
        if session is not None:
            session.progress(d.DeliveryValidationPhase.RECOMPUTATION, 1, 2)
        if compare_candidates(payload.comparison_request) != payload.comparison:
            _fail("COMPARISON_RESULT", "comparison", "comparison differs from numeric recomputation")
        if session is not None:
            session.progress(d.DeliveryValidationPhase.RECOMPUTATION, 2, 2)
    finally:
        if session is not None:
            session.recomputation_seconds += perf_counter() - started


def _validate_parameter_plans(payload, root, saved_requests, saved_policies):
    from ..research_tools.parameter_evaluation import (
        ParameterEvaluationPlan, ParameterEvaluationBinding, validate_parameter_contract,
        parameter_execution_policy,
    )

    plans = {}
    for reference in payload.parameter_plans:
        plan = ParameterEvaluationPlan.from_dict(json.loads(_read_evidence(root, reference)))
        _read_evidence(root, plan.mapping_evidence)
        _read_evidence(root, plan.feasibility_evidence)
        if plan.design.sha256 in plans:
            _fail("PARAMETER_PLAN", reference.path, "duplicate parameter design")
        plans[plan.design.sha256] = (reference, plan)
        central = saved_requests.get(plan.center_request_sha256)
        evidence = tuple(x for x in payload.assessment_request.evidence if x.candidate == plan.design.center
                         and x.window_id == payload.assessment_request.protocol.baseline_window
                         and x.scenario_id == payload.assessment_request.protocol.standard_scenario)
        if (central is None or not evidence or any(x.request_sha256 != plan.center_request_sha256 for x in evidence)
            or central["nonparameter_context_sha256"] != plan.nonparameter_context_sha256
            or central["content_sha256"] != plan.design.center.content_sha256
            or central["strategy_reference"] != plan.design.center.candidate_id):
            _fail("PARAMETER_CENTER", reference.path, "planned center differs from saved center account")
        center_bindings = {x.window_id: json.loads(x.binding_json) for x in plan.center_inputs}
        if central["input_bindings"] != center_bindings:
            _fail("PARAMETER_CENTER", reference.path, "planned center input identities differ")
        policy = json.loads(plan.execution_contract_json)["policy"]
        if any(parameter_execution_policy(x) != policy for x in saved_policies[plan.center_request_sha256]):
            _fail("PARAMETER_CENTER", reference.path, "planned center execution policy differs")
        links = tuple(x for x in payload.assessment_request.perturbations if x.parent == plan.design.center)
        expected = tuple((x.candidate, plan.design.bind_point(index)) for index, x in enumerate(plan.children))
        actual = tuple((x.child, x.parameter_point) for x in links)
        if set(actual) != set(expected) or len(actual) != len(expected):
            _fail("PARAMETER_PLAN", reference.path, "assessment links differ from complete plan")
    if set(plans) != {x.sha256 for x in payload.assessment_request.parameter_designs}:
        _fail("PARAMETER_PLAN", "parameter_plans", "assessment designs differ from published plans")
    for evidence in payload.assessment_request.evidence:
        if evidence.parameter_point is None:
            continue
        reference, plan = plans[evidence.parameter_point.design_sha256]
        contract = saved_requests[evidence.request_sha256]
        binding = ParameterEvaluationBinding.from_dict(contract["parameter_binding"])
        if binding.plan != reference or binding.point != evidence.parameter_point:
            _fail("PARAMETER_PLAN", evidence.evaluation_id, "saved account uses another parameter plan")
        validate_parameter_contract(contract, plan, binding)
        if any(parameter_execution_policy(x) != json.loads(plan.execution_contract_json)["policy"]
               for x in saved_policies[evidence.request_sha256]):
            _fail("PARAMETER_PLAN", evidence.evaluation_id, "saved child execution policy differs")


def _manifest(root) -> tuple[d.PublicationFile, ...]:
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        _resolve(root, relative)
        if path.is_file() and relative != "receipt.json":
            result.append(d.PublicationFile(relative, _file_hash(_read_bytes(path))))
    d._unique((x.path.casefold() for x in result), "manifest path")
    return tuple(result)


def _validate_public_copy(context, reference, root):
    public = _public_delivery_path(context, reference)
    if not public.is_dir() or {item.name for item in public.iterdir()} != {"report.md", "receipt.json"}:
        _fail("PUBLIC_DELIVERY", "delivery", "public delivery must contain its report and receipt")
    for name in ("report.md", "receipt.json"):
        if _read_bytes(_resolve(public, name)) != _read_bytes(_resolve(root, name)):
            _fail("PUBLIC_DELIVERY", name, "public delivery differs from the complete package")


def _read_delivery(context, reference, root, visited, scope=d.DeliveryValidationScope.INTEGRITY,
                   *, published=True, account_cache=None):
    session = _validation_session.get()
    if account_cache is None:
        account_cache = {} if session is None else session.account_cache
    identity = (reference.batch, reference.stage, reference.revision)
    if identity in visited:
        _fail("DELIVERY_CYCLE", "predecessors", "cyclic delivery references")
    if session is not None:
        session.reference_visits += 1
        session.identities.add((identity, reference.content_sha256))
    visited = visited | {identity}
    with _package_loading(session):
        document = _read_json(_resolve(root, "delivery.json"))
        if (reference.stage is d.DeliveryStage.INSPECTION and type(document) is dict
            and document.get("schema_version") == 8):
            _fail("UNSUPPORTED_LEGACY_INSPECTION", "delivery.json", "legacy inspection cannot certify the current protocol")
        if (type(document) is not dict or set(document) != {"schema_version", "definition", "content"}
            or type(document["schema_version"]) is not int
            or document["schema_version"] != d._schema_version(reference.stage)):
            _fail("DELIVERY_SCHEMA", "delivery.json", "unsupported delivery schema")
        receipt = d.DeliveryReceipt.from_dict(_read_json(_resolve(root, "receipt.json")))
        if receipt.reference != reference or d._digest(receipt.files) != reference.content_sha256:
            _fail("DELIVERY_IDENTITY", "receipt", "receipt differs from retained reference")
        if _manifest(root) != receipt.files:
            _fail("DELIVERY_FILES", "receipt.files", "published file manifest differs")
        key = (root.resolve(), reference, scope, published)
        if session is not None:
            previous = session.nodes.get(root.resolve())
            observed = (root, reference, receipt, published)
            if previous is not None and previous != observed:
                _fail("SOURCE_CHANGED", "delivery", "delivery identity changed during validation")
            session.nodes[root.resolve()] = observed
            if key in session.completed:
                if published:
                    _validate_public_copy(context, reference, root)
                session.semantic_reuses += 1
                return receipt
            session.recursive_expansions += 1
        definition = d.DeliveryDefinition.from_dict(document["definition"])
        if definition.schema_version != document["schema_version"] or receipt.schema_version != document["schema_version"]:
            _fail("DELIVERY_SCHEMA", "delivery.json", "envelope, definition and receipt schemas differ")
        content = d.DeliveryContent.from_dict(document["content"])
        if (definition.batch, definition.stage, definition.revision) != identity:
            _fail("DELIVERY_IDENTITY", "definition", "definition differs from reference")
    for predecessor in definition.predecessors:
        _read_delivery(context, predecessor, _delivery_path(context, predecessor), visited,
                       account_cache=account_cache)
    _validate_content(definition, content, root, context, scope, account_cache=account_cache)
    if _read_bytes(_resolve(root, "report.md")) != content.report.encode("utf-8"):
        _fail("REPORT_CONTENT", "report.md", "report differs from the submitted research report")
    if published:
        _validate_public_copy(context, reference, root)
    if session is not None:
        session.completed.add(key)
    return receipt


def validate_delivery(context: RepositoryContext, reference: d.DeliveryReference, *,
                      scope: d.DeliveryValidationScope = d.DeliveryValidationScope.FULL,
                      resources: ExecutionResources | None = None,
                      on_progress: Callable[[d.DeliveryValidationProgress], None] | None = None) -> d.DeliveryValidation:
    """Check evidence; FULL also recomputes SE without replaying research accounts."""
    if type(scope) is not d.DeliveryValidationScope:
        raise TypeError("scope requires DeliveryValidationScope")
    if type(context) is not RepositoryContext or type(reference) is not d.DeliveryReference:
        raise TypeError("validate_delivery requires RepositoryContext and DeliveryReference")
    session = _ValidationSession(resources, on_progress)
    token = _validation_session.set(session)
    issues = ()
    try:
        _read_delivery(context, reference, _delivery_path(context, reference), set(), scope)
        session.recheck(context)
    except d.DeliveryValidationError as exc:
        issues = exc.issues
    except (OSError, ValueError, TypeError, KeyError, StrategyManagerError, BrokenProcessPool) as exc:
        issues = (d.DeliveryIssue("INVALID_DELIVERY", "delivery", str(exc)),)
    finally:
        try:
            session.close()
        finally:
            _validation_session.reset(token)
    return d.DeliveryValidation(d.ValidationStatus.FAIL if issues else d.ValidationStatus.PASS,
                                scope, issues, session.stats())


def _validate_handoff(context, content):
    if not isinstance(content.payload, d.CandidateSet):
        return
    from strategy_manager import StrategyRegistry, StrategyManagerError
    from strategy_runtime.errors import StrategyRuntimeError
    from .candidate_service import load_candidate

    identities = {x.identity.key: x.identity for x in content.payload.candidates}
    for key in content.payload.handoff:
        try:
            registration = StrategyRegistry(context.research_registry_root).get_candidate(
                key, evidence_root=context.research_root / key.strategy_id)
            if registration.content_sha256 != identities[key].content_sha256:
                raise ValueError("registered candidate differs from handoff")
            load_candidate(context, key)
        except (OSError, ValueError, TypeError, KeyError, StrategyManagerError, StrategyRuntimeError) as exc:
            _fail("HANDOFF_REGISTRATION", key.candidate_id, str(exc))


def assemble_delivery(context: RepositoryContext, definition: d.DeliveryDefinition,
                      content: d.DeliveryContent, *, resources: ExecutionResources | None = None,
                      on_progress: Callable[[d.DeliveryValidationProgress], None] | None = None) -> d.DeliveryAssemblyResult:
    """Publish one immutable revision containing selected result evidence."""
    if (type(context) is not RepositoryContext or type(definition) is not d.DeliveryDefinition
        or type(content) is not d.DeliveryContent):
        raise TypeError("assembly requires RepositoryContext, DeliveryDefinition and DeliveryContent")
    lock = _resolve(context.root, f".tmp/delivery-publication/{definition.strategy_id}")
    session = _ValidationSession(resources, on_progress)
    token = _validation_session.set(session)
    try:
        with RegistryWriteLock(lock).hold():
            receipt = _assemble_delivery(context, definition, content)
            session.close()
            return d.DeliveryAssemblyResult(receipt, d.DeliveryValidation(
                d.ValidationStatus.PASS, d.DeliveryValidationScope.FULL, stats=session.stats()))
    except (RegistryError, OSError) as exc:
        raise d.DeliveryValidationError((d.DeliveryIssue("ASSEMBLY_FAILED", "delivery", str(exc)),)) from exc
    finally:
        try:
            session.close()
        finally:
            _validation_session.reset(token)


def _assemble_delivery(context, definition, content):
    session = _validation_session.get()
    account_cache = {} if session is None else session.account_cache
    staging = public_staging = None
    installed_package = installed_public = completed = False
    destination = public_destination = None
    try:
        definition = d.DeliveryDefinition.from_dict(definition.to_dict())
        content = d.DeliveryContent.from_dict(content.to_dict())
        document = {"schema_version": definition.schema_version, "definition": definition.to_dict(), "content": content.to_dict()}
        destination = _delivery_path(context, definition)
        public_destination = _public_delivery_path(context, definition)
        if destination.exists() or public_destination.exists():
            if not destination.is_dir() or not public_destination.is_dir():
                _fail("PARTIAL_PUBLICATION", "delivery", "delivery publication is incomplete")
            if _read_json(_resolve(destination, "delivery.json")) != document:
                raise d.DeliveryConflictError("delivery revision contains different content")
            receipt = d.DeliveryReceipt.from_dict(_read_json(_resolve(destination, "receipt.json")))
            checked = _read_delivery(context, receipt.reference, destination, set(),
                                     d.DeliveryValidationScope.FULL, account_cache=account_cache)
            if session is not None:
                session.recheck(context)
            return checked
        _validate_handoff(context, content)
        for predecessor in definition.predecessors:
            _read_delivery(context, predecessor, _delivery_path(context, predecessor), set(),
                           account_cache=account_cache)
        _resolve(context.root, ".tmp/delivery")
        staging = create_temporary_directory(context.root, "delivery")

        def copy(data, relative, expected):
            if _file_hash(data) != expected:
                _fail("EVIDENCE_HASH", relative, "source changed or hash differs")
            target = _resolve(staging, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != data:
                    _fail("EVIDENCE_CONFLICT", relative, "conflicting selected evidence")
            else:
                with target.open("xb") as stream:
                    stream.write(data)

        for reference in _references(content):
            if reference.experiment.strategy_id != definition.strategy_id:
                _fail("EVIDENCE_OWNER", reference.path, "evidence belongs to another batch")
            copy(reference._read_verified(context.root)[1], reference.path, reference.sha256)
        if isinstance(content.payload, d.CandidateAssessmentDelivery):
            from ..research_tools.parameter_evaluation import read_parameter_plan

            for reference in content.payload.parameter_plans:
                plan = read_parameter_plan(reference, context.root)
                for material in (plan.mapping_evidence, plan.feasibility_evidence):
                    copy(material._read_verified(context.root)[1], material.path, material.sha256)
        for reference in _support_references(context, content):
            copy(reference.resolve(context.root).read_bytes(), f"support/{reference.sha256}", reference.sha256)
        (staging / "delivery.json").write_bytes(d._canonical(document))
        (staging / "report.md").write_bytes(content.report.encode("utf-8"))
        files = _manifest(staging)
        reference = d.DeliveryReference(definition.batch, definition.stage, definition.revision, d._digest(files))
        receipt = d.DeliveryReceipt(reference, files, schema_version=definition.schema_version)
        (staging / "receipt.json").write_bytes(d._canonical(receipt))
        _read_delivery(context, reference, staging, set(), d.DeliveryValidationScope.FULL,
                       published=False, account_cache=account_cache)
        if session is not None:
            session.recheck(context)
        public_staging = create_temporary_directory(context.root, "delivery-public")
        for name in ("report.md", "receipt.json"):
            shutil.copyfile(staging / name, public_staging / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        public_destination.parent.mkdir(parents=True, exist_ok=True)
        staged_root = staging.resolve()
        staging.rename(destination)
        installed_package = True
        staging = None
        public_staging.rename(public_destination)
        installed_public = True
        public_staging = None
        _validate_public_copy(context, reference, destination)
        if session is not None:
            session.nodes.pop(staged_root, None)
            session.nodes[destination.resolve()] = (destination, reference, receipt, True)
            session.recheck(context)
        completed = True
        return receipt
    except (d.DeliveryValidationError, d.DeliveryConflictError):
        raise
    except (OSError, ValueError, TypeError, KeyError, StrategyManagerError, BrokenProcessPool) as exc:
        raise d.DeliveryValidationError((d.DeliveryIssue("ASSEMBLY_FAILED", "delivery", str(exc)),)) from exc
    finally:
        if not completed:
            for installed, path in ((installed_public, public_destination), (installed_package, destination)):
                if installed and path is not None and path.exists():
                    safe = _resolve(context.root, path.relative_to(context.root).as_posix())
                    shutil.rmtree(safe)
        for temporary in (staging, public_staging):
            if temporary is not None and temporary.exists():
                temporary_root = (context.root / ".tmp").resolve()
                if temporary.resolve().is_relative_to(temporary_root) and not temporary.is_symlink():
                    shutil.rmtree(temporary)
