from evaluation_seed_support import prepare_request
from dataclasses import replace
import json
import pickle
import shutil

import pytest
from strategy_manager import CandidateKey, ResearchState, StrategyFamily, StrategyRegistry
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m
from czsc_trader.application import (
    RepositoryContext, assemble_delivery, validate_delivery, CandidateRegistrationRequest,
    register_candidate, publish_evidence,
)
from czsc_trader.research_tools import build_assessment_evidence
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvaluationEvidenceWrite
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_research_delivery import content, attachment, published


@pytest.fixture
def fresh_completed(managed_evaluation):
    research, request = managed_evaluation
    context = research.repository
    family = StrategyFamily(2, "S900", "Freeze fixture", "ETF", {"hypothesis": "synthetic"},
        ResearchState.RESEARCHING, "2026-10-01T00:00:00+00:00", "test", "2026-10-01T00:00:00+00:00")
    StrategyRegistry(context.research_registry_root).create_family(family, actor="test", reason="fixture")
    request = prepare_request(research, request)
    result = research.evaluation.evaluate(request)
    experiment = ExperimentRef("S900", request.experiment_id)
    reference = publish_evidence(research, EvaluationEvidenceWrite(experiment, "account", request, result))
    registration = register_candidate(context, CandidateRegistrationRequest(request.strategy, experiment, (reference,), ()))
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
    candidate_receipt = assemble_delivery(context,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 1),
        content(d.CandidateSet((entry,), (key,), (), "交接一个候选"))).receipt
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


def test_acceptance_contract_persists(prepared_acceptance_delivery):
    context, definition, value = prepared_acceptance_delivery
    receipt = assemble_delivery(context, definition, value).receipt
    assert receipt.schema_version == 12
    saved = json.loads((published(context, receipt) / "delivery.json").read_text(encoding="utf-8"))
    assert d.DeliveryContent.from_dict(saved["content"]) == value
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    result = value.payload.comparison.rows[0]
    assert result.acceptance_status is m.TargetCheckStatus.INDETERMINATE
    assert result.pareto_layer is None
    assert len(result.target_checks) == 4
    with pytest.raises(ValueError, match="invalid delivery revision/schema"):
        replace(definition, schema_version=7)
    from czsc_trader.application import delivery_service
    with pytest.raises(d.DeliveryValidationError, match="version differs"):
        delivery_service._validate_parameter_method_schema(replace(definition, schema_version=11), value.payload)
    old_panel = replace(value.payload.assessment, formula_version="research-assessment-v6")
    old_comparison = replace(value.payload.comparison_request, panel=old_panel)
    with pytest.raises(d.DeliveryValidationError, match="version differs"):
        delivery_service._validate_parameter_method_schema(definition, replace(value.payload,
            assessment=old_panel, comparison_request=old_comparison))


def test_account_reuse_still_checks_current_file_and_reference_owner(completed):
    from czsc_trader.application import delivery_service

    context, _, _, _, evaluation = completed
    reference = evaluation.evidence
    root = context.root / ".tmp/account-authentication"
    target = root / reference.path
    target.parent.mkdir(parents=True)
    target.write_bytes(reference.resolve(context.root).read_bytes())
    cache = {}
    first = delivery_service._account_document(root, reference, cache)
    assert set(cache) == {reference.sha256}
    assert set(first[0]) == {"schema_version", "request_hash", "request_identity", "execution_policies"}
    wrong_owner = replace(reference, experiment=ExperimentRef("S900", "EX999_20261001"))
    with pytest.raises(d.DeliveryValidationError, match="origin differs"):
        delivery_service._account_document(root, wrong_owner, cache)
    assert delivery_service._account_document(root, reference, cache) == first
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(d.DeliveryValidationError, match="hash differs"):
        delivery_service._account_document(root, reference, cache)


