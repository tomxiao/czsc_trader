"""Candidate storage checks declarations; deep research checks are explicit."""

from dataclasses import replace
import json

import pytest
from dataflows import BarFrequency, MarketId
from strategy_manager import CandidateKey

from czsc_trader.application import (
    CandidateRegistrationRequest, assemble_delivery, publish_evidence,
    register_candidate, validate_delivery,
)
from czsc_trader.application import delivery_service as service
from czsc_trader.research_tools import EvaluationEvidenceWrite, ResearchExecutionSession
from czsc_trader.research_tools import delivery as d
from account_parity_support import setup_account


def candidate_content(context, request):
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        reference = publish_evidence(context, EvaluationEvidenceWrite(
            request.experiment, "candidate-boundary", prepared, outcome.result), execution=execution)
        header = json.loads(outcome.result.content)
    registration = register_candidate(context.repository, CandidateRegistrationRequest(
        request.candidate, request.experiment, (reference,), ()))
    entry = d.CandidateEntry(d.CandidateIdentityRef(request.candidate.key, registration.content_sha256),
        "Explicit caller hypothesis", "Caller selection",
        (d.EvaluationEvidenceRef(reference, (header["evaluation_id"],)),))
    content = d.DeliveryContent(d.CandidateSet((entry,), (request.candidate.key,), (), "Declared result"),
        d.DeliveryStatus.COMPLETE, (), (), report="# Candidate fixture\n")
    return content, reference, header


@pytest.mark.parametrize("market", [MarketId.CN, MarketId.US])
def test_candidate_storage_never_materializes_accounts_or_loads_strategy(tmp_path, monkeypatch, market):
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY)
    content, reference, header = candidate_content(context, request)
    from czsc_trader.application import candidate_service, equity_evidence_io

    def forbidden(*args, **kwargs):
        raise AssertionError("ordinary candidate delivery must not certify or execute research")

    monkeypatch.setattr(service, "_certify_account", forbidden)
    monkeypatch.setattr(equity_evidence_io, "materialize_equity_document", forbidden)
    monkeypatch.setattr(candidate_service, "load_candidate", forbidden)
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.CANDIDATES, 1, ())
    result = assemble_delivery(context.repository, definition, content)
    assert result.validation.scope is d.DeliveryValidationScope.INTEGRITY
    assert result.validation.stats.accounts_authenticated == 0
    assert result.validation.stats.recomputation_seconds == 0
    assert assemble_delivery(context.repository, definition, content).receipt == result.receipt
    with pytest.raises(d.DeliveryConflictError):
        assemble_delivery(context.repository, definition, replace(content, report="Changed declaration"))
    checked = validate_delivery(context.repository, result.receipt.reference)
    assert checked.status is d.ValidationStatus.PASS, checked.issues
    assert checked.scope is d.DeliveryValidationScope.INTEGRITY
    assert checked.stats.unique_deliveries == 1
    # The copied closure survives removal of the input source; its own bytes remain checked.
    source = reference.resolve(context.repository.root).parent / (header["input_ref"]["sha256"] + ".json")
    assert source.is_relative_to(tmp_path)
    source.unlink()
    assert validate_delivery(context.repository, result.receipt.reference).status is d.ValidationStatus.PASS
    package = service._delivery_path(context.repository, result.receipt.reference)
    (package / "evidence" / (header["input_ref"]["sha256"] + ".json")).write_bytes(b"corrupt")
    assert validate_delivery(context.repository, result.receipt.reference).status is d.ValidationStatus.FAIL
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context.repository, definition, content)


def test_candidate_integrity_does_not_traverse_history_but_full_does(tmp_path):
    context, request = setup_account(tmp_path, MarketId.US, BarFrequency.DAILY)
    content, _, _ = candidate_content(context, request)
    first = assemble_delivery(context.repository,
        d.DeliveryDefinition(context.batch, d.DeliveryStage.CANDIDATES, 1, ()), content).receipt.reference
    package = service._delivery_path(context.repository, first)
    (package / "report.md").write_text("changed historical report", encoding="utf-8")
    second = assemble_delivery(context.repository,
        d.DeliveryDefinition(context.batch, d.DeliveryStage.CANDIDATES, 2, (first,)), content).receipt.reference
    assert validate_delivery(context.repository, second).status is d.ValidationStatus.PASS
    assert validate_delivery(context.repository, second, scope=d.DeliveryValidationScope.FULL).status is d.ValidationStatus.FAIL


@pytest.mark.parametrize("damage", ["candidate", "evaluation", "legacy"])
def test_candidate_declaration_rejects_wrong_bindings_and_retired_account_contract(tmp_path, damage):
    context, request = setup_account(tmp_path, MarketId.US, BarFrequency.DAILY)
    content, reference, _ = candidate_content(context, request)
    entry, = content.payload.candidates
    evaluation, = entry.evaluations
    if damage == "candidate":
        entry = replace(entry, identity=replace(entry.identity, content_sha256="f" * 64))
    elif damage == "evaluation":
        entry = replace(entry, evaluations=(replace(evaluation, evaluation_ids=("f" * 64,)),))
    else:
        entry = replace(entry, evaluations=(replace(evaluation,
            evidence=replace(reference, schema="account_evaluation", schema_version=8)),))
    content = replace(content, payload=replace(content.payload, candidates=(entry,), handoff=()))
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context.repository,
            d.DeliveryDefinition(context.batch, d.DeliveryStage.CANDIDATES, 1, ()), content)


@pytest.mark.parametrize("damage", ["missing_registration", "different_content"])
def test_candidate_handoff_requires_matching_registration(tmp_path, damage):
    context, request = setup_account(tmp_path, MarketId.US, BarFrequency.DAILY)
    content, _, _ = candidate_content(context, request)
    entry, = content.payload.candidates
    identity = (replace(entry.identity, key=CandidateKey(context.strategy_id, "C9999"))
                if damage == "missing_registration"
                else replace(entry.identity, content_sha256="f" * 64))
    content = replace(content, payload=replace(content.payload,
        candidates=(replace(entry, identity=identity),), handoff=(identity.key,)))
    with pytest.raises(d.DeliveryValidationError) as failure:
        assemble_delivery(context.repository,
            d.DeliveryDefinition(context.batch, d.DeliveryStage.CANDIDATES, 1, ()), content)
    assert failure.value.issues[0].code == "HANDOFF_REGISTRATION"
