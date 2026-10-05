from delivery_workspace_support import fixture_delivery_workspace, fixture_research_workspace
from strategy_evaluator import research_models as m
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from factor_signal_catalog import (
    CatalogRegistry, CatalogStatus, FactorDefinition, InformationFamily, SignalDefinition,
)
from research_experiment import (
    EvaluationAttemptStatus,
    EvaluationRecord,
    ExperimentArtifact,
    ExperimentOutcome,
    ExperimentResult,
    ExperimentTrace,
    ExperimentDataScope,
    ExperimentReceipt,
    load_experiment_input,
)
from strategy_manager import CandidateKey
from strategy_runtime import canonical_sha256

from czsc_trader.application import RepositoryContext, assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d


class Deliverable(d.ResearchDeliverable):
    def __init__(self, definition, content):
        self._definition = definition
        self.content = content

    @property
    def definition(self):
        return self._definition

    def build(self):
        return self.content


@pytest.fixture
def context(tmp_path):
    (tmp_path / "src/czsc_trader").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("")
    result = RepositoryContext.discover(tmp_path, delivery_workspace=fixture_delivery_workspace(), research_workspace=fixture_research_workspace())
    owner_experiment(result)
    return result


def content(payload=None, **kwargs):
    return d.DeliveryContent(
        payload=payload if payload is not None else d.ComponentPanel((), "未发现支持机制的证据"),
        status=d.DeliveryStatus.COMPLETE,
        facts=(),
        explanations=(),
        reproduction=d.ReproductionSpec("仅复核声明证据", (), "合成数据，无外部权限", "确定性"),
        **kwargs,
    )


def definition(stage=d.DeliveryStage.COMPONENTS, **kwargs):
    return d.DeliveryDefinition(
        d.MandateOwner("S900")
        if stage is d.DeliveryStage.MANDATE
        else d.ExperimentOwner("S900", "20261001_S900_EX01"),
        stage,
        1,
        **kwargs,
    )


def attachment(context, name="source.json", value=None):
    source = context.root / ".tmp" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        json.dumps(value if value is not None else {"measurement": 0.25}), encoding="utf-8"
    )
    return d.EvidenceFile(
        source.relative_to(context.root).as_posix(),
        d.EvidenceRef(
            f"attachments/{name}", sha256(source.read_bytes()).hexdigest(), "application/json"
        ),
    )


def published(context, receipt):
    from czsc_trader.application.delivery_service import _delivery_path

    return _delivery_path(context, receipt.reference)


def experiment(context, *, records=(), number=1, predecessors=None):
    """Construct deterministic executor-format evidence, verified by the real REX reader."""
    experiment_id = f"20261001_S900_EX{number:02}"
    root = context.root / ".tmp" / experiment_id
    root.mkdir(parents=True)
    (root / "result.json").write_text('{"measurement":0.25}')
    artifact = ExperimentArtifact(
        "result.json", "measurement", sha256((root / "result.json").read_bytes()).hexdigest()
    )
    result = ExperimentResult(ExperimentOutcome.PASS, {"measurement": 0.25}, {}, (artifact,))
    trace = ExperimentTrace(
        capabilities=(),
        operations=(),
        data_requests=(),
        evaluations=records,
        data_scope=ExperimentDataScope.DEVELOPMENT,
    )
    receipt = ExperimentReceipt._from_execution(
        schema_version=2,
        experiment_id=experiment_id,
        definition_sha256="a" * 64,
        source_sha256="b" * 64,
        resources_sha256="c" * 64,
        predecessor_receipts=predecessors or {},
        result_sha256=canonical_sha256(result.to_dict()),
        artifact_sha256={artifact.path: artifact.sha256},
        trace=trace,
    )
    (root / "execution_receipt.json").write_text(
        json.dumps({**receipt.to_dict(), "receipt_sha256": receipt.sha256})
    )
    (root / "execution_envelope.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "receipt": receipt.to_dict(),
                "receipt_sha256": receipt.sha256,
                "result": result.to_dict(),
            }
        )
    )
    load_experiment_input(root, expected_receipt_sha256=receipt.sha256)
    return d.ExperimentEvidenceRef(
        experiment_id,
        root.relative_to(context.root).as_posix(),
        receipt.sha256,
        use=d.ExperimentEvidenceUse.CURRENT_EVALUATION,
    ), artifact