def test_parallel_authentication_failure_never_publishes_a_delivery(completed):
    from strategy_runtime.resources import ExecutionResources
    from czsc_trader.research_tools.evidence import MaterialEvidenceWrite

    context, research, request, result, good = completed
    malformed = publish_evidence(research, MaterialEvidenceWrite(
        good.evidence.experiment, "malformed-account", b'{"schema_version":7}', "application/json", "json"))
    malformed = replace(malformed, schema="account_evaluation", schema_version=7)
    candidate = build_assessment_evidence(request, result)[0].candidate
    entry = d.CandidateEntry(d.CandidateIdentityRef(CandidateKey("S900", "C0001"), candidate.content_sha256),
        "合成机制", "认证失败必须拒绝发布", (good, d.EvaluationEvidenceRef(malformed)))
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 1)
    with pytest.raises(d.DeliveryValidationError) as failed:
        assemble_delivery(context, definition, content(d.CandidateSet((entry,), (), (), "验证认证失败")),
                          resources=ExecutionResources(max_workers=2))
    assert failed.value.issues[0].code == "ACCOUNT_AUTHENTICATION"
    assert not (context.root / "research/S900/assets/deliveries/CANDIDATES/1").exists()
    assert not (context.root / "research/S900/deliveries/CANDIDATES/1").exists()


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


def test_unregistered_account_prototype_is_accepted_in_all_attachment_roles(managed_evaluation, monkeypatch):
    research, request = managed_evaluation
    request = prepare_request(research, request)
    result = research.evaluation.evaluate(request)
    account = publish_evidence(research, EvaluationEvidenceWrite(
        ExperimentRef("S900", request.experiment_id), "unregistered-account", request, result))

    def no_registration(*args, **kwargs):
        pytest.fail("account attachment must not require candidate registration")

    monkeypatch.setattr(StrategyRegistry, "get_candidate_registration", no_registration)
    for revision, location in enumerate(("component-test", "component-attachment", "candidate-attachment", "search"), 1):
        stage, value = _account_attachment_content(research, (account,), location)
        assembled = assemble_delivery(research.repository, d.DeliveryDefinition(research.batch, stage, revision), value)
        assert assembled.validation.stats.accounts_authenticated == 1
        for scope in d.DeliveryValidationScope:
            checked = validate_delivery(research.repository, assembled.receipt.reference, scope=scope)
            assert checked.status is d.ValidationStatus.PASS
            assert checked.stats.accounts_authenticated == 1


@pytest.mark.parametrize("location", ["component-test", "component-attachment", "candidate-attachment", "search"])
def test_account_attachment_roles_reject_opaque_material_relabelled_as_account(completed, location):
    context, research, _, _, _ = completed
    material = attachment(research, "opaque", {"schema_version": 7})
    stage, ordinary = _account_attachment_content(research, (material,), location)
    definition = d.DeliveryDefinition(research.batch, stage, 1)
    receipt = assemble_delivery(context, definition, ordinary).receipt
    account = replace(material, schema="account_evaluation", schema_version=7)
    _, claimed = _account_attachment_content(research, (account,), location)
    with pytest.raises(d.DeliveryValidationError) as failed:
        assemble_delivery(context, replace(definition, revision=2), claimed)
    assert failed.value.issues[0].code == "ACCOUNT_AUTHENTICATION"
    assert failed.value.issues[0].field_path == account.path
    for prefix in ("assets/deliveries", "deliveries"):
        assert not (context.root / f"research/S900/{prefix}/{stage.value}/2").exists()
    forged = _reseal_test_delivery(context, receipt, claimed)
    for scope in d.DeliveryValidationScope:
        checked = validate_delivery(context, forged, scope=scope)
        assert checked.status is d.ValidationStatus.FAIL
        assert checked.issues[0].code == "ACCOUNT_AUTHENTICATION"
        assert checked.issues[0].field_path == account.path


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.parametrize("damage,code", [
    ("json", "ACCOUNT_AUTHENTICATION"),
    ("duplicate-key", "ACCOUNT_AUTHENTICATION"),
    ("identity-type", "ACCOUNT_AUTHENTICATION"),
    ("missing-scenario", "ACCOUNT_AUTHENTICATION"),
    ("deep-json", "ACCOUNT_AUTHENTICATION"),
    ("ledger", "ACCOUNT_AUTHENTICATION"),
    ("version", "EVALUATION_REFERENCE"),
    ("hash", "EVIDENCE_HASH"),
])
def test_account_attachment_failures_have_same_codes_in_serial_and_parallel(completed, workers, damage, code):
    from strategy_runtime.resources import ExecutionResources
    from czsc_trader.research_tools.evidence import MaterialEvidenceWrite

    context, research, _, _, evaluation = completed
    good = evaluation.evidence
    data = good.resolve(context.root).read_bytes()
    if damage == "json":
        data = b'{"schema_version":'
    elif damage == "deep-json":
        data = b"[" * 100_000 + b"0" + b"]" * 100_000
    elif damage == "duplicate-key":
        data = b'{"schema_version":7,' + data.lstrip()[1:]
    elif damage in ("ledger", "identity-type", "missing-scenario"):
        document = json.loads(data)
        if damage == "ledger":
            document["runs"][0]["ledgers"]["account_daily"]["data"][0]["cash"] += 1.0
        elif damage == "missing-scenario":
            from strategy_runtime import canonical_sha256

            document["request_identity"]["costs"] = []
            document["request_hash"] = canonical_sha256(document["request_identity"])
            for record in document["assessment_evidence"]:
                record["request_sha256"] = document["request_hash"]
        else:
            document["request_identity"] = []
        data = json.dumps(document).encode()
    else:
        data += b"\n"
    material = publish_evidence(research, MaterialEvidenceWrite(
        good.experiment, "tampered-account", data, "application/json", "json"))
    bad = replace(material, schema="account_evaluation", schema_version=9 if damage == "version" else good.schema_version)
    resources = ExecutionResources(max_workers=workers)
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1)
    # Ordinary material remains opaque even if its bytes are malformed JSON.
    receipt = assemble_delivery(context, definition, content(evidence=(good, material)), resources=resources).receipt
    claimed = content(evidence=(good, bad))
    if damage != "hash":
        with pytest.raises(d.DeliveryValidationError) as failed:
            assemble_delivery(context, replace(definition, revision=2), claimed, resources=resources)
        assert failed.value.issues[0].code == code, failed.value.issues
        assert failed.value.issues[0].field_path == bad.path
        assert failed.value.issues[0].message.strip()
        assert not (context.root / "research/S900/assets/deliveries/COMPONENTS/2").exists()
        assert not (context.root / "research/S900/deliveries/COMPONENTS/2").exists()
    else:
        # Re-sign the manifest, but preserve the account reference's original hash.
        (published(context, receipt) / bad.path).write_bytes(data + b"changed")
    forged = _reseal_test_delivery(context, receipt, claimed)
    for scope in d.DeliveryValidationScope:
        checked = validate_delivery(context, forged, scope=scope, resources=resources)
        assert checked.status is d.ValidationStatus.FAIL
        assert checked.issues[0].code == code
        assert checked.issues[0].field_path == bad.path
        assert checked.issues[0].message.strip()


