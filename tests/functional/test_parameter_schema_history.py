"""Historical contracts remain readable without permitting relabelled new writes."""
from dataclasses import replace
import json
from hashlib import sha256
from types import SimpleNamespace

import pytest
from strategy_evaluator import research_models as m
from czsc_trader.application import RepositoryContext, assemble_delivery, validate_delivery
from czsc_trader.application import delivery_service as service
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef, ResearchBatchRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from test_research_delivery import content


@pytest.fixture
def context(minimal_repo):
    # A delivery-only fixture needs no database or market-data capability.
    return SimpleNamespace(repository=RepositoryContext.discover(minimal_repo),
                           batch=ResearchBatchRef("S900"))


def _historical_mandate(context, version=8):
    """Install an explicit immutable-format fixture, without a legacy write API."""
    target = m.ParameterGroupTarget("parameter", 32, 26,
        (m.ResearchTarget("return", m.ResearchMetric.NET_ANNUAL_RETURN,
                         lower=m.ConstantBound(0.0, False)),),
        (m.ResearchTarget("drawdown", m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                         upper=m.ConstantBound(0.25, True)),))
    if version == 11:
        target = m.ParameterNeighborhoodTarget(target.target_id, 13, 16,
                                               target.joint_targets, target.all_point_targets)
    payload = d.ResearchMandate((d.MandateItem("parameter", d.MandateItemKind.CONSTRAINT,
        "Historical fixed-count contract", d.ConfirmationRecord(d.ConfirmationStatus.PROPOSED),
        d.PerformanceRequirement((target,))),))
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.MANDATE, 1, schema_version=version)
    value = content(payload)
    root = service._delivery_path(context.repository, definition)
    root.mkdir(parents=True)
    (root / "delivery.json").write_bytes(d._canonical({"schema_version": version,
        "definition": definition.to_dict(), "content": value.to_dict()}))
    (root / "report.md").write_bytes(value.report.encode())
    files = service._manifest(root)
    reference = d.DeliveryReference(context.batch, d.DeliveryStage.MANDATE, 1, d._digest(files))
    receipt = d.DeliveryReceipt(reference, files, schema_version=version)
    (root / "receipt.json").write_bytes(d._canonical(receipt))
    public = service._public_delivery_path(context.repository, reference)
    public.mkdir(parents=True)
    for name in ("report.md", "receipt.json"):
        (public / name).write_bytes((root / name).read_bytes())
    return definition, value, receipt, root


@pytest.mark.parametrize("version", [8, 11])
def test_historical_mandate_full_read_preserves_bytes_and_cannot_be_republished(context, version):
    definition, value, receipt, root = _historical_mandate(context, version)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    result = validate_delivery(context.repository, receipt.reference)
    assert result.status is d.ValidationStatus.PASS, result.issues
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}
    assert d.DeliveryDefinition.from_dict(definition.to_dict()) == definition
    assert d.DeliveryReceipt.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(d.DeliveryValidationError, match="read-only"):
        assemble_delivery(context.repository, definition, value)
    if version == 8:
        with pytest.raises(d.DeliveryValidationError, match="historical methods"):
            assemble_delivery(context.repository, replace(definition, revision=2, schema_version=12), value)


def test_new_mandate_can_retain_legacy_predecessor_without_reinterpreting_it(context):
    from czsc_trader.application import create_research_batch, ResearchBatchRequest, get_research_overview

    batch = create_research_batch(context.repository,
        ResearchBatchRequest("S900", "Historical predecessor", ("588080.SH",), {"question": "synthetic"}),
        actor="test", reason="latest delivery navigation")
    assert batch == context.batch
    _, _, historical, root = _historical_mandate(context)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.MANDATE, 2,
                                     predecessors=(historical.reference,))
    receipt = assemble_delivery(context.repository, definition, content(d.ResearchMandate(()))).receipt
    assert receipt.schema_version == 12
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    assert validate_delivery(context.repository, historical.reference).status is d.ValidationStatus.PASS
    with pytest.raises(ValueError):
        replace(definition, schema_version=13)
    overview = get_research_overview(context.repository, context.batch)
    assert len(overview.deliveries) == 1
    latest = overview.deliveries[0]
    assert (latest.stage, latest.revision, latest.reference) == (d.DeliveryStage.MANDATE, 2, receipt.reference)
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}


def test_legacy_envelope_cannot_adopt_new_ratio_target(context):
    definition, value, _, _ = _historical_mandate(context)
    item = value.payload.items[0]
    old = item.requirement.targets[0]
    new = m.ParameterNeighborhoodTarget(old.target_id, 13, 16,
                                        old.joint_targets, old.all_point_targets)
    payload = replace(value.payload, items=(replace(item,
        requirement=d.PerformanceRequirement((new,))),))
    with pytest.raises(d.DeliveryValidationError, match="parameter method differs"):
        service._validate_parameter_method_schema(definition, payload)
    service._validate_parameter_method_schema(replace(definition, schema_version=11), payload)