def failed_record(number=1, digest="d" * 64):
    return EvaluationRecord(
        attempt_id="1" * 32,
        experiment_id=f"20261001_S900_EX{number:02}",
        candidate_id="S900-C0001",
        content_sha256=digest,
        request_hash="e" * 64,
        status=EvaluationAttemptStatus.FAILED,
        started_at="2026-10-01T00:00:00+00:00",
        requested_count=1,
        completed_count=0,
        finished_at="2026-10-01T00:00:01+00:00",
        elapsed_seconds=1.0,
        error_code="SYNTHETIC_ERROR",
        error_message="No account result",
    )




def new_named_experiment(context, strategy_id="S900"):
    from test_research_experiment import _write_v3_experiment, _flows
    from research_experiment import (
        experiment_source_sha256, load_experiment, ExperimentWorkspace, ExperimentResources,
    )
    from czsc_trader.research_tools import create_experiment_context, execute_experiment

    root = (context.root / "experiments") / strategy_id / "EX078_20261003"
    _write_v3_experiment(root)
    source = root / "experiment.py"
    source.write_text(
        source.read_text().replace("20260925_S009_EX99", root.name).replace("S009", strategy_id)
    )
    binding_path = root / "experiment_binding.json"
    binding = json.loads(binding_path.read_text())
    binding["source_sha256"] = experiment_source_sha256(root, ("experiment.py",))
    binding_path.write_text(json.dumps(binding))
    loaded = load_experiment(root)
    execution = create_experiment_context(
        loaded.definition,
        repository_root=context.root,
        dataflows=_flows(context.root),
        workspace=ExperimentWorkspace(context.root / ".tmp" / strategy_id / root.name, context.root),
        resources=ExperimentResources(1, loaded.definition.random_seed),
    )
    result = execute_experiment(loaded, execution)
    shutil.copytree(execution.workspace.root, root / "artifacts")
    return root, d.ExperimentEvidenceRef(
        root.name, (root / "artifacts").relative_to(context.root).as_posix(),
        result.receipt.sha256, d.ExperimentEvidenceUse.CURRENT_EVALUATION,
    )


def test_new_experiment_name_publishes_real_executor_receipt(context):
    root, ref = new_named_experiment(context)
    defined = d.DeliveryDefinition(
        d.ExperimentOwner("S900", root.name), d.DeliveryStage.COMPONENTS, 1, experiments=(ref,)
    )
    receipt = assemble_delivery(context, Deliverable(defined, content()))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS


def test_delivery_rejects_foreign_family_executor_receipt(context):
    root, ref = new_named_experiment(context)
    defined = d.DeliveryDefinition(
        d.ExperimentOwner("S900", root.name), d.DeliveryStage.COMPONENTS, 1, experiments=(ref,)
    )
    _, foreign = new_named_experiment(context, "S901")
    with pytest.raises(d.DeliveryValidationError, match="bound experiment"):
        assemble_delivery(
            context, Deliverable(replace(defined, revision=2, experiments=(foreign,)), content())
        )
    assert not (root / "deliveries").exists()


def test_new_experiment_owner_rejects_definition_from_other_family(context):
    root, _ = new_named_experiment(context, "S901")
    target = (context.root / "experiments") / "S900" / root.name
    shutil.copytree(root, target)
    defined = d.DeliveryDefinition(
        d.ExperimentOwner("S900", root.name), d.DeliveryStage.COMPONENTS, 1
    )
    with pytest.raises(d.DeliveryValidationError, match="definition family or ID differs"):
        assemble_delivery(context, Deliverable(defined, content()))


