"""Canonical public FSC definition fingerprints."""

from dataclasses import replace
import json
from pathlib import Path
import pytest
from factor_signal_catalog import FactorDefinition, SignalDefinition, CatalogValidationError


@pytest.mark.parametrize(
    "cls,filename", [(FactorDefinition, "factors"), (SignalDefinition, "signals")]
)
def test_catalog_fingerprints_are_canonical_and_finite(cls, filename):
    payload = json.loads(
        (Path(__file__).parents[4] / f"catalog/{filename}/definitions.json").read_text(
            encoding="utf-8"
        )
    )
    # Catalog files are arrays of the existing public definition schema.
    if isinstance(payload, dict):
        payload = payload["items"]
    value = cls.from_dict(payload[0])
    assert (
        cls.from_dict(dict(reversed(list(value.to_dict().items())))).definition_sha256
        == value.definition_sha256
    )
    assert replace(value, version=value.version + 1).definition_sha256 != value.definition_sha256
    with pytest.raises(CatalogValidationError):
        replace(value, parameters={"invalid": float("inf")}).definition_sha256
