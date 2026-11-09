"""Warm schema caches retain strict per-value and serialized-record validation."""

from dataclasses import replace

import pytest

from strategy_evaluator import research_models as m


@pytest.fixture
def warm_point(monkeypatch):
    m._record_hints.cache_clear()
    point = m.AccountPoint("2026-10-10", 100.0, 0, 10.0, 100.0)
    # Resolving this schema again would prove the cache does not avoid annotation work.
    def forbidden(record_type):
        pytest.fail(f"warm schema unexpectedly resolved again: {record_type}")

    monkeypatch.setattr(m, "get_type_hints", forbidden)
    return point


@pytest.mark.risk_cases('SE-02-C01')
def test_warm_schema_reuses_annotations_but_validates_new_values(warm_point):
    assert replace(warm_point, cash=200.0).cash == 200.0
    assert m.AccountPoint.from_dict(warm_point.to_dict()) == warm_point
    with pytest.raises(TypeError):
        replace(warm_point, quantity=True)
    with pytest.raises(TypeError):
        replace(warm_point, cash="100")
    with pytest.raises(ValueError, match="invalid account point"):
        replace(warm_point, equity=-1.0)


@pytest.mark.parametrize('mutation', [
    pytest.param("missing", id='SE-02-C04'),
    pytest.param("extra", id='SE-02-C05'),
    pytest.param("discriminator", id='SE-02-C06'),
])
@pytest.mark.risk_cases('SE-02-C04', 'SE-02-C05', 'SE-02-C06')
def test_warm_schema_does_not_relax_serialized_record_shape(warm_point, mutation):
    value = warm_point.to_dict()
    if mutation == "missing":
        del value["cash"]
    elif mutation == "extra":
        value["unrecognized"] = 1
    elif mutation == "discriminator":
        value["type"] = "AssessmentCandidate"
    else:
        value["quantity"] = False
    with pytest.raises(ValueError):
        m.AccountPoint.from_dict(value)


@pytest.mark.parametrize('nonfinite', [
    pytest.param(float("nan"), id='SE-02-C02'),
    pytest.param(float("inf"), id='SE-02-C03'),
])
@pytest.mark.risk_cases('SE-02-C02', 'SE-02-C03')
def test_warm_schema_rejects_nonfinite_numbers_in_constructor_and_decode(warm_point, nonfinite):
    with pytest.raises(TypeError):
        replace(warm_point, close=nonfinite)
    value = warm_point.to_dict()
    value["close"] = nonfinite
    with pytest.raises(ValueError):
        m.AccountPoint.from_dict(value)
