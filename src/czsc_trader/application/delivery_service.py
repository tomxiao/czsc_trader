"""Publish research conclusions and selected evidence without execution history."""

from dataclasses import fields, is_dataclass, replace
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil

from factor_signal_catalog import FactorDefinition, SignalDefinition
from strategy_evaluator import AssessmentEvidence, AssessmentPanel, assess_candidates, compare_candidates, ResearchMetric
from strategy_manager.write_lock import RegistryWriteLock
from strategy_manager.errors import RegistryError

from .context import RepositoryContext
from ..research_tools import delivery as d
from ..research_tools.evidence import EvidenceRef
from ..temp_workspace import create_temporary_directory


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
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def _read_evidence(root, reference):
    data = _resolve(root, reference.path).read_bytes()
    if sha256(data).hexdigest() != reference.sha256:
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


def _account_evidence(root, ref):
    from ..research_tools.evaluation import validate_evaluation_evidence

    if (ref.schema, ref.schema_version) != ("account_evaluation", 6):
        _fail("EVALUATION_REFERENCE", ref.path, "published account evaluation schema 6 required")
    _read_evidence(root, ref)
    value = _read_json(_resolve(root, ref.path))
    validate_evaluation_evidence(value)
    request = value["request_identity"]
    if (request["experiment_id"] != ref.experiment.experiment_id
        or not request["strategy_reference"].startswith(ref.experiment.strategy_id + "-")):
        _fail("EVALUATION_REFERENCE", ref.path, "evaluation origin differs from its evidence owner")
    return tuple(AssessmentEvidence.from_dict(item) for item in value["assessment_evidence"])


def _check_evaluation(root, ref, candidate):
    records = _account_evidence(root, ref.evidence)
    key = candidate.key
    if any((item.candidate.candidate_id, item.candidate.content_sha256) != (
        f"{key.strategy_id}-{key.candidate_id}", candidate.content_sha256,
    ) for item in records):
        _fail("CANDIDATE_CONFLICT", key.candidate_id, "evaluation candidate identity differs")
    if not set(ref.evaluation_ids).issubset({x.evaluation_id for x in records}):
        _fail("EVALUATION_REFERENCE", ref.evidence.path, "evaluation ID absent from saved result")


def _validate_content(definition, content, root, context, scope=d.DeliveryValidationScope.FULL):
    expected = {
        d.DeliveryStage.MANDATE: d.ResearchMandate,
        d.DeliveryStage.COMPONENTS: d.ComponentPanel,
        d.DeliveryStage.CANDIDATES: d.CandidateSet,
        d.DeliveryStage.ASSESSMENT: d.CandidateAssessmentDelivery,
        d.DeliveryStage.INSPECTION: d.CandidateInspectionDelivery,
    }
    if type(content.payload) is not expected[definition.stage]:
        _fail("STAGE_CONTENT", "content.payload", "stage and content type differ")
    for value in _walk(content):
        if isinstance(value, EvidenceRef):
            if value.experiment.strategy_id != definition.strategy_id:
                _fail("EVIDENCE_OWNER", value.path, "evidence belongs to another batch")
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
    payload = content.payload
    if isinstance(payload, d.CandidateSet):
        for candidate in payload.candidates:
            if not candidate.evaluations:
                _fail("CANDIDATE_EVIDENCE", candidate.identity.key.candidate_id,
                      "candidate requires a published account evaluation")
            for ref in candidate.evaluations:
                _check_evaluation(root, ref, candidate.identity)
    elif isinstance(payload, d.CandidateAssessmentDelivery):
        _validate_assessment_delivery(definition, payload, root, context, content, scope)
    elif isinstance(payload, d.CandidateInspectionDelivery):
        _validate_inspection_delivery(definition, content, root, context)


def _support_references(context, content):
    """Select inspection and decision evidence rather than whole directories."""
    from strategy_manager import ResearchEvidenceRef
    from .research_evidence import read_decision

    if not isinstance(content.payload, d.CandidateInspectionDelivery):
        return ()
    payload = content.payload
    records = [payload.inspection]
    for reference in (payload.inspection.selection, *payload.decisions):
        records.extend((reference, read_decision(context.root, reference)))
    return tuple(dict.fromkeys(x for record in records for x in _walk(record)
                              if isinstance(x, ResearchEvidenceRef)))


