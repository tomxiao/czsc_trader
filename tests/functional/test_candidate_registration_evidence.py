"""Registration records identity; declared account evidence remains authenticated."""

from dataclasses import replace
import json

import pytest
from strategy_manager import ResearchState, StrategyFamily, StrategyRegistry
from strategy_runtime import StrategyRuntime

from czsc_trader.application import (
    CandidateRegistrationRequest, assemble_delivery, load_candidate, publish_evidence,
    register_candidate, validate_delivery,
)
from czsc_trader.research_tools import ExperimentRef, EvaluationEvidenceWrite, MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
from test_research_delivery import content


@pytest.fixture
def registration_input(managed_evaluation):
    research, request = managed_evaluation
    family = StrategyFamily(2, "S900", "Registration fixture", "ETF", {"hypothesis": "synthetic"},
        ResearchState.RESEARCHING, "2026-10-01T00:00:00+00:00", "test", "2026-10-01T00:00:00+00:00")
    StrategyRegistry(research.repository.research_registry_root).create_family(family, actor="test", reason="fixture")
    experiment = ExperimentRef("S900", request.experiment_id)
    material = publish_evidence(research, MaterialEvidenceWrite(
        experiment, "rationale", b"Research rationale, not account facts.", "text/plain", "txt"))
    return research, request, experiment, material


def account_support(research, request, experiment):
    prepared = research.evaluation.prepare(request)
    result = research.evaluation.evaluate(prepared)
    return publish_evidence(research, EvaluationEvidenceWrite(experiment, "account", prepared, result))


@pytest.mark.parametrize("mode", ["empty", "material", "account", "mixed"])
def test_registration_accepts_optional_support_without_implying_delivery_readiness(registration_input, mode):
    research, request, experiment, material = registration_input
    evidence = (material,) if mode in ("material", "mixed") else ()
    if mode in ("account", "mixed"):
        evidence += (account_support(research, request, experiment),)
    operation = CandidateRegistrationRequest(request.strategy, experiment, evidence, request.dependencies)
    record = register_candidate(research.repository, operation)
    assert register_candidate(research.repository, operation) == record
    assert len(record.origin.evidence) == len(evidence)
    assert record.schema_version == 3
    loaded = load_candidate(research.repository, record.key)
    assert StrategyRuntime().identify(loaded, dependencies=request.dependencies).content_sha256 == record.content_sha256
    assert StrategyRegistry(research.repository.research_registry_root).get_candidate(
        record.key, evidence_root=research.repository.research_root / "S900") == record
    # Registration does not waive the separate account-evidence role in formal delivery.
    entry = d.CandidateEntry(d.CandidateIdentityRef(record.key, record.content_sha256),
                            "Synthetic mechanism", "Account evidence not attached", ())
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 1)
    with pytest.raises(d.DeliveryValidationError) as failed:
        assemble_delivery(research.repository, definition,
                          content(d.CandidateSet((entry,), (record.key,), (), "Synthetic handoff")))
    assert failed.value.issues[0].code == "CANDIDATE_EVIDENCE"
    if mode == "empty":
        # Later account evidence can support delivery without rewriting the original registration.
        account = account_support(research, request, experiment)
        document = json.loads(account.resolve(research.repository.root).read_text(encoding="utf-8"))
        evaluation = d.EvaluationEvidenceRef(account, tuple(
            item["evaluation_id"] for item in document["assessment_evidence"]))
        entry = replace(entry, evaluations=(evaluation,))
        receipt = assemble_delivery(research.repository, definition,
            content(d.CandidateSet((entry,), (record.key,), (), "Evaluated handoff"))).receipt
        assert validate_delivery(research.repository, receipt.reference).status is d.ValidationStatus.PASS
        assert StrategyRegistry(research.repository.research_registry_root).get_candidate_registration(record.key) == record


@pytest.mark.parametrize("damage", ["material-hash", "account-identity", "account-ledger", "account-schema",
                                    "duplicate", "duplicate-path", "foreign-batch"])
def test_registration_rejects_invalid_declared_support_before_candidate_publication(registration_input, damage):
    research, request, experiment, material = registration_input
    evidence = (material,)
    message = None
    if damage == "material-hash":
        material.resolve(research.repository.root).write_bytes(b"tampered")
        message = "content differs"
    elif damage.startswith("account-"):
        account = account_support(research, request, experiment)
        if damage == "account-identity":
            request = replace(request, strategy=replace(request.strategy, candidate_id="C0002"))
            evidence = (account,)
            message = "differs from content identity"
        elif damage == "account-schema":
            evidence = (replace(material, schema="account_evaluation", schema_version=99),)
            message = "account evaluation evidence"
        else:
            document = json.loads(account.resolve(research.repository.root).read_text(encoding="utf-8"))
            document["runs"][0]["ledgers"]["account_daily"]["data"][0]["cash"] += 1.0
            forged = publish_evidence(research, MaterialEvidenceWrite(
                experiment, "forged-account", json.dumps(document).encode(), "application/json", "json"))
            evidence = (replace(forged, schema=account.schema, schema_version=account.schema_version),)
    elif damage in ("duplicate", "duplicate-path"):
        evidence = (material, material if damage == "duplicate" else replace(material, name="renamed"))
        message = "unique"
    else:
        evidence = (replace(material, experiment=ExperimentRef("S901", experiment.experiment_id)),)
        message = "another research batch"
    with pytest.raises(ValueError, match=message):
        register_candidate(research.repository,
            CandidateRegistrationRequest(request.strategy, experiment, evidence, request.dependencies))
    assert not (research.repository.research_root / "S900/assets/candidates").exists()