@pytest.mark.parametrize("name", ["EX000_20261003", "EX78_20261003", "EX1000_20261003"])
def test_experiment_evidence_rejects_invalid_sequence(name):
    with pytest.raises(ValueError, match="invalid experiment_id"):
        d.ExperimentEvidenceRef(name, "artifacts", "a" * 64, d.ExperimentEvidenceUse.CURRENT_EVALUATION)


def test_negative_delivery_is_complete_idempotent_and_immutable(context):
    from czsc_trader.research_tools import ResearchDeliverable, DeliveryDefinition, DeliveryContent

    assert ResearchDeliverable is d.ResearchDeliverable
    assert DeliveryDefinition is d.DeliveryDefinition
    assert DeliveryContent is d.DeliveryContent
    deliverable = Deliverable(definition(), content())
    first = assemble_delivery(context, deliverable)
    assert validate_delivery(context, first.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, deliverable) == first
    report = (published(context, first) / "report.md").read_text(encoding="utf-8")
    assert "未发现支持机制的证据" in report
    assert "COMPLETE" in report
    deliverable.content = content(d.ComponentPanel((), "另一个结论"))
    with pytest.raises(d.DeliveryConflictError):
        assemble_delivery(context, deliverable)
    assert validate_delivery(context, first.reference).status is d.ValidationStatus.PASS


def test_partial_mandate_confirmation_and_roundtrip(context):
    evidence = attachment(context, value={"user": "目标待讨论"})
    mandate = d.ResearchMandate(
        (
            d.MandateItem(
                "symbol",
                d.MandateItemKind.TRADABLE_SYMBOL,
                "588080.SH",
                d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, evidence.reference),
            ),
            d.MandateItem(
                "return",
                d.MandateItemKind.OBJECTIVE,
                "讨论年化目标",
                d.ConfirmationRecord(d.ConfirmationStatus.PROPOSED),
                d.PerformanceRequirement(
                    (
                        m.ResearchTarget(
                            "net_annual_return",
                            m.ResearchMetric.NET_ANNUAL_RETURN,
                            lower=m.ConstantBound(0.1, True),
                        ),
                    )
                ),
            ),
        )
    )
    partial = replace(
        content(mandate, attachments=(evidence,)),
        status=d.DeliveryStatus.PARTIAL,
        incomplete_items=("目标尚待用户确认",),
    )
    receipt = assemble_delivery(context, Deliverable(definition(d.DeliveryStage.MANDATE), partial))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    document = json.loads(
        (published(context, receipt) / "delivery.json").read_text(encoding="utf-8")
    )
    decoded = d.DeliveryContent.from_dict(document["content"])
    assert decoded == partial
    assert decoded.payload.items[1].confirmation.status is d.ConfirmationStatus.PROPOSED


def test_delivery_survives_source_cleanup_and_keeps_report_facts(context):
    exp, artifact = experiment(context)
    source = attachment(context)
    ref = d.EvidenceRef(
        f"experiments/{exp.experiment_id}/{artifact.path}", artifact.sha256, "application/json"
    )
    value = replace(
        content(attachments=(source,)),
        facts=(
            d.FactValue("measurement", 0.25, "ratio", d.FactStatus.AVAILABLE, (ref,)),
            d.FactValue(
                "unobserved",
                None,
                "ratio",
                d.FactStatus.INSUFFICIENT_DATA,
                (source.reference,),
                "样本不足",
            ),
        ),
        explanations=(
            d.Explanation(
                d.ExplanationKind.RESEARCH_JUDGMENT,
                "仅支持进一步研究",
                ("measurement",),
                (ref,),
                (source.reference,),
            ),
        ),
    )
    receipt = assemble_delivery(context, Deliverable(definition(experiments=(exp,)), value))
    # All removed paths are explicitly verified below this test's .tmp boundary.
    temporary = (context.root / ".tmp").resolve()
    assert temporary.is_relative_to(context.root.resolve())
    shutil.rmtree(temporary)
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, Deliverable(definition(experiments=(exp,)), value)) == receipt
    report = (published(context, receipt) / "report.md").read_text(encoding="utf-8")
    assert "0.25" in report and "样本不足" in report and "不利证据" in report
    original = (published(context, receipt) / "report.md").read_bytes()
    (published(context, receipt) / "report.md").write_bytes(original.replace(b"0.25", b"0.99"))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.FAIL