def _validate_inspection_delivery(definition, content, root, context):
    from strategy_manager import freeze_contracts as f
    from .research_evidence import read_decision, validate_inspection

    payload = content.payload
    if payload.inspection.owner.strategy_id != definition.strategy_id:
        _fail("INSPECTION_OWNER", "inspection", "inspection and delivery batch differ")
    if payload.source_assessment not in definition.predecessors:
        _fail("INSPECTION_SOURCE", "source_assessment", "assessment predecessor missing")
    report = f.CandidateInspectionReport.from_dict(json.loads(_read_evidence(root, payload.inspection_evidence)))
    if report != payload.inspection or report != validate_inspection(context.root, report.reference):
        _fail("INSPECTION_REPORT", "inspection", "inspection differs from persisted evidence")
    selection = read_decision(context.root, report.selection)
    receipt_path = _public_delivery_path(context, payload.source_assessment) / "receipt.json"
    if (not isinstance(selection.subject, f.CandidateSelectionSubject)
        or selection.subject.delivery.path != receipt_path.relative_to(context.root).as_posix()
        or selection.subject.delivery.sha256 != sha256(receipt_path.read_bytes()).hexdigest()):
        _fail("INSPECTION_SELECTION", "source_assessment", "selection refers to another assessment")
    for ref in payload.decisions:
        record = read_decision(context.root, ref)
        if record.strategy_id != definition.strategy_id:
            _fail("INSPECTION_DECISION", ref.decision_id, "decision family differs")
        if isinstance(record.subject, f.FreezeSubject) and record.subject.inspection != report.reference:
            _fail("INSPECTION_DECISION", ref.decision_id, "freeze decision report differs")
    for ref in _support_references(context, content):
        snapshot = _resolve(root, f"support/{ref.sha256}").read_bytes()
        if sha256(snapshot).hexdigest() != ref.sha256 or snapshot != ref.resolve(context.root).read_bytes():
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


def _validate_assessment_delivery(definition, payload, root, context, content, scope):
    for ref in (payload.source_candidates, payload.source_mandate):
        if ref not in definition.predecessors:
            _fail("ASSESSMENT_SOURCE", "predecessors", "assessment sources must be predecessors")

    def source(ref):
        document = _read_json(_resolve(_delivery_path(context, ref), "delivery.json"))
        if document.get("schema_version") != 7:
            _fail("ASSESSMENT_SOURCE", ref.stage.value, "assessment requires schema 7 handoffs")
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
    if any(x.metric in (ResearchMetric.FREQUENCY_MEDIAN, ResearchMetric.FREQUENCY_Q10,
                       ResearchMetric.FULL_SAMPLE_FREQUENCY) for x in targets.values()):
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
        if (reference.schema, reference.schema_version) == ("account_evaluation", 6):
            account = _read_json(_resolve(root, reference.path))
            saved_requests[account["request_hash"]] = account["request_identity"]
            saved_policies[account["request_hash"]] = tuple(x["signal_support"]["execution_policy"]
                                                          for x in account["runs"])
            for evidence in _account_evidence(root, reference):
                saved[evidence.evaluation_id] = evidence
    predecessor_root = _delivery_path(context, payload.source_candidates)
    for candidate in candidates.candidates:
        for reference in candidate.evaluations:
            account = _read_json(_resolve(predecessor_root, reference.evidence.path))
            saved_requests[account["request_hash"]] = account["request_identity"]
            saved_policies[account["request_hash"]] = tuple(x["signal_support"]["execution_policy"]
                                                          for x in account["runs"])
            for evidence in _account_evidence(predecessor_root, reference.evidence):
                previous = saved.setdefault(evidence.evaluation_id, evidence)
                if previous != evidence:
                    _fail("ASSESSMENT_EVIDENCE", evidence.evaluation_id, "conflicting saved account facts")
    for evidence in payload.assessment_request.evidence:
        if saved.get(evidence.evaluation_id) != evidence:
            _fail("ASSESSMENT_EVIDENCE", evidence.evaluation_id, "assessment differs from saved evaluation facts")
    _validate_parameter_plans(payload, root, saved_requests, saved_policies)
    if scope is d.DeliveryValidationScope.INTEGRITY:
        return
    if not _assessment_recomputation_matches(assess_candidates(payload.assessment_request), payload.assessment):
        _fail("ASSESSMENT_RESULT", "assessment", "assessment differs from numeric recomputation")
    if compare_candidates(payload.comparison_request) != payload.comparison:
        _fail("COMPARISON_RESULT", "comparison", "comparison differs from numeric recomputation")


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
            result.append(d.PublicationFile(relative, sha256(path.read_bytes()).hexdigest()))
    d._unique((x.path.casefold() for x in result), "manifest path")
    return tuple(result)


