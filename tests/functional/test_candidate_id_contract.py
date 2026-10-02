"""Candidate identity boundaries shared by registration, execution and assessment."""

import pytest

from strategy_manager import CandidateKey, FreezeRequestId, FrozenVersionReference
from strategy_manager.errors import ValidationError as RegistryValidationError
from strategy_evaluator.models import ValidationError as AssessmentValidationError
from strategy_runtime import StrategyCandidate
from strategy_runtime.contracts import StrategyIdentity
from strategy_evaluator import AssessmentCandidate
from czsc_trader.research_tools.delivery import MandateOwner, ExperimentOwner


@pytest.mark.parametrize("candidate_id", ["C0000", "C0001", "C0621", "C9999"])
def test_candidate_ids_have_one_format_across_public_contracts(candidate_id):
    key = CandidateKey("S011", candidate_id)
    runtime = StrategyCandidate("S011", candidate_id, {"runtime": {}, "parameters": {}})
    assessment = AssessmentCandidate(runtime.reference_id, "a" * 64)
    identity = StrategyIdentity("S011", runtime.reference_id, "a" * 64, "b" * 64, "159326.SZ")
    assert key.candidate_id == candidate_id
    assert assessment.candidate_id == identity.reference_id == f"S011-{candidate_id}"


@pytest.mark.parametrize("candidate_id", [
    "", "C001", "C10000", "c0621", "CFG000621", "CFG000621R2", "P000621J00R2",
    "S011-C0621", "v1", "C０６２１", "C٠٦٢١", " C0621", "C0621 ", "C0621\n",
])
def test_noncanonical_candidate_ids_fail_before_execution(candidate_id):
    with pytest.raises(RegistryValidationError):
        CandidateKey("S011", candidate_id)
    with pytest.raises(ValueError):
        StrategyCandidate("S011", candidate_id, {"runtime": {}, "parameters": {}})
    with pytest.raises(AssessmentValidationError):
        AssessmentCandidate(f"S011-{candidate_id}", "a" * 64)
    if candidate_id != "v1":
        with pytest.raises(ValueError):
            StrategyIdentity("S011", f"S011-{candidate_id}", "a" * 64, "b" * 64, "159326.SZ")


@pytest.mark.parametrize("family", ["S01", "S0011", "S０１１", "S٠١١", " S011", "S011 "])
def test_family_ids_are_strict_at_registration_and_owner_boundaries(family):
    for create in (
        lambda: CandidateKey(family, "C0621"),
        lambda: StrategyCandidate(family, "C0621", {"runtime": {}, "parameters": {}}),
        lambda: MandateOwner(family),
        lambda: ExperimentOwner(family, f"20261002_{family}_EX01"),
        lambda: FreezeRequestId(family, "request-1"),
    ):
        with pytest.raises((ValueError, RegistryValidationError)):
            create()


def test_family_only_contracts_do_not_require_a_dummy_candidate():
    assert MandateOwner("S011").strategy_id == "S011"
    assert ExperimentOwner("S011", "20261002_S011_EX01").strategy_id == "S011"
    assert FreezeRequestId("S011", "request-1").strategy_id == "S011"
    assert FrozenVersionReference("S011", "v1", "a" * 64, "b" * 64).version == "v1"
    assert StrategyIdentity("S011", "S011-v1", "a" * 64, "b" * 64, "159326.SZ").reference_id == "S011-v1"


@pytest.mark.parametrize("reference", ["S011-v0", "S011-v01", "S011-v１", "S012-C0621"])
def test_runtime_reference_rejects_invalid_version_or_different_family(reference):
    with pytest.raises(ValueError):
        StrategyIdentity("S011", reference, "a" * 64, "b" * 64, "159326.SZ")


def test_benchmark_identity_preserves_existing_serialization_and_content_binding():
    from dataclasses import asdict, replace
    from datetime import date
    from strategy_runtime.contracts import signal_identity_for

    identity = StrategyIdentity("BuyHold", "BuyHold", "a" * 64, "b" * 64, "159326.SZ")
    assert StrategyIdentity(**asdict(identity)) == identity
    assert set(asdict(identity)) == {
        "strategy_id", "reference_id", "release_hash", "runtime_sha256", "symbol",
    }
    request = dict(signal_date=date(2026, 9, 1), target_position=1.0,
                   input_identities={"data": "c" * 64}, price_identities={"price": "d" * 64})
    assert signal_identity_for(strategy=identity, **request) != signal_identity_for(
        strategy=replace(identity, release_hash="e" * 64), **request,
    )


@pytest.mark.parametrize("family,reference", [
    ("BuyHold", "S011-C0621"), ("BuyHold", "S011-v1"), ("S011", "BuyHold"),
    ("BuyHold", "OtherBenchmark"), ("OtherBenchmark", "OtherBenchmark"),
    ("buyhold", "buyhold"), ("BuyHold ", "BuyHold"), ("BuyHold", "BuyHold "),
])
def test_benchmark_identity_cannot_bypass_strategy_identity_boundaries(family, reference):
    with pytest.raises(ValueError):
        StrategyIdentity(family, reference, "a" * 64, "b" * 64, "159326.SZ")


@pytest.mark.parametrize("field", ["release_hash", "runtime_sha256"])
def test_benchmark_identity_still_requires_content_hashes(field):
    values = dict(strategy_id="BuyHold", reference_id="BuyHold", release_hash="a" * 64,
                  runtime_sha256="b" * 64, symbol="159326.SZ")
    values[field] = "invalid"
    with pytest.raises(ValueError, match="SHA-256"):
        StrategyIdentity(**values)