def test_candidate_and_trial_states_remain_independent(context):
    record = failed_record()
    exp, _ = experiment(context, records=(record,))
    identity = d.CandidateIdentityRef(CandidateKey("S900", "C0001"), record.content_sha256)
    evaluation = d.EvaluationEvidenceRef(exp.experiment_id, record.attempt_id)
    entry = d.CandidateEntry(identity, "固定阈值假设", "技术失败，研究结论未定", (evaluation,))
    trials = tuple(
        d.SearchTrial(
            str(i),
            (d.ParameterValue("threshold", 0.5),),
            d.SearchTrialStatus.PRUNED,
            "研究员停止",
            identity,
            (evaluation,),
        )
        for i in range(2)
    )
    search = d.SearchRecord(
        "search",
        (d.NumericParameterDomain("threshold", 0.0, 1.0),),
        "optuna",
        "4.9.0",
        1,
        "研究代码串行调度",
        1,
        trials,
        "研究员决定停止",
    )
    payload = d.CandidateSet((entry,), (), (search,), "没有交接候选")
    # Recorded trial count exceeds the declared budget: platform records, never enforces it.
    receipt = assemble_delivery(
        context,
        Deliverable(definition(d.DeliveryStage.CANDIDATES, experiments=(exp,)), content(payload)),
    )
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    wrong = replace(entry, identity=replace(identity, content_sha256="f" * 64))
    bad = d.CandidateSet((wrong,), (), (), "身份不一致")
    with pytest.raises(d.DeliveryValidationError, match="identity differs"):
        assemble_delivery(
            context,
            Deliverable(
                replace(definition(d.DeliveryStage.CANDIDATES, experiments=(exp,)), revision=2),
                content(bad),
            ),
        )


def test_delivery_rejects_cross_experiment_candidate_content_conflict(context):
    first, _ = experiment(context, records=(failed_record(),))
    second, _ = experiment(context, number=2, records=(failed_record(2, "f" * 64),))
    with pytest.raises(d.DeliveryValidationError, match="conflicting"):
        assemble_delivery(context, Deliverable(definition(experiments=(first, second)), content()))


def test_delivery_requires_complete_predecessor_receipt_closure(context):
    first, _ = experiment(context, records=(failed_record(),))
    successor, _ = experiment(
        context, number=3, predecessors={first.experiment_id: first.receipt_sha256}
    )
    with pytest.raises(d.DeliveryValidationError, match="predecessor"):
        assemble_delivery(context, Deliverable(definition(experiments=(successor,)), content()))
    receipt = assemble_delivery(
        context, Deliverable(definition(experiments=(first, successor)), content())
    )
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS


def test_custom_component_and_bound_test_evidence(context):
    exp, artifact = experiment(context)
    protocol = attachment(context, "protocol.json", {"control": "constant"})
    ref = d.EvidenceRef(
        f"experiments/{exp.experiment_id}/{artifact.path}", artifact.sha256, "application/json"
    )
    test = d.ComponentTestResult(
        "t1",
        exp.experiment_id,
        protocol.reference,
        d.ComponentTestStatus.INEFFECTIVE,
        "无效结果",
        (ref,),
    )
    component = d.ComponentEntry(
        "component",
        d.ExperimentDefinitionRef(exp.experiment_id, "a" * 64, "b" * 64, "experiment.Component"),
        "环境识别",
        "未来收益",
        "5日",
        "常量",
        "收盘后",
        "前复权",
        "仅开发样本",
        "不支持",
        (test,),
    )
    value = content(d.ComponentPanel((component,), "保留无效组件的证据"), attachments=(protocol,))
    receipt = assemble_delivery(context, Deliverable(definition(experiments=(exp,)), value))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    wrong = replace(component, definition=replace(component.definition, source_sha256="f" * 64))
    with pytest.raises(d.DeliveryValidationError, match="source identity"):
        assemble_delivery(
            context,
            Deliverable(
                replace(definition(experiments=(exp,)), revision=2),
                replace(value, payload=d.ComponentPanel((wrong,), "错误定义")),
            ),
        )


