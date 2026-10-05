import pytest

from strategy_runtime import StrategyCandidate, StrategyIdentity

@pytest.mark.parametrize("candidate_id", ["C0000", "C9999"])
def test_candidate_identity_valid_boundaries(candidate_id):
    candidate = StrategyCandidate("S011", candidate_id, {"runtime": {}, "parameters": {}})
    identity = StrategyIdentity("S011", candidate.reference_id, "a" * 64, "b" * 64, "159326.SZ")
    assert identity.reference_id == f"S011-{candidate_id}"

@pytest.mark.parametrize("candidate_id", ['', 'C001', 'C10000', 'c0621', 'CFG000621', 'S011-C0621', 'v1', 'C０６２１', ' C0621', 'C0621 ', 'C0621\n'])
def test_runtime_candidate_identity_rejects_noncanonical_values(candidate_id):
    with pytest.raises(ValueError):
        StrategyCandidate("S011", candidate_id, {"runtime": {}, "parameters": {}})
    if candidate_id != "v1":
        with pytest.raises(ValueError):
            StrategyIdentity("S011", f"S011-{candidate_id}", "a" * 64, "b" * 64, "159326.SZ")

@pytest.mark.parametrize("family", ['S01', 'S0011', 'S０１１', ' S011', 'S011 '])
def test_runtime_candidate_family_is_canonical(family):
    with pytest.raises(ValueError):
        StrategyCandidate(family, "C0621", {"runtime": {}, "parameters": {}})

def test_release_reference_needs_no_dummy_candidate():
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
