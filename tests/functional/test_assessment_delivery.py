from dataclasses import replace
import json
import shutil

import pytest
from research_experiment import experiment_source_sha256, load_experiment
from strategy_manager import CandidateKey
from strategy_runtime import StrategyRuntime
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m

from czsc_trader.application import RepositoryContext, assemble_delivery, validate_delivery
from czsc_trader.research_tools import build_assessment_evidence, execute_experiment
from czsc_trader.research_tools import delivery as d
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_research_delivery import Deliverable, content, attachment, published


@pytest.fixture
def completed(managed_evaluation):
    execution, request = managed_evaluation
    root = request.repository_root
    (root / "src/czsc_trader").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    source_root = root / "experiments/S900/20261001_S900_EX01"
    source_root.mkdir(parents=True)
    source = """from datetime import date
from research_experiment import (
    ExperimentDefinition, ExperimentDataScope, ExperimentMode, ExperimentProtocol,
    ExperimentStage, ExperimentCapabilities, ResearchExperiment, ExperimentResult, ExperimentOutcome,
)
class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, experiment_id="20261001_S900_EX01", strategy_id="S900",
            mode=ExperimentMode.FORMAL, data_scope=ExperimentDataScope.DEVELOPMENT,
            research_question="Does each independent evaluation retain identity?",
            hypothesis="Repeat evaluations have independent records and stable input identity",
            falsification_conditions=("A failure returns success",), development_cutoff=date(2026, 9, 21),
            random_seed=1, subjects=("588080.SH",), allowed_datasets=DATASETS,
            protocol=ExperimentProtocol(ExperimentStage.PARAMETER_SEARCH, ("Bound inputs",), ("Data to account",), ("Evaluate",), ("identity",), ("Synthetic replay",)),
            capabilities=ExperimentCapabilities(reads_real_returns=True, searches_parameters=True),
        )
    def synthetic_precheck(self):
        assert 1 + 1 == 2
    def execute(self, context):
        self.result = context.evaluation.evaluate(self.request)
        return ExperimentResult(ExperimentOutcome.PASS, {"result_hash": self.result.result_hash}, {})
""".replace("DATASETS", repr(execution.definition.allowed_datasets))
    (source_root / "experiment.py").write_text(source)
    (source_root / "experiment_binding.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "module": "experiment",
                "qualname": "Experiment",
                "source_files": ["experiment.py"],
                "dependencies": [],
                "source_sha256": experiment_source_sha256(source_root, ("experiment.py",)),
            }
        )
    )
    loaded = load_experiment(source_root)
    loaded.implementation.request = request
    receipt_result = execute_experiment(loaded, execution)
    ref = d.ExperimentEvidenceRef(
        request.experiment_id,
        execution.workspace.root.relative_to(root).as_posix(),
        receipt_result.receipt.sha256,
    )
    return RepositoryContext.discover(root), execution, request, loaded.implementation.result, ref


def assessment_request(evidence):
    protocol = m.SelfCheckProtocol(
        "1",
        "full",
        "standard",
        "fee_x2",
        2,
        1,
        m.QuantileMethod.LINEAR,
        1,
        1,
        40,
        2,
        1,
        1e-7,
        pbo_blocks=2,
    )
    return m.CandidateAssessmentRequest(
        (evidence[0].candidate,),
        protocol,
        (),
        evidence,
        (
            m.IncompleteEvaluation(
                evidence[0].candidate,
                "full",
                "fee_x2",
                m.IncompleteEvaluationStatus.NOT_RUN,
                "压力实验尚未执行",
            ),
        ),
    )


def comparison_request(panel):
    policy = m.ComparisonPolicy(
        "1", tuple(m.MetricBinSpec(x, 0.0001, 0.0, m.BinRounding.FLOOR) for x in m.RANKING_METRICS)
    )
    targets = m.ResearchTargets(
        (m.ResearchTarget(m.ResearchMetric.NET_ANNUAL_RETURN, lower=-1.0),), 60
    )
    return m.CandidateComparisonRequest(
        tuple(x.candidate for x in panel.rows), targets, panel, policy
    )