def test_pruned_trial_retains_successful_evaluation_record(context):
    artifact = ExperimentArtifact(
        "result.json", "measurement", sha256(b'{"measurement":0.25}').hexdigest()
    )
    record = replace(
        failed_record(),
        status=EvaluationAttemptStatus.SUCCEEDED,
        completed_count=1,
        evaluation_ids=("f" * 64,),
        result_hash="e" * 64,
        result_artifact=artifact,
        error_code=None,
        error_message=None,
    )
    exp, _ = experiment(context, records=(record,))
    identity = d.CandidateIdentityRef(CandidateKey("S900", "C0001"), record.content_sha256)
    evaluation = d.EvaluationEvidenceRef(
        exp.experiment_id, record.attempt_id, record.evaluation_ids
    )
    trial = d.SearchTrial(
        "1", (), d.SearchTrialStatus.PRUNED, "研究员剪枝", identity, (evaluation,)
    )
    search = d.SearchRecord("s", (), "manual", "1", 1, "serial", 1, (trial,), "停止")
    payload = d.CandidateSet(
        (d.CandidateEntry(identity, "假设", "剪枝", (evaluation,)),), (), (search,), "无交接"
    )
    receipt = assemble_delivery(
        context,
        Deliverable(definition(d.DeliveryStage.CANDIDATES, experiments=(exp,)), content(payload)),
    )
    evidence = (
        published(context, receipt) / f"experiments/{exp.experiment_id}/execution_receipt.json"
    )
    assert json.loads(evidence.read_text())["trace"]["evaluations"][0]["status"] == "SUCCEEDED"
    assert trial.status is d.SearchTrialStatus.PRUNED


def test_candidate_without_authenticated_content_is_rejected(context):
    identity = d.CandidateIdentityRef(CandidateKey("S900", "C0001"), "a" * 64)
    payload = d.CandidateSet(
        (d.CandidateEntry(identity, "假设", "待检验", ()),), (), (), "缺少证据"
    )
    with pytest.raises(d.DeliveryValidationError, match="authenticated"):
        assemble_delivery(
            context, Deliverable(definition(d.DeliveryStage.CANDIDATES), content(payload))
        )


@pytest.mark.parametrize(
    "path", ["../x", "/x", "C:/x", "a\\x", "a/../x", "a//x", "CON", "a/x.", "a/x:stream"]
)
def test_evidence_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        d.EvidenceRef(path, "a" * 64, "text/plain")


@pytest.mark.parametrize("revision", [True, "1", 0, -1])
def test_revision_strict_types(revision):
    with pytest.raises((ValueError, TypeError)):
        d.DeliveryDefinition(d.MandateOwner("S900"), d.DeliveryStage.MANDATE, revision)


@pytest.mark.parametrize(
    "invalid,error_type",
    [
        pytest.param(
            lambda: d.DeliveryDefinition(
                d.ExperimentOwner("S900", "20261001_S900_EX01"), "MANDATE", 1
            ),
            TypeError,
            id="stage-enum",
        ),
        pytest.param(
            lambda: d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED),
            ValueError,
            id="confirmation-evidence",
        ),
        pytest.param(
            lambda: d.FactValue(
                "x",
                0.0,
                "ratio",
                d.FactStatus.FAILED,
                (d.EvidenceRef("attachments/x", "a" * 64, "text/plain"),),
                "failed",
            ),
            ValueError,
            id="unavailable-fact-value",
        ),
        pytest.param(
            lambda: replace(content(), status=d.DeliveryStatus.PARTIAL),
            ValueError,
            id="partial-without-incomplete-items",
        ),
        pytest.param(
            lambda: replace(
                content(),
                explanations=(d.Explanation(d.ExplanationKind.FACT, "引用", ("absent",)),),
            ),
            ValueError,
            id="unknown-explained-fact",
        ),
        pytest.param(
            lambda: d.NumericRequirement("return", "ratio", lower=float("nan")),
            TypeError,
            id="nonfinite-requirement",
        ),
    ],
)
def test_delivery_typed_values_reject_inconsistent_business_input(invalid, error_type):
    with pytest.raises(error_type):
        invalid()


