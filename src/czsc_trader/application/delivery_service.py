"""Assemble and verify immutable, self-contained stage evidence publications."""

from dataclasses import fields, is_dataclass, replace
from hashlib import sha256
import json
import math
from pathlib import Path

from factor_signal_catalog import FactorDefinition, SignalDefinition
from research_experiment import EvaluationRecord, load_experiment_input
from strategy_evaluator import (
    AssessmentEvidence,
    AssessmentPanel,
    assess_candidates,
    compare_candidates,
    ResearchMetric,
    IncompleteEvaluationStatus,
)

from .context import RepositoryContext
from ..research_tools import delivery as d
from ..temp_workspace import create_temporary_directory


def _fail(code: str, path: str, message: str):
    raise d.DeliveryValidationError((d.DeliveryIssue(code, path, message),))


def _resolve(root: Path, relative: str) -> Path:
    d._path(relative)
    root = root.resolve()
    target = root.joinpath(*relative.split("/"))
    # Reject links even when they currently point inside the boundary. A published
    # tree must retain its bytes independently of subsequent link-target changes.
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink() or parent.is_junction():
            _fail("UNSAFE_PATH", relative, "evidence path contains a link")
    if not target.resolve().is_relative_to(root):
        _fail("UNSAFE_PATH", relative, "path escapes evidence root")
    return target


def _delivery_path(context: RepositoryContext, reference) -> Path:
    if isinstance(reference.owner, d.MandateOwner):
        return _resolve(
            context.root, f"research/{reference.strategy_id}/mandates/{reference.revision}"
        )
    return _resolve(
        context.root,
        f"experiments/{reference.strategy_id}/{reference.owner.experiment_id}/deliveries/{reference.stage.value}/{reference.revision}",
    )


def _validate_owner(context, definition, *, publishing=False):
    if isinstance(definition.owner, d.MandateOwner):
        return
    from research_experiment import ExperimentBinding, experiment_source_sha256
    from ..experiment_archive import validate_experiment_archive

    owner = definition.owner
    root = _resolve(context.root, f"experiments/{owner.strategy_id}/{owner.experiment_id}")
    binding = ExperimentBinding.from_mapping(_read_json(_resolve(root, "experiment_binding.json")))
    for name in binding.source_files:
        _resolve(root, name)
    if experiment_source_sha256(root, binding.source_files) != binding.source_sha256:
        _fail("OWNER_BINDING", "owner", "experiment source differs from binding")
    if owner.experiment_id.startswith("EX"):
        _load_scoped_experiment(context, owner.strategy_id, owner.experiment_id)
    if (root / "experiment_manifest.json").exists():
        if publishing:
            _fail("EXPERIMENT_SEALED", "owner", "cannot publish into a sealed experiment")
        validate_experiment_archive(root)
    return root


def _read_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def _read_evidence(root: Path, reference: d.EvidenceRef) -> bytes:
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


def _load_scoped_experiment(context, strategy_id, experiment_id):
    from research_experiment import load_experiment

    source = _resolve(context.root, f"experiments/{strategy_id}/{experiment_id}")
    loaded = load_experiment(source)
    if (loaded.definition.strategy_id, loaded.definition.experiment_id) != (
        strategy_id, experiment_id
    ):
        _fail("EXPERIMENT_IDENTITY", experiment_id, "experiment definition family or ID differs")
    return loaded


def _load_experiments(definition, root: Path, *, published: bool, context):
    results = {}
    candidates = {}
    for ref in definition.experiments:
        relative = f"experiments/{ref.experiment_id}" if published else ref.workspace_path
        experiment_root = _resolve(root, relative)
        # Validate all file paths before handing off to the existing REX reader.
        envelope = _read_json(_resolve(experiment_root, "execution_envelope.json"))
        for name in envelope["receipt"]["artifact_sha256"]:
            _resolve(experiment_root, name)
        _resolve(experiment_root, "execution_receipt.json")
        result = load_experiment_input(experiment_root, expected_receipt_sha256=ref.receipt_sha256)
        if result.experiment_id != ref.experiment_id:
            _fail("EXPERIMENT_IDENTITY", relative, "experiment ID differs from reference")
        receipt = envelope["receipt"]
        if ref.experiment_id.startswith("EX"):
            loaded = _load_scoped_experiment(context, definition.strategy_id, ref.experiment_id)
            if (receipt["definition_sha256"], receipt["source_sha256"]) != (
                loaded.definition.sha256, loaded.binding.source_sha256
            ):
                _fail("EXPERIMENT_IDENTITY", relative, "receipt differs from bound experiment")
        if ref.use is d.ExperimentEvidenceUse.CURRENT_EVALUATION and receipt["schema_version"] != 2:
            _fail(
                "EXPERIMENT_SCHEMA",
                relative,
                "new stage deliveries require typed schema 2 receipts",
            )
        records = (
            tuple(EvaluationRecord.from_dict(x) for x in receipt["trace"]["evaluations"])
            if ref.use is d.ExperimentEvidenceUse.CURRENT_EVALUATION
            else ()
        )
        for record in records:
            previous = candidates.setdefault(record.candidate_id, record.content_sha256)
            if previous != record.content_sha256:
                _fail(
                    "CANDIDATE_CONFLICT", relative, "candidate ID has conflicting evidence content"
                )
        results[ref.experiment_id] = (experiment_root, result, receipt, records)
    # REX binds predecessor identities, but its single-input reader does not load
    # predecessor directories. Require the declared transitive closure here.
    for _, _, receipt, _ in results.values():
        for predecessor, digest in receipt["predecessor_receipts"].items():
            if predecessor not in results or results[predecessor][1].receipt_sha256 != digest:
                _fail("EXPERIMENT_CLOSURE", predecessor, "missing or differing predecessor receipt")
    return results


