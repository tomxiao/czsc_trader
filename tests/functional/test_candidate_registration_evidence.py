# Risk ownership: TDR-03
"""Candidate publication retains declared evidence without historical account authentication."""
from dataclasses import replace
import json

import pytest
from dataflows import BarFrequency, MarketId
from strategy_runtime import EquityStrategyCandidate
from czsc_trader.application import CandidateRegistrationRequest, load_candidate, publish_evidence, register_candidate
from czsc_trader.research_tools import MaterialEvidenceWrite
from account_parity_support import setup_account


def declared_support(context, request, **changes):
    # A valid V4 envelope deliberately references absent account/input files.
    # Registration checks its declaration; explicit account tools own those files.
    document = {
        "schema_version": 4,
        "request": {"schema": "equity-research/v4", "candidate_definition": {"contract_version": 4},
                    "price_basis": "HFQ", "quantity_basis": "SIMULATED_INTEGER_UNITS",
                    "candidate_id": request.candidate.candidate_id,
                    "implementation_hash": request.candidate.implementation_hash,
                    "experiment": request.experiment.to_dict()},
        "input_ref": {"kind": "equity_input", "sha256": "a" * 64},
        "candidate_ref": {"kind": "equity_account", "sha256": "b" * 64},
        "benchmark_ref": {"kind": "equity_account", "sha256": "c" * 64},
    }
    document["request"].update(changes)
    reference = publish_evidence(context, MaterialEvidenceWrite(request.experiment, "declared-account",
        json.dumps(document).encode(), "application/json", "json"))
    return replace(reference, schema="equity_research", schema_version=4)


@pytest.mark.parametrize('market', [MarketId.CN])
def test_TDR_03_C01_registration_retains_declarations_without_loading_account_dependencies(tmp_path, monkeypatch, market):
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY)
    evidence = declared_support(context, request)
    from czsc_trader.application import equity_evidence_io
    def forbidden(*args, **kwargs):
        raise AssertionError("ordinary candidate registration must not authenticate historical accounts")
    monkeypatch.setattr(equity_evidence_io, "materialize_equity_document", forbidden)
    operation = CandidateRegistrationRequest(request.candidate, request.experiment, (evidence,), ())
    record = register_candidate(context.repository, operation)
    assert register_candidate(context.repository, operation) == record
    assert len(record.origin.evidence) == 1
    assert load_candidate(context.repository, record.key).content_identity.content_sha256 == record.content_sha256


@pytest.mark.parametrize('damage', [pytest.param('digest', id='TDR-03-C02'), pytest.param('experiment', id='TDR-03-C03')])
def test_registration_rejects_direct_declaration_errors_before_publishing(tmp_path, damage):
    context, request = setup_account(tmp_path, MarketId.US, BarFrequency.DAILY)
    changes = {"candidate_id": "C0002"} if damage == "candidate" else {}
    if damage == "experiment":
        changes["experiment"] = {**request.experiment.to_dict(), "experiment_id": "EX002_20261028"}
    evidence = declared_support(context, request, **changes)
    if damage == "digest":
        (context.repository.root / evidence.repository_path).write_bytes(b"tampered")
    if damage == "schema":
        evidence = replace(evidence, schema_version=3)
    with pytest.raises(ValueError):
        register_candidate(context.repository, CandidateRegistrationRequest(request.candidate,
            request.experiment, (evidence, evidence) if damage == "duplicate" else (evidence,), ()))
    assert not (context.repository.research_root / request.candidate.strategy_id / "assets/candidates").exists()






def test_TDR_03_C06_registration_does_not_admit_runtime_but_loading_does_once(tmp_path, monkeypatch):
    context, request = setup_account(tmp_path, MarketId.US, BarFrequency.DAILY)
    original = EquityStrategyCandidate.verify
    calls = []
    def verify(candidate):
        calls.append(candidate.source_root)
        return original(candidate)
    monkeypatch.setattr(EquityStrategyCandidate, "verify", verify)
    record = register_candidate(context.repository, CandidateRegistrationRequest(request.candidate,
        request.experiment, (), ()))
    assert calls == []
    load_candidate(context.repository, record.key)
    assert len(calls) == 1
    def wrong_environment(candidate):
        raise ValueError("equity dependency version differs: synthetic")
    monkeypatch.setattr(EquityStrategyCandidate, "verify", wrong_environment)
    with pytest.raises(ValueError, match="dependency version differs"):
        load_candidate(context.repository, record.key)


def test_TDR_03_C05_registered_source_tamper_is_rejected(tmp_path):
    context, request = setup_account(tmp_path, MarketId.US, BarFrequency.DAILY)
    record = register_candidate(context.repository, CandidateRegistrationRequest(request.candidate,
        request.experiment, (), ()))
    loaded = load_candidate(context.repository, record.key)
    source = loaded.source_root / loaded.definition.source_files[0]
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash|source|content|closure"):
        load_candidate(context.repository, record.key)