def _validate_public_copy(context, reference, root):
    public = _public_delivery_path(context, reference)
    if not public.is_dir() or {item.name for item in public.iterdir()} != {"report.md", "receipt.json"}:
        _fail("PUBLIC_DELIVERY", "delivery", "public delivery must contain its report and receipt")
    for name in ("report.md", "receipt.json"):
        if _resolve(public, name).read_bytes() != _resolve(root, name).read_bytes():
            _fail("PUBLIC_DELIVERY", name, "public delivery differs from the complete package")


def _read_delivery(context, reference, root, visited, scope=d.DeliveryValidationScope.INTEGRITY,
                   *, published=True):
    identity = (reference.batch, reference.stage, reference.revision)
    if identity in visited:
        _fail("DELIVERY_CYCLE", "predecessors", "cyclic delivery references")
    visited = visited | {identity}
    document = _read_json(_resolve(root, "delivery.json"))
    if (type(document) is not dict or set(document) != {"schema_version", "definition", "content"}
        or type(document["schema_version"]) is not int or document["schema_version"] != 7):
        _fail("DELIVERY_SCHEMA", "delivery.json", "unsupported delivery schema")
    receipt = d.DeliveryReceipt.from_dict(_read_json(_resolve(root, "receipt.json")))
    if receipt.reference != reference or d._digest(receipt.files) != reference.content_sha256:
        _fail("DELIVERY_IDENTITY", "receipt", "receipt differs from retained reference")
    if _manifest(root) != receipt.files:
        _fail("DELIVERY_FILES", "receipt.files", "published file manifest differs")
    definition = d.DeliveryDefinition.from_dict(document["definition"])
    content = d.DeliveryContent.from_dict(document["content"])
    if (definition.batch, definition.stage, definition.revision) != identity:
        _fail("DELIVERY_IDENTITY", "definition", "definition differs from reference")
    for predecessor in definition.predecessors:
        _read_delivery(context, predecessor, _delivery_path(context, predecessor), visited)
    _validate_content(definition, content, root, context, scope)
    if _resolve(root, "report.md").read_bytes() != content.report.encode("utf-8"):
        _fail("REPORT_CONTENT", "report.md", "report differs from the submitted research report")
    if published:
        _validate_public_copy(context, reference, root)
    return receipt