@pytest.mark.parametrize("workers", [1, 2])
def test_account_attachment_cache_rechecks_each_reference_owner(completed, workers):
    from strategy_runtime.resources import ExecutionResources
    from czsc_trader.research_tools.evidence import MaterialEvidenceWrite

    context, research, _, _, evaluation = completed
    good = evaluation.evidence
    # A second distinct but valid document makes max_workers=2 actually use workers.
    companion = publish_evidence(research, MaterialEvidenceWrite(good.experiment, "companion-account",
        good.resolve(context.root).read_bytes() + b"\n", "application/json", "json"))
    companion = replace(companion, schema="account_evaluation", schema_version=good.schema_version)
    resources = ExecutionResources(max_workers=workers)
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1)
    receipt = assemble_delivery(context, definition, content(evidence=(good, companion)), resources=resources).receipt
    wrong = replace(good, experiment=ExperimentRef("S900", "EX999_20261007"))
    # The correct and incorrect owner references intentionally have identical bytes/hash.
    target = context.root / wrong.repository_path
    target.parent.mkdir(parents=True)
    target.write_bytes(good.resolve(context.root).read_bytes())
    claimed = content(evidence=(good, companion, wrong))
    with pytest.raises(d.DeliveryValidationError) as failed:
        assemble_delivery(context, replace(definition, revision=2), claimed, resources=resources)
    assert failed.value.issues[0].code == "EVALUATION_REFERENCE"
    forged = _reseal_test_delivery(context, receipt, claimed)
    for scope in d.DeliveryValidationScope:
        checked = validate_delivery(context, forged, scope=scope, resources=resources)
        assert checked.status is d.ValidationStatus.FAIL
        assert checked.issues[0].code == "EVALUATION_REFERENCE"