def _check_evaluation(ref, candidate, experiments):
    if ref.experiment_id not in experiments:
        _fail("EVALUATION_REFERENCE", ref.experiment_id, "undeclared source experiment")
    records = experiments[ref.experiment_id][3]
    record = next((x for x in records if x.attempt_id == ref.attempt_id), None)
    if record is None:
        _fail("EVALUATION_REFERENCE", ref.attempt_id, "attempt is absent from experiment receipt")
    key = candidate.key
    if (record.candidate_id, record.content_sha256) != (
        f"{key.strategy_id}-{key.candidate_id}",
        candidate.content_sha256,
    ):
        _fail("CANDIDATE_CONFLICT", ref.attempt_id, "evaluation candidate identity differs")
    if any(x not in record.evaluation_ids for x in ref.evaluation_ids):
        _fail("EVALUATION_REFERENCE", ref.attempt_id, "evaluation ID is absent from this attempt")


def _validate_content(definition, content, root, experiments, context):
    expected = {
        d.DeliveryStage.MANDATE: d.ResearchMandate,
        d.DeliveryStage.COMPONENTS: d.ComponentPanel,
        d.DeliveryStage.CANDIDATES: d.CandidateSet,
        d.DeliveryStage.ASSESSMENT: d.CandidateAssessmentDelivery,
        d.DeliveryStage.INSPECTION: d.CandidateInspectionDelivery,
    }
    if type(content.payload) is not expected[definition.stage]:
        _fail("STAGE_CONTENT", "content.payload", "stage and content type differ")
    available = {x.reference.path: x.reference.sha256 for x in content.attachments}
    for experiment_id, (_, result, _, _) in experiments.items():
        for artifact in result.artifacts:
            available[f"experiments/{experiment_id}/{artifact.path}"] = artifact.sha256
    for value in _walk(content):
        if isinstance(value, d.EvidenceRef):
            if available.get(value.path) != value.sha256:
                _fail(
                    "EVIDENCE_REFERENCE", value.path, "reference is absent from declared evidence"
                )
            _read_evidence(root, value)
        elif isinstance(value, d.CatalogDefinitionRef):
            payload = _read_json(_resolve(root, value.evidence.path))
            cls = (
                FactorDefinition
                if value.kind is d.CatalogDefinitionKind.FACTOR
                else SignalDefinition
            )
            catalog = cls.from_dict(payload)
            identifier = (
                catalog.factor_id if isinstance(catalog, FactorDefinition) else catalog.signal_id
            )
            if (identifier, catalog.version, catalog.definition_sha256) != (
                value.catalog_id,
                value.version,
                value.definition_sha256,
            ):
                _fail(
                    "COMPONENT_DEFINITION", value.catalog_id, "catalog definition identity differs"
                )
        elif isinstance(value, d.ExperimentDefinitionRef):
            if value.experiment_id not in experiments:
                _fail(
                    "COMPONENT_DEFINITION", value.experiment_id, "undeclared definition experiment"
                )
            receipt = experiments[value.experiment_id][2]
            if (receipt["definition_sha256"], receipt["source_sha256"]) != (
                value.definition_sha256,
                value.source_sha256,
            ):
                _fail(
                    "COMPONENT_DEFINITION",
                    value.experiment_id,
                    "definition/source identity differs",
                )
        elif isinstance(value, d.ComponentTestResult):
            if value.experiment_id not in experiments:
                _fail("COMPONENT_TEST", value.test_id, "undeclared test experiment")
            prefix = f"experiments/{value.experiment_id}/"
            if not any(ref.path.startswith(prefix) for ref in value.evidence):
                _fail(
                    "COMPONENT_TEST",
                    value.test_id,
                    "test must cite its receipted experiment evidence",
                )
        elif isinstance(value, d.EvaluationEvidenceRef):
            if any(
                ref.experiment_id == value.experiment_id
                and ref.use is d.ExperimentEvidenceUse.HISTORICAL_REFERENCE
                for ref in definition.experiments
            ):
                _fail(
                    "EVALUATION_REFERENCE",
                    value.experiment_id,
                    "historical reference cannot authenticate a current evaluation",
                )
        elif isinstance(value, d.CandidateIdentityRef):
            if value.key.strategy_id != definition.strategy_id:
                _fail("CANDIDATE_FAMILY", value.key.candidate_id, "candidate family differs")
    if isinstance(content.payload, d.CandidateSet):
        identities = {
            record.candidate_id: record.content_sha256
            for _, _, _, records in experiments.values()
            for record in records
        }
        for candidate in content.payload.candidates:
            key = candidate.identity.key
            digest = identities.get(f"{key.strategy_id}-{key.candidate_id}")
            if digest is None:
                _fail(
                    "CANDIDATE_EVIDENCE",
                    key.candidate_id,
                    "candidate requires authenticated evaluation attempt evidence",
                )
            if digest != candidate.identity.content_sha256:
                _fail(
                    "CANDIDATE_CONFLICT",
                    key.candidate_id,
                    "candidate identity differs from source evidence",
                )
            for ref in candidate.evaluations:
                _check_evaluation(ref, candidate.identity, experiments)
        for search in content.payload.searches:
            for trial in search.trials:
                for ref in trial.evaluations:
                    _check_evaluation(ref, trial.candidate, experiments)
    if isinstance(content.payload, d.CandidateAssessmentDelivery):
        _validate_assessment_delivery(definition, content.payload, experiments, context)
    if isinstance(content.payload, d.CandidateInspectionDelivery):
        _validate_inspection_delivery(definition, content, root, context)


