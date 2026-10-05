from dataclasses import replace
from hashlib import sha256
import json
import math
import shutil

import pytest
from research_experiment import experiment_source_sha256, load_experiment, ExperimentResources
from strategy_manager import (
    CandidateKey,
    CandidateEvidence,
    CandidateRegistrationOrigin,
    ResearchState,
    StrategyFamily,
    StrategyRegistry,
)
from strategy_runtime import StrategyRuntime
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m

from czsc_trader.application import (
    RepositoryContext,
    assemble_delivery,
    validate_delivery,
    CandidateRegistrationRequest,
    register_candidate,
)
from czsc_trader.research_tools import (
    build_assessment_evidence,
    execute_experiment,
    preflight_experiment,
)
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
        use=d.ExperimentEvidenceUse.CURRENT_EVALUATION,
    )
    evaluation_result = loaded.implementation.result
    context = RepositoryContext.discover(root)
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
    register_candidate(
        context,
        CandidateRegistrationRequest(
            request.strategy,
            CandidateRegistrationOrigin(
                request.experiment_id,
                loaded.definition.sha256,
                sha256((path / "experiment_binding.json").read_bytes()).hexdigest(),
                CandidateEvidence(
                    preflight_path.relative_to(root).as_posix(),
                    sha256(preflight_path.read_bytes()).hexdigest(),
                ),
            ),
            (),
        ),
    )
    return context, execution, request, evaluation_result, ref


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
        "1",
        tuple((m.MetricBinSpec(x, 0.0001, 0.0, m.BinRounding.FLOOR) for x in m.RANKING_METRICS)),
        pareto_basis=m.ParetoBasis.RAW,
        missing_evidence_policy=m.MissingEvidencePolicy.REQUIRE_COMPLETE,
    )
    targets = m.ResearchTargets(
        (
            m.ResearchTarget(
                "net_annual_return",
                m.ResearchMetric.NET_ANNUAL_RETURN,
                lower=m.ConstantBound(-1.0, True),
            ),
        ),
        60,
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
                d.PerformanceRequirement(
                    (
                        m.ResearchTarget(
                            "net_annual_return",
                            m.ResearchMetric.NET_ANNUAL_RETURN,
                            lower=m.ConstantBound(-1.0, True),
                        ),
                    )
                ),
            ),
        )
    )
    mandate = replace(
        mandate,
        items=(
            *mandate.items,
            d.MandateItem(
                "benchmark",
                d.MandateItemKind.BENCHMARK,
                "显式基准",
                d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation.reference),
                d.BenchmarkRequirement(request.benchmark),
            ),
        ),
    )
    mandate_receipt = assemble_delivery(
        context,
        Deliverable(
            d.DeliveryDefinition(d.MandateOwner("S900"), d.DeliveryStage.MANDATE, 1),
            content(mandate, attachments=(confirmation,)),
        ),
    )
    key = CandidateKey("S900", "C0001")
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
            d.DeliveryDefinition(
                d.ExperimentOwner("S900", "20261001_S900_EX01"),
                d.DeliveryStage.CANDIDATES,
                1,
                experiments=(exp,),
            ),
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
        (d.TargetMandateBinding("net_annual_return", "return"),),
        None,
        "benchmark",
        "先补充缺失自检证据，再由用户选型",
        (contrary,),
        ("是否补做压力与参数扰动实验",),
    )
    definition = d.DeliveryDefinition(
        d.ExperimentOwner("S900", "20261001_S900_EX01"),
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
    assert evidence[0].candidate.candidate_id == "S900-C0001"
    artifact = execution.trace.evaluations[0].result_artifact
    saved = json.loads(execution.workspace.path(artifact.path).read_text())
    assert saved["schema_version"] == 4
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
    assert "逐项目标检查" in report and "观测值" in report
    assert "排序敏感性" in report and "行为分组" in report
    document = json.loads(
        (published(context, receipt) / "delivery.json").read_text(encoding="utf-8")
    )
    assert d.DeliveryContent.from_dict(document["content"]) == value
    temporary = (context.root / ".tmp").resolve()
    assert temporary.is_relative_to(context.root.resolve())
    shutil.rmtree(temporary)
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, Deliverable(definition, value)) == receipt