@pytest.mark.parametrize("version", [None, True, 11.0, "11"])
def test_serialized_schema_cannot_use_constructor_default_or_coercion(context, version):
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.MANDATE, 1)
    saved = definition.to_dict()
    saved["schema_version"] = version
    with pytest.raises(ValueError, match="explicit integer"):
        d.DeliveryDefinition.from_dict(saved)
    reference = d.DeliveryReference(context.batch, d.DeliveryStage.MANDATE, 1, "a" * 64)
    saved = d.DeliveryReceipt(reference, (d.PublicationFile("report.md", "b" * 64),)).to_dict()
    saved["schema_version"] = version
    with pytest.raises(ValueError, match="explicit integer"):
        d.DeliveryReceipt.from_dict(saved)


def _account_ref(version):
    return EvidenceRef(ExperimentRef("S900", "EX001_20261007"), "a" * 64 + ".json", "a" * 64,
                       "application/json", "account", "account_evaluation", version)


@pytest.mark.parametrize("body,reference", [(7, 8), (8, 7), (9, 9)])
def test_account_reference_schema_cannot_relabel_document(monkeypatch, body, reference):
    from czsc_trader.research_tools import evaluation
    calls = []
    monkeypatch.setattr(evaluation, "validate_evaluation_evidence", calls.append)
    with pytest.raises(d.DeliveryValidationError, match="schema differs"):
        service._certify_account(json.dumps({"schema_version": body}).encode(), _account_ref(reference))
    assert calls == []


@pytest.mark.parametrize("version", [7, 8])
def test_account_reference_schema_remains_bound_on_cache_reuse(monkeypatch, version, tmp_path):
    reference = _account_ref(version)
    projection = {"schema_version": 15 - version,
                  "request_identity": {"experiment_id": reference.experiment.experiment_id,
                                       "strategy_reference": "S900-C0001"}}
    monkeypatch.setattr(service, "_read_evidence", lambda root, ref: b"authenticated bytes")
    with pytest.raises(d.DeliveryValidationError, match="schema differs") as failed:
        service._account_document(tmp_path, reference, {reference.sha256: (projection, ())})
    assert failed.value.issues[0].code == "ACCOUNT_AUTHENTICATION"


@pytest.fixture
def account_schema_bytes(request, frozen_seed_root):
    """Synthetic legacy encoding, never a legacy publication or historical edit."""
    from copy import deepcopy
    from strategy_runtime import canonical_sha256
    from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, _evaluation_result_hash

    seed = frozen_seed_root / "historical-account-schemas.json"
    if not seed.exists():
        context, evaluation = request.getfixturevalue("fresh_managed_evaluation")
        prepared = context.evaluation.prepare(evaluation)
        result = context.evaluation.evaluate(prepared)
        current = serialize_evaluation_evidence(prepared, result)
        assert (current["schema_version"], current["request_identity"]["schema_version"]) == (8, 7)
        validate_evaluation_evidence(current)
        legacy = deepcopy(current)
        # Without parameter lineage, these readable schemas share the exact
        # economic account. Rebind only format-dependent authenticated digests.
        assert legacy["request_identity"]["parameter_binding"] is None
        assert legacy["request_identity"]["lineage"] is None
        legacy["schema_version"] = 7
        legacy["request_identity"]["schema_version"] = 6
        legacy["request_hash"] = canonical_sha256(legacy["request_identity"])
        legacy["result_hash"] = _evaluation_result_hash(legacy["request_hash"], result.runs)
        for assessment in legacy["assessment_evidence"]:
            assessment["request_sha256"] = legacy["request_hash"]
            assessment["result_sha256"] = legacy["result_hash"]
            assessment["attempt_id"] = legacy["result_hash"][:32]
        assert legacy["runs"] == current["runs"]
        validate_evaluation_evidence(legacy)
        seed.write_bytes(json.dumps({"7": legacy, "8": current}).encode())
    return seed.read_bytes()


@pytest.mark.parametrize("version,request_version", [(7, 6), (8, 7), (7, 7), (8, 6)])
def test_published_account_versions_are_paired(account_schema_bytes, version, request_version):
    document = json.loads(account_schema_bytes)[str(version)]
    original = json.dumps(document).encode()
    validate_evaluation_evidence(document)  # Complete legitimate baseline, including numeric audit.
    assert json.dumps(document).encode() == original
    document["request_identity"]["schema_version"] = request_version
    if request_version == version - 1:
        validate_evaluation_evidence(document)
    else:
        with pytest.raises(ValueError, match="^evaluation request and evidence schema versions differ$"):
            validate_evaluation_evidence(document)


@pytest.mark.parametrize("version", [7, 8])
def test_diagnosis_authenticates_reference_version_before_ledger(context, monkeypatch, version):
    from czsc_trader.application import account_diagnosis_service as diagnosis
    data = json.dumps({"schema_version": 15 - version}).encode()
    digest = sha256(data).hexdigest()
    reference = replace(_account_ref(version), evidence_id=f"{digest}.json", sha256=digest)
    path = context.repository.root / reference.repository_path
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    monkeypatch.setattr(diagnosis, "validate_evaluation_evidence", lambda document: pytest.fail("must reject first"))
    with pytest.raises(ValueError, match="schema differs"):
        diagnosis._load(context.repository, SimpleNamespace(evidence=reference))
