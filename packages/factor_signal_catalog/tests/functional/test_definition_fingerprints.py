"""Canonical public FSC definition fingerprints."""

from dataclasses import replace
import pytest
from factor_signal_catalog import FactorDefinition, SignalDefinition, CatalogValidationError


@pytest.mark.parametrize(
    "cls", [FactorDefinition, SignalDefinition], ids=["factor", "signal"]
)
def test_catalog_fingerprints_are_canonical_and_finite(cls):
    # Fingerprint semantics depend on the public schema, not catalog ordering
    # or any particular migration's definitions and revision numbers.
    payload = {
        "name": "Synthetic daily range", "description": "Fingerprint contract",
        "information_family": "PRICE", "tags": ["daily"], "provider": "synthetic",
        "implementation": "synthetic.daily_range", "availability": "After close",
        "causality": "Completed bars only", "parameters": {"window": 2},
        "status": "READY", "version": 1,
    }
    if cls is FactorDefinition:
        payload.update(factor_id="F-RANGE", inputs=["daily.high", "daily.low"],
                       formula="high/low-1")
    else:
        payload.update(signal_id="SIG-RANGE", factor_ids=["F-RANGE"],
                       embedded_factor=False, rule="range > threshold",
                       states=["active", "inactive"])
    value = cls.from_dict(payload)
    assert (
        cls.from_dict(dict(reversed(list(value.to_dict().items())))).definition_sha256
        == value.definition_sha256
    )
    assert replace(value, version=value.version + 1).definition_sha256 != value.definition_sha256
    with pytest.raises(CatalogValidationError):
        replace(value, parameters={"invalid": float("inf")}).definition_sha256