def test_stage_four_public_validation_tolerates_only_effective_dsr_roundoff(completed, monkeypatch):
    from czsc_trader.application import delivery_service

    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    probability = 0.6396147383007816
    saved = replace(
        value.payload.assessment,
        family_diagnostics=tuple(
            replace(x, status=m.DiagnosticStatus.AVAILABLE, value=probability, reason=None)
            if x.name == "DSR_EFFECTIVE" else x
            for x in value.payload.assessment.family_diagnostics
        ),
    )
    comparison = replace(value.payload.comparison_request, panel=saved)
    payload = replace(
        value.payload, assessment=saved, comparison_request=comparison,
        comparison=compare_candidates(comparison),
    )

    def rounded_panel(probability):
        return replace(
            saved,
            family_diagnostics=tuple(
                replace(x, value=probability) if x.name == "DSR_EFFECTIVE" else x
                for x in saved.family_diagnostics
            ),
        )

    # A controlled numerical oracle makes the publication/read checks independent
    # of which BLAS kernel happens to be installed on the test host.
    rounded = rounded_panel(0.639614738300782)
    monkeypatch.setattr(delivery_service, "assess_candidates", lambda _: rounded)
    receipt = assemble_delivery(context, Deliverable(definition, replace(value, payload=payload)))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS

    first = saved.rows[0]
    changed_row = replace(
        first,
        diagnostics=tuple(
            replace(x, value=math.nextafter(x.value, math.inf))
            if x.metric is m.ResearchMetric.NET_ANNUAL_RETURN else x
            for x in first.diagnostics
        ),
    )
    for changed in (
        rounded_panel(probability + 1e-6),
        replace(saved, rows=(changed_row, *saved.rows[1:])),
        replace(saved, request_sha256="f" * 64),
    ):
        monkeypatch.setattr(delivery_service, "assess_candidates", lambda _, result=changed: result)
        checked = validate_delivery(context, receipt.reference)
        assert checked.status is d.ValidationStatus.FAIL
        assert checked.issues[0].code == "ASSESSMENT_RESULT"

    monkeypatch.setattr(delivery_service, "assess_candidates", lambda _: rounded)
    artifact = published(context, receipt) / "delivery.json"
    artifact.write_bytes(artifact.read_bytes() + b" ")
    checked = validate_delivery(context, receipt.reference)
    assert checked.status is d.ValidationStatus.FAIL
    assert checked.issues[0].code == "DELIVERY_FILES"