@pytest.mark.parametrize("damage,code", [
    ("candidate", "CANDIDATE_CONFLICT"), ("evaluation-id", "EVALUATION_REFERENCE"),
])
def test_candidate_binding_remains_required_after_shared_account_authentication(completed, damage, code):
    context, research, request, result, evaluation = completed
    candidate = build_assessment_evidence(request, result)[0].candidate
    entry = d.CandidateEntry(d.CandidateIdentityRef(CandidateKey("S900", "C0001"), candidate.content_sha256),
        "合成机制", "验证候选绑定", (evaluation,))
    value = content(d.CandidateSet((entry,), (), (), "验证额外身份约束"), evidence=(evaluation.evidence,))
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 1)
    receipt = assemble_delivery(context, definition, value).receipt
    if damage == "candidate":
        entry = replace(entry, identity=replace(entry.identity, content_sha256="0" * 64))
    else:
        entry = replace(entry, evaluations=(replace(evaluation, evaluation_ids=("0" * 64,)),))
    changed = replace(value, payload=replace(value.payload, candidates=(entry,)))
    with pytest.raises(d.DeliveryValidationError) as failed:
        assemble_delivery(context, replace(definition, revision=2), changed)
    assert failed.value.issues[0].code == code
    forged = _reseal_test_delivery(context, receipt, changed)
    for scope in d.DeliveryValidationScope:
        checked = validate_delivery(context, forged, scope=scope)
        assert checked.status is d.ValidationStatus.FAIL
        assert checked.issues[0].code == code


def test_adapter_authenticates_requests_and_does_not_reload_source(completed):
    _, execution, request, result, _ = completed

    shutil.rmtree(request.strategy.source_root)
    evidence = build_assessment_evidence(request, result)
    assert evidence[0].evaluation_id == result.runs[0].identity.evaluation_id
    assert evidence[0].candidate.candidate_id == "S900-C0001"
    with pytest.raises(ValueError, match="identity differs"):
        build_assessment_evidence(replace(request, initial_cash=request.initial_cash + 1), result)
    with pytest.raises(ValueError, match="identity differs"):
        build_assessment_evidence(request, replace(result, result_hash="f" * 64))
    original = result.runs[0]
    changed = replace(result, runs=(replace(original, signals=replace(original.signals,
        support_data={**original.signals.support_data, "available_through": "2099-01-01"})),))
    with pytest.raises(ValueError, match="identity differs"):
        build_assessment_evidence(request, changed)


def test_stage_four_integrity_roundtrip_and_source_cleanup(completed):
    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    comparison = value.payload.comparison_request
    assert comparison.panel.formula_version == "research-assessment-v7"
    assert comparison.policy.formula_version == "research-ranking-v4"
    assert len(comparison.policy.bins) == 8
    comparison = replace(comparison, policy=replace(comparison.policy, sensitivities=(m.ComparisonVariant("coarse-bins", comparison.policy.bins),)))
    value = replace(value, payload=replace(value.payload, comparison_request=comparison, comparison=compare_candidates(comparison)))
    receipt = assemble_delivery(context, definition, value).receipt
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    report = (published(context, receipt) / "report.md").read_text(encoding="utf-8")
    assert report == value.report
    document = json.loads(
        (published(context, receipt) / "delivery.json").read_text(encoding="utf-8")
    )
    assert d.DeliveryContent.from_dict(document["content"]) == value
    temporary = (context.root / ".tmp").resolve()
    assert temporary.is_relative_to(context.root.resolve())
    shutil.rmtree(temporary)
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, definition, value).receipt == receipt