def _validate_inspection_delivery(definition, content, root, context):
    from strategy_manager import CandidateEvidence, StrategyRegistry
    from strategy_manager import freeze_contracts as f
    from strategy_manager.freeze_store import read_decision, validate_inspection

    payload = content.payload
    if payload.source_assessment not in definition.predecessors:
        _fail("INSPECTION_SOURCE", "source_assessment", "assessment predecessor missing")
    report = f.CandidateInspectionReport.from_dict(
        json.loads(_read_evidence(root, payload.inspection_evidence))
    )
    if report != payload.inspection or report != validate_inspection(
        context.strategy_root, report.reference
    ):
        _fail("INSPECTION_REPORT", "inspection", "inspection differs from persisted evidence")
    selection = read_decision(context.strategy_root, report.selection)
    receipt_path = _delivery_path(context, payload.source_assessment) / "receipt.json"
    if (
        selection.subject.delivery.path != receipt_path.relative_to(context.root).as_posix()
        or selection.subject.delivery.sha256 != sha256(receipt_path.read_bytes()).hexdigest()
    ):
        _fail("INSPECTION_SELECTION", "source_assessment", "selection refers to another assessment")
    # Explicit attachments preserve the complete report evidence closure.
    attached = {
        (x.reference.sha256, _read_evidence(root, x.reference)) for x in content.attachments
    }
    records = [report]
    for ref in (report.selection, *payload.decisions):
        record = read_decision(context.strategy_root, ref)
        if record.strategy_id != definition.strategy_id:
            _fail("INSPECTION_DECISION", ref.decision_id, "decision family differs")
        for evidence in (ref.evidence, record.confirmation_source):
            if (
                evidence.sha256,
                evidence.resolve(context.strategy_root).read_bytes(),
            ) not in attached:
                _fail("INSPECTION_EVIDENCE", evidence.path, "decision evidence must be attached")
        if (
            isinstance(record.subject, f.FreezeSubject)
            and record.subject.inspection != report.reference
        ):
            _fail("INSPECTION_DECISION", ref.decision_id, "freeze decision report differs")
    for value in _walk(records[0]):
        if isinstance(value, CandidateEvidence):
            if (value.sha256, value.resolve(context.strategy_root).read_bytes()) not in attached:
                _fail("INSPECTION_EVIDENCE", value.path, "inspection evidence must be attached")
    if payload.freeze is not None:
        receipt = StrategyRegistry(context.strategy_root).get_freeze_result(
            payload.freeze.request_id
        )
        if receipt != payload.freeze:
            _fail("FREEZE_RECEIPT", "freeze", "freeze receipt differs from actual result")
        if receipt.status is f.FreezeStatus.COMMITTED:
            request_path = (context.strategy_root / "freeze_requests"
                            / receipt.request_id.strategy_id / receipt.request_id.value
                            / "request.json")
            request = f.FreezeCandidateRequest.from_dict(
                json.loads(request_path.read_text(encoding="utf-8")))
            if (
                request.sha256 != receipt.request_sha256
                or request.inspection != report.reference
                or request.approval not in payload.decisions
            ):
                _fail("FREEZE_RECEIPT", "freeze", "freeze request report/approval differs")


def _assessment_recomputation_matches(
    recomputed: AssessmentPanel, published: AssessmentPanel
) -> bool:
    # Parallel BLAS/eigensolvers can change the last bits of the correlation-based
    # effective trial count and hence DSR_EFFECTIVE. This is a relative numerical
    # comparison only; persisted bytes, identities, account metrics and decisions
    # remain exact. No absolute tolerance is applied near zero.
    if replace(recomputed, family_diagnostics=published.family_diagnostics) != published:
        return False
    if len(recomputed.family_diagnostics) != len(published.family_diagnostics):
        return False
    for actual, expected in zip(recomputed.family_diagnostics, published.family_diagnostics):
        if actual == expected:
            continue
        if (
            actual.name != "DSR_EFFECTIVE"
            or (actual.name, actual.status, actual.reason)
            != (expected.name, expected.status, expected.reason)
            or actual.value is None
            or expected.value is None
            or not 0.0 <= actual.value <= 1.0
            or not 0.0 <= expected.value <= 1.0
            or not math.isclose(actual.value, expected.value, rel_tol=1e-12, abs_tol=0.0)
        ):
            return False
    return True