def prepare(completed):
    context, execution, request, result, exp = completed
    evidence = build_assessment_evidence(request, result)
    assessment = assessment_request(evidence)
    panel = assess_candidates(assessment)
    comparison = comparison_request(panel)
    confirmation = attachment(context, "confirmation.json", {"user": "合成测试：净年化下界 -1"})
    mandate = d.ResearchMandate(
        (
            d.MandateItem(
                "return",
                d.MandateItemKind.OBJECTIVE,
                "净年化下界",
                d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation.reference),
                d.NumericRequirement("net_annual_return", "ratio", lower=-1.0),
            ),
        )
    )
    mandate_receipt = assemble_delivery(
        context,
        Deliverable(
            d.DeliveryDefinition("S900", d.DeliveryStage.MANDATE, 1),
            content(mandate, attachments=(confirmation,)),
        ),
    )
    key = CandidateKey("S900", "C001")
    identity = d.CandidateIdentityRef(key, evidence[0].candidate.content_sha256)
    entry = d.CandidateEntry(
        identity,
        "完整可执行假设",
        "提交自检",
        (
            d.EvaluationEvidenceRef(
                exp.experiment_id, result.attempt_id, tuple(x.evaluation_id for x in evidence)
            ),
        ),
    )
    candidates = d.CandidateSet((entry,), (key,), (), "交接一个候选")
    candidate_receipt = assemble_delivery(
        context,
        Deliverable(
            d.DeliveryDefinition("S900", d.DeliveryStage.CANDIDATES, 1, experiments=(exp,)),
            content(candidates),
        ),
    )
    artifact = execution.trace.evaluations[0].result_artifact
    contrary = d.EvidenceRef(
        f"experiments/{exp.experiment_id}/{artifact.path}", artifact.sha256, "application/json"
    )
    payload = d.CandidateAssessmentDelivery(
        candidate_receipt.reference,
        mandate_receipt.reference,
        assessment,
        panel,
        comparison,
        compare_candidates(comparison),
        (d.TargetMandateBinding(m.ResearchMetric.NET_ANNUAL_RETURN, "return"),),
        None,
        "先补充缺失自检证据，再由用户选型",
        (contrary,),
        ("是否补做压力与参数扰动实验",),
    )
    definition = d.DeliveryDefinition(
        "S900",
        d.DeliveryStage.ASSESSMENT,
        1,
        predecessors=(candidate_receipt.reference, mandate_receipt.reference),
        experiments=(exp,),
    )
    value = replace(
        content(payload),
        status=d.DeliveryStatus.PARTIAL,
        incomplete_items=("压力与扰动实验尚未完成",),
    )
    return definition, value


def test_adapter_authenticates_requests_and_does_not_reload_source(completed, monkeypatch):
    _, execution, request, result, _ = completed

    def unexpected(*args, **kwargs):
        raise AssertionError("adapter must not load mutable candidate source")

    monkeypatch.setattr(StrategyRuntime, "identify", unexpected)
    evidence = build_assessment_evidence(request, result)
    assert evidence[0].evaluation_id == result.runs[0].identity.evaluation_id
    assert evidence[0].candidate.candidate_id == "S900-C001"
    artifact = execution.trace.evaluations[0].result_artifact
    saved = json.loads(execution.workspace.path(artifact.path).read_text())
    assert saved["schema_version"] == 2
    assert saved["runs"][0]["signal_support"] == result.runs[0].signals.support_data
    assert (
        saved["runs"][0]["signal_window"]["evaluation_start"]
        == result.runs[0].signals.evaluation_start.isoformat()
    )
    assert (
        tuple(m.AssessmentEvidence.from_dict(x) for x in saved["assessment_evidence"]) == evidence
    )
    with pytest.raises(ValueError, match="identity differs"):
        build_assessment_evidence(replace(request, initial_cash=request.initial_cash + 1), result)
    with pytest.raises(ValueError, match="identity differs"):
        build_assessment_evidence(request, replace(result, result_hash="f" * 64))


def test_stage_four_roundtrip_recomputation_and_source_cleanup(completed):
    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    receipt = assemble_delivery(context, Deliverable(definition, value))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    report = (published(context, receipt) / "report.md").read_text(encoding="utf-8")
    assert (
        "INCOMPARABLE" in report
        and "待用户决定" in report
        and "MISSING_OR_INCOMPARABLE_STRESS" in report
    )
    document = json.loads(
        (published(context, receipt) / "delivery.json").read_text(encoding="utf-8")
    )
    assert d.DeliveryContent.from_dict(document["content"]) == value
    temporary = (context.root / ".tmp").resolve()
    assert temporary.is_relative_to(context.root.resolve())
    shutil.rmtree(temporary)
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, Deliverable(definition, value)) == receipt


def test_stage_four_rejects_changed_targets_and_forged_panel(completed):
    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    payload = value.payload
    changed_target = replace(
        payload.comparison_request,
        targets=m.ResearchTargets(
            (m.ResearchTarget(m.ResearchMetric.NET_ANNUAL_RETURN, lower=0.0),), 60
        ),
    )
    changed = replace(
        payload, comparison_request=changed_target, comparison=compare_candidates(changed_target)
    )
    with pytest.raises(d.DeliveryValidationError, match="confirmed mandate"):
        assemble_delivery(context, Deliverable(definition, replace(value, payload=changed)))
    first = payload.assessment.rows[0]
    forged = replace(
        first,
        diagnostics=tuple(
            replace(x, value=0.25) if x.metric is m.ResearchMetric.NET_ANNUAL_RETURN else x
            for x in first.diagnostics
        ),
    )
    panel = replace(payload.assessment, rows=(forged,))
    comparison = replace(payload.comparison_request, panel=panel)
    changed = replace(
        payload,
        assessment=panel,
        comparison_request=comparison,
        comparison=compare_candidates(comparison),
    )
    with pytest.raises(d.DeliveryValidationError, match="recomputation"):
        assemble_delivery(context, Deliverable(definition, replace(value, payload=changed)))
    dropped = replace(payload.comparison_request, targets=m.ResearchTargets((), 60))
    changed = replace(
        payload,
        comparison_request=dropped,
        comparison=compare_candidates(dropped),
        target_bindings=(),
    )
    with pytest.raises(d.DeliveryValidationError, match="targets must be preserved"):
        assemble_delivery(context, Deliverable(definition, replace(value, payload=changed)))


