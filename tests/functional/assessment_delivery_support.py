# Risk ownership: TDR-12
from historical_evaluation_support import prepare_historical as prepare_request, evaluate_historical, publish_historical
from dataclasses import replace
import json
import pickle
import shutil

import pytest
from strategy_manager import CandidateKey, ResearchState, StrategyFamily, StrategyRegistry
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m
from czsc_trader.application import (
    RepositoryContext, assemble_delivery,
)
from historical_evaluation_support import historical_assessment as build_assessment_evidence
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from managed_evaluation_support import managed_evaluation as managed_evaluation
from test_research_delivery import content, attachment, published
from historical_candidate_support import seed_historical_candidate


@pytest.fixture
def fresh_completed(managed_evaluation):
    research, request = managed_evaluation
    context = research.repository
    family = StrategyFamily(2, "S900", "Freeze fixture", "ETF", {"hypothesis": "synthetic"},
        ResearchState.RESEARCHING, "2026-10-01T00:00:00+00:00", "test", "2026-10-01T00:00:00+00:00")
    StrategyRegistry(context.research_registry_root).create_family(family, actor="test", reason="fixture")
    request = prepare_request(research, request)
    result = evaluate_historical(research, request)
    experiment = ExperimentRef("S900", request.experiment_id)
    reference = publish_historical(research, request, result)
    registration = seed_historical_candidate(context, request.strategy, experiment, (reference,), request.dependencies)
    assert registration.payload.path == f"assets/candidates/C0001/payload/{registration.payload.sha256}.json"
    assert registration.source_root == f"assets/candidates/C0001/source/{registration.source_sha256}/strategy_runtime"
    assert all(item.path.startswith(f"{registration.source_root}/") for item in registration.source_files)
    assert registration.origin.evidence[0].path == f"assets/evidence/{experiment.experiment_id}/{reference.evidence_id}"
    evidence = build_assessment_evidence(request, result)
    return context, research, request, result, d.EvaluationEvidenceRef(reference, tuple(x.evaluation_id for x in evidence))


@pytest.fixture
def completed(request, tmp_path, frozen_seed_root):
    """Generate real supporting evidence once; isolate every consumer's files/frames."""
    from czsc_trader.research_tools._evaluation_workers import pack
    from evaluation_seed_support import relocate_request, relocate_result, restored_context

    seed = frozen_seed_root / "completed-evaluation"
    data = frozen_seed_root / "completed-evaluation.pkl"
    if not seed.exists():
        context, _, evaluation, result, reference = request.getfixturevalue("fresh_completed")
        data.write_bytes(pack((evaluation, result, reference)))
        shutil.copytree(context.root, seed)
    root = tmp_path / "completed-repo"
    shutil.copytree(seed, root)
    evaluation, result, reference = pickle.loads(data.read_bytes())
    result = relocate_result(result, evaluation, root)
    evaluation = relocate_request(evaluation, root)
    research = restored_context(root)
    return research.repository, research, evaluation, result, reference


def assessment_request(evidence):
    protocol = m.NeighborhoodSelfCheckProtocol(
        "1",
        "full",
        "standard",
        "fee_x2",
        2,
        1,
        m.QuantileMethod.LINEAR,
        1,
        40,
        2,
        1,
        1e-7,
        parameter_protocol=m.ParameterNeighborhoodProtocol(),
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


def _seed_historical_delivery(context, definition, value):
    """Store an archived fixture; new publications cannot write this retired contract."""
    from czsc_trader.application.delivery_service import _references, _manifest, _delivery_path, _public_delivery_path
    root = _delivery_path(context, definition)
    root.mkdir(parents=True)
    for reference in _references(value):
        target = root / reference.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(reference._read_verified(context.root)[1])
    (root / "delivery.json").write_bytes(d._canonical({"schema_version": definition.schema_version,
        "definition": definition.to_dict(), "content": value.to_dict()}))
    (root / "report.md").write_bytes(value.report.encode("utf-8"))
    files = _manifest(root)
    reference = d.DeliveryReference(definition.batch, definition.stage, definition.revision, d._digest(files))
    receipt = d.DeliveryReceipt(reference, files, schema_version=definition.schema_version)
    (root / "receipt.json").write_bytes(d._canonical(receipt))
    public = _public_delivery_path(context, reference)
    public.mkdir(parents=True)
    for name in ("receipt.json", "report.md"):
        shutil.copyfile(root / name, public / name)
    return receipt


def prepare(completed, targets=None):
    context, research, request, result, evaluation = completed
    evidence = build_assessment_evidence(request, result)
    assessment = assessment_request(evidence)
    if targets is not None:
        assessment = replace(assessment, protocol=replace(
            assessment.protocol, frequency_min_closed_cycles=3))
    panel = assess_candidates(assessment)
    comparison = comparison_request(panel)
    if targets is not None:
        comparison = replace(comparison, targets=m.ResearchTargets(targets, 60))
    confirmation = attachment(research, "confirmation", {"user": "合成测试：净年化下界 -1"})
    mandate = d.ResearchMandate((
        d.MandateItem("return", d.MandateItemKind.OBJECTIVE, "净年化下界",
            d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation),
            d.PerformanceRequirement(comparison.targets.requirements)),
        d.MandateItem("benchmark", d.MandateItemKind.BENCHMARK, "显式基准",
            d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation), d.BenchmarkRequirement(request.benchmark)),
        *((d.MandateItem("frequency_days", d.MandateItemKind.EXECUTION, "统计窗口",
            d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation),
            d.NumericRequirement("frequency_window_days", "sessions", lower=60.0, upper=60.0)),)
          if targets is not None else ()),
    ))
    mandate_receipt = assemble_delivery(context,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.MANDATE, 1), content(mandate)).receipt
    key = CandidateKey("S900", "C0001")
    identity = d.CandidateIdentityRef(key, evidence[0].candidate.content_sha256)
    entry = d.CandidateEntry(identity, "完整可执行假设", "提交自检", (evaluation,))
    candidate_receipt = _seed_historical_delivery(context,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 1),
        content(d.CandidateSet((entry,), (key,), (), "交接一个候选")))
    payload = d.CandidateAssessmentDelivery(candidate_receipt.reference, mandate_receipt.reference,
        assessment, panel, comparison, compare_candidates(comparison),
        tuple(d.TargetMandateBinding(x.target_id, "return") for x in comparison.targets.requirements),
        "frequency_days" if targets is not None else None, "benchmark",
        "先补充缺失自检证据，再由用户选型", (evaluation.evidence,), ("是否补做压力与参数扰动实验",))
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.ASSESSMENT, 1,
        predecessors=(candidate_receipt.reference, mandate_receipt.reference))
    return definition, replace(content(payload), status=d.DeliveryStatus.PARTIAL,
                               incomplete_items=("压力与扰动实验尚未完成",))


