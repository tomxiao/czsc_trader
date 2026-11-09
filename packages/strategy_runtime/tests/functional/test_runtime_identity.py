"""SRT-01: canonical identities are pure contracts, not frozen-package fixtures."""

from dataclasses import asdict
import pytest
from strategy_runtime import StrategyCandidate, StrategyIdentity


@pytest.mark.parametrize(
    "candidate_id",
    [
        "C0000",
        "C9999",
    ],
    ids=["SRT-01-C01", "SRT-01-C02"],
)
def test_candidate_boundary_roundtrip(candidate_id):
    candidate = StrategyCandidate("S011", candidate_id, {"runtime": {}, "parameters": {}})
    identity = StrategyIdentity("S011", candidate.reference_id, "a" * 64, "b" * 64, "159326.SZ")
    assert StrategyIdentity(**asdict(identity)) == identity
    assert identity.reference_id == "S011-" + candidate_id


@pytest.mark.parametrize(
    "candidate_id",
    [
        "C001",
    ],
    ids=["SRT-01-C03"],
)
def test_candidate_is_exact_ascii_identity(candidate_id):
    with pytest.raises(ValueError):
        StrategyCandidate("S011", candidate_id, {"runtime": {}, "parameters": {}})


def test_SRT_01_C04_reference_cannot_cross_family():
    with pytest.raises(ValueError):
        StrategyIdentity("S011", "S012-C0621", "a" * 64, "b" * 64, "159326.SZ")


@pytest.mark.parametrize(
    "family,reference",
    [
        ("BuyHold", "S011-C0621"),
        ("S011", "BuyHold"),
    ],
    ids=["SRT-01-C05", "SRT-01-C06"],
)
def test_benchmark_and_strategy_namespaces_do_not_alias(family, reference):
    with pytest.raises(ValueError):
        StrategyIdentity(family, reference, "a" * 64, "b" * 64, "159326.SZ")