def test_delivery_content_rejects_unknown_serialized_fields():
    payload = content().to_dict()
    payload["extra"] = True
    with pytest.raises(ValueError, match="fields"):
        d.DeliveryContent.from_dict(payload)


def test_delivery_rejects_stage_content_mismatch_without_publication(context):
    with pytest.raises(d.DeliveryValidationError, match="stage"):
        assemble_delivery(context, Deliverable(definition(d.DeliveryStage.MANDATE), content()))
    assert not ((context.root / "research") / "S900/mandates").exists()


def test_delivery_rejects_changed_attachment_without_publication(context):
    source = attachment(context)
    (context.root / source.source_path).write_text("changed")
    with pytest.raises(d.DeliveryValidationError, match="hash"):
        assemble_delivery(context, Deliverable(definition(), content(attachments=(source,))))
    assert not ((context.root / "experiments") / "S900/20261001_S900_EX01/deliveries").exists()


def test_delivery_publication_interruption_leaves_no_visible_revision(context, monkeypatch):
    def interrupt(path, target):
        raise OSError("simulated publication interruption")

    monkeypatch.setattr(Path, "rename", interrupt)
    with pytest.raises(d.DeliveryValidationError, match="interruption"):
        assemble_delivery(context, Deliverable(definition(), content()))
    assert not (
        (context.root / "experiments") / "S900/20261001_S900_EX01/deliveries/COMPONENTS/1"
    ).exists()


def test_delivery_refuses_reuse_of_incompletely_published_revision(context):
    receipt = assemble_delivery(context, Deliverable(definition(), content()))
    destination = published(context, receipt)
    (destination / "receipt.json").unlink()
    before = {
        p.relative_to(destination).as_posix(): p.read_bytes()
        for p in destination.rglob("*")
        if p.is_file()
    }
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.FAIL
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context, Deliverable(definition(), content()))
    after = {
        p.relative_to(destination).as_posix(): p.read_bytes()
        for p in destination.rglob("*")
        if p.is_file()
    }
    assert after == before


def test_delivery_predecessor_is_verified_without_advancing_stage(context):
    first = assemble_delivery(context, Deliverable(definition(), content()))
    successor = replace(definition(), revision=2, predecessors=(first.reference,))
    second = assemble_delivery(context, Deliverable(successor, content()))
    assert validate_delivery(context, second.reference).status is d.ValidationStatus.PASS
    (published(context, first) / "report.md").write_text("tampered")
    assert validate_delivery(context, second.reference).status is d.ValidationStatus.FAIL


def test_actual_rex_executor_receipt_can_be_published(context):
    from test_research_experiment import _execute_fixture

    loaded, execution, result = _execute_fixture(context.root, "delivery-integration")
    ref = d.ExperimentEvidenceRef(
        loaded.definition.experiment_id,
        execution.workspace.root.relative_to(context.root).as_posix(),
        result.receipt.sha256,
        use=d.ExperimentEvidenceUse.CURRENT_EVALUATION,
    )
    defined = d.DeliveryDefinition(
        d.ExperimentOwner(loaded.definition.strategy_id, loaded.definition.experiment_id),
        d.DeliveryStage.COMPONENTS,
        1,
        experiments=(ref,),
    )
    owner_root = (
        (context.root / "experiments") / loaded.definition.strategy_id / loaded.definition.experiment_id
    )
    shutil.copytree(loaded.root, owner_root)
    receipt = assemble_delivery(context, Deliverable(defined, content()))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS


def test_real_filesystem_link_cannot_supply_delivery_evidence(context):
    import os
    import subprocess

    source = attachment(context)
    target = (context.root / source.source_path).parent
    linked = context.root / "linked-evidence"
    assert target.resolve().is_relative_to(context.root.resolve())
    assert linked.parent == context.root
    if os.name == "nt":
        # A directory junction is a real Windows link and needs no symlink privilege.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked), str(target)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert linked.is_junction()
    else:
        linked.symlink_to(target, target_is_directory=True)
        assert linked.is_symlink()
    try:
        linked_source = replace(
            source, source_path=f"linked-evidence/{Path(source.source_path).name}"
        )
        with pytest.raises(d.DeliveryValidationError, match="link"):
            assemble_delivery(
                context, Deliverable(definition(), content(attachments=(linked_source,)))
            )
        assert not ((context.root / "experiments") / "S900/20261001_S900_EX01/deliveries").exists()
    finally:
        if os.name == "nt":
            linked.rmdir()
        else:
            linked.unlink()


def test_search_trial_must_obey_declared_numeric_step():
    domain = d.NumericParameterDomain("period", 1.0, 5.0, step=2.0, integer=True)
    trial = d.SearchTrial(
        "1", (d.ParameterValue("period", 2),), d.SearchTrialStatus.FAILED, "未评价"
    )
    with pytest.raises(ValueError, match="step"):
        d.SearchRecord("s", (domain,), "manual", "1", None, "serial", None, (trial,), "stop")


def test_categorical_search_distinguishes_bool_numeric_and_string_choices():
    categorical = d.CategoricalParameterDomain("choice", (True, 1, "1"))
    assert len(categorical.choices) == 3


def test_candidate_handoff_requires_membership_in_candidate_set():
    with pytest.raises(ValueError, match="handoff"):
        d.CandidateSet((), (CandidateKey("S900", "C0001"),), (), "无可交接候选")


@pytest.fixture
def delivery_catalog(context):
    family = InformationFamily("PRICE", "Price", "Completed prices", CatalogStatus.READY)
    factor = FactorDefinition(
        factor_id="F-PRICE", name="Daily range", description="Completed daily range",
        information_family="PRICE", tags=("daily",), inputs=("daily.high", "daily.low"),
        provider="project", implementation="factor_signal_catalog.calculations.calculate_daily_intraday_range",
        formula="high/low-1", availability="After close", causality="Completed bars only",
        parameters={}, status=CatalogStatus.DISCOVERED, version=1,
    )
    signal = SignalDefinition(
        signal_id="SIG-PRICE", name="Range signal", description="Daily range threshold",
        information_family="PRICE", tags=("range",), factor_ids=(factor.factor_id,),
        embedded_factor=False, provider="synthetic", implementation="fixture.signal",
        rule="range > threshold", states=("active", "inactive"), parameters={"threshold": 0.1},
        availability="After close", causality="Completed bars only", status=CatalogStatus.READY,
        version=1,
    )
    for name, items in (("information_families.json", [family]),
                        ("factors/definitions.json", [factor]),
                        ("signals/definitions.json", [signal])):
        path = context.root / "catalog" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "items": [item.to_dict() for item in items]}),
                        encoding="utf-8")
    catalog = CatalogRegistry(context.root / "catalog")
    assert {row["id"] for row in catalog.list_definitions()} == {factor.factor_id, signal.signal_id}
    return {d.CatalogDefinitionKind.FACTOR: factor.to_dict(),
            d.CatalogDefinitionKind.SIGNAL: signal.to_dict()}