def acceptance_targets():
    return (
        m.ResearchTarget("median", m.ResearchMetric.FREQUENCY_MEDIAN,
                         lower=m.ConstantBound(6.0, True)),
        m.FrequencyCoverageTarget("coverage", 60, 3, 9, 10),
        m.ParameterNeighborhoodTarget("parameters", 13, 16,
            (m.ResearchTarget("point-return", m.ResearchMetric.NET_ANNUAL_RETURN,
                             lower=m.ConstantBound(0.0, False), one_way_cost=0.001),),
            (m.ResearchTarget("point-dd", m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                             upper=m.ConstantBound(0.25, True), one_way_cost=0.001),)),
        m.ResearchTarget("stress-return", m.ResearchMetric.NET_ANNUAL_RETURN,
                         lower=m.BenchmarkBound(1.0, False),
                         scope=m.TargetScope.STRESS, one_way_cost=0.002),
    )


def _account_attachment_content(research, references, location):
    """Explicit account references need no CandidateEntry or registration."""
    if location == "component-test":
        protocol = attachment(research, "component-protocol")
        test = d.ComponentTestResult("comparison", "EX999_20261007", protocol,
            d.ComponentTestStatus.SUPPORTED, "允许复用本批次其他实验的账户", references)
        component = d.ComponentEntry("component", d.ExperimentDefinitionRef(protocol, "prototype"),
            "入场", "收益", "一日", "固定对照", "决策前", "复权价格", "开发池", "研究员判断", (test,))
        return d.DeliveryStage.COMPONENTS, content(d.ComponentPanel((component,), "组件账户证据"))
    if location == "component-attachment":
        return d.DeliveryStage.COMPONENTS, content(evidence=references)
    searches = ((d.SearchSummary("search", "固定对照", "开发池", 1, 1,
        "未选出候选", evidence=references),) if location == "search" else ())
    return d.DeliveryStage.CANDIDATES, content(d.CandidateSet((), (), searches, "无候选交接"),
        evidence=references if location == "candidate-attachment" else ())


def _reseal_test_delivery(context, receipt, value):
    """Forge only the isolated fixture's outer envelope to test inner authentication."""
    from czsc_trader.application.delivery_service import _manifest, _public_delivery_path

    root = published(context, receipt)
    document = json.loads((root / "delivery.json").read_bytes())
    document["content"] = value.to_dict()
    (root / "delivery.json").write_bytes(d._canonical(document))
    files = _manifest(root)
    forged = replace(receipt, reference=replace(receipt.reference, content_sha256=d._digest(files)), files=files)
    for directory in (root, _public_delivery_path(context, receipt.reference)):
        (directory / "receipt.json").write_bytes(d._canonical(forged))
    return forged.reference






@pytest.fixture
def prepared_delivery(request, tmp_path, frozen_seed_root):
    return _prepared_delivery_copy(request, tmp_path, frozen_seed_root)


@pytest.fixture
def prepared_acceptance_delivery(request, tmp_path, frozen_seed_root):
    return _prepared_delivery_copy(request, tmp_path, frozen_seed_root, acceptance_targets())


def _prepared_delivery_copy(request, tmp_path, frozen_seed_root, targets=None):
    """Copy real stage-three preparation without repeating it for numeric faults."""
    from czsc_trader.research_tools._evaluation_workers import pack
    name = "tdr-assessment-delivery-input" if targets is None else "tdr-acceptance-delivery-input"
    seed = frozen_seed_root / name
    data = frozen_seed_root / (name + ".pkl")
    if not seed.exists():
        completed = request.getfixturevalue("completed")
        definition, value = prepare(completed, targets)
        shutil.copytree(completed[0].root, seed)
        data.write_bytes(pack((definition, value)))
    root = tmp_path / "assessment-repo"
    shutil.copytree(seed, root)
    definition, value = pickle.loads(data.read_bytes())
    return RepositoryContext.discover(root), definition, value