def _validate_assessment_delivery(definition, payload, experiments, context):
    for ref in (payload.source_candidates, payload.source_mandate):
        if ref not in definition.predecessors:
            _fail(
                "ASSESSMENT_SOURCE",
                "predecessors",
                "assessment sources must be declared predecessors",
            )

    def source(ref):
        document = _read_json(_resolve(_delivery_path(context, ref), "delivery.json"))
        if document["schema_version"] != 4:
            _fail(
                "ASSESSMENT_SOURCE",
                ref.stage.value,
                "assessment requires schema 3 or 4 mandate and candidate handoffs",
            )
        return d.DeliveryContent.from_dict(document["content"]).payload

    candidates = source(payload.source_candidates)
    mandate = source(payload.source_mandate)
    expected = {
        f"{key.strategy_id}-{key.candidate_id}": next(
            x.identity.content_sha256 for x in candidates.candidates if x.identity.key == key
        )
        for key in candidates.handoff
    }
    actual = {x.candidate_id: x.content_sha256 for x in payload.assessment_request.centers}
    if expected != actual:
        _fail("ASSESSMENT_SCOPE", "centers", "assessment centers differ from stage-three handoff")
    declarations = {x.item_id: x for x in mandate.items}
    targets = {x.target_id: x for x in payload.comparison_request.targets.requirements}
    if {x.target_id for x in payload.target_bindings} != set(targets):
        _fail(
            "TARGET_BINDING",
            "target_bindings",
            "each target requires one confirmed mandate binding",
        )
    expected = {
        target.target_id: (item.item_id, target)
        for item in mandate.items
        if isinstance(item.requirement, d.PerformanceRequirement)
        and item.confirmation.status is d.ConfirmationStatus.CONFIRMED
        for target in item.requirement.targets
    }
    if set(expected) != set(targets):
        _fail(
            "TARGET_BINDING", "target_bindings", "confirmed performance targets must be preserved"
        )
    for binding in payload.target_bindings:
        if expected[binding.target_id] != (binding.mandate_item_id, targets[binding.target_id]):
            _fail(
                "TARGET_BINDING",
                binding.target_id,
                "target differs from confirmed mandate contract",
            )
    if any(
        x.metric
        in (
            ResearchMetric.FREQUENCY_MEDIAN,
            ResearchMetric.FREQUENCY_Q10,
            ResearchMetric.FULL_SAMPLE_FREQUENCY,
        )
        for x in targets.values()
    ):
        item = declarations.get(payload.frequency_window_item_id)
        days = payload.comparison_request.targets.frequency_window_days
        if (
            item is None
            or item.confirmation.status is not d.ConfirmationStatus.CONFIRMED
            or not isinstance(item.requirement, d.NumericRequirement)
            or (
                item.requirement.metric,
                item.requirement.unit,
                item.requirement.lower,
                item.requirement.upper,
            )
            != ("frequency_window_days", "sessions", float(days), float(days))
        ):
            _fail(
                "TARGET_BINDING",
                "frequency_window",
                "frequency window requires a confirmed exact session count",
            )
    benchmark_item = declarations.get(payload.benchmark_mandate_item_id)
    if (
        benchmark_item is None
        or benchmark_item.confirmation.status is not d.ConfirmationStatus.CONFIRMED
        or not isinstance(benchmark_item.requirement, d.BenchmarkRequirement)
    ):
        _fail("BENCHMARK_BINDING", "benchmark", "benchmark requires a confirmed typed mandate")
    benchmark = benchmark_item.requirement.benchmark
    for evidence in payload.assessment_request.evidence:
        if (
            evidence.scenario_context.benchmark_contract_sha256 != benchmark.fingerprint
            or evidence.scenario_context.benchmark_id != benchmark.benchmark_id
            or evidence.scenario_context.benchmark_kind != benchmark.kind
        ):
            _fail(
                "BENCHMARK_BINDING",
                evidence.evaluation_id,
                "benchmark differs from confirmed mandate",
            )
    saved = {}
    attempts = {}
    for experiment_id, (root, _, _, records) in experiments.items():
        for record in records:
            attempts[(experiment_id, record.attempt_id)] = record
            if record.result_artifact is None:
                continue
            result = _read_json(_resolve(root, record.result_artifact.path))
            if result.get("schema_version") != 4:
                continue
            for item in result["assessment_evidence"]:
                evidence = AssessmentEvidence.from_dict(item)
                if (
                    evidence.experiment_id,
                    evidence.attempt_id,
                    evidence.result_sha256,
                    evidence.request_sha256,
                    evidence.candidate.candidate_id,
                    evidence.candidate.content_sha256,
                ) != (
                    experiment_id,
                    record.attempt_id,
                    record.result_hash,
                    record.request_hash,
                    record.candidate_id,
                    record.content_sha256,
                ) or evidence.evaluation_id not in record.evaluation_ids:
                    _fail(
                        "ASSESSMENT_EVIDENCE",
                        evidence.evaluation_id,
                        "projection differs from receipted evaluation identity",
                    )
                saved[(experiment_id, record.attempt_id, evidence.evaluation_id)] = evidence
    for evidence in payload.assessment_request.evidence:
        if (
            saved.get((evidence.experiment_id, evidence.attempt_id, evidence.evaluation_id))
            != evidence
        ):
            _fail(
                "ASSESSMENT_EVIDENCE",
                evidence.evaluation_id,
                "assessment input differs from saved evaluation facts",
            )
    for missing in payload.assessment_request.incomplete:
        if missing.status is IncompleteEvaluationStatus.NOT_RUN:
            continue
        record = attempts.get((missing.experiment_id, missing.attempt_id))
        if record is None or (record.status.value, record.candidate_id, record.content_sha256) != (
            missing.status.value,
            missing.candidate.candidate_id,
            missing.candidate.content_sha256,
        ):
            _fail(
                "ASSESSMENT_EVIDENCE",
                "incomplete",
                "failed evaluation differs from experiment receipt",
            )
    if not _assessment_recomputation_matches(
        assess_candidates(payload.assessment_request), payload.assessment
    ):
        _fail(
            "ASSESSMENT_RESULT", "assessment", "assessment differs from deterministic recomputation"
        )
    if compare_candidates(payload.comparison_request) != payload.comparison:
        _fail(
            "COMPARISON_RESULT", "comparison", "comparison differs from deterministic recomputation"
        )