def test_stage_four_must_cover_exact_handoff_scope(completed):
    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    other = m.AssessmentCandidate("S900-C002", "f" * 64)
    req = replace(value.payload.assessment_request, centers=(other,))
    panel = assess_candidates(req)
    comp = comparison_request(panel)
    changed = replace(
        value.payload,
        assessment_request=req,
        assessment=panel,
        comparison_request=comp,
        comparison=compare_candidates(comp),
    )
    with pytest.raises(d.DeliveryValidationError, match="stage-three handoff"):
        assemble_delivery(context, Deliverable(definition, replace(value, payload=changed)))


def test_stage_four_rejects_forged_evidence_and_failure_reference(completed):
    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    payload = value.payload
    evidence = payload.assessment_request.evidence[0]
    changed_evidence = replace(
        evidence, account=(replace(evidence.account[0], cash=0.0), *evidence.account[1:])
    )
    changed_request = replace(payload.assessment_request, evidence=(changed_evidence,))
    panel = assess_candidates(changed_request)
    comparison = comparison_request(panel)
    changed = replace(
        payload,
        assessment_request=changed_request,
        assessment=panel,
        comparison_request=comparison,
        comparison=compare_candidates(comparison),
    )
    with pytest.raises(d.DeliveryValidationError, match="saved evaluation facts"):
        assemble_delivery(context, Deliverable(definition, replace(value, payload=changed)))
    failed = m.IncompleteEvaluation(
        evidence.candidate,
        "full",
        "fee_x2",
        m.IncompleteEvaluationStatus.FAILED,
        "声称失败",
        evidence.experiment_id,
        evidence.attempt_id,
    )
    changed = replace(
        payload, assessment_request=replace(payload.assessment_request, incomplete=(failed,))
    )
    with pytest.raises(d.DeliveryValidationError, match="failed evaluation"):
        assemble_delivery(context, Deliverable(definition, replace(value, payload=changed)))


def test_signal_support_changes_are_detected(completed):
    _, _, request, result, _ = completed
    original = result.runs[0]
    support = {**original.signals.support_data, "available_through": "2099-01-01"}
    changed = replace(
        result, runs=(replace(original, signals=replace(original.signals, support_data=support)),)
    )
    with pytest.raises(ValueError, match="identity differs"):
        build_assessment_evidence(request, changed)


def test_frequency_targets_require_the_confirmed_window(completed):
    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    payload = value.payload
    source = context.root / "research/S900/deliveries/MANDATE/1/delivery.json"
    original = d.DeliveryContent.from_dict(
        json.loads(source.read_text(encoding="utf-8"))["content"]
    )
    confirmation = original.payload.items[0].confirmation
    mandate = d.ResearchMandate(
        (
            *original.payload.items,
            d.MandateItem(
                "frequency",
                d.MandateItemKind.OBJECTIVE,
                "滚动闭合次数中位数",
                confirmation,
                d.NumericRequirement("frequency_median", "closed_cycles_per_window", lower=0.0),
            ),
            d.MandateItem(
                "frequency_days",
                d.MandateItemKind.EXECUTION,
                "统计窗口",
                confirmation,
                d.NumericRequirement("frequency_window_days", "sessions", lower=60.0, upper=60.0),
            ),
        )
    )
    receipt = assemble_delivery(
        context,
        Deliverable(
            d.DeliveryDefinition(
                "S900", d.DeliveryStage.MANDATE, 2, predecessors=(payload.source_mandate,)
            ),
            replace(original, payload=mandate),
        ),
    )
    targets = replace(
        payload.comparison_request.targets,
        requirements=(
            *payload.comparison_request.targets.requirements,
            m.ResearchTarget(m.ResearchMetric.FREQUENCY_MEDIAN, lower=0.0),
        ),
    )
    comparison = replace(payload.comparison_request, targets=targets)
    changed = replace(
        payload,
        source_mandate=receipt.reference,
        comparison_request=comparison,
        comparison=compare_candidates(comparison),
        frequency_window_item_id="frequency_days",
        target_bindings=(
            *payload.target_bindings,
            d.TargetMandateBinding(m.ResearchMetric.FREQUENCY_MEDIAN, "frequency"),
        ),
    )
    defined = replace(definition, predecessors=(payload.source_candidates, receipt.reference))
    result = assemble_delivery(context, Deliverable(defined, replace(value, payload=changed)))
    assert validate_delivery(context, result.reference).status is d.ValidationStatus.PASS
    wrong = replace(comparison, targets=replace(targets, frequency_window_days=30))
    changed = replace(changed, comparison_request=wrong, comparison=compare_candidates(wrong))
    with pytest.raises(d.DeliveryValidationError, match="frequency window"):
        assemble_delivery(
            context, Deliverable(replace(defined, revision=2), replace(value, payload=changed))
        )