@pytest.mark.parametrize("version", [8, 11])
def test_historical_assessment_integrity_preserves_original_schema(completed, version):
    """Install historical fixture bytes directly; never use a legacy publication path."""
    from czsc_trader.application import delivery_service as service
    from strategy_evaluator.research_assessment import (
        recompute_historical_assessment, recompute_historical_comparison,
    )

    context = completed[0]
    definition, value = prepare(completed)
    receipt = assemble_delivery(context, definition, value).receipt
    request = value.payload.assessment_request
    if version == 8:
        protocol = m.SelfCheckProtocol("historical", "full", "standard", "fee_x2",
            2, 1, m.QuantileMethod.LINEAR, 1, 1, 40, 2, 1, 1e-7, pbo_blocks=2)
    else:
        protocol = replace(request.protocol, parameter_protocol=m.ParameterNeighborhoodProtocol(
            version="parameter-cartesian-neighborhood-v1"))
    request = replace(request, protocol=protocol)
    panel = recompute_historical_assessment(request)
    comparison = replace(value.payload.comparison_request, panel=panel,
        policy=replace(value.payload.comparison_request.policy, formula_version="research-ranking-v3"))
    historical = replace(value, payload=replace(value.payload, assessment_request=request, assessment=panel,
        comparison_request=comparison, comparison=recompute_historical_comparison(comparison)))
    old_definition = replace(definition, schema_version=version)
    root = published(context, receipt)
    (root / "delivery.json").write_bytes(d._canonical({"schema_version": version,
        "definition": old_definition.to_dict(), "content": historical.to_dict()}))
    files = service._manifest(root)
    old_receipt = replace(receipt, schema_version=version, files=files,
        reference=replace(receipt.reference, content_sha256=d._digest(files)))
    for directory in (root, service._public_delivery_path(context, receipt.reference)):
        (directory / "receipt.json").write_bytes(d._canonical(old_receipt))
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert validate_delivery(context, old_receipt.reference).status is d.ValidationStatus.PASS
    assert before == {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(d.DeliveryValidationError, match="read-only"):
        assemble_delivery(context, old_definition, historical)


def test_stage_four_rejects_old_formula_versions(completed):
    context, _, _, _, _ = completed
    definition, value = prepare(completed)
    payload = value.payload
    old_panel = payload.assessment.to_dict()
    old_panel["formula_version"] = "research-assessment-v3"
    with pytest.raises(ValueError, match="unsupported assessment formula version"):
        m.AssessmentPanel.from_dict(old_panel)
    old_policy = payload.comparison_request.policy.to_dict()
    old_policy["formula_version"] = "research-ranking-v1"
    with pytest.raises(ValueError, match="unsupported ranking formula version"):
        m.ComparisonPolicy.from_dict(old_policy)



@pytest.mark.parametrize("damage", ["missing", "content", "source"])
def test_handoff_requires_registered_content_but_published_delivery_is_independent(
    completed, damage
):
    context, _, _, _, _ = completed
    prepare(completed)
    root = context.research_root / "S900/assets/deliveries/CANDIDATES/1"
    document = json.loads((root / "delivery.json").read_text(encoding="utf-8"))
    definition = d.DeliveryDefinition.from_dict(document["definition"])
    value = d.DeliveryContent.from_dict(document["content"])
    receipt = d.DeliveryReceipt.from_dict(json.loads((root / "receipt.json").read_text()))
    registry = StrategyRegistry(context.research_registry_root)
    registration = registry.get_candidate(
        CandidateKey("S900", "C0001"), evidence_root=context.research_root / "S900"
    )
    if damage == "missing":
        path = context.research_registry_root / "S900/candidates/C0001.json"
        path.rename(path.with_suffix(".removed"))
    elif damage == "content":
        path = registration.payload.resolve(context.research_root / "S900")
        path.write_text("{}")
    else:
        path = registration.source_files[0].resolve(
            context.research_root / "S900"
        )
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
    with pytest.raises(d.DeliveryValidationError) as error:
        assemble_delivery(context, replace(definition, revision=2), value).receipt
    assert error.value.issues[0].code == "HANDOFF_REGISTRATION"
    assert not (root.parent / "2").exists()
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS




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


def test_assessment_integrity_is_default_and_full_is_unsupported(prepared_delivery, monkeypatch):
    from czsc_trader.application import delivery_service

    context, definition, value = prepared_delivery
    assembled = assemble_delivery(context, definition, value)

    def forbidden(*args, **kwargs):
        pytest.fail("assessment integrity must not process account facts")

    monkeypatch.setattr(delivery_service, "_certify_account", forbidden)
    checked = validate_delivery(context, assembled.receipt.reference)
    assert checked.status is d.ValidationStatus.PASS
    assert checked.scope is d.DeliveryValidationScope.INTEGRITY
    assert checked.stats.accounts_authenticated == 0
    assert checked.stats.recomputation_seconds == 0
    assert d.DeliveryValidation.from_dict(checked.to_dict()) == checked
    full = validate_delivery(context, assembled.receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert full.status is d.ValidationStatus.FAIL
    assert full.issues[0].code == "UNSUPPORTED_SCOPE"
    with pytest.raises(TypeError, match="scope"):
        validate_delivery(context, assembled.receipt.reference, scope="INTEGRITY")
    path = published(context, assembled.receipt) / "report.md"
    path.write_bytes(path.read_bytes() + b"altered")
    checked = validate_delivery(context, assembled.receipt.reference)
    assert checked.status is d.ValidationStatus.FAIL
    assert checked.issues[0].code == "DELIVERY_FILES"