def validate_delivery(context: RepositoryContext, reference: d.DeliveryReference, *,
                      scope: d.DeliveryValidationScope = d.DeliveryValidationScope.FULL) -> d.DeliveryValidation:
    """Check evidence; FULL also recomputes SE without replaying research accounts."""
    if type(scope) is not d.DeliveryValidationScope:
        raise TypeError("scope requires DeliveryValidationScope")
    if type(context) is not RepositoryContext or type(reference) is not d.DeliveryReference:
        raise TypeError("validate_delivery requires RepositoryContext and DeliveryReference")
    try:
        _read_delivery(context, reference, _delivery_path(context, reference), set(), scope)
        return d.DeliveryValidation(d.ValidationStatus.PASS, scope)
    except d.DeliveryValidationError as exc:
        return d.DeliveryValidation(d.ValidationStatus.FAIL, scope, exc.issues)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return d.DeliveryValidation(d.ValidationStatus.FAIL, scope,
            (d.DeliveryIssue("INVALID_DELIVERY", "delivery", str(exc)),))


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
                      content: d.DeliveryContent) -> d.DeliveryReceipt:
    """Publish one immutable revision containing selected result evidence."""
    if (type(context) is not RepositoryContext or type(definition) is not d.DeliveryDefinition
        or type(content) is not d.DeliveryContent):
        raise TypeError("assembly requires RepositoryContext, DeliveryDefinition and DeliveryContent")
    lock = _resolve(context.root, f".tmp/delivery-publication/{definition.strategy_id}")
    try:
        with RegistryWriteLock(lock).hold():
            return _assemble_delivery(context, definition, content)
    except (RegistryError, OSError) as exc:
        raise d.DeliveryValidationError((d.DeliveryIssue("ASSEMBLY_FAILED", "delivery", str(exc)),)) from exc


def _assemble_delivery(context, definition, content):
    staging = public_staging = None
    installed_package = installed_public = completed = False
    destination = public_destination = None
    try:
        definition = d.DeliveryDefinition.from_dict(definition.to_dict())
        content = d.DeliveryContent.from_dict(content.to_dict())
        document = {"schema_version": 7, "definition": definition.to_dict(), "content": content.to_dict()}
        destination = _delivery_path(context, definition)
        public_destination = _public_delivery_path(context, definition)
        if destination.exists() or public_destination.exists():
            if not destination.is_dir() or not public_destination.is_dir():
                _fail("PARTIAL_PUBLICATION", "delivery", "delivery publication is incomplete")
            if _read_json(_resolve(destination, "delivery.json")) != document:
                raise d.DeliveryConflictError("delivery revision contains different content")
            receipt = d.DeliveryReceipt.from_dict(_read_json(_resolve(destination, "receipt.json")))
            return _read_delivery(context, receipt.reference, destination, set())
        _validate_handoff(context, content)
        for predecessor in definition.predecessors:
            _read_delivery(context, predecessor, _delivery_path(context, predecessor), set())
        _resolve(context.root, ".tmp/delivery")
        staging = create_temporary_directory(context.root, "delivery")

        def copy(data, relative, expected):
            if sha256(data).hexdigest() != expected:
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
            copy(reference.resolve(context.root).read_bytes(), reference.path, reference.sha256)
        if isinstance(content.payload, d.CandidateAssessmentDelivery):
            from ..research_tools.parameter_evaluation import read_parameter_plan

            for reference in content.payload.parameter_plans:
                plan = read_parameter_plan(reference, context.root)
                for material in (plan.mapping_evidence, plan.feasibility_evidence):
                    copy(material.resolve(context.root).read_bytes(), material.path, material.sha256)
        for reference in _support_references(context, content):
            copy(reference.resolve(context.root).read_bytes(), f"support/{reference.sha256}", reference.sha256)
        _validate_content(definition, content, staging, context)
        (staging / "delivery.json").write_bytes(d._canonical(document))
        (staging / "report.md").write_bytes(content.report.encode("utf-8"))
        files = _manifest(staging)
        reference = d.DeliveryReference(definition.batch, definition.stage, definition.revision, d._digest(files))
        receipt = d.DeliveryReceipt(reference, files)
        (staging / "receipt.json").write_bytes(d._canonical(receipt))
        _read_delivery(context, reference, staging, set(), published=False)
        public_staging = create_temporary_directory(context.root, "delivery-public")
        for name in ("report.md", "receipt.json"):
            shutil.copyfile(staging / name, public_staging / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        public_destination.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(destination)
        installed_package = True
        staging = None
        public_staging.rename(public_destination)
        installed_public = True
        public_staging = None
        _validate_public_copy(context, reference, destination)
        completed = True
        return receipt
    except (d.DeliveryValidationError, d.DeliveryConflictError):
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
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