def _report(definition, content, root) -> bytes:
    # Tables/numbers are rendered only from the machine contract. Free-text
    # explanations remain researcher statements; no semantic NLP certification.
    def safe(value):
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("|", "\\|")
            .replace("\n", "<br>")
        )

    lines = [
        f"# {definition.strategy_id} · {definition.stage.value} · {definition.revision}",
        "",
        f"研究员声明状态：{content.status.value}",
        f"归属：{safe(definition.owner.experiment_id) if isinstance(definition.owner, d.ExperimentOwner) else '研究任务治理'}",
        "",
        "技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。",
        "",
        "[完整机器契约](delivery.json)",
        "",
        "## 阶段内容",
        "",
    ]
    for ref in definition.experiments:
        lines.append(
            f"- 实验证据：{safe(ref.experiment_id)}；用途：{ref.use.value}；回执：`{ref.receipt_sha256}`"
        )
    lines.append("")
    payload = content.payload
    if isinstance(payload, d.ResearchMandate):
        lines.extend(
            [
                "| 项目 | 类别 | 内容 | 确认状态 | 强类型约束 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in payload.items:
            requirement = item.requirement
            bounds = (
                "—"
                if requirement is None
                else str(requirement.targets)
                if isinstance(requirement, d.PerformanceRequirement)
                else str(requirement.benchmark.to_dict())
                if isinstance(requirement, d.BenchmarkRequirement)
                else (
                    f"{requirement.metric}: [{requirement.lower}, {requirement.upper}] {requirement.unit}"
                )
            )
            lines.append(
                "| "
                + " | ".join(
                    safe(x)
                    for x in (
                        item.item_id,
                        item.kind.value,
                        item.statement,
                        item.confirmation.status.value,
                        bounds,
                    )
                )
                + " |"
            )
        for item in payload.items:
            if item.confirmation.source is not None:
                ref = item.confirmation.source
                lines.extend(
                    ["", f"{safe(item.item_id)} 确认来源：[{safe(ref.path)}](<{ref.path}>)"]
                )
    elif isinstance(payload, d.ComponentPanel):
        lines.extend([payload.conclusion, ""])
        for component in payload.components:
            lines.extend(
                [
                    f"### {safe(component.component_id)}",
                    "",
                    f"职责：{component.role}",
                    "",
                    f"研究判断：{component.judgment}",
                    "",
                    f"适用边界：{component.applicability}",
                    "",
                    f"标签／期限／对照：{component.label} / {component.horizon} / {component.control}",
                    "",
                    f"可用时点／价格口径：{component.availability} / {component.price_basis}",
                    "",
                ]
            )
            for test in component.tests:
                lines.append(f"- {safe(test.test_id)}：{test.status.value}；{test.explanation}")
                lines.extend(f"  - 证据：[{safe(ref.path)}](<{ref.path}>)" for ref in test.evidence)
    elif isinstance(payload, d.CandidateAssessmentDelivery):
        lines.extend(
            [
                payload.recommendation,
                "",
                "| 候选 | 状态 | 绩效层 | 层内名次 | 原因 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in payload.comparison.rows:
            lines.append(
                "| "
                + " | ".join(
                    safe(x)
                    for x in (
                        row.candidate.candidate_id,
                        row.status.value,
                        row.pareto_layer,
                        f"{row.rank_in_layer} [{row.rank_min}, {row.rank_max}]",
                        "; ".join(row.reasons),
                    )
                )
                + " |"
            )
        lines.extend(["", "### 成对关系", ""])
        for pair in payload.comparison.pairs:
            lines.append(
                f"- {safe(pair.candidate_a.candidate_id)} / {safe(pair.candidate_b.candidate_id)}："
                f"{pair.relation.value}；指标 {pair.decisive_metric}；{safe(pair.reason or '—')}"
            )
        lines.extend(["", "### 逐项目标检查", ""])
        for row in payload.comparison.rows:
            for check in row.target_checks:
                lines.append(
                    f"- {safe(row.candidate.candidate_id)} / {check.target.metric.value}："
                    f"目标 {safe(check.target.target_id)}；观测值 {check.observed}；下界 {check.target.lower}；上界 {check.target.upper}；"
                    f"状态 {check.status.value}；实际边界 {check.resolved_lower} / {check.resolved_upper}；"
                    f"条件观测 {check.condition_observed}；原因 {safe(check.reason or '—')}"
                )
        lines.extend(["", "### 排序敏感性", ""])
        if not payload.comparison.sensitivities:
            lines.append("未提供敏感性方案。")
        for variant in payload.comparison.sensitivities:
            lines.append(f"- 方案：{safe(variant.name)}")
            for pair in variant.pairs:
                lines.append(
                    f"  - {safe(pair.candidate_a.candidate_id)} / {safe(pair.candidate_b.candidate_id)}："
                    f"{pair.relation.value}；{pair.decisive_metric}；{safe(pair.reason or '—')}"
                )
            for row in variant.rows:
                lines.append(
                    f"  - {safe(row.candidate.candidate_id)}：{row.status.value}；"
                    f"绩效层 {row.pareto_layer}；层内名次 {row.rank_in_layer}；区间 {row.rank_min}—{row.rank_max}；"
                    f"原因 {safe('; '.join(row.reasons) or '—')}"
                )
        lines.extend(["", "### 行为分组", ""])
        for group in payload.comparison.behavior_groups:
            lines.append(
                f"- `{group.behavior_sha256}`："
                + "、".join(safe(x.candidate_id) for x in group.candidates)
            )
        for row in payload.assessment.rows:
            lines.extend(
                [
                    "",
                    f"### {safe(row.candidate.candidate_id)} 自检",
                    "",
                    "| 指标 | 值 | 单位 | 状态 | 原因 |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for label, metric in (
                *(("STRATEGY", x) for x in row.diagnostics),
                *(("BENCHMARK", x) for x in row.benchmark.diagnostics),
            ):
                lines.append(
                    "| "
                    + " | ".join(
                        safe(x)
                        for x in (
                            label + ":" + metric.metric.value,
                            metric.value,
                            metric.unit.value,
                            metric.status.value,
                            metric.reason or "—",
                        )
                    )
                    + " |"
                )
            lines.extend(
                [
                    "",
                    f"超额年化95%区间：{row.uncertainty.lower_95} 至 {row.uncertainty.upper_95}；"
                    f"{row.uncertainty.status.value}；{row.uncertainty.reason or '—'}",
                    "",
                ]
            )
            lines.extend(f"- 覆盖缺口：{safe(x)}" for x in row.coverage_gaps)
        lines.extend(["", "统计限制与研究族诊断：", ""])
        lines.extend(
            f"- {safe(x.name)}：{x.status.value}；{x.value}；{safe(x.reason or '—')}"
            for x in payload.assessment.family_diagnostics
        )
        lines.extend(f"- {safe(x)}" for x in payload.assessment.family_limitations)
        lines.extend(["", "不利证据：", ""])
        lines.extend(f"- [{safe(x.path)}](<{x.path}>)" for x in payload.contrary_evidence)
        lines.extend(["", "待用户决定：", "", *[f"- {safe(x)}" for x in payload.pending_decisions]])
    elif isinstance(payload, d.CandidateSet):
        lines.extend(
            [
                payload.conclusion,
                "",
                "交接候选："
                + ("、".join(f"{x.strategy_id}-{x.candidate_id}" for x in payload.handoff) or "无"),
                "",
            ]
        )
        for candidate in payload.candidates:
            key = candidate.identity.key
            lines.extend(
                [
                    f"### {key.strategy_id}-{key.candidate_id}",
                    "",
                    f"内容指纹：`{candidate.identity.content_sha256}`",
                    "",
                    f"策略假设：{candidate.hypothesis}",
                    "",
                    f"研究判断：{candidate.judgment}",
                    "",
                ]
            )
        for search in payload.searches:
            lines.extend(
                [
                    f"### 搜索 {safe(search.search_id)}",
                    "",
                    f"方法：{search.method} {search.method_version}；种子：{search.seed}",
                    "",
                    f"调度：{search.scheduling}；声明预算：{search.declared_budget}；"
                    f"已提交记录数：{len(search.trials)}",
                    "",
                    f"停止原因：{search.stop_reason}",
                    "",
                    "| 提议 | 参数 | 试验状态 | 原因 |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for trial in search.trials:
                parameters = ", ".join(f"{p.name}={p.value}" for p in trial.parameters)
                lines.append(
                    "| "
                    + " | ".join(
                        safe(x)
                        for x in (trial.proposal_id, parameters, trial.status.value, trial.reason)
                    )
                    + " |"
                )
    if isinstance(payload, d.CandidateInspectionDelivery):
        report = payload.inspection
        plan = report.plan
        lines.extend(
            [
                f"候选：{plan.origin.candidate.strategy_id}-{plan.origin.candidate.candidate_id}",
                "",
                f"内容指纹：`{plan.origin.content_sha256}`",
                "",
                f"拟冻结版本：{plan.version}；计划摘要：`{plan.sha256}`",
                "",
                f"技术检验：{report.status.value}；方法：{report.protocol.method_version}",
                "",
                "| 检验项 | 状态 | 说明 |",
                "| --- | --- | --- |",
                *[
                    f"| {x.check.value} | {x.status.value} | {safe(x.detail)} |"
                    for x in report.checks
                ],
                "",
                "剩余风险：",
                *[f"- {safe(x)}" for x in report.remaining_risks],
                "",
                f"冻结状态：{payload.freeze.status.value if payload.freeze else '尚未请求'}",
                "",
                *[f"待用户决定：{safe(x)}" for x in payload.pending_decisions],
            ]
        )
        if payload.freeze is not None and payload.freeze.version is not None:
            lines.extend(
                [
                    "",
                    f"已冻结版本：{payload.freeze.version.strategy_id}-{payload.freeze.version.version}",
                    f"发布哈希：`{payload.freeze.version.release_hash}`",
                ]
            )
        if payload.freeze is not None and payload.freeze.reason:
            lines.extend(["", f"冻结原因：{safe(payload.freeze.reason)}"])
        from strategy_manager import ResearchDecision

        lines.extend(["", "### 用户决定与确认来源", ""])
        for ref in dict.fromkeys((report.selection, *payload.decisions)):
            attachment = next(
                x.reference
                for x in content.attachments
                if x.reference.sha256 == ref.evidence.sha256
            )
            decision = ResearchDecision.from_dict(json.loads(_read_evidence(root, attachment)))
            confirmation = next(
                x.reference
                for x in content.attachments
                if x.reference.sha256 == decision.confirmation_source.sha256
            )
            lines.append(
                f"- {safe(decision.decision_id)}：{decision.action.value}；"
                f"理由：{safe(decision.reason)}；"
                f"[确认来源](<{confirmation.path}>)"
            )
    lines.extend(
        [
            "",
            "## 事实",
            "",
            "| ID | 值 | 单位 | 状态 | 缺失原因 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for fact in content.facts:
        lines.append(
            "| "
            + " | ".join(
                safe(v)
                for v in (
                    fact.fact_id,
                    fact.value if fact.value is not None else "—",
                    fact.unit,
                    fact.status.value,
                    fact.reason or "—",
                )
            )
            + " |"
        )
    for fact in content.facts:
        lines.extend(
            f"\n{safe(fact.fact_id)} 证据：[{safe(ref.path)}](<{ref.path}>) `{ref.sha256}`"
            for ref in fact.evidence
        )
    lines.extend(["", "## 解释", ""])
    facts = {x.fact_id: x for x in content.facts}
    for explanation in content.explanations:
        lines.extend([f"**{explanation.kind.value}**：{explanation.text}", ""])
        for name in explanation.fact_ids:
            fact = facts[name]
            value = fact.value if fact.value is not None else fact.reason
            lines.append(f"- {safe(name)}：{safe(value)} {safe(fact.unit)}")
        for label, refs in (
            ("支持证据", explanation.supporting),
            ("不利证据", explanation.contrary),
        ):
            lines.extend(f"- {label}：[{safe(x.path)}](<{x.path}>) `{x.sha256}`" for x in refs)
    lines.extend(
        [
            "",
            "## 未完成事项",
            "",
            *[f"- {safe(x)}" for x in content.incomplete_items],
            "",
            "## 复算",
            "",
            content.reproduction.instructions,
            "",
            f"数据访问：{content.reproduction.data_access}",
            "",
            f"确定性及容差：{content.reproduction.determinism}",
            "",
        ]
    )
    lines.extend(
        f"- 环境：[{safe(x.path)}](<{x.path}>) `{x.sha256}`"
        for x in content.reproduction.environment
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _manifest(root: Path) -> tuple[d.EvidenceRef, ...]:
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        _resolve(root, relative)
        if path.is_file() and relative != "receipt.json":
            media = {".json": "application/json", ".md": "text/markdown"}.get(
                path.suffix, "application/octet-stream"
            )
            result.append(d.EvidenceRef(relative, sha256(path.read_bytes()).hexdigest(), media))
    d._unique((x.path.casefold() for x in result), "manifest path")
    return tuple(result)


def _read_delivery(context, reference, root, visited):
    document = _read_json(_resolve(root, "delivery.json"))
    version = document.get("schema_version") if type(document) is dict else None
    if type(version) is not int or version != 4:
        _fail("DELIVERY_SCHEMA", "delivery.json", "unsupported delivery schema")
    identity = (reference.owner, reference.stage, reference.revision)
    if identity in visited:
        _fail("DELIVERY_CYCLE", "predecessors", "cyclic delivery references")
    visited = visited | {identity}
    receipt = d.DeliveryReceipt.from_dict(_read_json(_resolve(root, "receipt.json")))
    if (
        receipt.schema_version != 4
        or receipt.reference != reference
        or d._digest(receipt.files) != reference.content_sha256
    ):
        _fail(
            "DELIVERY_IDENTITY", "receipt", "receipt differs from independently retained reference"
        )
    if _manifest(root) != receipt.files:
        _fail("DELIVERY_FILES", "receipt.files", "published file manifest differs")
    if (
        set(document) != {"schema_version", "definition", "content"}
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 4
    ):
        _fail("DELIVERY_SCHEMA", "delivery.json", "unsupported delivery schema")
    definition = d.DeliveryDefinition.from_dict(document["definition"])
    content = d.DeliveryContent.from_dict(document["content"])
    if (definition.owner, definition.stage, definition.revision) != identity:
        _fail("DELIVERY_IDENTITY", "definition", "definition differs from reference")
    _validate_owner(context, definition)
    experiments = _load_experiments(definition, root, published=True, context=context)
    _validate_content(definition, content, root, experiments, context)
    if _resolve(root, "report.md").read_bytes() != _report(definition, content, root):
        _fail("REPORT_FACTS", "report.md", "report differs from machine content")
    for predecessor in definition.predecessors:
        _read_delivery(context, predecessor, _delivery_path(context, predecessor), visited)
    return receipt


def validate_delivery(
    context: RepositoryContext, reference: d.DeliveryReference
) -> d.DeliveryValidation:
    """Verify persisted bytes exactly; DSR_EFFECTIVE recomputation uses 1e-12 rtol.

    Read-only: never executes research code or reproduction commands.
    """
    if not isinstance(context, RepositoryContext) or not isinstance(
        reference, d.DeliveryReference
    ):
        raise TypeError("validate_delivery requires RepositoryContext and DeliveryReference")
    try:
        _read_delivery(context, reference, _delivery_path(context, reference), set())
        return d.DeliveryValidation(d.ValidationStatus.PASS)
    except d.DeliveryValidationError as exc:
        return d.DeliveryValidation(d.ValidationStatus.FAIL, exc.issues)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return d.DeliveryValidation(
            d.ValidationStatus.FAIL, (d.DeliveryIssue("INVALID_DELIVERY", "delivery", str(exc)),)
        )


def assemble_delivery(
    context: RepositoryContext, deliverable: d.ResearchDeliverable
) -> d.DeliveryReceipt:
    """Build once, verify, then publish one immutable revision with an atomic rename."""
    if not isinstance(context, RepositoryContext) or not isinstance(
        deliverable, d.ResearchDeliverable
    ):
        raise TypeError("assemble_delivery requires RepositoryContext and ResearchDeliverable")
    try:
        definition = deliverable.definition
        content = deliverable.build()
        if type(definition) is not d.DeliveryDefinition or type(content) is not d.DeliveryContent:
            _fail(
                "DELIVERY_TYPE", "deliverable", "build/definition must return typed delivery values"
            )
        # Round-trip also catches externally mutated frozen objects and noncanonical values.
        definition = d.DeliveryDefinition.from_dict(definition.to_dict())
        content = d.DeliveryContent.from_dict(content.to_dict())
        destination = _delivery_path(context, definition)
        if destination.exists():
            existing = _read_json(_resolve(destination, "delivery.json"))
            expected = {
                "schema_version": 4,
                "definition": definition.to_dict(),
                "content": content.to_dict(),
            }
            if existing != expected:
                raise d.DeliveryConflictError(
                    "delivery revision already contains different content"
                )
            receipt = d.DeliveryReceipt.from_dict(_read_json(_resolve(destination, "receipt.json")))
            return _read_delivery(context, receipt.reference, destination, set())
        owner_root = _validate_owner(context, definition, publishing=True)
        if owner_root is not None:
            from research_experiment import load_experiment

            loaded = load_experiment(owner_root)
            if loaded.definition.schema_version != 2:
                _fail(
                    "OWNER_BINDING", "owner", "new deliveries require a typed experiment definition"
                )
        for predecessor in definition.predecessors:
            _read_delivery(context, predecessor, _delivery_path(context, predecessor), set())
        experiments = _load_experiments(definition, context.root, published=False, context=context)
        if isinstance(content.payload, d.CandidateSet):
            from strategy_manager import StrategyRegistry, StrategyManagerError
            from strategy_runtime.errors import StrategyRuntimeError
            from .candidate_service import load_candidate

            identities = {x.identity.key: x.identity for x in content.payload.candidates}
            for key in content.payload.handoff:
                try:
                    registration = StrategyRegistry(context.research_registry_root).get_candidate(
                        key, experiments_root=context.experiments_root
                    )
                    if registration.content_sha256 != identities[key].content_sha256:
                        raise ValueError("registered candidate content differs from handoff")
                    load_candidate(context, key)
                except (
                    OSError,
                    ValueError,
                    TypeError,
                    KeyError,
                    StrategyManagerError,
                    StrategyRuntimeError,
                ) as exc:
                    _fail("HANDOFF_REGISTRATION", key.candidate_id, str(exc))
        _resolve(context.root, ".tmp/delivery")
        staging = create_temporary_directory(context.root, "delivery")

        def copy(source, relative, expected):
            target = _resolve(staging, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            if sha256(data).hexdigest() != expected:
                _fail("EVIDENCE_HASH", relative, "source changed or hash differs")
            with target.open("xb") as output:
                output.write(data)

        for attachment in content.attachments:
            copy(
                _resolve(context.root, attachment.source_path),
                attachment.reference.path,
                attachment.reference.sha256,
            )
        for experiment_id, (source, result, _, _) in experiments.items():
            prefix = f"experiments/{experiment_id}"
            for name in ("execution_envelope.json", "execution_receipt.json"):
                path = _resolve(source, name)
                copy(path, f"{prefix}/{name}", sha256(path.read_bytes()).hexdigest())
            for artifact in result.artifacts:
                copy(_resolve(source, artifact.path), f"{prefix}/{artifact.path}", artifact.sha256)
        verified = _load_experiments(definition, staging, published=True, context=context)
        _validate_content(definition, content, staging, verified, context)
        document = {"schema_version": 4, "definition": definition, "content": content}
        (staging / "delivery.json").write_bytes(d._canonical(document))
        (staging / "report.md").write_bytes(_report(definition, content, staging))
        files = _manifest(staging)
        reference = d.DeliveryReference(
            definition.owner, definition.stage, definition.revision, d._digest(files)
        )
        receipt = d.DeliveryReceipt(reference, files)
        (staging / "receipt.json").write_bytes(d._canonical(receipt))
        _read_delivery(context, reference, staging, set())
        destination = _delivery_path(context, reference)
        _validate_owner(context, definition, publishing=True)
        if destination.exists():
            return _existing(context, reference, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            staging.rename(destination)
        except OSError:
            if destination.exists():
                return _existing(context, reference, destination)
            raise
        return receipt
    except (d.DeliveryValidationError, d.DeliveryConflictError):
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise d.DeliveryValidationError(
            (d.DeliveryIssue("ASSEMBLY_FAILED", "delivery", str(exc)),)
        ) from exc


def _existing(context, reference, destination):
    receipt = d.DeliveryReceipt.from_dict(_read_json(_resolve(destination, "receipt.json")))
    if receipt.reference != reference:
        raise d.DeliveryConflictError("delivery revision already contains different content")
    return _read_delivery(context, reference, destination, set())