def test_catalog_component_binds_snapshot_identity(context, delivery_catalog):
    source = delivery_catalog[d.CatalogDefinitionKind.FACTOR]
    catalog = FactorDefinition.from_dict(source)
    evidence = attachment(context, "factor.json", source)
    ref = d.CatalogDefinitionRef(
        d.CatalogDefinitionKind.FACTOR,
        catalog.factor_id,
        catalog.version,
        catalog.definition_sha256,
        evidence.reference,
    )
    component = d.ComponentEntry(
        "c", ref, "信息", "标签", "1日", "常量", "T+1", "前复权", "开发池", "尚未检验", ()
    )
    partial = replace(
        content(d.ComponentPanel((component,), "定义登记"), attachments=(evidence,)),
        status=d.DeliveryStatus.PARTIAL,
        incomplete_items=("尚无检验结果",),
    )
    receipt = assemble_delivery(context, Deliverable(definition(), partial))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    # A later catalog revision cannot invalidate a published historical snapshot.
    canonical = context.root / "catalog/factors/definitions.json"
    current = json.loads(canonical.read_text(encoding="utf-8"))
    current["items"][0]["version"] += 1
    canonical.write_text(json.dumps(current), encoding="utf-8")
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context, Deliverable(definition(), partial)) == receipt
    bad = replace(component, definition=replace(ref, definition_sha256="f" * 64))
    with pytest.raises(d.DeliveryValidationError, match="catalog definition"):
        assemble_delivery(
            context,
            Deliverable(
                replace(definition(), revision=2),
                replace(partial, payload=d.ComponentPanel((bad,), "错误指纹")),
            ),
        )


@pytest.mark.parametrize("kind", [d.CatalogDefinitionKind.FACTOR, d.CatalogDefinitionKind.SIGNAL])
@pytest.mark.parametrize("mutation", ["valid", "unknown_id", "wrong_version", "experiment_implementation"])
def test_new_catalog_reference_requires_real_fsc_membership(context, delivery_catalog, kind, mutation):
    group = "factors" if kind is d.CatalogDefinitionKind.FACTOR else "signals"
    cls = FactorDefinition if kind is d.CatalogDefinitionKind.FACTOR else SignalDefinition
    identity_key = "factor_id" if group == "factors" else "signal_id"
    source = dict(delivery_catalog[kind])
    if mutation == "unknown_id":
        source[identity_key] = "UNREGISTERED-COMPONENT"
    elif mutation == "wrong_version":
        source["version"] += 1
    elif mutation == "experiment_implementation":
        source["implementation"] = "experiments/S900/20261001_S900_EX01/experiment.py"
    snapshot = cls.from_dict(source)
    evidence = attachment(context, "definition.json", source)
    reference = d.CatalogDefinitionRef(
        kind, source[identity_key], snapshot.version, snapshot.definition_sha256, evidence.reference,
    )
    component = d.ComponentEntry(
        "c", reference, "信息", "标签", "1日", "常量", "T+1", "前复权", "开发池", "尚未检验", (),
    )
    package = replace(
        content(d.ComponentPanel((component,), "自定义定义"), attachments=(evidence,)),
        status=d.DeliveryStatus.PARTIAL, incomplete_items=("尚无检验结果",),
    )
    if mutation == "valid":
        receipt = assemble_delivery(context, Deliverable(definition(), package))
        assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
        return
    with pytest.raises(d.DeliveryValidationError, match="registered FSC"):
        assemble_delivery(context, Deliverable(definition(), package))
    assert not ((context.root / "experiments") / "S900/20261001_S900_EX01/deliveries").exists()




def owner_experiment(context, number=1):
    from test_research_experiment import _write_v3_experiment
    from research_experiment import experiment_source_sha256

    root = (context.root / "experiments") / "S900" / f"20261001_S900_EX{number:02}"
    _write_v3_experiment(root)
    source = root / "experiment.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace("20260925_S009_EX99", root.name)
        .replace("S009", "S900"),
        encoding="utf-8",
    )
    path = root / "experiment_binding.json"
    binding = json.loads(path.read_text())
    binding["source_sha256"] = experiment_source_sha256(root, ("experiment.py",))
    path.write_text(json.dumps(binding))
    return root