def test_stage_four_rejects_changed_targets_and_forged_panel(completed):
    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    payload = value.payload
    changed_target = replace(
        payload.comparison_request,
        targets=m.ResearchTargets(
            (
                m.ResearchTarget(
                    "net_annual_return",
                    m.ResearchMetric.NET_ANNUAL_RETURN,
                    lower=m.ConstantBound(0.0, True),
                ),
            ),
            60,
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
    other = m.AssessmentCandidate("S900-C0002", "f" * 64)
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
    source = context.root / "research/S900/mandates/1/delivery.json"
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
                d.PerformanceRequirement(
                    (
                        m.ResearchTarget(
                            "frequency_median",
                            m.ResearchMetric.FREQUENCY_MEDIAN,
                            lower=m.ConstantBound(0.0, True),
                        ),
                    )
                ),
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
                d.MandateOwner("S900"),
                d.DeliveryStage.MANDATE,
                2,
                predecessors=(payload.source_mandate,),
            ),
            replace(original, payload=mandate),
        ),
    )
    targets = replace(
        payload.comparison_request.targets,
        requirements=(
            *payload.comparison_request.targets.requirements,
            m.ResearchTarget(
                "frequency_median",
                m.ResearchMetric.FREQUENCY_MEDIAN,
                lower=m.ConstantBound(0.0, True),
            ),
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
            d.TargetMandateBinding("frequency_median", "frequency"),
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


@pytest.mark.parametrize("damage", ["missing", "content", "source"])
def test_handoff_requires_registered_content_but_published_delivery_is_independent(
    completed, damage
):
    context, _, _, _, _ = completed
    prepare(completed)
    root = context.experiments_root / "S900/20261001_S900_EX01/deliveries/CANDIDATES/1"
    document = json.loads((root / "delivery.json").read_text(encoding="utf-8"))
    definition = d.DeliveryDefinition.from_dict(document["definition"])
    value = d.DeliveryContent.from_dict(document["content"])
    receipt = d.DeliveryReceipt.from_dict(json.loads((root / "receipt.json").read_text()))
    registry = StrategyRegistry(context.research_registry_root)
    registration = registry.get_candidate(
        CandidateKey("S900", "C0001"), experiments_root=context.experiments_root
    )
    if damage == "missing":
        path = context.research_registry_root / "S900/candidates/C0001.json"
        path.rename(path.with_suffix(".removed"))
    elif damage == "content":
        path = registration.payload.resolve(context.experiments_root / "S900/20261001_S900_EX01")
        path.write_text("{}")
    else:
        path = registration.source_files[0].resolve(
            context.experiments_root / "S900/20261001_S900_EX01"
        )
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
    with pytest.raises(d.DeliveryValidationError) as error:
        assemble_delivery(context, Deliverable(replace(definition, revision=2), value))
    assert error.value.issues[0].code == "HANDOFF_REGISTRATION"
    assert not (root.parent / "2").exists()
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS


def test_report_renders_sensitivity_rows_and_behavior_members(tmp_path):
    from czsc_trader.application.delivery_service import _report

    candidate = m.AssessmentCandidate("S900-C0001", "a" * 64)
    evidence = m.AssessmentEvidence(
        candidate, "20261001_S900_EX01", "1" * 32, "2" * 64,
        "3" * 64, "4" * 64, "5" * 64, "full", "standard", "test-v1",
        m.EvaluationScenarioContext(0.001, "FORMAL", "BuyHold", "BUYHOLD", "6" * 64),
        1000.0, 1000.0, 0, 60,
        (m.AccountPoint("2026-01-05", 1000.0, 0, 1.0, 1000.0),
         m.AccountPoint("2026-01-06", 1000.0, 0, 1.0, 1000.0)),
        (), (), (1000.0, 1000.0), None, None, "7" * 64, None,
    )
    assessment = assessment_request((evidence,))
    panel = assess_candidates(assessment)
    comparison = comparison_request(panel)
    owner = d.ExperimentOwner("S900", "20261001_S900_EX01")
    definition = d.DeliveryDefinition(owner, d.DeliveryStage.ASSESSMENT, 1)
    value = content(d.CandidateAssessmentDelivery(
        d.DeliveryReference(owner, d.DeliveryStage.CANDIDATES, 1, "a" * 64),
        d.DeliveryReference(d.MandateOwner("S900"), d.DeliveryStage.MANDATE, 1, "b" * 64),
        assessment, panel, comparison, compare_candidates(comparison),
        (d.TargetMandateBinding("net_annual_return", "return"),),
        None, "benchmark", "展示合成自检结果", (), ("待用户决定",),
    ))
    result = value.payload.comparison
    result = replace(
        result,
        sensitivities=(m.SensitivityRanking("coarse-bins", result.rows, result.pairs),),
        behavior_groups=(m.BehaviorGroup("f" * 64, (result.rows[0].candidate,)),),
    )
    rendered = _report(
        definition, replace(value, payload=replace(value.payload, comparison=result)), tmp_path
    ).decode()
    assert "coarse-bins" in rendered and "f" * 64 in rendered
    assert "S900-C0001" in rendered and "逐项目标检查" in rendered


def test_validation_scope_controls_recomputation_and_always_checks_hashes(completed, monkeypatch):
    from czsc_trader.application import delivery_service

    context = completed[0]
    definition, value = prepare(completed)
    receipt = assemble_delivery(context, Deliverable(definition, value))
    calls = []
    assess, compare = delivery_service.assess_candidates, delivery_service.compare_candidates

    def counted_assess(request):
        calls.append("assessment")
        return assess(request)

    def counted_compare(request):
        calls.append("comparison")
        return compare(request)

    monkeypatch.setattr(delivery_service, "assess_candidates", counted_assess)
    monkeypatch.setattr(delivery_service, "compare_candidates", counted_compare)
    integrity = validate_delivery(context, receipt.reference, scope=d.DeliveryValidationScope.INTEGRITY)
    assert integrity.status is d.ValidationStatus.PASS
    assert integrity.scope is d.DeliveryValidationScope.INTEGRITY
    assert calls == []
    full = validate_delivery(context, receipt.reference)
    assert full.status is d.ValidationStatus.PASS
    assert full.scope is d.DeliveryValidationScope.FULL
    assert calls == ["assessment", "comparison"]
    assert d.DeliveryValidation.from_dict(full.to_dict()) == full
    with pytest.raises(TypeError, match="scope"):
        validate_delivery(context, receipt.reference, scope="INTEGRITY")
    path = delivery_service._delivery_path(context, receipt.reference) / "report.md"
    path.write_bytes(path.read_bytes() + b"altered")
    calls.clear()
    assert validate_delivery(context, receipt.reference, scope=d.DeliveryValidationScope.INTEGRITY).status is d.ValidationStatus.FAIL
    assert calls == []
